"""Offline price-model and integration contracts; no local real dataset dependency."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import io
import contextlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from backend.domain.planning import Money, JourneyOffer, TripLeg, SearchSettings
from backend.domain.pricing import ForecastQuery
from backend.domain.travel import TransportType as M
from backend.infrastructure.fixtures.extract_pricing import initialize
from backend.infrastructure.pricing.forecast import (
    ForecastService,
    load_forecaster,
    route,
    MODELS,
)
from backend.infrastructure.pricing.overlay import reprice_offers, ForecastOfferProvider
from backend.infrastructure.pricing.train import train, summary

DAY = date(2026, 11, 14)


def fixture_artifact():
    cells = lambda v: dict(baseline=summary([Decimal(v)], dates=["2026-11-14"]))
    return dict(
        format="explorer.price_forecasts",
        version=1,
        metadata=dict(information_date=DAY.isoformat()),
        models={
            mode.value: dict(model_id=mode.value + "-test", entries={}) for mode in M
        },
    )


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.artifact = fixture_artifact()
        for mode in (M.PLANES, M.TRAINS, M.BUSSES):
            self.artifact["models"][mode.value]["entries"][
                route("Paris", "Berlin", "FR", "DE")
            ] = dict(
                baseline=summary(
                    [Decimal("10"), Decimal("30")], dates=["2017-01-01", "2017-01-02"]
                )
            )
        entry = self.artifact["models"]["PLANES"]["entries"][
            route("Paris", "Berlin", "FR", "DE")
        ]
        entry["months"] = {"2026-12": summary([Decimal("42.005")])}
        entry = self.artifact["models"]["BUSSES"]["entries"][
            route("Paris", "Berlin", "FR", "DE")
        ]
        entry["lead"] = {"3": summary([Decimal("7")], dates=["2017-01-01"])}
        fid = json.dumps(["feed-1", "route-1", "", ""], separators=(",", ":"))
        self.artifact["models"]["FERRIES"]["entries"][fid] = dict(
            baseline=summary([Decimal("3")])
        )
        self.service = ForecastService(self.artifact)

    def query(self, mode=M.PLANES, **kw):
        return replace(
            ForecastQuery(mode, "Paris", "Berlin", date(2026, 12, 1), DAY, "FR", "DE"),
            **kw,
        )

    def test_distinct_models_and_exact_month(self):
        self.assertEqual({type(m) for m in self.service.models.values()}, set(MODELS))
        p = self.service.predict(self.query())
        self.assertEqual(p.price, Money(Decimal("42.01"), "EUR"))
        self.assertEqual(p.lower.amount, Decimal("42.00"))
        self.assertEqual(p.basis, "route_departure_month")

    def test_route_baseline_does_not_invent_annual_seasonality(self):
        p = self.service.predict(self.query(departure_date=date(2027, 12, 1)))
        self.assertEqual(p.price.amount, Decimal("20"))
        self.assertEqual(p.basis, "route_baseline")

    def test_bus_lead_cell_and_historical_warning(self):
        p = self.service.predict(
            self.query(M.BUSSES, departure_date=DAY + timedelta(days=2))
        )
        self.assertEqual(p.price.amount, Decimal("7"))
        self.assertEqual(p.basis, "route_lead_time")
        self.assertTrue(any("one year" in w for w in p.warnings))
        self.assertEqual(
            self.service.predict(self.query(M.BUSSES)).price.amount, Decimal("20")
        )

    def test_rail_and_ferry_keep_product_semantics(self):
        self.assertEqual(
            self.service.predict(self.query(M.TRAINS)).basis,
            "published_tariff_midpoint",
        )
        self.assertIsNone(self.service.predict(self.query(M.FERRIES)))
        p = self.service.predict(
            self.query(M.FERRIES, feed_id="feed-1", route_id="route-1")
        )
        self.assertEqual(p.price.amount, Decimal("3"))
        self.assertIsNone(
            self.service.predict(
                self.query(M.FERRIES, feed_id="feed1", route_id="route1")
            )
        )

    def test_unknown_reverse_and_country_mismatch_have_no_mock_fallback(self):
        for kw in [
            dict(origin="Unknown"),
            dict(origin="Berlin", destination="Paris"),
            dict(origin_country="GB"),
        ]:
            self.assertIsNone(self.service.predict(self.query(**kw)))

    def test_ambiguous_country_without_country_hint_is_unsupported(self):
        data = deepcopy(self.artifact)
        data["models"]["PLANES"]["entries"][route("Paris", "Berlin", "DE", "FR")] = (
            deepcopy(next(iter(data["models"]["PLANES"]["entries"].values())))
        )
        service = ForecastService(data)
        self.assertIsNone(
            service.predict(self.query(origin_country=None, destination_country=None))
        )
        self.assertIsNotNone(service.predict(self.query()))

    def test_travelers_scale_before_rounding(self):
        p = self.service.predict(self.query(travelers=2))
        self.assertEqual(p.price.amount, Decimal("84.01"))
        self.assertTrue(p.lower.amount <= p.price.amount <= p.upper.amount)

    def test_information_dates_and_invalid_travelers(self):
        with self.assertRaisesRegex(ValueError, "leak"):
            self.service.predict(self.query(as_of=DAY - timedelta(days=1)))
        with self.assertRaises(ValueError):
            self.query(departure_date=DAY - timedelta(days=1))
        for travelers in (0, True, 10, 1.5):
            with self.subTest(travelers=travelers), self.assertRaises(ValueError):
                self.query(travelers=travelers)
        with self.assertRaises(ValueError):
            self.query(departure_date=datetime(2026, 11, 14, tzinfo=timezone.utc))

    def test_artifact_rejects_bad_format_and_inconsistent_bounds(self):
        for value in ("NaN", "-1", "50"):
            data = deepcopy(self.artifact)
            data["models"]["PLANES"]["entries"][route("Paris", "Berlin", "FR", "DE")][
                "baseline"
            ]["lower"] = value
            with self.assertRaises(ValueError):
                ForecastService(data)
        with self.assertRaises(ValueError):
            ForecastService(dict(self.artifact, version=3))

    def test_missing_artifact_fails_and_safe_cache_reloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "models.json"
            with self.assertRaisesRegex(ValueError, "mock fallback is disabled"):
                load_forecaster(p)
            p.write_text(json.dumps(self.artifact))
            a = load_forecaster(p)
            self.assertIs(a, load_forecaster(p))
            p.write_text("{}")
            with self.assertRaises(ValueError):
                load_forecaster(p)

    def test_batch_boundary_reports_null_coverage_and_preserves_party_rounding(self):
        from backend.presentation.cli.forecast_prices import forecast_batch

        query = dict(
            mode="PLANES",
            origin="Paris",
            destination="Berlin",
            departure_date="2026-12-01",
            travelers=2,
        )
        result = forecast_batch(
            dict(queries=[query, dict(query, destination="Unknown")]), self.service, DAY
        )
        self.assertEqual(result["forecasts"][0]["price"]["amount"], Decimal("84.01"))
        self.assertIsNone(result["forecasts"][1])
        for bad in [
            None,
            dict(queries=[]),
            dict(queries=[query] * 65),
            dict(queries=[dict(query, as_of="2017-01-01")]),
        ]:
            with self.subTest(payload=bad), self.assertRaises(ValueError):
                forecast_batch(bad, self.service, DAY)

    def test_bundled_ticket_is_priced_once_and_parallel_offers_preserved(self):
        start = datetime(2026, 12, 1, tzinfo=timezone.utc)
        path = (
            TripLeg("a", "via", start, start + timedelta(hours=1), M.PLANES),
            TripLeg(
                "via",
                "b",
                start + timedelta(hours=2),
                start + timedelta(hours=3),
                M.PLANES,
            ),
        )
        offers = tuple(
            JourneyOffer(str(i), path, Money(Decimal("999"), "USD"), "mock", True)
            for i in range(2)
        )
        priced, evidence, skipped = reprice_offers(
            offers,
            self.service,
            dict(
                a=dict(name="Paris", country="FR"), b=dict(name="Berlin", country="DE")
            ),
            as_of=DAY,
        )
        self.assertFalse(skipped)
        self.assertEqual(len(priced), 2)
        self.assertEqual(priced[0].price.amount, Decimal("42.01"))
        self.assertEqual(priced[0].path, path)
        self.assertTrue(priced[0].synthetic)
        self.assertEqual(offers[0].price.currency, "USD")
        mixed = replace(
            offers[0], path=(path[0], replace(path[1], transport_type=M.TRAINS))
        )
        self.assertEqual(
            reprice_offers((mixed,), self.service, {}, as_of=DAY)[2][0]["reason"],
            "mixed_mode_bundle_unsupported",
        )


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.database = self.root / "pricing.duckdb"
        self.output = self.root / "models.json"
        with duckdb.connect(str(self.database)) as d:
            initialize(d)
            d.execute(
                "INSERT INTO extraction VALUES (?)",
                [json.dumps(dict(extracted_at="2026-11-14T00:00:00+00:00"))],
            )
            for month, price in [
                ("2026-09", "10"),
                ("2026-10", "20"),
                ("2026-11", "100"),
            ]:
                self.add(
                    d,
                    "air",
                    "route_month_aggregate",
                    "Paris",
                    "Berlin",
                    price,
                    month=month,
                )
            # This overlapping whole-route aggregate must not enter training.
            self.add(d, "air", "route_aggregate", "Paris", "Berlin", "99999")
            for i, price in enumerate(["10", "20", "30", "40", "50"]):
                self.add(
                    d,
                    "bus",
                    "advertised_seat_fare",
                    "Paris",
                    "Berlin",
                    price,
                    observed=f"2017-08-0{i+1}",
                    departure="2017-09-01",
                    raw=dict(seat=1, dep="08:00"),
                )
                self.add(
                    d,
                    "bus",
                    "advertised_seat_fare",
                    "Paris",
                    "Berlin",
                    "9999",
                    observed=f"2017-08-0{i+1}",
                    departure="2017-09-01",
                    raw=dict(seat=2, dep="08:00"),
                )
            self.add(
                d,
                "rail",
                "published_tariff_bounds",
                "Paris",
                "Berlin",
                None,
                low="10",
                high="50",
                raw=dict(classe="2", profil_tarifaire="Tarif Normal"),
            )
            self.add(
                d,
                "rail",
                "published_tariff_bounds",
                "Paris",
                "Berlin",
                None,
                low="1000",
                high="2000",
                raw=dict(classe="1", profil_tarifaire="Tarif Normal"),
            )
            for route_id, fare, price, currency, constraint in [
                ("safe", "f1", "3", "EUR", ""),
                ("zone", "f2", "100", "EUR", "Z"),
                ("foreign", "f3", "20", "GBP", ""),
            ]:
                d.execute(
                    "INSERT INTO gtfs_context VALUES (?,?,?,?)",
                    [
                        "gtfs:feed",
                        "routes",
                        1,
                        json.dumps(dict(route_id=route_id, route_type="4")),
                    ],
                )
                for table, r in [
                    (
                        "fare_attributes",
                        dict(fare_id=fare, price=price, currency_type=currency),
                    ),
                    (
                        "fare_rules",
                        dict(fare_id=fare, route_id=route_id, origin_id=constraint),
                    ),
                ]:
                    d.execute(
                        "INSERT INTO gtfs_fare_records VALUES (?,?,?,?)",
                        ["gtfs:feed", table, 1, json.dumps(r)],
                    )

    def add(
        self,
        d,
        mode,
        kind,
        origin,
        destination,
        price,
        month=None,
        low=None,
        high=None,
        raw=None,
        observed=None,
        departure=None,
    ):
        d.execute(
            "INSERT INTO pricing VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                mode + str(d.execute("SELECT count(*) FROM pricing").fetchone()[0]),
                1,
                mode,
                kind,
                origin,
                destination,
                "FR",
                "DE",
                "EUR",
                price,
                low,
                high,
                None,
                5,
                month,
                observed,
                departure,
                json.dumps(raw or {}),
            ],
        )

    def fit(self):
        return train(
            self.database, self.output, fixtures_dir=self.root, graph_path=None
        )

    def test_fit_model_policies_and_ferry_constraints(self):
        result = self.fit()
        model = load_forecaster(self.output)
        self.assertEqual(result["models"]["PLANES"]["routes"], 1)
        request = ForecastQuery(M.PLANES, "Paris", "Berlin", date(2026, 12, 1), DAY)
        self.assertEqual(model.predict(request).price.amount, Decimal("20"))
        self.assertEqual(
            model.predict(replace(request, mode=M.TRAINS)).price.amount, Decimal("30")
        )
        self.assertEqual(
            model.predict(replace(request, mode=M.BUSSES)).price.amount, Decimal("35")
        )
        for rid, expected in [("safe", True), ("zone", False), ("foreign", False)]:
            self.assertEqual(
                model.predict(
                    replace(request, mode=M.FERRIES, feed_id="feed", route_id=rid)
                )
                is not None,
                expected,
            )
        self.assertEqual(
            result["models"]["PLANES"]["validation"]["mae_eur"], "85.000000000000000000"
        )
        self.assertEqual(result["models"]["BUSSES"]["validation"]["test_units"], 1)
        self.assertEqual(
            result["models"]["TRAINS"]["validation"]["status"], "not_available"
        )

    def test_ferry_rejects_product_with_any_constrained_rule(self):
        with duckdb.connect(str(self.database)) as db:
            db.execute(
                "INSERT INTO gtfs_fare_records VALUES (?,?,?,?)",
                [
                    "gtfs:feed",
                    "fare_rules",
                    2,
                    json.dumps(dict(fare_id="f1", route_id="safe", contains_id="Z")),
                ],
            )
        self.fit()
        request = ForecastQuery(
            M.FERRIES,
            "Paris",
            "Berlin",
            date(2026, 12, 1),
            DAY,
            feed_id="feed",
            route_id="safe",
        )
        self.assertIsNone(load_forecaster(self.output).predict(request))

    def test_ferry_rejects_conflicting_currency_definitions(self):
        with duckdb.connect(str(self.database)) as db:
            db.execute(
                "INSERT INTO gtfs_fare_records VALUES (?,?,?,?)",
                [
                    "gtfs:feed",
                    "fare_attributes",
                    2,
                    json.dumps(dict(fare_id="f1", price="3", currency_type="GBP")),
                ],
            )
        self.fit()
        request = ForecastQuery(
            M.FERRIES,
            "Paris",
            "Berlin",
            date(2026, 12, 1),
            DAY,
            feed_id="feed",
            route_id="safe",
        )
        self.assertIsNone(load_forecaster(self.output).predict(request))

    def test_cli_forecast_prices_replace_fixture_amounts(self):
        self.fit()
        data = json.loads(self.output.read_text())
        entries = data["models"]["PLANES"]["entries"]
        for origin, destination, oc, dc in [
            ("Paris", "Amsterdam", "FR", "NL"),
            ("Amsterdam", "Paris", "NL", "FR"),
        ]:
            entries[route(origin, destination, oc, dc)] = dict(
                baseline=summary([Decimal("12.34")])
            )
        self.output.write_text(json.dumps(data))
        payload = dict(
            departure_city="fr-paris",
            mandatory_cities=["nl-amsterdam"],
            excluded_cities=[],
            transport_types=["PLANES"],
            departure_date="2026-12-01T00:00:00Z",
            desired_arrival_date="2026-12-03T19:00:00Z",
            time_tolerance=600,
            expenses_tolerance=dict(amount="500.00", currency="EUR"),
        )
        path = self.root / "request.json"
        path.write_text(json.dumps(payload))
        command = [
            sys.executable,
            "-B",
            "-m",
            "backend.presentation.cli.round_trip",
            "--request",
            str(path),
            "--models",
            str(self.output),
            "--as-of",
            DAY.isoformat(),
        ]
        actual = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        result = json.loads(actual.stdout)
        self.assertTrue(result["options"])
        self.assertEqual(
            result["options"][0]["total_price"], dict(amount="24.68", currency="EUR")
        )
        self.assertTrue(
            all(
                v["price"]["currency"] == "EUR"
                for v in result["forecast_evidence"].values()
            )
        )
        self.assertTrue(result["synthetic_schedule"])
        payload["expenses_tolerance"]["currency"] = "USD"
        path.write_text(json.dumps(payload))
        failed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(failed.returncode, 2)
        self.assertIn("EUR budget", failed.stderr)
        self.assertEqual(failed.stdout, "")

    def test_training_is_deterministic_and_preserves_previous_artifact_on_failure(self):
        self.fit()
        before = self.output.read_bytes()
        self.fit()
        self.assertEqual(before, self.output.read_bytes())
        with self.assertRaisesRegex(ValueError, "earlier"):
            train(
                self.database,
                self.output,
                DAY - timedelta(days=1),
                fixtures_dir=self.root,
                graph_path=None,
            )
        self.assertEqual(before, self.output.read_bytes())

    def test_cli_default_forecast_and_missing_artifact_clean_error(self):
        self.fit()
        payload = dict(
            departure_city="fr-paris",
            mandatory_cities=["nl-amsterdam"],
            excluded_cities=[],
            transport_types=["BUSSES"],
            departure_date="2026-12-01T00:00:00Z",
            desired_arrival_date="2026-12-03T19:00:00Z",
            time_tolerance=180,
            expenses_tolerance=dict(amount="500.00", currency="EUR"),
        )
        request = self.root / "request.json"
        request.write_text(json.dumps(payload))
        command = [
            sys.executable,
            "-B",
            "-m",
            "backend.presentation.cli.round_trip",
            "--request",
            str(request),
            "--models",
            str(self.output),
            "--as-of",
            DAY.isoformat(),
        ]
        actual = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        result = json.loads(actual.stdout)
        self.assertEqual(result["pricing"], "forecast")
        self.assertEqual(result["price_status"], "estimated")
        self.assertEqual(result["options"], [])
        self.assertTrue(result["unpriced_offers"])
        self.output.unlink()
        failed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(failed.stdout, "")
        self.assertNotIn("Traceback", failed.stderr)

    def test_reactive_default_uses_injected_forecasts_and_eur(self):
        self.fit()
        from backend.presentation.notebooks.reactive import search

        with patch(
            "backend.presentation.notebooks.reactive.mock_scrappa_search",
            side_effect=AssertionError("Mock price used"),
        ):
            options, result = search(
                departure="Paris",
                departure_date=date(2026, 12, 1),
                duration=3,
                modes=(M.PLANES,),
                forecaster=load_forecaster(self.output),
                as_of=DAY,
                budget=500,
            )
        self.assertFalse(options)  # No reverse evidence; do not invent it.

    def test_algorithm_notebook_forecast_mode_prices_parallel_edges_and_reports_gaps(
        self,
    ):
        self.fit()
        from test_algo_notebook import execute_notebook
        import networkx as nx

        scope = execute_notebook()
        self.addCleanup(scope["demo"].close)
        graph = nx.MultiDiGraph()
        graph.add_node("a", name="Paris", country="France")
        graph.add_node("b", name="Berlin", country="Germany")
        graph.add_node("c", name="Unknown", country="Germany")
        for connection in ("one", "two"):
            graph.add_edge(
                "a",
                "b",
                key=connection,
                mode="PLANES",
                travel_time_minutes=60,
                operator=connection,
            )
        graph.add_edge(
            "b", "c", key="unsupported", mode="PLANES", travel_time_minutes=60
        )
        demo = scope["ReactiveTripDemo"](
            scope["BaseGraphSource"](graph),
            pricing="forecast",
            forecaster=load_forecaster(self.output),
            as_of=DAY,
        )
        self.addCleanup(demo.close)
        self.assertIsNone(demo.error)
        self.assertEqual(demo.settings.expenses_tolerance.currency, "EUR")
        self.assertEqual({o.connection_id for o in demo.offers}, {"one", "two"})
        self.assertEqual({o.price.amount for o in demo.offers}, {Decimal("20")})
        self.assertTrue(all(o.source.startswith("forecast:") for o in demo.offers))
        self.assertEqual(demo.forecast_diagnostics["unpriced_connections"], 1)
        self.assertEqual(graph.number_of_edges(), 3)
        old_prices = {o.price for o in demo.offers}
        demo.generate.click()
        self.assertEqual({o.price for o in demo.offers}, old_prices)


if __name__ == "__main__":
    unittest.main()
