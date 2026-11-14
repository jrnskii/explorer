"""Offline coverage only: never call Scrappa or read the real .env file."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from backend.infrastructure.scrappa.client import ScrappaClient
from backend.infrastructure.scrappa.route_probe import fetch_routes
from backend.presentation.cli.test_omio import main

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
DAY = "2026-12-01"
DESTINATIONS = (("Warsaw", "PL"), ("Berlin", "DE"))


def body(data):
    return 200, json.dumps({"success": True, "data": data})


def places(city, country, position_id):
    return body({"results": [{"name": city, "type": "location",
                             "country_code": country, "position_id": position_id}]})


def trips(page, ids, more=False, total=None):
    return body({"origin_id": 1, "destination_id": 2, "date": DAY,
                 "trip_type": "one_way", "currency": "EUR",
                 "passengers": {"adults": 1, "children": 0, "infants": 0},
                 "results": [{"trip_id": i, "price": {"amount_minor": 1234}} for i in ids],
                 "pagination": {"page": page, "has_more": more,
                                "total": len(ids) if total is None else total},
                 "search_meta": {"modes_done": ["train", "bus", "flight"]}})


class OmioProbeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "scrappa.duckdb"
        self.transport = Mock(side_effect=self.respond)
        self.client = ScrappaClient(self.path, api_key="test-secret", transport=self.transport,
                                    clock=lambda: NOW)
        self.addCleanup(self.client.close)
        self.enterContext(redirect_stderr(StringIO()))

    def respond(self, url, key, timeout):
        p = parse_qs(urlparse(url).query)
        if urlparse(url).path.endswith("places"):
            return {"Vilnius": places("Vilnius", "LT", 1),
                    "Warsaw": places("Warsaw", "PL", 2),
                    "Berlin": places("Berlin", "DE", 3)}[p["query"][0]]
        self.assertEqual(p["travel_mode[]"], ["bus", "flight", "train"])
        self.assertEqual(p["limit"], ["100"])
        if p["destination_id"] == ["2"]:
            page = int(p["page"][0])
            result = trips(page, [f"warsaw-{page}"], page == 1, total=2)
        else:
            result = trips(1, [])
        status, raw = result
        payload = json.loads(raw)
        payload["data"].update(
            origin_id=int(p["origin_id"][0]), destination_id=int(p["destination_id"][0]),
            date=p["date"][0], trip_type="one_way", currency="EUR",
            passengers={"adults": 1, "children": 0, "infants": 0},
        )
        return status, json.dumps(payload)

    def run_probe(self, **kwargs):
        return fetch_routes(self.client, DAY, DESTINATIONS, **kwargs)

    def test_all_pages_and_empty_destination_are_cached_and_resume_without_http(self):
        first = self.run_probe()
        self.assertEqual([r["status"] for r in first["destinations"]], ["complete", "empty"])
        self.assertEqual(first["destinations"][0]["trips"], 2)
        self.assertEqual(self.transport.call_count, 6)
        self.transport.reset_mock(side_effect=True)
        self.transport.side_effect = AssertionError("Resume must not access network")
        self.assertEqual(self.run_probe(), first)
        self.transport.assert_not_called()
        self.assertEqual(self.client.db.execute("SELECT count(*) FROM responses").fetchone()[0], 6)

    def test_failure_keeps_pages_continues_other_destinations_and_rerun_retries_only_failure(self):
        def fail_page(url, key, timeout):
            p = parse_qs(urlparse(url).query)
            if p.get("page") == ["2"]:
                return 503, "upstream down"
            return self.respond(url, key, timeout)
        self.transport.side_effect = fail_page
        report = self.run_probe()
        self.assertEqual([r["status"] for r in report["destinations"]], ["failed", "empty"])
        self.assertEqual(report["destinations"][0]["trips"], 1)
        self.assertEqual(self.client.db.execute("SELECT body FROM responses WHERE status=503").fetchone()[0],
                         "upstream down")
        self.transport.reset_mock()
        self.transport.side_effect = self.respond
        self.assertEqual(self.run_probe()["destinations"][0]["status"], "complete")
        self.transport.assert_called_once()

    def test_interrupt_leaves_committed_data_readable_after_reopen(self):
        def interrupt(url, key, timeout):
            if parse_qs(urlparse(url).query).get("page") == ["2"]:
                raise KeyboardInterrupt
            return self.respond(url, key, timeout)
        self.transport.side_effect = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_probe()
        self.client.close()
        self.client = ScrappaClient(self.path, api_key="test-secret", transport=self.transport,
                                    clock=lambda: NOW)
        self.addCleanup(self.client.close)
        self.assertEqual(self.client.db.execute("SELECT count(*) FROM responses").fetchone()[0], 3)
        self.transport.reset_mock()
        self.transport.side_effect = self.respond
        self.assertEqual(self.run_probe()["destinations"][0]["status"], "complete")
        self.assertEqual(self.transport.call_count, 3)

    def test_malformed_json_and_transport_exception_are_saved_and_do_not_abort_batch(self):
        for bad in [(200, "not json"), RuntimeError("test-secret")]:
            with self.subTest(bad=type(bad).__name__):
                def fail(url, key, timeout):
                    if parse_qs(urlparse(url).query).get("page") == ["2"]:
                        if isinstance(bad, Exception):
                            raise bad
                        return bad
                    return self.respond(url, key, timeout)
                self.transport.side_effect = fail
                report = self.run_probe(refresh=True)
                self.assertEqual([r["status"] for r in report["destinations"]], ["failed", "empty"])
                self.assertNotIn("test-secret", json.dumps(report))
        self.assertEqual(self.client.db.execute("SELECT count(*) FROM responses WHERE NOT reusable").fetchone()[0], 2)

    def test_invalid_pagination_partial_modes_duplicate_trips_and_wrong_total_fail(self):
        malformed = [
            {"results": [], "pagination": {}},
            {"results": [], "pagination": {"page": 1, "total": 0, "has_more": False},
             "search_meta": {"modes_done": ["train"]}},
            json.loads(trips(1, ["same", "same"])[1])["data"],
            json.loads(trips(1, ["one"], total=2)[1])["data"],
        ]
        for data in malformed:
            data = {**json.loads(trips(1, [])[1])["data"], **data}
            def invalid(url, key, timeout):
                if urlparse(url).path.endswith("search"):
                    return body(data)
                return self.respond(url, key, timeout)
            self.transport.side_effect = invalid
            report = self.run_probe(refresh=True)
            self.assertTrue(all(r["status"] == "failed" for r in report["destinations"]))

    def test_wrong_search_cohort_is_cached_but_never_reported_complete(self):
        for field, value in (
            ("origin_id", 99), ("destination_id", 99), ("date", "2026-12-02"),
            ("origin_id", True),
            ("currency", "USD"), ("trip_type", "round_trip"),
            ("passengers", {"adults": 2, "children": 0, "infants": 0}),
            ("passengers", {"adults": True, "children": 0, "infants": 0}),
        ):
            with self.subTest(field=field):
                def wrong_cohort(url, key, timeout):
                    status, raw = self.respond(url, key, timeout)
                    payload = json.loads(raw)
                    if urlparse(url).path.endswith("search"):
                        payload["data"][field] = value
                    return status, json.dumps(payload)
                self.transport.side_effect = wrong_cohort
                report = fetch_routes(self.client, DAY, DESTINATIONS[:1], refresh=True)
                result = report["destinations"][0]
                self.assertEqual(result["status"], "failed")
                self.assertIn("does not match", result["error"])
                saved = self.client.db.execute(
                    "SELECT body FROM responses WHERE response_id=?", [result["pages"][0]]
                ).fetchone()[0]
                self.assertEqual(json.loads(saved)["data"][field], value)

    def test_ambiguous_or_wrong_country_place_is_not_guessed(self):
        for results in [
            [{"name": "Vilnius", "type": "location", "country_code": "US", "position_id": 1}],
            [{"name": "Vilnius", "type": "location", "country_code": "LT", "position_id": i}
             for i in (1, 2)],
        ]:
            self.transport.return_value = body({"results": results})
            self.transport.side_effect = None
            with self.assertRaisesRegex(ValueError, "exactly one"):
                self.run_probe(refresh=True)

    def test_repeated_page_and_provider_page_limit_are_reported_as_incomplete(self):
        for repeat in (True, False):
            def pages(url, key, timeout):
                p = parse_qs(urlparse(url).query)
                if "page" in p:
                    page = int(p["page"][0])
                    return trips(page, ["same" if repeat else str(page)], True, total=51)
                return self.respond(url, key, timeout)
            self.transport.side_effect = pages
            report = fetch_routes(self.client, DAY, DESTINATIONS[:1], refresh=True)
            result = report["destinations"][0]
            self.assertEqual(result["status"], "failed")
            self.assertIn("repeated" if repeat else "page limit", result["error"])
            self.assertEqual(len(result["pages"]), 2 if repeat else 50)

    def test_invalid_cli_date_fails_before_loading_dotenv_or_opening_client(self):
        with patch("sys.argv", ["test-omio", "--date", "2020-01-01"]), patch(
            "backend.presentation.cli.test_omio.load_dotenv"
        ) as dotenv, patch("backend.presentation.cli.test_omio.ScrappaClient") as client:
            with self.assertRaises(SystemExit) as exc:
                main()
            self.assertEqual(exc.exception.code, 2)
            dotenv.assert_not_called()
            client.assert_not_called()

    def test_cli_loads_explicit_dotenv_and_returns_failure_with_json(self):
        env = self.path.parent / ".env"
        env.write_text("SCRAPPA_API_KEY=dotenv-test-key\n")
        report = {"destinations": [{"status": "failed"}]}
        with patch.dict(os.environ, {}, clear=True), patch(
            "sys.argv", ["test-omio", "--date", DAY, "--env-file", str(env)]
        ), patch("backend.presentation.cli.test_omio.datetime") as clock, patch(
            "backend.presentation.cli.test_omio.ScrappaClient"
        ) as client, patch(
            "backend.presentation.cli.test_omio.fetch_routes", return_value=report
        ), redirect_stdout(StringIO()) as output:
            clock.now.return_value = NOW
            with self.assertRaises(SystemExit) as exc:
                main()
            self.assertEqual(exc.exception.code, 1)
            self.assertEqual(client.call_args.kwargs["api_key"], "dotenv-test-key")
            self.assertEqual(json.loads(output.getvalue())["destinations"], report["destinations"])


if __name__ == "__main__":
    unittest.main()
