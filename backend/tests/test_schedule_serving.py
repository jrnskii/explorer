"""Deterministic real-calendar extraction and serving boundary regression tests."""

from datetime import date, datetime, timezone
from contextlib import closing
from decimal import Decimal
import json
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import duckdb

from backend.domain.planning import Money, SearchSettings
from backend.domain.pricing import PriceForecast, QuotedPurchase, RoundTripQuote
from backend.domain.travel import TransportType
from backend.infrastructure.fixtures.combine_mobilitydatabase import initialize
from backend.infrastructure.schedules.build import (
    active_dates,
    build_snapshot,
    gtfs_seconds,
    service_instant,
)
from backend.infrastructure.schedules.store import (
    ScheduleSearch,
    SearchInputError,
    SearchUnavailable,
)

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def prediction(query):
    price = Money(Decimal("12.34"), "EUR")
    return PriceForecast(
        price, price, price, "unit-model", "unit-evidence", 1, None, None, ()
    )


class ScheduleServingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.catalog, self.models, self.output = [
            self.root / name
            for name in ("gtfs.duckdb", "cities.json", "model.json", "serving.sqlite")
        ]
        self.catalog.write_text(
            json.dumps(
                [[1, "Vilnius", "LT", 54.68, 25.28], [2, "Riga", "LV", 56.95, 24.11]]
            )
        )
        self.models.write_text("{}")
        with duckdb.connect(str(self.source)) as db:
            initialize(db)
            db.execute("INSERT INTO feeds VALUES ('feed','archive','digest',1)")
            db.execute(
                "INSERT INTO agency(feed_id,agency_id,agency_timezone) VALUES ('feed','agency','Europe/Vilnius')"
            )
            db.execute(
                "INSERT INTO routes(feed_id,route_id,agency_id,route_type) VALUES ('feed','route','agency','3')"
            )
            for trip, service in [
                ("out", "active"),
                ("back", "active"),
                ("cancelled", "cancelled"),
                ("frequency", "active"),
            ]:
                db.execute(
                    "INSERT INTO trips(feed_id,trip_id,route_id,service_id) VALUES ('feed',?,'route',?)",
                    [trip, service],
                )
            db.execute(
                "INSERT INTO stops(feed_id,stop_id,stop_lat,stop_lon) VALUES ('feed','v','54.68','25.28'),('feed','r','56.95','24.11')"
            )
            for trip, a, b, start, end in [
                ("out", "v", "r", "08:00:00", "12:00:00"),
                ("back", "r", "v", "18:00:00", "22:00:00"),
                ("cancelled", "v", "r", "09:00:00", "11:00:00"),
                ("frequency", "v", "r", "07:00:00", "10:00:00"),
            ]:
                for seq, stop, clock in [(1, a, start), (2, b, end)]:
                    db.execute(
                        "INSERT INTO stop_times(feed_id,trip_id,stop_id,stop_sequence,arrival_time,departure_time) VALUES ('feed',?,?,?,?,?)",
                        [trip, stop, str(seq), clock, clock],
                    )
            for service in ("active", "cancelled"):
                db.execute(
                    "INSERT INTO calendar(feed_id,service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date) VALUES ('feed',?,'1','1','1','1','1','1','1','20300102','20300102')",
                    [service],
                )
            db.execute(
                "INSERT INTO calendar_dates(feed_id,service_id,date,exception_type) VALUES ('feed','cancelled','20300102','2')"
            )
            db.execute(
                "INSERT INTO frequencies(feed_id,trip_id) VALUES ('feed','frequency')"
            )

    def build(self, predict=prediction):
        with patch("backend.infrastructure.schedules.build.load_forecaster") as loader:
            loader.return_value.predict.side_effect = predict
            return build_snapshot(
                self.source,
                self.catalog,
                self.models,
                self.output,
                start=date(2030, 1, 2),
                days=1,
                now=NOW,
            )

    def settings(self, **overrides):
        return SearchSettings(
            **(
                dict(
                    departure_city="gn-1",
                    departure_date=datetime(2030, 1, 2, tzinfo=timezone.utc),
                    desired_arrival_date=datetime(2030, 1, 2, 23, tzinfo=timezone.utc),
                    time_tolerance=1380,
                    max_trip_duration=86400,
                    expenses_tolerance=Money(Decimal("100"), "EUR"),
                    transport_types=(TransportType.BUSSES,),
                )
                | overrides
            )
        )

    def test_actual_calendar_services_prices_and_canonical_markers(self):
        metadata = self.build()
        self.assertEqual(metadata["coverage"]["priced_services"], 2)
        service = ScheduleSearch(self.output, clock=lambda: NOW)
        result = service(self.settings())
        self.assertEqual(len(result.options), 1)
        option = result.options[0]
        self.assertEqual(option["total_price"]["amount"], "24.68")
        self.assertEqual(option["path"][0]["from_city"]["id"], "gn-1")
        self.assertEqual(option["path"][0]["departure_at"], "2030-01-02T08:00:00+02:00")
        self.assertFalse(result.metadata["synthetic_schedule"])
        self.assertEqual(result.metadata["pricing"], "forecast")

    def test_over_budget_schedules_are_returned_and_marked(self):
        self.build()
        result = ScheduleSearch(self.output, clock=lambda: NOW)(
            self.settings(expenses_tolerance=Money(Decimal("1"), "EUR"))
        )
        self.assertEqual(len(result.options), 1)
        self.assertTrue(result.metadata["option_pricing"][0]["over_budget"])

    def test_budget_badge_uses_exact_decimal_boundary_without_filtering(self):
        self.build()
        service = ScheduleSearch(self.output, clock=lambda: NOW)
        for budget, over_budget in (("24.67", True), ("24.68", False), ("24.69", False)):
            with self.subTest(budget=budget):
                result = service(self.settings(expenses_tolerance=Money(Decimal(budget), "EUR")))
                self.assertEqual(len(result.options), 1)
                self.assertEqual(result.metadata["option_pricing"][0]["over_budget"], over_budget)

    def test_missing_city_coverage_is_not_an_empty_search(self):
        self.build()
        with closing(sqlite3.connect(self.output)) as db:
            db.execute("INSERT INTO cities VALUES ('gn-3','Kaunas',54.9,23.9,'LT')")
            db.commit()
        factory = Mock()
        service = ScheduleSearch(self.output, clock=lambda: NOW, pricer_factory=factory)
        for overrides in ({"departure_city": "gn-3"}, {"mandatory_cities": ("gn-3",)}):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(SearchInputError, "Kaunas.*coverage"):
                service(self.settings(**overrides))
        factory.assert_not_called()

    def test_frontend_query_returns_built_schedules_over_http(self):
        from fastapi.testclient import TestClient
        from backend.presentation.api import create_app

        self.build()
        source = (Path(__file__).resolve().parents[2] / "frontend/lib/round-trip-search.ts").read_text()
        query = source.split("ROUND_TRIP_QUERY = `", 1)[1].split("`", 1)[0]
        service = ScheduleSearch(self.output, clock=lambda: NOW)
        with patch.dict("os.environ", {"APP_ACCESS_TOKEN": "test-secret"}), TestClient(create_app(service)) as client:
            response = client.post("/graphql", headers={"Authorization": "Bearer test-secret"}, json={
                "query": query, "operationName": "RoundTripOptions", "variables": {"input": {
                    "departure_city": "gn-1", "departure_date": "2030-01-02T00:00:00Z",
                    "desired_arrival_date": "2030-01-03T00:00:00Z", "time_tolerance": 1440,
                    "max_trip_duration": 86400, "expenses_tolerance": {"amount": "200", "currency": "EUR"},
                    "transport_types": ["PLANES", "TRAINS", "BUSSES"], "min_cities": 1,
                    "mandatory_cities": [], "excluded_cities": [],
                }},
            })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("errors", payload)
        self.assertEqual(len(payload["data"]["round_trip_options"]), 1)
        option = payload["data"]["round_trip_options"][0]
        self.assertEqual(option["total_price"], {"amount": "24.68", "currency": "EUR"})
        self.assertEqual(option["path"][0]["from_city"]["name"], "Vilnius")
        self.assertEqual(option["path"][-1]["to_city"]["id"], "gn-1")

    def test_forecast_failure_preserves_published_snapshot(self):
        self.build()
        original = self.output.read_bytes()
        with self.assertRaises(ValueError):
            self.build(lambda query: None)
        self.assertEqual(self.output.read_bytes(), original)

    def test_missing_stale_dates_unknown_city_and_offer_limit(self):
        with self.assertRaises(SearchUnavailable):
            ScheduleSearch(self.output, clock=lambda: NOW)
        self.build()
        with self.assertRaises(SearchUnavailable):
            ScheduleSearch(
                self.output, clock=lambda: datetime(2030, 1, 4, tzinfo=timezone.utc)
            )
        service = ScheduleSearch(self.output, clock=lambda: NOW)
        with self.assertRaises(SearchInputError):
            service(self.settings(departure_city="gn-999"))
        with self.assertRaises(SearchInputError):
            service(
                self.settings(
                    desired_arrival_date=datetime(2030, 1, 5, tzinfo=timezone.utc),
                    max_trip_duration=None,
                )
            )
        limited = ScheduleSearch(self.output, clock=lambda: NOW, max_offers=1)(
            self.settings()
        )
        self.assertIn("max_offers", limited.metadata["truncation_reasons"])

    def test_minimum_connection_time_is_enforced(self):
        self.build()
        with closing(sqlite3.connect(self.output)) as db:
            arrival = db.execute(
                "SELECT arrival FROM offers WHERE origin='gn-1'"
            ).fetchone()[0]
            db.execute(
                "UPDATE offers SET departure=?,arrival=? WHERE origin='gn-2'",
                [arrival + 60, arrival + 3600],
            )
            db.commit()
        result = ScheduleSearch(self.output, clock=lambda: NOW)(self.settings())
        self.assertEqual(result.options, [])

    def test_gtfs_midnight_extended_hours_and_dst(self):
        self.assertEqual(gtfs_seconds("25:10:00"), 90600)
        for value in ("invalid", "12:60:00", "-1:00:00", "72:00:00"):
            with self.assertRaises(ValueError):
                gtfs_seconds(value)
        # GTFS uses noon minus 12 elapsed hours on the spring transition day.
        self.assertEqual(
            service_instant(date(2030, 3, 31), 43200, "Europe/Vilnius"),
            datetime(2030, 3, 31, 9, tzinfo=timezone.utc),
        )
        self.assertEqual(
            service_instant(date(2030, 1, 2), 90000, "Europe/Vilnius"),
            datetime(2030, 1, 2, 23, tzinfo=timezone.utc),
        )
        self.assertEqual(
            active_dates(None, {"20300102": "1"}, date(2030, 1, 2), date(2030, 1, 3)),
            [date(2030, 1, 2)],
        )

    def test_only_single_best_opportunity_is_reconciled(self):
        self.build()
        pricer = Mock()

        def quote(option, settings):
            return RoundTripQuote(
                tuple(
                    QuotedPurchase(
                        offer.id,
                        replace(offer, price=Money(Decimal("20"), "EUR")),
                        ("response",),
                        NOW,
                        offer.id,
                    )
                    for offer in option.offers
                )
            )

        pricer.quote.side_effect = quote
        result = ScheduleSearch(
            self.output, clock=lambda: NOW, pricer_factory=lambda cities: pricer
        )(self.settings())
        pricer.quote.assert_called_once()
        self.assertEqual(result.options[0]["total_price"]["amount"], "40")
        self.assertEqual(result.metadata["provider_checked_opportunities"], 1)
        self.assertEqual(
            result.metadata["option_pricing"][0]["price_status"], "provider_advertised"
        )

    def test_interrupted_build_resumes_completed_feeds(self):
        with duckdb.connect(str(self.source)) as db:
            db.execute("INSERT INTO feeds VALUES ('aaa-empty','archive','digest',0)")
        with self.assertRaises(ValueError):
            self.build(
                lambda query: (_ for _ in ()).throw(
                    ValueError("transient compile error")
                )
            )
        self.assertFalse(self.output.exists())
        metadata = self.build()
        self.assertEqual(metadata["coverage"]["feeds"], 2)
        self.assertEqual(metadata["coverage"]["priced_services"], 2)

    def test_invalid_calendar_is_omitted_without_aborting_other_services(self):
        with duckdb.connect(str(self.source)) as db:
            db.execute(
                "INSERT INTO trips(feed_id,trip_id,route_id,service_id) VALUES ('feed','broken','route','broken')"
            )
            db.execute(
                "INSERT INTO calendar(feed_id,service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date) VALUES ('feed','broken','1','1','1','1','1','1','1','20300101',NULL)"
            )
        metadata = self.build()
        self.assertEqual(metadata["coverage"]["invalid_calendars"], 1)
        self.assertEqual(metadata["coverage"]["priced_services"], 2)

    def test_parallel_services_do_not_multiply_reachability_work(self):
        self.build()
        with closing(sqlite3.connect(self.output)) as db:
            rows = db.execute("SELECT * FROM offers").fetchall()
            db.executemany(
                "INSERT INTO offers VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    (f"{row[0]}-{index}", *row[1:])
                    for index in range(20000)
                    for row in rows
                ),
            )
            db.commit()
        # A deterministic virtual-machine work budget, independent of machine speed.
        from itertools import count

        steps = count()
        with patch(
            "backend.infrastructure.schedules.store.time.monotonic",
            side_effect=lambda: next(steps) * 0.02,
        ):
            limited = ScheduleSearch(self.output, clock=lambda: NOW, max_offers=1)(
                self.settings()
            )
            self.assertEqual(limited.options, [])
            self.assertIn("max_offers", limited.metadata["truncation_reasons"])

    def test_index_upgrade_preserves_data_freshness_and_route_results(self):
        from backend.infrastructure.schedules.optimize import optimize_snapshot

        metadata = self.build()
        with closing(sqlite3.connect(self.output)) as db:
            db.execute("DROP INDEX offer_outgoing_cover")
            metadata["query_index_version"] = 1
            db.execute(
                "UPDATE metadata SET value=? WHERE key='snapshot'",
                [json.dumps(metadata)],
            )
            db.commit()
        with self.assertRaises(SearchUnavailable):
            ScheduleSearch(self.output, clock=lambda: NOW)
        self.output.chmod(0o640)
        optimize_snapshot(self.output)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o640)
        service = ScheduleSearch(self.output, clock=lambda: NOW)
        self.assertEqual(service.ready()["built_at"], metadata["built_at"])
        self.assertEqual(len(service(self.settings()).options), 1)
