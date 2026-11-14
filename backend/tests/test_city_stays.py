"""Weighted approximate city stays without relaxing itinerary feasibility."""

from dataclasses import replace
from datetime import timedelta
import json
import unittest
from zoneinfo import ZoneInfo
from datetime import datetime

from backend.application.round_trip_search import (
    SearchLimits,
    city_stays,
    find_round_trips,
)
from backend.domain.planning import CityAttractiveness, JourneyOffer, RoundTrip, instant
from backend.infrastructure.fixtures.cities import CITY_LOCATIONS
from backend.infrastructure.graphql.models import RoundTripOption
from backend.infrastructure.graphql.round_trip import serialize_options
from backend.presentation.cli.round_trip import parse_settings
from test_round_trip import START, leg, offer, payload, settings


class CityStayTests(unittest.TestCase):
    def routes(self):
        # Identical route, price, movement time and return; different city allocation.
        return [
            offer("out", "A", "B", 0, 1),
            offer("balanced", "B", "C", 4, 5),
            offer("weighted", "B", "C", 6, 7),
            offer("home", "C", "A", 9, 10),
        ]

    def test_weights_rank_approximate_stays_and_keep_alternatives(self):
        request = settings(
            fuzzy_search=True,
            mandatory_cities=("B", "C"),
            city_attractiveness=(
                CityAttractiveness("B", 3),
                CityAttractiveness("C", 1),
            ),
        )
        result = find_round_trips(request, self.routes())
        self.assertEqual(len(result.options), 2)
        best, other = result.options
        self.assertEqual(best.offers[1].id, "weighted")
        self.assertGreater(best.stay_fit, other.stay_fit)
        # Seven hours for stays; ideal B:C = 5.25:1.75, actual = 5:2.
        self.assertAlmostEqual(best.stay_fit, 1 - 0.5 / 14)
        self.assertEqual(
            [
                (s.city, s.time_spent / 3600, s.target_time / 3600)
                for s in best.city_stays
            ],
            [("B", 5, 5.25), ("C", 2, 1.75)],
        )
        limited = find_round_trips(request, self.routes(), SearchLimits(max_results=1))
        self.assertEqual(limited.options, (best,))
        self.assertTrue(limited.results_limited)
        reversed_result = find_round_trips(request, reversed(self.routes()))
        self.assertEqual(result, reversed_result)

    def test_equal_defaults_and_price_first_compatibility(self):
        request = settings(fuzzy_search=True, mandatory_cities=("B", "C"))
        best = find_round_trips(request, self.routes()).options[0]
        self.assertEqual(best.offers[1].id, "balanced")
        self.assertEqual([s.attractiveness for s in best.city_stays], [1, 1])
        priced = self.routes()
        priced[2] = replace(
            priced[2], price=replace(priced[2].price, amount=priced[2].price.amount / 2)
        )
        fuzzy = find_round_trips(request, priced).options[0]
        self.assertEqual(fuzzy.offers[1].id, "balanced")
        self.assertGreater(fuzzy.total_price.amount, 25)
        old = find_round_trips(replace(request, fuzzy_search=False), priced).options[0]
        self.assertEqual(old.offers[1].id, "weighted")
        self.assertIsNone(old.stay_fit)

    def test_hard_duration_includes_initial_wait_and_intersects_return_window(self):
        request = settings(
            fuzzy_search=True, time_tolerance=120, max_trip_duration=10 * 3600
        )
        routes = [offer("out", "A", "B", 2, 3), offer("home", "B", "A", 9, 10)]
        self.assertTrue(find_round_trips(request, routes).options)
        self.assertFalse(
            find_round_trips(
                replace(request, max_trip_duration=10 * 3600 - 1), routes
            ).options
        )
        self.assertFalse(
            find_round_trips(
                replace(request, max_trip_duration=7 * 3600), routes
            ).options
        )
        best = find_round_trips(request, routes).options[0]
        self.assertEqual(best.city_stays[0].target_time, 6 * 3600)
        self.assertEqual(best.city_stays[0].time_spent, 6 * 3600)
        self.assertEqual(best.stay_fit, 1)
        self.assertFalse(
            find_round_trips(
                request, [routes[0], offer("late", "B", "A", 10, 11)]
            ).options
        )

    def test_bundled_connections_revisits_and_zero_time(self):
        bundle = JourneyOffer(
            "bundle",
            (leg("A", "B", 0, 1), leg("B", "C", 2, 3)),
            offer("x", "A", "B", 0, 1).price,
            "test",
            True,
        )
        routes = [bundle, offer("cb", "C", "B", 4, 5), offer("ba", "B", "A", 9, 10)]
        self.assertFalse(find_round_trips(settings(fuzzy_search=True), routes).options)
        best = find_round_trips(
            settings(fuzzy_search=True), routes, allow_city_revisits=True
        ).options[0]
        self.assertEqual(
            [(s.city, s.time_spent) for s in best.city_stays],
            [("B", 5 * 3600), ("C", 3600)],
        )
        self.assertEqual(sum(s.target_time for s in best.city_stays), 6 * 3600)
        self.assertEqual(best.total_price.amount, 30)  # bundle counted once
        zero = find_round_trips(
            settings(fuzzy_search=True),
            [offer("out", "A", "B", 0, 5), offer("back", "B", "A", 5, 10)],
        ).options[0]
        self.assertEqual(zero.city_stays[0].time_spent, 0)
        self.assertEqual(zero.stay_fit, 0)
        self.assertEqual(
            city_stays(RoundTrip((), zero.total_price), settings()), ((), 0)
        )

    def test_dst_gap_uses_elapsed_time_and_fractional_seconds(self):
        zone = ZoneInfo("Europe/Warsaw")
        first = replace(
            leg("A", "B", 0, 1),
            departure_at=datetime(2026, 10, 25, 1, 30, tzinfo=zone),
            arrival_at=datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=0),
        )
        second = replace(
            leg("B", "A", 2, 3),
            departure_at=datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=1),
            arrival_at=datetime(2026, 10, 25, 3, 30, tzinfo=zone),
        )
        original = offer("out", "A", "B", 0, 1)
        routes = [
            replace(original, path=(first,)),
            replace(original, id="back", path=(second,)),
        ]
        request = settings(
            departure_date=first.departure_at,
            desired_arrival_date=second.arrival_at,
            max_trip_duration=3 * 3600,
            fuzzy_search=True,
        )
        result = find_round_trips(request, routes).options[0]
        self.assertEqual(result.city_stays[0].time_spent, 3600)
        self.assertEqual(result.stay_fit, 1)
        offset = timedelta(microseconds=500000)
        routes[1] = replace(
            routes[1],
            path=(
                replace(
                    second,
                    departure_at=instant(second.departure_at) + offset,
                    arrival_at=instant(second.arrival_at) + offset,
                ),
            ),
        )
        result = find_round_trips(
            replace(request, time_tolerance=1, max_trip_duration=None), routes
        ).options[0]
        self.assertEqual(result.city_stays[0].time_spent, 3600.5)

    def test_fuzzy_preferences_never_override_hard_constraints(self):
        request = settings(fuzzy_search=True, mandatory_cities=("C",))
        self.assertFalse(find_round_trips(request, self.routes()[:1]).options)
        self.assertFalse(
            find_round_trips(
                replace(request, excluded_cities=("B",)), self.routes()
            ).options
        )
        self.assertTrue(
            find_round_trips(
                replace(
                    request,
                    expenses_tolerance=replace(
                        request.expenses_tolerance,
                        amount=request.expenses_tolerance.amount / 10,
                    ),
                ),
                self.routes(),
            ).options
        )

    def test_invalid_preferences_and_duration_at_boundaries(self):
        for value in (0, -1, True, float("nan"), float("inf"), "1"):
            with self.subTest(weight=value), self.assertRaises(ValueError):
                CityAttractiveness("B", value)
        for value in (0, -1, True, 1.5, 2**31):
            with self.subTest(duration=value), self.assertRaises(ValueError):
                settings(max_trip_duration=value)
        for values in (
            (CityAttractiveness("B", 1), CityAttractiveness("B", 2)),
            (CityAttractiveness("A", 1),),
        ):
            with self.assertRaises(ValueError):
                settings(city_attractiveness=values)
        with self.assertRaises(ValueError):
            settings(
                city_attractiveness=(CityAttractiveness("B", 1),),
                excluded_cities=("B",),
            )
        for weights in ((1e308, 1e308), (1e-300, 1e308)):
            result = find_round_trips(
                settings(
                    fuzzy_search=True,
                    mandatory_cities=("B", "C"),
                    city_attractiveness=tuple(
                        CityAttractiveness(city, weight)
                        for city, weight in zip(("B", "C"), weights)
                    ),
                ),
                self.routes(),
            )
            self.assertTrue(all(0 <= item.stay_fit <= 1 for item in result.options))

    def test_json_input_and_generated_output_round_trip(self):
        request = parse_settings(
            json.dumps(
                payload()
                | {
                    "fuzzy_search": True,
                    "max_trip_duration": 19 * 3600,
                    "city_attractiveness": [{"city": "pl-krakow", "weight": 3}],
                }
            )
        )
        routes = [
            offer("out", "pl-warsaw", "pl-krakow", 0, 3),
            offer("back", "pl-krakow", "pl-warsaw", 16, 19),
        ]
        result = serialize_options(
            find_round_trips(request, routes).options, CITY_LOCATIONS
        )[0]
        self.assertEqual(
            result["city_stays"],
            [
                {
                    "city": "pl-krakow",
                    "time_spent": 13 * 3600,
                    "target_time": 13 * 3600,
                    "attractiveness": 3,
                }
            ],
        )
        self.assertEqual(result["stay_fit"], 1)
        self.assertEqual(
            RoundTripOption.model_validate_json(json.dumps(result)).model_dump(
                mode="json", by_alias=True
            ),
            result,
        )
        for mutation in (
            {"fuzzy_search": None},
            {"fuzzy_search": 1},
            {"max_trip_duration": True},
            {"city_attractiveness": None},
            {"city_attractiveness": [{"city": "pl-krakow", "weight": 0}]},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                parse_settings(json.dumps(payload() | mutation))


if __name__ == "__main__":
    unittest.main()
