"""Static EU multimodal imports use route evidence and never copy fares/times."""

import csv
import json
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

import duckdb
import networkx as nx

from backend.infrastructure.catalog.base_graph import build_base_graph
from backend.infrastructure.catalog.graph_snapshot import load_base_graph
from backend.infrastructure.catalog.static_transport import (
    EU_COUNTRIES,
    GTFS_SECONDS_MACRO,
    CityIndex,
    distance_km,
    gtfs_mode,
)
from backend.infrastructure.fixtures.combine_mobilitydatabase import initialize


class StaticTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.cities = self.directory / "Cities.csv"
        with self.cities.open("w") as stream:
            writer = csv.writer(stream)
            writer.writerow(["city", "country", "population", "latitude", "longitude"])
            writer.writerows(
                [
                    ["Paris", "France", 1, 48.85, 2.35],
                    ["Berlin", "Germany", 2, 52.52, 13.405],
                    ["London", "United Kingdom", 3, 51.5, -0.1],
                    ["Isolated", "Malta", 0, 35.8, 14.4],
                ]
            )
        self.routes = self.directory / "airline_routes.json"
        self.routes.write_text(
            json.dumps(
                {
                    "CDG": {
                        "iata": "CDG",
                        "country": "France",
                        "city_name": "Paris",
                        "routes": [
                            {
                                "iata": "BER",
                                "carriers": [{"iata": "AF"}],
                                "price": 999,
                                "min": 12,
                            }
                        ],
                    },
                    "BER": {
                        "iata": "BER",
                        "country": "Germany",
                        "city_name": "Berlin",
                        "routes": [],
                    },
                }
            )
        )
        self.stations = self.directory / "stations.csv"
        with self.stations.open("w") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "id",
                    "name",
                    "country",
                    "latitude",
                    "longitude",
                    "is_city",
                    "parent_station_id",
                ]
            )
            writer.writerows(
                [
                    ["1", "Dijon", "FR", 47.32, 5.04, "TRUE", "NA"],
                    ["2", "Dijon Ville", "FR", 47.32, 5.04, "FALSE", "1"],
                    ["3", "London", "GB", 51.5, -0.1, "TRUE", "NA"],
                ]
            )
        self.db_path = self.directory / "schedules.duckdb"
        with duckdb.connect(str(self.db_path)) as db:
            initialize(db)
            for feed in ["one", "two"]:
                db.execute(
                    "INSERT INTO feeds VALUES (?, ?, ?, 0)", [feed, feed + ".zip", feed]
                )
                for route, kind in [("rail", "2"), ("bus", "3"), ("ferry", "1000")]:
                    db.execute(
                        "INSERT INTO routes(feed_id, route_id, route_type, agency_id) VALUES (?, ?, ?, ?)",
                        [feed, route, kind, "operator"],
                    )
                for stop, lat, lon in [
                    ("a", "48.85", "2.35"),
                    ("b", "52.52", "13.405"),
                    ("unknown", "0", "0"),
                ]:
                    db.execute(
                        "INSERT INTO stops(feed_id, stop_id, stop_lat, stop_lon) VALUES (?, ?, ?, ?)",
                        [feed, stop, lat, lon],
                    )
                for trip, route, stops in [
                    ("train", "rail", ["a", "a", "b"]),
                    ("repeat", "rail", ["a", "b"]),
                    ("bus", "bus", ["a", "b"]),
                    ("ferry", "ferry", ["b", "a"]),
                    ("gap", "bus", ["b", "unknown", "a"]),
                ]:
                    db.execute(
                        "INSERT INTO trips(feed_id, trip_id, route_id) VALUES (?, ?, ?)",
                        [feed, trip, route],
                    )
                    for i, stop in enumerate(stops):
                        # Reverse insertion and double-digit sequences check numeric ordering.
                        db.execute(
                            "INSERT INTO stop_times(feed_id, trip_id, stop_id, stop_sequence, arrival_time) VALUES (?, ?, ?, ?, ?)",
                            [feed, trip, stop, str((i + 1) * 10), "12:00:00"],
                        )

    def build(self):
        return build_base_graph(
            self.cities,
            self.routes,
            stations_path=self.stations,
            schedules_path=self.db_path,
        )

    def test_eu_cities_and_parallel_modes_are_static(self):
        graph = self.build()
        self.assertEqual(len(EU_COUNTRIES), 27)
        nodes = {a["name"]: n for n, a in graph.nodes(data=True)}
        self.assertEqual(set(nodes), {"Paris", "Berlin", "Dijon", "Isolated"})
        self.assertEqual(graph.nodes[nodes["Paris"]]["population"], 1)
        self.assertIsNone(graph.nodes[nodes["Dijon"]]["population"])
        self.assertEqual(graph.nodes[nodes["Isolated"]]["population"], 0)
        self.assertTrue(
            all(a["attractiveness"] == 1 for _, a in graph.nodes(data=True))
        )
        self.assertEqual(graph.graph["cities_without_population"], 1)
        edges = list(graph[nodes["Paris"]][nodes["Berlin"]].values())
        self.assertEqual(len(edges), 5)  # Air + rail/bus for each feed.
        self.assertEqual({e["mode"] for e in edges}, {"PLANES", "TRAINS", "BUSSES"})
        reverse = list(graph[nodes["Berlin"]][nodes["Paris"]].values())
        self.assertEqual(len(reverse), 2)
        self.assertEqual({e["mode"] for e in reverse}, {"FERRIES"})
        for _, _, edge in graph.edges(data=True):
            self.assertGreater(edge["distance_km"], 0)
            self.assertEqual(edge["distance_basis"], "city_centres_great_circle")
            self.assertFalse(
                {
                    "price",
                    "fare",
                    "currency",
                    "arrival_time",
                    "departure_time",
                    "duration",
                }
                & edge.keys()
            )
        self.assertEqual(
            graph.graph["terminals"]["station:2"]["city_id"], nodes["Dijon"]
        )
        self.assertEqual(graph.graph["gtfs_feed_count"], 2)
        self.assertEqual(graph.graph["gtfs_mapping_counts"]["unmapped_coordinates"], 2)
        self.assertTrue(graph.graph["static_only"])
        self.assertFalse(graph.graph["live_search_eligible"])

    def test_repeatability_serialization_and_input_unchanged(self):
        before = self.db_path.read_bytes()
        graph = self.build()
        self.assertEqual(nx.node_link_data(graph), nx.node_link_data(self.build()))
        restored = nx.node_link_graph(json.loads(json.dumps(nx.node_link_data(graph))))
        self.assertEqual(nx.node_link_data(graph), nx.node_link_data(restored))
        for u, v, key, attrs in graph.edges(keys=True, data=True):
            self.assertEqual(restored[u][v][key], attrs)
        self.assertEqual(before, self.db_path.read_bytes())

    def test_mode_specific_times_and_minimum_scheduled_duration(self):
        with duckdb.connect(str(self.db_path)) as db:
            for trip, times in {
                "train": [
                    ("23:00:00", "23:10:00"),
                    ("23:40:00", "23:50:00"),
                    ("25:05:00", "25:10:00"),
                ],
                "repeat": [("24:00:00", "24:00:00"), ("24:45:00", "24:50:00")],
                "bus": [("8:00:00", "8:00:00"), ("9:30:00", "9:30:00")],
                "ferry": [("10:00:00", "10:00:00"), ("12:00:00", "12:00:00")],
            }.items():
                for seq, (arrival, departure) in enumerate(times, 1):
                    db.execute(
                        "UPDATE stop_times SET arrival_time=?, departure_time=? WHERE feed_id='one' AND trip_id=? AND stop_sequence=?",
                        [arrival, departure, trip, str(seq * 10)],
                    )
        graph = self.build()
        modes = {
            e["mode"]: e
            for _, _, e in graph.edges(data=True)
            if e.get("feed_id") == "one"
        }
        self.assertEqual(modes["TRAINS"]["travel_time_minutes"], 45)
        self.assertEqual(modes["TRAINS"]["travel_time_samples"], 2)
        self.assertEqual(modes["BUSSES"]["travel_time_minutes"], 90)
        self.assertEqual(modes["FERRIES"]["travel_time_minutes"], 120)
        self.assertEqual(
            modes["TRAINS"]["travel_time_basis"], "gtfs_min_scheduled_stop_pair"
        )
        plane = next(e for _, _, e in graph.edges(data=True) if e["mode"] == "PLANES")
        self.assertEqual(plane["travel_time_minutes"], 12)
        self.assertEqual(plane["travel_time_basis"], "airline_route_reference_minutes")
        self.assertEqual(
            graph.graph["weight_attributes"], ["distance_km", "travel_time_minutes"]
        )
        self.assertEqual(graph.graph["schema_version"], 4)

    def test_missing_invalid_negative_and_zero_durations_preserve_connections(self):
        for arrival, departure, expected in [
            (None, None, None),
            ("bad", "bad", None),
            ("12:00:00", "13:00:00", None),
            ("12:00:00", "12:00:00", 0),
            ("25:00:30", "23:59:30", 61),
        ]:
            with self.subTest(arrival=arrival, departure=departure):
                with duckdb.connect(str(self.db_path)) as db:
                    db.execute(
                        "UPDATE stop_times SET arrival_time=?, departure_time=? WHERE trip_id='bus' AND stop_id='a'",
                        [departure, departure],
                    )
                    db.execute(
                        "UPDATE stop_times SET arrival_time=?, departure_time=? WHERE trip_id='bus' AND stop_id='b'",
                        [arrival, arrival],
                    )
                graph = self.build()
                buses = [
                    e for _, _, e in graph.edges(data=True) if e["mode"] == "BUSSES"
                ]
                self.assertEqual(len(buses), 2)
                for edge in buses:
                    self.assertEqual(edge["travel_time_minutes"], expected)
                    self.assertEqual(
                        edge["travel_time_samples"], int(expected is not None)
                    )
                    self.assertEqual(
                        edge["travel_time_basis"] == "unknown", expected is None
                    )

    def test_gtfs_service_day_parser_is_not_wall_clock_time(self):
        with duckdb.connect() as db:
            db.execute(GTFS_SECONDS_MACRO)
            for value, expected in [
                ("1:02:03", 3723),
                ("25:00:00", 90000),
                ("49:00:00", 176400),
                ("00:00:00", 0),
                ("12:60:00", None),
                ("12:00:60", None),
                ("-1:00:00", None),
                ("12:00", None),
                ("NaN", None),
                ("999999999999999999999:00:00", None),
                ("9223372036854775807:00:00", None),
                (None, None),
            ]:
                with self.subTest(value=value):
                    self.assertEqual(
                        db.execute("SELECT gtfs_seconds(?)", [value]).fetchone()[0],
                        expected,
                    )

    def test_duplicate_flight_durations_use_valid_minimum_and_missing_stays_unknown(
        self,
    ):
        payload = json.loads(self.routes.read_text())
        route = payload["CDG"]["routes"][0]
        for value in [None, "invalid", True, -1, float("inf")]:
            with self.subTest(value=value):
                route["min"] = value
                self.routes.write_text(json.dumps(payload))
                graph = self.build()
                plane = next(
                    e for _, _, e in graph.edges(data=True) if e["mode"] == "PLANES"
                )
                self.assertIsNone(plane["travel_time_minutes"])
                self.assertEqual(plane["travel_time_samples"], 0)
        route["min"] = 80
        payload["CDG"]["routes"].append(dict(route, min=65))
        self.routes.write_text(json.dumps(payload))
        plane = next(
            e for _, _, e in self.build().edges(data=True) if e["mode"] == "PLANES"
        )
        self.assertEqual(plane["travel_time_minutes"], 65)
        self.assertEqual(plane["travel_time_samples"], 2)

    def test_invalid_and_missing_sources(self):
        self.stations.write_text("bad,columns\n1,2\n")
        with self.assertRaisesRegex(ValueError, "Station CSV"):
            self.build()
        with self.assertRaisesRegex(ValueError, "does not exist"):
            build_base_graph(
                self.cities,
                self.routes,
                stations_path=None,
                schedules_path=self.directory / "missing.duckdb",
            )

    def test_bad_sequence_does_not_bridge_and_duplicate_sequence_is_ambiguous(self):
        with duckdb.connect(str(self.db_path)) as db:
            for trip, seqs in [
                ("bad", ["10", "bad", "30"]),
                ("duplicate", ["10", "20", "20", "30"]),
            ]:
                db.execute(
                    "INSERT INTO trips(feed_id, trip_id, route_id) VALUES ('one', ?, 'bus')",
                    [trip],
                )
                stops = ["b", "unknown", "a"] if trip == "bad" else ["b", "a", "b", "a"]
                for seq, stop in zip(seqs, stops, strict=True):
                    db.execute(
                        "INSERT INTO stop_times(feed_id, trip_id, stop_id, stop_sequence) VALUES ('one', ?, ?, ?)",
                        [trip, stop, seq],
                    )
        graph = self.build()
        self.assertFalse(
            any(
                edge["mode"] == "BUSSES" and graph.nodes[u]["name"] == "Berlin"
                for u, _, edge in graph.edges(data=True)
            )
        )

    def test_full_cli_and_missing_schedule_error(self):
        command = [
            sys.executable,
            "-m",
            "backend.presentation.cli.base_graph",
            "--cities",
            str(self.cities),
            "--routes",
            str(self.routes),
            "--stations",
            str(self.stations),
            "--schedules",
            str(self.db_path),
            "--output",
            str(self.directory / "base_graph.pickle"),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        payload = nx.node_link_data(load_base_graph(Path(summary["output"])))
        self.assertEqual(payload["graph"]["scope"], "EU-27")
        self.assertEqual(
            payload["graph"]["node_weight_attributes"], ["population", "attractiveness"]
        )
        self.assertTrue(
            all(
                n["attractiveness"] == 1 and "population" in n for n in payload["nodes"]
            )
        )
        # Rebuild a lost snapshot from the source files, with every field intact.
        output = Path(summary["output"])
        output.unlink()
        rebuilt = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)
        self.assertEqual(nx.node_link_data(load_base_graph(output)), payload)
        self.assertEqual(
            set(payload["graph"]["transport_modes"]),
            {"PLANES", "TRAINS", "BUSSES", "FERRIES"},
        )
        result = subprocess.run(
            command + ["--schedules", str(self.directory / "missing.duckdb")],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Cannot build base graph", result.stderr)

    def test_city_index_avoids_global_distance_scan(self):
        graph = nx.MultiDiGraph()
        for i in range(10000):
            graph.add_node(str(i), latitude=20, longitude=20, country="France")
        graph.add_node("local", latitude=48, longitude=2, country="France")
        with patch(
            "backend.infrastructure.catalog.static_transport.distance_km",
            wraps=distance_km,
        ) as distance:
            self.assertEqual(CityIndex(graph).nearest(graph.nodes["local"]), "local")
            self.assertEqual(distance.call_count, 1)

    def test_distance_radius_ties_and_modes(self):
        graph = nx.MultiDiGraph()
        graph.add_node("a", latitude=48, longitude=2, country="France")
        index = CityIndex(graph)
        self.assertEqual(index.nearest({"latitude": 48, "longitude": 2}), "a")
        self.assertIsNone(index.nearest({"latitude": 49, "longitude": 2}))
        self.assertIsNone(
            index.nearest({"latitude": 48, "longitude": 2}, country="Germany")
        )
        self.assertEqual(distance_km(graph.nodes["a"], graph.nodes["a"]), 0)
        graph.add_node("b", **graph.nodes["a"])
        self.assertIsNone(CityIndex(graph).nearest(graph.nodes["a"]))
        for value, mode in [
            (100, "TRAINS"),
            (200, "BUSSES"),
            (700, "BUSSES"),
            (4, "FERRIES"),
            (1200, "FERRIES"),
            ("bad", None),
            (1, None),
        ]:
            self.assertEqual(gtfs_mode(value), mode)


if __name__ == "__main__":
    unittest.main()
