"""Scheduled solver, mock-provider and JSON CLI regression coverage."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

from backend.application.round_trip_search import SearchLimits, find_round_trips
from backend.domain.planning import JourneyOffer, Money, SearchSettings, TripLeg
from backend.domain.travel import TransportType as Mode
from backend.infrastructure.fixtures.round_trip import (
    mock_offers,
    StaticTransportPrices,
)
from backend.presentation.cli.round_trip import parse_settings

START = datetime(2026, 12, 1, tzinfo=timezone.utc)


def settings(**changes):
    return replace(
        SearchSettings(
            "A",
            START,
            START + timedelta(hours=10),
            0,
            Money(Decimal("100"), "USD"),
            tuple(Mode),
        ),
        **changes,
    )


def leg(a, b, departure, arrival, mode=Mode.TRAINS):
    return TripLeg(
        a, b, START + timedelta(hours=departure), START + timedelta(hours=arrival), mode
    )


def offer(id, a, b, departure, arrival, price="10", mode=Mode.TRAINS):
    return JourneyOffer(
        id,
        (leg(a, b, departure, arrival, mode),),
        Money(Decimal(price), "USD"),
        "test",
        True,
    )


def payload():
    return {
        "departure_city": "pl-warsaw",
        "departure_date": "2026-12-01T00:00:00Z",
        "desired_arrival_date": "2026-12-01T19:00:00Z",
        "time_tolerance": 0,
        "expenses_tolerance": {"amount": "100.00", "currency": "USD"},
        "transport_types": ["TRAINS"],
        "mandatory_cities": ["pl-krakow"],
    }


class SolverTests(unittest.TestCase):
    def test_minimum_distinct_cities_excludes_home_and_allows_more(self):
        offers = [offer("ab", "A", "B", 0, 1),
                  offer("ba", "B", "A", 9, 10),
                  offer("bc", "B", "C", 2, 3),
                  offer("ca", "C", "A", 9, 10)]
        self.assertEqual(len(find_round_trips(settings(), offers).options), 2)
        result = find_round_trips(settings(min_cities=2), offers)
        self.assertEqual(len(result.options), 1)
        self.assertEqual([l.destination for l in result.options[0].path], ["B", "C", "A"])
        self.assertEqual(find_round_trips(settings(min_cities=3), offers).options, ())

    def test_minimum_cities_counts_internal_connections_once_across_revisits(self):
        bundled = JourneyOffer("bundle", (leg("A", "B", 0, 1), leg("B", "C", 2, 3)),
                                Money(Decimal("10"), "USD"), "test", True)
        offers = [bundled, offer("cb", "C", "B", 4, 5), offer("ba", "B", "A", 9, 10)]
        self.assertEqual(len(find_round_trips(settings(min_cities=2), offers, allow_city_revisits=True).options), 1)
        self.assertEqual(find_round_trips(settings(min_cities=3), offers, allow_city_revisits=True).options, ())

    def test_minimum_cities_requires_positive_graphql_integer(self):
        for value in (0, -1, True, None, 1.5, "2", 2**31):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings(min_cities=value)


    def test_lazy_index_matches_exhaustive_price_order(self):
        supplied = [offer("ab", "A", "B", 0, 1, "1"), offer("ba", "B", "A", 9, 10, "1"),
                    offer("ac", "A", "C", 0, 1, "2"), offer("ca", "C", "A", 9, 10, "2"),
                    offer("bc", "B", "C", 2, 3, "0.1"), offer("cb", "C", "B", 2, 3, "0.1")]
        class Index:
            def __init__(self):
                self.calls = []
            def outgoing(self, city):
                self.calls.append(city)
                return tuple(o for o in supplied if o.path[0].origin == city)
            def reverse_connections(self):
                reverse = {}
                for o in supplied:
                    reverse.setdefault(o.path[-1].destination, set()).add(o.path[0].origin)
                return reverse
        for count in (1, 2, 20):
            with self.subTest(count=count):
                index = Index()
                limits = SearchLimits(max_results=count)
                expected = find_round_trips(settings(), supplied, limits)
                actual = find_round_trips(settings(), (), limits, offer_index=index)
                self.assertEqual(actual.options, expected.options)
                self.assertEqual(len(index.calls), len(set(index.calls)))
                self.assertFalse(actual.truncation_reasons)

    def test_lazy_transition_budget_is_explicit(self):
        class Index:
            def outgoing(self, city):
                return (offer("ab", "A", "B", 0, 1),) if city == "A" else (offer("ba", "B", "A", 9, 10),)
            def reverse_connections(self):
                return {"A": {"B"}, "B": {"A"}}
        result = find_round_trips(settings(), (), offer_index=Index(), max_transitions=1)
        self.assertIn("max_transitions", result.truncation_reasons)
        self.assertEqual(result.options, ())

    def test_completed_routes_survive_budget_exhaustion_in_dense_schedule(self):
        class Index:
            def outgoing(self, city):
                if city == "A":
                    return tuple(offer(f"out-{i}", "A", "B", 0, 1, "1") for i in range(100))
                return (offer("back", "B", "A", 9, 10, "1"),)

            def reverse_connections(self):
                return {"A": {"B"}, "B": {"A"}}

        for limits, budget, expected_reason in (
            (SearchLimits(), 101, "max_transitions"),
            (SearchLimits(max_states=2), None, "max_states"),
        ):
            with self.subTest(reason=expected_reason):
                result = find_round_trips(settings(), (), limits, offer_index=Index(), max_transitions=budget)
                self.assertIn(expected_reason, result.truncation_reasons)
                self.assertEqual(len(result.options), 1)
                self.assertEqual(result.options[0].total_price.amount, Decimal("2"))
                self.assertEqual([leg.destination for leg in result.options[0].path], ["B", "A"])

    def test_revisits_skipped_by_default_but_final_return_home_allowed(self):
        offers = [
            offer("out", "A", "B", 0, 1),
            offer("bc", "B", "C", 2, 3),
            offer("cb", "C", "B", 4, 5),
            offer("home", "B", "A", 9, 10),
        ]
        result = find_round_trips(settings(), offers)
        self.assertEqual([tuple(o.id for o in r.offers) for r in result.options], [("out", "home")])
        self.assertFalse(result.truncation_reasons)
        revisits = find_round_trips(settings(), offers, allow_city_revisits=True)
        self.assertEqual(len(revisits.options), 2)

    def test_internal_ticket_arrivals_cannot_repeat_any_visited_city(self):
        out = offer("out", "A", "B", 0, 1)
        home = offer("home", "C", "A", 9, 10)
        for path in (
            (leg("B", "C", 2, 3), leg("C", "B", 4, 5), leg("B", "C", 6, 7)),
            (leg("B", "B", 2, 3), leg("B", "C", 4, 5)),
        ):
            with self.subTest(path=path):
                bundle = replace(out, id="bundle", path=path)
                offers = [out, bundle, home]
                self.assertFalse(find_round_trips(settings(), offers).options)
                self.assertTrue(find_round_trips(settings(), offers, allow_city_revisits=True).options)

    def test_internal_connection_counts_as_visited_on_later_tickets(self):
        bundle = replace(offer("out", "A", "B", 0, 1),
                         path=(leg("A", "C", 0, 1), leg("C", "B", 2, 3)))
        offers = [bundle, offer("bc", "B", "C", 4, 5), offer("home", "C", "A", 9, 10)]
        self.assertFalse(find_round_trips(settings(), offers).options)
        self.assertTrue(find_round_trips(settings(), offers, allow_city_revisits=True).options)

    def test_visits_are_per_branch_and_bundled_final_home_is_allowed(self):
        offers = [offer("slow", "A", "B", 0, 2), offer("fast", "A", "B", 0, 1)]
        bundle = replace(offers[0], id="home",
                         path=(leg("B", "C", 3, 4), leg("C", "A", 9, 10)))
        result = find_round_trips(settings(), [*offers, bundle])
        self.assertEqual(len(result.options), 2)
        self.assertEqual({r.offers[0].id for r in result.options}, {"slow", "fast"})

    def test_revisit_flag_must_be_boolean(self):
        for value in (None, 0, 1, "false"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "boolean"):
                find_round_trips(settings(), [], allow_city_revisits=value)

    def test_price_then_movement_time_parallel_edges_and_budget(self):
        offers = [
            offer("slow", "A", "B", 0, 4),
            offer("fast", "A", "B", 1, 2),
            offer("cheap", "A", "B", 0, 1, "9.99"),
            offer("return", "B", "A", 9, 10),
        ]
        result = find_round_trips(settings(), offers)
        self.assertEqual(
            [r.offers[0].id for r in result.options], ["cheap", "fast", "slow"]
        )
        self.assertEqual(
            find_round_trips(
                settings(expenses_tolerance=Money(Decimal("19.99"), "USD")), offers
            )
            .options[0]
            .total_price.amount,
            Decimal("19.99"),
        )
        self.assertEqual(
            len(
                find_round_trips(
                    settings(expenses_tolerance=Money(Decimal("19.98"), "USD")), offers
                ).options
            ),
            3,
        )

    def test_required_cities_excluded_internal_connections_bundle_price_once(self):
        bundle = JourneyOffer(
            "bundle",
            (leg("A", "C", 0, 1), leg("C", "B", 2, 3)),
            Money(Decimal("15"), "USD"),
            "test",
            True,
        )
        offers = [bundle, offer("back", "B", "A", 9, 10)]
        result = find_round_trips(settings(mandatory_cities=("B", "C")), offers)
        self.assertEqual(result.options[0].total_price.amount, Decimal("25"))
        self.assertEqual(len(result.options[0].path), 3)
        self.assertFalse(
            find_round_trips(settings(excluded_cities=("C",)), offers).options
        )
        self.assertFalse(
            find_round_trips(settings(mandatory_cities=("D",)), offers).options
        )

    def test_chronology_return_window_earliest_and_first_return(self):
        outbound = offer("out", "A", "B", 1, 3)
        self.assertFalse(
            find_round_trips(
                settings(), [outbound, offer("missed", "B", "A", 2, 10)]
            ).options
        )
        self.assertFalse(
            find_round_trips(
                settings(),
                [offer("early", "A", "B", -1, 1), offer("back", "B", "A", 9, 10)],
            ).options
        )
        self.assertTrue(
            find_round_trips(
                settings(time_tolerance=60), [outbound, offer("back", "B", "A", 8, 9)]
            ).options
        )
        offers = [
            outbound,
            offer("back", "B", "A", 4, 5),
            offer("again", "A", "C", 6, 7),
            offer("last", "C", "A", 9, 10),
        ]
        self.assertFalse(
            find_round_trips(settings(mandatory_cities=("B", "C")), offers).options
        )

    def test_modes_empty_results_and_upper_window_boundary(self):
        offers = [
            offer("out", "A", "B", 0, 1, mode=Mode.BUSSES),
            offer("back", "B", "A", 9, 11),
        ]
        self.assertFalse(find_round_trips(settings(), offers).options)
        self.assertTrue(find_round_trips(settings(time_tolerance=60), offers).options)
        self.assertFalse(
            find_round_trips(
                settings(time_tolerance=60, transport_types=(Mode.TRAINS,)), offers
            ).options
        )
        self.assertFalse(find_round_trips(settings(), []).options)

    def test_state_budget_bounds_cyclic_schedule(self):
        offers = []
        for hour in range(20):
            offers.append(offer(f"bc-{hour}", "B", "C", hour, hour + 0.25, "0"))
            offers.append(offer(f"cb-{hour}", "C", "B", hour + 0.5, hour + 0.75, "0"))
        offers += [offer("out", "A", "B", 0, 0.25), offer("home", "C", "A", 19, 20)]
        result = find_round_trips(
            settings(desired_arrival_date=START + timedelta(hours=20)),
            offers,
            SearchLimits(max_states=25, max_legs=100),
            allow_city_revisits=True,
        )
        self.assertEqual(result.states_explored, 25)
        self.assertIn("max_states", result.truncation_reasons)

    def test_exact_decimal_and_duplicate_identity(self):
        offers = [
            offer("out", "A", "B", 0, 1, "0.123456789012345678901234567890"),
            offer("back", "B", "A", 9, 10, "0.000000000000000000000000000001"),
        ]
        result = find_round_trips(settings(), offers + offers)
        self.assertEqual(len(result.options), 1)
        self.assertEqual(
            result.options[0].total_price.amount,
            Decimal("0.123456789012345678901234567891"),
        )
        with self.assertRaisesRegex(ValueError, "identity"):
            find_round_trips(
                settings(),
                offers + [replace(offers[0], price=Money(Decimal(1), "USD"))],
            )
        with self.assertRaisesRegex(ValueError, "currency"):
            find_round_trips(
                settings(), [replace(offers[0], price=Money(Decimal(1), "EUR"))]
            )

    def test_limits_are_explicit_and_top_k_is_not_early_stop(self):
        offers = [
            offer("out", "A", "B", 0, 1),
            offer("expensive", "B", "A", 9, 10, "30"),
            offer("cheap", "B", "A", 9, 10, "1"),
        ]
        result = find_round_trips(settings(), offers, SearchLimits(max_results=1))
        self.assertEqual(result.options[0].total_price.amount, 11)
        self.assertTrue(result.results_limited)
        self.assertIn(
            "max_states",
            find_round_trips(
                settings(), offers, SearchLimits(max_states=1)
            ).truncation_reasons,
        )
        self.assertIn(
            "max_legs",
            find_round_trips(
                settings(), offers, SearchLimits(max_legs=1)
            ).truncation_reasons,
        )

    def test_exhaustive_small_schedule_oracle(self):
        offers = [
            offer("ab", "A", "B", 0, 1),
            offer("ac", "A", "C", 1, 2, "3"),
            offer("bc", "B", "C", 3, 4, "2"),
            offer("ba", "B", "A", 9, 10),
            offer("ca", "C", "A", 9, 10),
        ]
        expected = set()
        for length in range(1, 4):
            for path in itertools.permutations(offers, length):
                if (
                    path[0].path[0].origin != "A"
                    or path[-1].path[-1].destination != "A"
                ):
                    continue
                if any(
                    a.path[-1].destination != b.path[0].origin
                    or a.path[-1].arrival_at > b.path[0].departure_at
                    or a.path[-1].destination == "A"
                    for a, b in zip(path, path[1:])
                ):
                    continue
                expected.add(tuple(item.id for item in path))
        actual = find_round_trips(settings(), offers)
        self.assertEqual(
            {tuple(item.id for item in option.offers) for option in actual.options},
            expected,
        )

    def test_dst_duration_uses_instants_and_invalid_movements_fail(self):
        zone = ZoneInfo("Europe/Warsaw")
        movement = TripLeg(
            "A",
            "B",
            datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=0),
            datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=1),
            Mode.TRAINS,
        )
        self.assertEqual(movement.time_in_travel, 3600)
        for arrival in (0, -1):
            with self.assertRaises(ValueError):
                leg("A", "B", 0, arrival)
        with self.assertRaises(ValueError):
            replace(movement, departure_at=datetime(2026, 1, 1))


class BoundaryAndProviderTests(unittest.TestCase):
    def test_invalid_schema_constraints(self):
        mutations = [
            *({"min_cities": value} for value in (0, -1, True, None, 1.5, "2", 2**31)),
            {"time_tolerance": -1},
            {"time_tolerance": True},
            {"transport_types": []},
            {"mandatory_cities": ["pl-krakow", "pl-krakow"]},
            {"excluded_cities": ["pl-warsaw"]},
            {"departure_city": " "},
            {"departure_date": "2026-12-01T00:00:00"},
            {"desired_arrival_date": "2026-11-01T00:00:00Z"},
            {"expenses_tolerance": {"amount": "-1", "currency": "USD"}},
            {"expenses_tolerance": {"amount": 1, "currency": "USD"}},
            {"transport_types": ["TRAINS", "TRAINS"]},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                parse_settings(json.dumps(payload() | mutation))

    def test_static_prices_and_multimodal_provider_reproducibility(self):
        self.assertEqual(StaticTransportPrices.train(250).amount, Decimal("28.00"))
        self.assertEqual(StaticTransportPrices.bus(100).amount, Decimal("9.00"))
        self.assertEqual(StaticTransportPrices.ferry(100).amount, Decimal("25.00"))
        with self.assertRaises(ValueError):
            StaticTransportPrices.train(-1)
        request = parse_settings(
            json.dumps(payload() | {"transport_types": [mode.value for mode in Mode]})
        )
        offers = mock_offers(request, seed=42, count=4)
        self.assertEqual(offers, mock_offers(request, seed=42, count=4))
        self.assertEqual(
            {leg.transport_type for offer in offers for leg in offer.path}, set(Mode)
        )
        self.assertTrue(all(item.synthetic for item in offers))
        self.assertTrue(any(item.source == "mock-ignav" for item in offers))
        with self.assertRaisesRegex(ValueError, "USD"):
            mock_offers(replace(request, expenses_tolerance=Money(Decimal(100), "EUR")))

    def test_cli_success_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(payload()))
            command = [
                sys.executable,
                "-m",
                "backend.presentation.cli.round_trip",
                "--request",
                str(path),
                "--pricing",
                "mock",
            ]
            actual = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(actual.returncode, 0, actual.stderr)
            result = json.loads(actual.stdout)
            self.assertTrue(result["synthetic"])
            self.assertEqual(result["options"][0]["total_price"]["amount"], "56.00")
            self.assertEqual(result["options"][0]["path"][0]["from"], "pl-warsaw")
            self.assertEqual(actual.stderr, "")
            for invalid in ("{", "null", "[]", "{}"):
                path.write_text(invalid)
                failed = subprocess.run(
                    command, capture_output=True, text=True, timeout=30
                )
                self.assertEqual(failed.returncode, 2)
                self.assertEqual(failed.stdout, "")
                self.assertIn("round-trip:", failed.stderr)
                self.assertNotIn("Traceback", failed.stderr)


class VilniusDemoTests(unittest.TestCase):
    def test_demo_logs_actions_and_skips_repeated_warsaw_by_default(self):
        command = [sys.executable, "-m", "backend.presentation.cli.round_trip_demo"]
        actual = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        result = json.loads(actual.stdout)
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["departure_city"], "lt-vilnius")
        self.assertEqual(result["truncation_reasons"], [])
        self.assertEqual(result["options"], [])
        self.assertIn("city already visited", actual.stderr)
        for action in (
            "Loading deterministic demo settings",
            "Mock BUSSES price lookup",
            "Mock TRAINS price lookup",
            "Mock Ignav lookup",
            "Mock Ignav returned",
            "Inspect offer=",
            "Index offer=",
            "Explore state=",
            "Consider next ticket=",
            "Expand ticket=",
            "Skip ticket=",
            "Search finished",
            "Serializing",
            "Demo complete",
        ):
            self.assertIn(action, actual.stderr)
        repeated = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(repeated.stdout, actual.stdout)
        # Action messages are deterministic; timing and per-run correlation IDs vary.
        def actions(stderr):
            return [line.split('span_id=', 1)[1].split(' ', 1)[1].rsplit(' {', 1)[0]
                    for line in stderr.splitlines()]

        self.assertEqual(actions(repeated.stderr), actions(actual.stderr))

    def test_demo_can_explicitly_allow_city_revisits(self):
        actual = subprocess.run(
            [sys.executable, "-m", "backend.presentation.cli.round_trip_demo", "--allow-city-revisits"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(actual.returncode, 0, actual.stderr)
        options = json.loads(actual.stdout)["options"]
        self.assertEqual(options[0]["total_price"]["amount"], "98.00")
        for option in options:
            self.assertEqual([leg["to"] for leg in option["path"]].count("pl-warsaw"), 2)
