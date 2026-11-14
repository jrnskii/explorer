"""Offline Mobility Database HTTP, archive, pagination, and CLI contracts."""

import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from zipfile import ZipFile

from backend.infrastructure.fixtures import download_mobilitydatabase as downloads


def response(value):
    return io.BytesIO(json.dumps(value).encode())


def feed(identifier, countries=("LT",), latest=None):
    return {
        "id": identifier,
        "provider": "Transport",
        "locations": [{"country_code": country} for country in countries],
        "latest_dataset": latest,
    }


class MobilityDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        stream = io.BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr("agency.txt", "agency_id,agency_name\n1,Example\n")
        self.zip = stream.getvalue()
        self.sha = hashlib.sha256(self.zip).hexdigest()
        self.latest = {
            "id": "mdb-1-20260101",
            "hosted_url": "https://storage.example/feed.zip",
            "hash": self.sha,
        }

    @patch.object(downloads, "urlopen")
    def test_http_pagination_filters_all_locations_and_keeps_parallel_provider_feeds(
        self, opening
    ):
        opening.side_effect = [
            response(
                [
                    feed("mdb-1", ("US", "LT")),
                    feed("mdb-2", ("US",)),
                ]
            ),
            response([feed("mdb-1"), feed("mdb-3", ("GB",)), feed("mdb-4", ("TR",))]),
            response([]),
        ]
        client = downloads.CatalogClient("secret", None, 30)
        result = downloads.european_feeds(client, 500)
        self.assertEqual([row["id"] for row in result], ["mdb-1", "mdb-3", "mdb-4"])
        self.assertEqual(
            [call.args[0].full_url for call in opening.call_args_list],
            [
                f"{downloads.API_URL}/gtfs_feeds?limit=500&offset={offset}"
                for offset in (0, 2, 5)
            ],
        )
        self.assertEqual(
            opening.call_args.args[0].get_header("Authorization"), "Bearer secret"
        )
        self.assertEqual(opening.call_args.kwargs, {"timeout": 30})

    def test_empty_invalid_and_stuck_catalogues(self):
        client = Mock()
        client.get.return_value = []
        self.assertEqual(downloads.european_feeds(client, 1), [])
        for pages in (
            [{}],
            [[feed("../escape")]],
            [[feed("a")], [feed("a")]],
            [[{**feed("a"), "locations": "LT"}]],
        ):
            with self.subTest(pages=pages):
                client.get.side_effect = pages
                with self.assertRaises(ValueError):
                    downloads.european_feeds(client, 1)

    @patch.object(downloads, "urlopen")
    def test_refresh_initial_and_expired_tokens(self, opening):
        unauthorized = HTTPError("https://example", 401, "secret", {}, None)
        opening.side_effect = [
            response({"access_token": "first"}),
            unauthorized,
            response({"access_token": "second"}),
            response([]),
        ]
        client = downloads.CatalogClient(None, "refresh-secret", 10)
        self.assertEqual(client.get("gtfs_feeds"), [])
        calls = opening.call_args_list
        self.assertEqual(
            json.loads(calls[0].args[0].data), {"refresh_token": "refresh-secret"}
        )
        self.assertEqual(calls[-1].args[0].get_header("Authorization"), "Bearer second")

    @patch.object(downloads, "urlopen")
    def test_archive_is_streamed_cached_and_token_free(self, opening):
        opening.return_value = io.BytesIO(self.zip)
        destination = self.root / "mdb-1.zip"
        self.assertEqual(
            downloads.download_archive(
                self.latest["hosted_url"], destination, self.sha, 10
            ),
            "downloaded",
        )
        self.assertEqual(destination.read_bytes(), self.zip)
        self.assertIsNone(opening.call_args.args[0].get_header("Authorization"))
        self.assertEqual(
            downloads.download_archive(
                self.latest["hosted_url"], destination, self.sha, 10
            ),
            "cached",
        )
        opening.assert_called_once()

    @patch.object(downloads, "urlopen")
    def test_api_failures_are_not_retried_indefinitely(self, opening):
        for code in (401, 403, 429, 500):
            error = HTTPError("https://example", code, "upstream", {}, io.BytesIO())
            self.addCleanup(error.close)
            opening.reset_mock()
            opening.side_effect = error
            client = downloads.CatalogClient("secret", None, 10)
            with self.assertRaises(HTTPError):
                client.get("gtfs_feeds")
            opening.assert_called_once()
        opening.side_effect = [response({})]
        with self.assertRaises(ValueError):
            downloads.CatalogClient(None, "refresh", 10).get("gtfs_feeds")

    @patch.object(downloads, "urlopen")
    def test_interrupted_stream_is_removed(self, opening):
        body = Mock()
        body.read.side_effect = [b"partial archive", TimeoutError("secret URL")]
        opening.return_value.__enter__.return_value = body
        destination = self.root / "mdb-1.zip"
        with self.assertRaises(TimeoutError):
            downloads.download_archive(self.latest["hosted_url"], destination, None, 10)
        self.assertFalse(destination.exists())
        self.assertFalse(destination.with_suffix(".zip.part").exists())

    @patch.object(downloads, "urlopen")
    def test_failed_download_retains_previous_archive_and_removes_partial(
        self, opening
    ):
        destination = self.root / "mdb-1.zip"
        destination.write_bytes(b"previous")
        for payload, expected in ((self.zip, "0" * 64), (b"not zip", None)):
            opening.return_value = io.BytesIO(payload)
            with self.assertRaises(Exception):
                downloads.download_archive(
                    self.latest["hosted_url"], destination, expected, 10
                )
            self.assertEqual(destination.read_bytes(), b"previous")
            self.assertFalse(destination.with_suffix(".zip.part").exists())
        for url in (
            "file:///etc/passwd",
            "http://example/file",
            "https://user:secret@example/file",
        ):
            with self.assertRaises(ValueError):
                downloads.download_archive(url, destination, None, 10)

    @patch.object(downloads, "urlopen")
    def test_manifest_records_missing_failed_and_successful_downloads_and_fallback(
        self, opening
    ):
        client = downloads.CatalogClient("secret", None, 10)
        opening.side_effect = [
            response(
                [
                    feed("mdb-1", latest={"id": self.latest["id"]}),
                    feed("mdb-2"),
                    feed("mdb-3", latest={"hosted_url": "http://unsafe"}),
                    feed("mdb-4", latest=self.latest),
                ]
            ),
            response([]),
            response(self.latest),
            io.BytesIO(self.zip),
            io.BytesIO(self.zip),
        ]
        with redirect_stderr(io.StringIO()):
            result = downloads.download_schedules(client, self.root)
        self.assertEqual(
            [row["status"] for row in result["feeds"]],
            ["downloaded", "unavailable", "failed", "downloaded"],
        )
        self.assertEqual(json.loads((self.root / "manifest.json").read_text()), result)
        self.assertEqual(len(json.loads((self.root / "catalog.json").read_text())), 4)
        for index, feed_id in ((0, "mdb-1"), (3, "mdb-4")):
            relative_path = f"raw/{feed_id}.zip"
            self.assertEqual(result["feeds"][index]["path"], relative_path)
            self.assertEqual((self.root / relative_path).read_bytes(), self.zip)
            self.assertFalse((self.root / f"{feed_id}.zip").exists())

    def test_cli_summary_exit_codes_and_redacted_failures(self):
        for status, expected in (("downloaded", 0), ("unavailable", 1), ("failed", 1)):
            with patch.dict(
                os.environ, {"MOBILITYDATABASE_ACCESS_TOKEN": "secret"}, clear=True
            ), patch.object(
                downloads,
                "download_schedules",
                return_value={"feeds": [{"status": status}]},
            ), redirect_stdout(
                io.StringIO()
            ) as stdout:
                self.assertEqual(
                    downloads.main(["--output-dir", str(self.root)]), expected
                )
                self.assertEqual(json.loads(stdout.getvalue())[status], 1)
        with patch.dict(os.environ, {}, clear=True), redirect_stderr(
            io.StringIO()
        ) as stderr:
            self.assertEqual(downloads.main([]), 1)
            self.assertIn("MOBILITYDATABASE_REFRESH_TOKEN", stderr.getvalue())
        with patch.dict(
            os.environ, {"MOBILITYDATABASE_ACCESS_TOKEN": "secret"}
        ), patch.object(
            downloads, "download_schedules", side_effect=RuntimeError("secret URL")
        ), redirect_stderr(
            io.StringIO()
        ) as stderr:
            self.assertEqual(downloads.main([]), 1)
            self.assertNotIn("secret URL", stderr.getvalue())

    def test_module_cli_validation_and_import_have_no_network_side_effects(self):
        module = "backend.infrastructure.fixtures.download_mobilitydatabase"
        for arguments, status in (
            (["--help"], 0),
            (["--page-size", "0"], 2),
            (["--page-size", "2501"], 2),
            (["--timeout", "nan"], 2),
            (["--timeout", "0"], 2),
        ):
            completed = subprocess.run(
                [sys.executable, "-m", module, *arguments],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, status, completed.stderr)
        completed = subprocess.run(
            [sys.executable, "-c", f"import {module}"], capture_output=True, text=True
        )
        self.assertEqual(
            (completed.returncode, completed.stdout, completed.stderr), (0, "", "")
        )


if __name__ == "__main__":
    unittest.main()
