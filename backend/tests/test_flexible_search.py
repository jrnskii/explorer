"""Offline coverage of flexible ranking and the shared two-attempt provider limit."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from unittest import TestCase
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from backend.domain.planning import Money, SearchSettings
from backend.domain.pricing import (
    ExactPricingUnavailable,
    QuotedPurchase,
    RoundTripQuote,
    PriceForecast,
)
from backend.domain.travel import TransportType as Mode
from backend.infrastructure.graphql.inputs import parse_settings
from backend.infrastructure.schedules.flexible import FlexibleSearch
from backend.infrastructure.schedules.reference import ReferenceSearch, ReferenceEdge
from backend.infrastructure.schedules.store import SearchCoverageError, SearchInputError

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class FlexibleSearchTests(TestCase):
    def setUp(self):
        self.cities = {
            f"gn-{i}": dict(
                name=f"City {i}", country="LT", latitude=54 + i / 10, longitude=25
            )
            for i in range(1, 7)
        }
        self.routes = {
            a: [
                ReferenceEdge(a, b, Mode.PLANES, 60, int(b[-1]) * 100)
                for b in self.cities
                if a != b
            ]
            for a in self.cities
        }
        forecaster = Mock()

        def predict(query):
            price = Money(Decimal(str(query.distance_km / 100)), "EUR")
            return PriceForecast(price, price, price, "test", "test", 1, None, None, ())

        forecaster.predict.side_effect = predict
        self.pricer = Mock()
        self.factory = Mock(return_value=self.pricer)
        self.reference = ReferenceSearch(
            self.routes, self.cities, forecaster, self.factory, clock=lambda: NOW
        )
        self.schedules = Mock(side_effect=SearchCoverageError("Missing coverage"))
        self.schedules.clock.return_value = NOW
        self.search = FlexibleSearch(
            self.schedules, lambda: self.reference, self.factory
        )
        self.settings = SearchSettings(
            "gn-1",
            NOW + timedelta(days=3),
            NOW + timedelta(days=6),
            3 * 1440,
            Money(Decimal(0), "EUR"),
            (Mode.PLANES,),
            max_trip_duration=3 * 86400,
        )
        self.pricer.quote.side_effect = self.quote

    def quote(self, route, settings):
        return RoundTripQuote(
            tuple(
                QuotedPurchase(
                    o.id,
                    replace(o, synthetic=False, source="provider"),
                    ("response",),
                    NOW,
                    o.id,
                )
                for o in route.offers
            )
        )

    def test_estimated_prices_and_legs_respect_selected_transport_types(self):
        self.reference.routes = {
            origin: [replace(edge, mode=mode) for edge in edges
                     for mode in (Mode.PLANES, Mode.TRAINS, Mode.BUSSES)]
            for origin, edges in self.routes.items()
        }
        fares = {Mode.PLANES: 100, Mode.TRAINS: 10, Mode.BUSSES: 1}
        def predict(query):
            price = Money(Decimal(fares[query.mode]), "EUR")
            return PriceForecast(price, price, price, "test", "test", 1, None, None, ())
        self.reference.forecaster.predict.side_effect = predict
        self.pricer.quote.side_effect = ExactPricingUnavailable("offline")
        for selected in ((Mode.PLANES,), (Mode.TRAINS,), (Mode.BUSSES,), (Mode.PLANES, Mode.TRAINS)):
            with self.subTest(selected=selected):
                self.reference.forecaster.predict.reset_mock()
                result = self.search(replace(self.settings, transport_types=selected))
                estimates = result.metadata["estimated_routes"]
                self.assertTrue(estimates)
                for estimate in estimates:
                    modes = [Mode(mode) for mode in estimate["transport_types"]]
                    self.assertEqual(len(modes), len(estimate["cities"]) - 1)
                    self.assertTrue(set(modes) <= set(selected))
                    self.assertEqual(Decimal(estimate["total_price"]["amount"]), sum(fares[mode] for mode in modes))
                self.assertTrue(all(call.args[0].mode in selected
                                    for call in self.reference.forecaster.predict.call_args_list))

    def test_cache_metadata_tracks_only_successful_provider_quote(self):
        for cached in (True, False):
            with self.subTest(cached=cached):
                self.pricer.quote.side_effect = lambda route, settings: replace(
                    self.quote(route, settings), from_cache=cached
                )
                self.assertEqual(self.search(self.settings).metadata["provider_results_cached"], cached)
        self.pricer.quote.side_effect = ExactPricingUnavailable("unavailable")
        self.assertFalse(self.search(self.settings).metadata["provider_results_cached"])

    def test_rank_seven_across_three_dates_quote_only_best_and_keep_estimates(self):
        result = self.search(self.settings)
        self.assertEqual(len(result.options), 1)
        self.assertEqual(len(result.metadata["estimated_routes"]), 6)
        self.factory.assert_called_once()
        self.pricer.quote.assert_called_once()
        self.assertEqual(
            [c.args[0].departure_date.day for c in self.schedules.call_args_list],
            [3, 4, 5],
        )
        self.assertTrue(
            all(c.kwargs == {"rank_only": True} for c in self.schedules.call_args_list)
        )
        rows = result.metadata["estimated_routes"]
        for row in rows:
            ids = [city["id"] for city in row["cities"]]
            self.assertEqual(ids[0], ids[-1])
            self.assertGreaterEqual(len(ids), 4)
            self.assertEqual(len(set(ids[:-1])), len(ids) - 1)
            self.assertNotIn("departure_at", json.dumps(row))
        prices = [(r["rank"], Decimal(r["total_price"]["amount"])) for r in rows]
        prices += [
            (
                result.metadata["option_pricing"][0]["rank"],
                Decimal(result.options[0]["total_price"]["amount"]),
            )
        ]
        ordered = [p for _, p in sorted(prices)]
        self.assertEqual(ordered, sorted(ordered))
        self.assertNotIn("over_budget", json.dumps(result.metadata))

    def test_second_best_only_after_failure(self):
        count = 0

        def quote(route, settings):
            nonlocal count
            count += 1
            if count == 1:
                raise ExactPricingUnavailable("missing service")
            return self.quote(route, settings)

        self.pricer.quote.side_effect = quote
        result = self.search(self.settings)
        self.assertEqual(result.metadata["provider_pricing_attempts"], 2)
        self.assertEqual(len(result.options), 1)
        self.factory.assert_called_once()

    def test_both_fail_still_show_seven_estimates(self):
        self.pricer.quote.side_effect = ExactPricingUnavailable("secret-provider-token")
        result = self.search(self.settings)
        self.assertEqual(result.options, [])
        self.assertEqual(len(result.metadata["estimated_routes"]), 7)
        self.assertEqual(result.metadata["price_status"], "unavailable")
        self.assertEqual(self.pricer.quote.call_count, 2)
        self.assertNotIn("secret-provider-token", json.dumps(result.metadata))

    def test_no_aba_no_revisit_and_excluded_cities(self):
        result = self.search(replace(self.settings, excluded_cities=("gn-2",)))
        self.assertNotIn('"id": "gn-2"', json.dumps(result.metadata))
        self.reference.routes = {
            "gn-1": [self.routes["gn-1"][0]],
            "gn-2": [self.routes["gn-2"][0]],
        }
        self.factory.reset_mock()
        with self.assertRaises(SearchCoverageError):
            self.search(self.settings)
        self.factory.assert_not_called()

    def test_live_fare_uplift_keeps_verified_route_first_without_another_check(self):
        def quote(route, settings):
            original = self.quote(route, settings)
            return replace(
                original,
                purchases=tuple(
                    replace(p, offer=replace(p.offer, price=Money(Decimal(999), "EUR")))
                    for p in original.purchases
                ),
            )

        self.pricer.quote.side_effect = quote
        result = self.search(self.settings)
        self.assertEqual(result.metadata["option_pricing"], [{"price_status": "provider_advertised", "rank": 1}])
        self.assertEqual(len(result.options), 1)
        self.assertEqual(len(result.metadata["estimated_routes"]), 6)
        self.assertEqual(Decimal(result.options[0]["total_price"]["amount"]), Decimal(2997))
        self.pricer.quote.assert_called_once()

    def test_calendar_windows_cross_dst_and_year_boundary(self):
        for start in (
            datetime(2030, 10, 27, tzinfo=ZoneInfo("Europe/Vilnius")),
            datetime(2031, 1, 1, tzinfo=timezone.utc),
        ):
            self.schedules.reset_mock()
            self.search(
                replace(
                    self.settings,
                    departure_date=start,
                    desired_arrival_date=start + timedelta(days=3),
                    departure_timezone="Europe/Vilnius" if start.month == 10 else "UTC",
                )
            )
            windows = [c.args[0] for c in self.schedules.call_args_list]
            self.assertEqual(
                [w.departure_date.date() for w in windows],
                [(start + timedelta(days=i)).date() for i in (-1, 0, 1)],
            )
            self.assertTrue(
                all(
                    w.latest_departure_date.date() == w.departure_date.date()
                    for w in windows
                )
            )
            if start.month == 10:
                self.assertEqual(
                    windows[1].latest_departure_date.utcoffset(), timedelta(hours=2)
                )
                self.assertEqual(
                    windows[1].departure_date.utcoffset(), timedelta(hours=3)
                )

    def test_past_days_skipped_and_all_past_rejected_without_provider_access(self):
        result = self.search(
            replace(
                self.settings,
                departure_date=NOW,
                desired_arrival_date=NOW + timedelta(days=3),
            )
        )
        self.assertEqual(self.schedules.call_count, 2)
        self.assertTrue(result.options)
        self.factory.reset_mock()
        with self.assertRaises(SearchInputError):
            self.search(
                replace(
                    self.settings,
                    departure_date=NOW - timedelta(days=3),
                    desired_arrival_date=NOW,
                )
            )
        self.factory.assert_not_called()

    def test_budget_optional_and_timezone_validated_at_wire_boundary(self):
        payload = dict(
            departure_city="gn-1",
            departure_date="2030-01-04T00:00:00Z",
            desired_arrival_date="2030-01-07T00:00:00Z",
            time_tolerance=4320,
            transport_types=["PLANES"],
        )
        settings = parse_settings(json.dumps(payload))
        self.assertEqual(settings.expenses_tolerance.amount, 0)
        with self.assertRaises(ValueError):
            parse_settings(
                json.dumps(payload | {"departure_timezone": "Invalid/Timezone"})
            )

    def test_departure_day_bound_applies_to_local_and_provider_times(self):
        from backend.application.round_trip_search import (
            find_round_trips,
            verify_selected_route,
        )
        from test_round_trip import settings, offer, START

        offers = (
            offer("ab", "A", "B", 2, 3),
            offer("bc", "B", "C", 4, 5),
            offer("ca", "C", "A", 9, 10),
        )
        request = settings(
            min_cities=2, latest_departure_date=START + timedelta(hours=1)
        )
        self.assertFalse(find_round_trips(request, offers).options)
        request = replace(request, latest_departure_date=START + timedelta(hours=2))
        route = find_round_trips(request, offers).options[0]
        quote = self.quote(route, request)
        self.assertEqual(
            verify_selected_route(route, quote, request, 1800).total_price.amount, 30
        )
        with self.assertRaisesRegex(ExactPricingUnavailable, "departure window"):
            verify_selected_route(
                route,
                quote,
                replace(request, latest_departure_date=START + timedelta(hours=1)),
                1800,
            )

    def test_http_returns_estimates_when_provider_is_unavailable(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        from backend.presentation.api import create_app

        self.pricer.quote.side_effect = ExactPricingUnavailable("no cache")
        with patch.dict("os.environ", {"APP_ACCESS_TOKEN": "test-secret"}), TestClient(
            create_app(self.search)
        ) as client:
            response = client.post(
                "/graphql",
                headers={"Authorization": "Bearer test-secret"},
                json={
                    "query": "query($input: RoundTripSearchInput!) { round_trip_options(input: $input) { total_price { amount currency } } }",
                    "variables": {
                        "input": {
                            "departure_city": "gn-1",
                            "departure_date": "2030-01-04T00:00:00Z",
                            "desired_arrival_date": "2030-01-07T00:00:00Z",
                            "time_tolerance": 4320,
                            "transport_types": ["PLANES"],
                        }
                    },
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("errors", payload)
        self.assertEqual(len(payload["extensions"]["estimated_routes"]), 7)
        self.assertEqual(payload["data"]["round_trip_options"], [])
