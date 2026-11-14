"""Offline contract/cache/estimation tests: never use credentials or live HTTP."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from backend.infrastructure.scrappa.client import (
    ScrappaClient,
    ScrappaError,
    http_get,
    _NoRedirect,
)

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
PARAMS = {
    "origin_id": 376217,
    "destination_id": 379727,
    "date": "2026-12-01",
    "travel_mode": "train",
}


def payload(amount=1234, currency="EUR", **extra):
    return {
        "success": True,
        "data": {
            "trip_type": "one_way",
            "price_floor_per_mode": {
                "train": {"amount_minor": amount, "currency": currency}
            },
            **extra,
        },
        "meta": {"billable": True},
    }


class ScrappaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "history.duckdb"
        self.now = NOW
        self.transport = Mock(return_value=(200, json.dumps(payload())))
        self.client = ScrappaClient(
            self.path,
            api_key="secret-test-key",
            transport=self.transport,
            clock=lambda: self.now,
        )
        self.addCleanup(self.client.close)

    def test_exact_cache_is_persistent_and_normalizes_defaults(self):
        first = self.client.request("search", PARAMS)
        second = self.client.request(
            "search", {**PARAMS, "currency": "EUR", "adults": 1, "sort": "smart"}
        )
        self.assertEqual(first.source, "api")
        self.assertEqual(second.source, "cache")
        self.assertEqual(first.response_id, second.response_id)
        self.transport.assert_called_once()
        with ScrappaClient(self.path, clock=lambda: NOW) as other:
            cached = other.request("search", PARAMS)
            self.assertEqual(cached.payload, first.payload)
            self.assertEqual(cached.source, "cache")
        row = self.client.db.execute(
            "SELECT parameters, body FROM responses"
        ).fetchone()
        self.assertNotIn("secret-test-key", " ".join(row))
        self.assertEqual(json.loads(row[1]), payload())

    def test_cache_age_refresh_and_history(self):
        self.client.request("search", PARAMS)
        self.now += timedelta(hours=7)
        with self.assertRaises(ScrappaError):
            self.client.request("search", PARAMS, cache_only=True)
        self.transport.assert_called_once()
        self.client.request("search", PARAMS)
        self.client.request("search", PARAMS, refresh=True)
        self.assertEqual(self.transport.call_count, 3)
        self.assertEqual(
            self.client.db.execute("SELECT count(*) FROM responses").fetchone()[0], 3
        )

    def test_all_six_endpoint_paths_and_parameter_encoding(self):
        cases = [
            ("places", {"query": "Berlin Hbf"}, "/api/omio/places"),
            (
                "summary",
                {
                    "origin_id": 1,
                    "destination_id": 2,
                    "date_start": "2026-12-01",
                    "calendar": True,
                },
                "/api/omio/search/summary",
            ),
            ("trip", {"search_id": "abc", "trip_id": "x&y"}, "/api/omio/trip"),
            ("providers", {}, "/api/omio/providers"),
            (
                "route-page",
                {"origin": "berlin", "destination": "paris"},
                "/api/omio/route-page",
            ),
            ("search", PARAMS, "/api/omio/search"),
        ]
        for endpoint, params, path in cases:
            with self.subTest(endpoint=endpoint):
                self.client.request(endpoint, params)
                url, key, timeout = self.transport.call_args.args
                self.assertEqual(urlparse(url).path, path)
                self.assertEqual(key, "secret-test-key")
                self.assertEqual(timeout, 60)
                if endpoint == "trip":
                    self.assertEqual(parse_qs(urlparse(url).query)["trip_id"], ["x&y"])
                if endpoint == "summary":
                    self.assertEqual(
                        parse_qs(urlparse(url).query)["calendar"], ["true"]
                    )

    def test_all_error_bodies_cached_and_reused_without_retry(self):
        for status, body in [
            (429, '{"error":"quota"}'),
            (503, "upstream down"),
            (200, '{"success":false,"data":{}}'),
            (200, "not JSON"),
            (200, '{"success":true,"data":null}'),
        ]:
            with self.subTest(status=status, body=body):
                self.transport.return_value = status, body
                with self.assertRaises(ScrappaError) as error:
                    self.client.request("search", PARAMS, refresh=True)
                self.assertNotIn("secret-test-key", str(error.exception))
                calls = self.transport.call_count
                with self.assertRaisesRegex(ScrappaError, "Cached Scrappa failure"):
                    self.client.request("search", PARAMS)
                self.assertEqual(self.transport.call_count, calls)
                stored = self.client.db.execute(
                    "SELECT body FROM responses ORDER BY rowid DESC LIMIT 1"
                ).fetchone()[0]
                self.assertEqual(stored, body)
        self.assertEqual(self.transport.call_count, 5)
        self.assertEqual(
            self.client.db.execute(
                "SELECT count(*) FROM responses WHERE NOT reusable"
            ).fetchone()[0],
            5,
        )
        with self.assertRaises(ScrappaError):
            self.client.request("search", PARAMS, cache_only=True)

    def test_invalid_input_fails_before_http(self):
        for change in [
            {"adults": 0},
            {"children": -1},
            {"infants": 2},
            {"origin_id": True},
            {"travel_mode": "ferry"},
            {"currency": "JPY"},
            {"date": "bad"},
            {"return_date": "2026-11-30"},
            {"page": 51},
            {"api_key": "oops"},
            {"date": "2026-01-01"},
            {"date": "2028-01-01"},
            {"limit": None},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.client.request("search", {**PARAMS, **change})
        self.transport.assert_not_called()

    def test_pagination_and_passengers_do_not_collide(self):
        for change in [
            {},
            {"page": 2},
            {"adults": 2},
            {"currency": "USD"},
            {"return_date": "2026-12-02"},
        ]:
            self.client.request("search", {**PARAMS, **change})
        self.assertEqual(self.transport.call_count, 5)

    def test_estimate_exact_date_zero_and_no_http(self):
        self.transport.return_value = 200, json.dumps(payload(0))
        self.client.search(**PARAMS)
        result = self.client.estimate(376217, 379727, "2026-12-01", "train")
        self.assertEqual(result["amount"], "0")
        self.assertEqual(result["date_match"], "exact")
        self.assertFalse(result["live_search_eligible"])
        self.transport.assert_called_once()

    def test_estimate_uses_latest_per_date_not_every_refresh(self):
        for day, amount in [
            ("2026-12-01", 1000),
            ("2026-12-01", 2000),
            ("2026-12-03", 3001),
        ]:
            self.transport.return_value = 200, json.dumps(payload(amount))
            self.client.request("search", {**PARAMS, "date": day}, refresh=True)
            self.now += timedelta(minutes=1)
        result = self.client.estimate(376217, 379727, "2026-12-02", "train")
        self.assertEqual(result["amount"], "25.005")
        self.assertEqual(result["sample_days"], 2)
        self.assertEqual(result["min_amount"], "20")
        self.assertEqual(self.transport.call_count, 3)

    def test_summary_observations_can_estimate_without_search(self):
        self.transport.return_value = 200, json.dumps(
            {
                "success": True,
                "data": {
                    "days": [
                        {
                            "date": "2026-12-01",
                            "modes": {
                                "train": {
                                    "price": {"amount_minor": 999, "currency": "EUR"},
                                    "updated_at": NOW.isoformat(),
                                }
                            },
                        }
                    ]
                },
            }
        )
        self.client.summary(
            origin_id=376217, destination_id=379727, date_start="2026-12-01"
        )
        result = self.client.estimate(376217, 379727, "2026-12-01", "train")
        self.assertEqual(result["amount"], "9.99")
        self.transport.assert_called_once()

    def test_stale_upstream_summary_not_mistaken_for_new_price(self):
        self.transport.return_value = 200, json.dumps(
            {
                "success": True,
                "data": {
                    "days": [
                        {
                            "date": "2026-12-01",
                            "modes": {
                                "train": {
                                    "price": {"amount_minor": 999, "currency": "EUR"},
                                    "updated_at": (
                                        NOW - timedelta(days=60)
                                    ).isoformat(),
                                }
                            },
                        }
                    ]
                },
            }
        )
        self.client.summary(
            origin_id=376217, destination_id=379727, date_start="2026-12-01"
        )
        self.assertIsNone(
            self.client.estimate(376217, 379727, "2026-12-01", "train")["amount"]
        )

    def test_estimate_excludes_wrong_cohort_direction_currency_bundle_and_bad_prices(
        self,
    ):
        for params, data in [
            ({**PARAMS, "adults": 2}, payload()),
            ({**PARAMS, "origin_id": 379727, "destination_id": 376217}, payload()),
            ({**PARAMS, "return_date": "2026-12-03"}, payload()),
            (PARAMS, payload(currency="USD")),
            (PARAMS, payload(-1)),
            (PARAMS, payload(True)),
            (PARAMS, payload(None)),
        ]:
            self.transport.return_value = 200, json.dumps(data)
            self.client.request("search", params, refresh=True)
        self.assertIsNone(
            self.client.estimate(376217, 379727, "2026-12-01", "train")["amount"]
        )

    def test_estimate_age_window_empty_and_no_credentials(self):
        self.client.search(**PARAMS)
        self.assertIsNone(
            self.client.estimate(376217, 379727, "2027-02-01", "train")["amount"]
        )
        self.now += timedelta(days=31)
        self.assertIsNone(
            self.client.estimate(376217, 379727, "2026-12-01", "train")["amount"]
        )
        self.client.api_key = None
        with self.assertRaisesRegex(ScrappaError, "SCRAPPA_API_KEY"):
            self.client.request("search", {**PARAMS, "date": "2027-01-01"})
        self.transport.assert_called_once()

    def test_transport_failures_do_not_leak_or_retry(self):
        self.transport.side_effect = RuntimeError("secret-test-key")
        with self.assertRaises(ScrappaError) as error:
            self.client.search(**PARAMS)
        self.assertNotIn("secret-test-key", str(error.exception))
        self.transport.assert_called_once()

    def test_http_authentication_timeout_errors_and_redirect_policy(self):
        from urllib.error import HTTPError, URLError
        from io import BytesIO

        with patch("backend.infrastructure.scrappa.client.build_opener") as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"success":true,"data":{}}'
            status, body = http_get(
                "https://scrappa.co/api/omio/providers", "test-key", 12
            )
            self.assertEqual(status, 200)
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header("X-api-key"), "test-key")
            self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 12)
            opener.return_value.open.side_effect = HTTPError(
                request.full_url, 429, "quota", {}, BytesIO(b"quota body")
            )
            self.assertEqual(
                http_get(request.full_url, "test-key", 12), (429, "quota body")
            )
            opener.return_value.open.side_effect = URLError("test-key")
            with self.assertRaises(ScrappaError) as error:
                http_get(request.full_url, "test-key", 12)
            self.assertNotIn("test-key", str(error.exception))
        self.assertIsNone(
            _NoRedirect().redirect_request(
                None, None, 302, "", {}, "https://example.com"
            )
        )

    def test_malformed_optional_price_fields_are_archived_but_not_estimated(self):
        for data in [
            {"trip_type": "one_way", "price_floor_per_mode": None},
            {
                "trip_type": "round_trip",
                "price_floor_per_mode": {
                    "train": {"amount_minor": 123, "currency": "EUR"}
                },
            },
        ]:
            self.transport.return_value = 200, json.dumps(
                {"success": True, "data": data}
            )
            self.client.request("search", PARAMS, refresh=True)
        for days in [
            None,
            [None],
            [{"date": "2026-12-01", "modes": None}],
            [{"date": "2026-12-01", "modes": {"train": None}}],
        ]:
            self.transport.return_value = 200, json.dumps(
                {"success": True, "data": {"days": days}}
            )
            self.client.request(
                "summary",
                {
                    "origin_id": 376217,
                    "destination_id": 379727,
                    "date_start": "2026-12-01",
                },
                refresh=True,
            )
        self.assertIsNone(
            self.client.estimate(376217, 379727, "2026-12-01", "train")["amount"]
        )

    def test_parameter_boundaries_and_cache_policy(self):
        self.client.request(
            "summary",
            {
                "origin_id": 1,
                "destination_id": 2,
                "date_start": "2026-12-01",
                "date_end": "2027-02-01",
                "adults": 9,
                "children": 9,
                "infants": 9,
            },
        )
        with self.assertRaises(ValueError):
            self.client.request(
                "summary",
                {
                    "origin_id": 1,
                    "destination_id": 2,
                    "date_start": "2026-12-01",
                    "date_end": "2027-02-02",
                },
            )
        with self.assertRaises(ValueError):
            self.client.request("search", PARAMS, refresh=True, cache_only=True)
        with self.assertRaises(ValueError):
            self.client.request("search", PARAMS, max_age_seconds=-1)
        for options in [{"date_window_days": -1}, {"max_age_days": 0}]:
            with self.assertRaises(ValueError):
                self.client.estimate(1, 2, "2026-12-01", "train", **options)
        self.assertEqual(self.transport.call_count, 1)

    def test_transport_failure_persists_and_refresh_recovers(self):
        self.transport.side_effect = TimeoutError("secret-test-key")
        with self.assertRaises(ScrappaError):
            self.client.search(**PARAMS)
        row = self.client.db.execute("SELECT status, body FROM responses").fetchone()
        self.assertEqual(row[0], 0)
        self.assertEqual(json.loads(row[1])["error"]["code"], "TRANSPORT_FAILURE")
        self.assertNotIn("secret-test-key", row[1])
        self.transport.assert_called_once()
        with ScrappaClient(self.path, clock=lambda: NOW) as offline:
            with self.assertRaisesRegex(ScrappaError, "Cached Scrappa failure"):
                offline.request("search", PARAMS, cache_only=True)
        self.transport.side_effect = None
        self.transport.return_value = 200, json.dumps(payload())
        self.assertEqual(
            self.client.request("search", PARAMS, refresh=True).source, "api"
        )
        self.assertEqual(self.client.search(**PARAMS).source, "cache")
        self.assertEqual(self.transport.call_count, 2)
        self.assertEqual(
            self.client.db.execute("SELECT count(*) FROM responses").fetchone()[0], 2
        )

    def test_newer_failure_takes_precedence_over_old_success_until_expiry(self):
        self.client.search(**PARAMS)
        self.now += timedelta(minutes=1)
        self.transport.return_value = 429, "quota"
        with self.assertRaises(ScrappaError):
            self.client.request("search", PARAMS, refresh=True)
        with self.assertRaisesRegex(ScrappaError, "Cached Scrappa failure"):
            self.client.search(**PARAMS)
        self.assertEqual(self.transport.call_count, 2)
        self.now += timedelta(hours=7)
        self.transport.return_value = 200, json.dumps(payload())
        self.assertEqual(self.client.search(**PARAMS).source, "api")
        self.assertEqual(self.transport.call_count, 3)
        # Failures never turn into price observations.
        self.assertEqual(
            self.client.estimate(376217, 379727, "2026-12-01", "train")["sample_days"],
            1,
        )

    def test_cli_offline_estimate_and_invalid_input(self):
        command = [
            sys.executable,
            "-m",
            "backend.presentation.cli.scrappa",
            "--database",
            str(self.path),
        ]
        # Close parent connection before subprocess opens DuckDB (one writer process).
        self.client.close()
        result = subprocess.run(
            command
            + [
                "estimate",
                "--origin-id",
                "1",
                "--destination-id",
                "2",
                "--date",
                "2026-12-01",
                "--mode",
                "bus",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIsNone(json.loads(result.stdout)["amount"])
        result = subprocess.run(
            command + ["request", "search", "--params", "[]"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Parameters", result.stderr)


if __name__ == "__main__":
    unittest.main()
