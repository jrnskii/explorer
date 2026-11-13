import hashlib
import math
import os
import re
import subprocess
import sys
import unittest
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import networkx as nx
from pydantic import BaseModel

from backend.infrastructure.ignav.models import AirportModel, PriceModel, SegmentModel
from backend.infrastructure.fixtures.network import (
    AirportLocation,
    MockFlightNetwork,
    MockNetworkFlight,
    generate_network,
)


def route_graph(network):
    graph = nx.DiGraph()
    graph.add_nodes_from(airport.code for airport in network.airports)
    graph.add_edges_from(
        (flight.segment.departure_airport, flight.segment.arrival_airport)
        for flight in network.flights
    )
    return graph


class MockNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = generate_network()

    def test_default_contract_and_connectivity(self):
        network = self.network
        self.assertIsInstance(network, BaseModel)
        self.assertIsInstance(network, MockFlightNetwork)
        self.assertEqual(network.seed, 0)
        self.assertIs(network.synthetic, True)
        self.assertEqual(len(network.airports), 100)
        self.assertEqual(len(network.flights), 100 * 4 * 2 * 7)
        codes = [airport.code for airport in network.airports]
        self.assertEqual(len(set(codes)), 100)
        self.assertEqual(set(codes), set(network.locations))
        for airport in network.airports:
            self.assertIsInstance(airport, AirportModel)
            self.assertRegex(airport.code, r"^[A-Z]{3}$")
            self.assertTrue(airport.name.startswith("Synthetic "))
            self.assertTrue(airport.city.startswith("Synthetic "))
            self.assertTrue(airport.country)
            location = network.locations[airport.code]
            self.assertIsInstance(location, AirportLocation)
            self.assertTrue(-90 <= location.latitude <= 90)
            self.assertTrue(-180 <= location.longitude <= 180)
            self.assertEqual(ZoneInfo(location.timezone).key, location.timezone)
        self.assertGreater(
            len({location.timezone for location in network.locations.values()}), 5
        )
        graph = route_graph(network)
        self.assertTrue(nx.is_strongly_connected(graph))
        self.assertEqual(graph.number_of_edges(), 400)
        self.assertEqual(list(nx.selfloop_edges(graph)), [])
        self.assertTrue(all(degree == 4 for _, degree in graph.out_degree()))

    def test_exact_daily_route_counts_and_unique_ids(self):
        network = self.network
        self.assertEqual(
            len({flight.id for flight in network.flights}), len(network.flights)
        )
        counts = Counter()
        for flight in network.flights:
            segment = flight.segment
            local_day = datetime.fromisoformat(segment.departure_time_local).date()
            self.assertTrue(
                network.start_date <= local_day < network.start_date + timedelta(days=7)
            )
            counts[segment.departure_airport, segment.arrival_airport, local_day] += 1
        self.assertEqual(len(counts), 100 * 4 * 7)
        self.assertEqual(set(counts.values()), {2})

    def test_prices_segments_and_distance_based_duration(self):
        for flight in self.network.flights:
            self.assertIsInstance(flight, MockNetworkFlight)
            self.assertIsInstance(flight.segment, SegmentModel)
            self.assertIsInstance(flight.price, PriceModel)
            self.assertTrue(math.isfinite(flight.price.amount))
            self.assertGreater(flight.price.amount, 0)
            self.assertEqual(flight.price.currency, "USD")
            self.assertEqual(flight.price.status, "unverified")
            segment = flight.segment
            self.assertTrue(segment.marketing_carrier_code)
            self.assertRegex(segment.flight_number, r"^[1-9][0-9]{0,3}$")
            self.assertTrue(segment.operating_carrier_name.startswith("Synthetic "))
            self.assertTrue(segment.aircraft)
            a = self.network.locations[segment.departure_airport]
            b = self.network.locations[segment.arrival_airport]
            lat_a, lat_b = math.radians(a.latitude), math.radians(b.latitude)
            h = (
                math.sin((lat_b - lat_a) / 2) ** 2
                + math.cos(lat_a)
                * math.cos(lat_b)
                * math.sin(math.radians(b.longitude - a.longitude) / 2) ** 2
            )
            distance = 12_742 * math.asin(math.sqrt(min(1, h)))
            self.assertGreaterEqual(
                segment.duration_minutes,
                max(35, round(25 + distance / 780 * 60 * 0.92)),
            )
            self.assertLessEqual(
                segment.duration_minutes,
                max(35, round(25 + distance / 780 * 60 * 1.10)),
            )

    def test_reproducibility_and_seed_variation(self):
        self.assertEqual(
            self.network.model_dump_json(), generate_network().model_dump_json()
        )
        other = generate_network(seed=1)
        self.assertNotEqual(self.network.airports, other.airports)
        self.assertNotEqual(self.network.locations, other.locations)
        self.assertNotEqual(
            set(route_graph(self.network).edges), set(route_graph(other).edges)
        )
        self.assertNotEqual(self.network.flights, other.flights)
        self.assertEqual(
            generate_network(seed=-10, airport_count=3, routes_per_airport=1, days=1),
            generate_network(seed=-10, airport_count=3, routes_per_airport=1, days=1),
        )

    def test_reproducibility_across_process_hash_seeds(self):
        kwargs = dict(seed=71, airport_count=9, routes_per_airport=3, days=2)
        expected = hashlib.sha256(
            generate_network(**kwargs).model_dump_json().encode()
        ).hexdigest()
        script = (
            "import hashlib; from backend.infrastructure.fixtures.network import generate_network; "
            "print(hashlib.sha256(generate_network(seed=71, airport_count=9, "
            "routes_per_airport=3, days=2).model_dump_json().encode()).hexdigest())"
        )
        for hash_seed in ("1", "12345"):
            with self.subTest(hash_seed=hash_seed):
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    env=dict(os.environ, PYTHONHASHSEED=hash_seed),
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                )
                self.assertEqual(result.stdout.strip(), expected)

    def test_schedule_changes_preserve_airports_and_topology(self):
        for overrides in (
            {"days": 1},
            {"days": 10},
            {"flights_per_route": 1},
            {"flights_per_route": 24, "days": 1},
            {"start_date": date(2026, 6, 20)},
        ):
            with self.subTest(overrides=overrides):
                other = generate_network(**overrides)
                self.assertEqual(self.network.airports, other.airports)
                self.assertEqual(self.network.locations, other.locations)
                self.assertEqual(
                    set(route_graph(self.network).edges), set(route_graph(other).edges)
                )

    def test_json_roundtrip(self):
        restored = MockFlightNetwork.model_validate_json(self.network.model_dump_json())
        self.assertEqual(restored, self.network)
        self.assertEqual(
            restored.to_graph().number_of_edges(), len(self.network.flights)
        )

    def test_graph_preserves_all_nodes_parallel_edges_and_weights(self):
        network = self.network
        graph = network.to_graph()
        self.assertIsInstance(graph, nx.MultiDiGraph)
        self.assertTrue(graph.is_directed())
        self.assertEqual(graph.number_of_nodes(), len(network.airports))
        self.assertEqual(graph.number_of_edges(), len(network.flights))
        self.assertTrue(nx.is_strongly_connected(graph))
        self.assertEqual(graph.graph, {"seed": 0, "synthetic": True})
        for airport in network.airports:
            self.assertEqual(
                graph.nodes[airport.code],
                dict(
                    airport.model_dump(), **network.locations[airport.code].model_dump()
                ),
            )
        for flight in network.flights:
            segment = flight.segment
            edge = graph[segment.departure_airport][segment.arrival_airport][flight.id]
            self.assertEqual(edge["id"], flight.id)
            self.assertEqual(edge["flight_id"], flight.id)
            self.assertEqual(edge["price"], flight.price.amount)
            self.assertEqual(edge["weight"], flight.price.amount)
            self.assertEqual(edge["currency"], flight.price.currency)
            self.assertEqual(edge["duration_minutes"], segment.duration_minutes)
            self.assertEqual(edge["departure_time_utc"], segment.departure_time_utc)
            self.assertEqual(edge["arrival_time_utc"], segment.arrival_time_utc)
            self.assertEqual(edge["segment"], segment.model_dump())
            self.assertEqual(
                graph.number_of_edges(
                    segment.departure_airport, segment.arrival_airport
                ),
                14,
            )
        first = network.flights[0]
        edge = graph[first.segment.departure_airport][first.segment.arrival_airport][
            first.id
        ]
        edge["segment"]["aircraft"] = "changed"
        self.assertNotEqual(first.segment.aircraft, "changed")
        self.assertNotEqual(
            network.to_graph()[first.segment.departure_airport][
                first.segment.arrival_airport
            ][first.id]["segment"]["aircraft"],
            "changed",
        )

    def test_utc_local_consistency_and_dst(self):
        # US/EU spring and autumn plus southern-hemisphere transitions.
        for start in (
            date(2026, 3, 7),
            date(2026, 3, 28),
            date(2026, 10, 24),
            date(2026, 10, 31),
            date(2026, 4, 4),
            date(2026, 10, 3),
        ):
            with self.subTest(start=start):
                network = generate_network(
                    airport_count=40,
                    routes_per_airport=1,
                    flights_per_route=24,
                    start_date=start,
                    days=3,
                )
                counts = Counter()
                offsets = {}
                for flight in network.flights:
                    segment = flight.segment
                    departure = datetime.fromisoformat(segment.departure_time_utc)
                    arrival = datetime.fromisoformat(segment.arrival_time_utc)
                    self.assertEqual(departure.utcoffset(), timedelta(0))
                    self.assertEqual(arrival.utcoffset(), timedelta(0))
                    self.assertGreater(arrival, departure)
                    self.assertEqual(
                        arrival - departure, timedelta(minutes=segment.duration_minutes)
                    )
                    for code, utc_time, local_string, zone_name in (
                        (
                            segment.departure_airport,
                            departure,
                            segment.departure_time_local,
                            segment.departure_timezone,
                        ),
                        (
                            segment.arrival_airport,
                            arrival,
                            segment.arrival_time_local,
                            segment.arrival_timezone,
                        ),
                    ):
                        self.assertEqual(zone_name, network.locations[code].timezone)
                        self.assertEqual(
                            utc_time.astimezone(ZoneInfo(zone_name)).isoformat(),
                            local_string,
                        )
                        self.assertEqual(
                            datetime.fromisoformat(local_string).astimezone(
                                timezone.utc
                            ),
                            utc_time,
                        )
                    local = datetime.fromisoformat(segment.departure_time_local)
                    self.assertTrue(start <= local.date() < start + timedelta(days=3))
                    counts[
                        segment.departure_airport, segment.arrival_airport, local.date()
                    ] += 1
                    offsets.setdefault(segment.departure_timezone, set()).add(
                        local.utcoffset()
                    )
                self.assertEqual(len(counts), 40 * 3)
                self.assertEqual(set(counts.values()), {24})
                self.assertTrue(
                    any(len(values) > 1 for values in offsets.values()),
                    "test must actually cross a DST offset change",
                )

    def test_integer_type_validation(self):
        defaults = dict(
            airport_count=3, routes_per_airport=1, flights_per_route=1, days=1
        )
        for name in (
            "seed",
            "airport_count",
            "routes_per_airport",
            "flights_per_route",
            "days",
        ):
            for value in (True, False, 1.0, "2", None):
                with (
                    self.subTest(name=name, value=value),
                    self.assertRaisesRegex(ValueError, name),
                ):
                    generate_network(**dict(defaults, **{name: value}))

    def test_range_and_date_validation(self):
        for overrides in (
            {"airport_count": 1},
            {"airport_count": 17_577},
            {"routes_per_airport": 0},
            {"routes_per_airport": 3},
            {"flights_per_route": 0},
            {"flights_per_route": 25},
            {"days": 0},
            {"days": 367},
            {"start_date": "2026-01-01"},
            {"start_date": None},
            {"start_date": True},
            {"start_date": datetime(2026, 1, 1)},
            {"start_date": date.max},
            {"start_date": date.min},
            {"start_date": date(9999, 12, 1), "days": 31},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                generate_network(
                    **dict(
                        airport_count=3,
                        routes_per_airport=1,
                        flights_per_route=1,
                        days=1,
                    )
                    | overrides
                )

    def test_small_ring_and_dense_boundaries(self):
        for n, routes, flights, days in (
            (2, 1, 1, 1),
            (2, 1, 24, 1),
            (2, 1, 1, 366),
            (12, 11, 1, 1),
        ):
            with self.subTest(n=n, routes=routes, flights=flights, days=days):
                network = generate_network(
                    airport_count=n,
                    routes_per_airport=routes,
                    flights_per_route=flights,
                    days=days,
                )
                graph = route_graph(network)
                self.assertTrue(nx.is_strongly_connected(graph))
                self.assertEqual(graph.number_of_edges(), n * routes)
                self.assertTrue(
                    all(degree == routes for _, degree in graph.out_degree())
                )
                self.assertEqual(len(network.flights), n * routes * flights * days)
                self.assertFalse(list(nx.selfloop_edges(graph)))

    def test_maximum_airport_count_sparse_request(self):
        network = generate_network(
            airport_count=17_576, routes_per_airport=1, flights_per_route=1, days=1
        )
        self.assertEqual(len(network.airports), 17_576)
        self.assertEqual(len({airport.code for airport in network.airports}), 17_576)
        self.assertTrue(
            all(re.fullmatch(r"[A-Z]{3}", airport.code) for airport in network.airports)
        )
        self.assertEqual(len(network.flights), 17_576)
        self.assertTrue(nx.is_strongly_connected(route_graph(network)))

    def test_flight_limit_rejected_before_random_generation(self):
        with patch("backend.infrastructure.fixtures.network.random.Random") as rng:
            with self.assertRaisesRegex(ValueError, "1,000,000"):
                generate_network(
                    airport_count=100,
                    routes_per_airport=99,
                    flights_per_route=24,
                    days=366,
                )
            rng.assert_not_called()
        # Check the inclusive production boundary without allocating a million
        # Pydantic objects: accepted input must reach the first RNG construction.
        with patch(
            "backend.infrastructure.fixtures.network.random.Random", side_effect=RuntimeError("accepted")
        ):
            with self.assertRaisesRegex(RuntimeError, "accepted"):
                generate_network(
                    airport_count=100,
                    routes_per_airport=10,
                    flights_per_route=10,
                    days=100,
                )
        with patch("backend.infrastructure.fixtures.network._MAX_FLIGHTS", 12):
            self.assertEqual(
                len(
                    generate_network(
                        airport_count=3,
                        routes_per_airport=2,
                        flights_per_route=2,
                        days=1,
                    ).flights
                ),
                12,
            )
            with self.assertRaises(ValueError):
                generate_network(
                    airport_count=3, routes_per_airport=2, flights_per_route=2, days=2
                )


if __name__ == "__main__":
    unittest.main()
