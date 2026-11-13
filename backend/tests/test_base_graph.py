"""Offline topology imports preserve identity, direction and missing evidence."""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import networkx as nx

from backend.infrastructure.catalog.base_graph import build_base_graph
from backend.infrastructure.catalog.graph_snapshot import load_base_graph


class BaseGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cities = Path(self.temp.name) / "cities.csv"
        self.routes = Path(self.temp.name) / "routes.json"
        self.rows = [
            ["Paris", "France", 10, 48.8, 2.3],
            ["Berlin", "Germany", 20, 51.5, -0.1],
            ["Isolated", "France", 0, 44, 2],
            ["Paris", "United States", 1, 33, -95],
        ]
        self.airports = {
            "CDG": self.airport("Paris", "France", ["LHR", "LHR", "LGW", "XXX"]),
            "ORY": self.airport("Paris", "France", ["LHR"]),
            "LHR": self.airport("Berlin", "Germany", []),
            "LGW": self.airport("Berlin", "Germany", []),
            "BAD": self.airport("Unknown", "France", []),
        }

    @staticmethod
    def airport(city, country, destinations):
        return {
            "city_name": city,
            "country": country,
            "routes": [
                {"iata": destination, "carriers": [{"iata": "BA"}, {"iata": "AF"}]}
                for destination in destinations
            ],
        }

    def build(self, **kwargs):
        with self.cities.open("w") as stream:
            writer = csv.writer(stream)
            writer.writerow(["city", "country", "population", "latitude", "longitude"])
            writer.writerows(self.rows)
        for code, airport in self.airports.items():
            airport["iata"] = code
        self.routes.write_text(json.dumps(self.airports))
        return build_base_graph(
            self.cities, self.routes, stations_path=None, schedules_path=None, **kwargs
        )

    def test_city_nodes_parallel_directional_edges_and_unknown_overlays(self):
        graph = self.build()
        cities = {a["name"]: n for n, a in graph.nodes(data=True)}
        self.assertEqual(set(cities), {"Paris", "Berlin", "Isolated"})
        self.assertEqual(graph.number_of_edges(cities["Paris"], cities["Berlin"]), 6)
        self.assertFalse(graph.has_edge(cities["Berlin"], cities["Paris"]))
        self.assertEqual(graph.graph["isolated_cities"], [cities["Isolated"]])
        self.assertEqual(len(graph.graph["missing_reverse_connections"]), 6)
        self.assertEqual(graph.nodes[cities["Isolated"]]["population"], 0)
        for _, _, edge in graph.edges(data=True):
            self.assertNotIn("weight", edge)
            self.assertNotIn("price", edge)
            self.assertNotIn("duration", edge)
        duplicate = next(
            e
            for _, _, e in graph.edges(data=True)
            if e["origin_terminal"] == "airport:CDG"
            and e["destination_terminal"] == "airport:LHR"
        )
        self.assertEqual(duplicate["source_records"], ["CDG/routes/0", "CDG/routes/1"])
        self.assertFalse(graph.graph["live_search_eligible"])
        self.assertTrue(nx.is_frozen(graph))

    def test_city_weights_support_population_filtering_and_default_attractiveness(self):
        self.rows.append(["Unknown population", "France", "", 46, 3])
        graph = self.build()
        cities = {a["name"]: a for _, a in graph.nodes(data=True)}
        self.assertEqual(cities["Paris"]["population"], 10)
        self.assertEqual(cities["Isolated"]["population"], 0)
        self.assertIsNone(cities["Unknown population"]["population"])
        self.assertTrue(all(a["attractiveness"] == 1 for a in cities.values()))
        selected = {
            a["name"]
            for _, a in graph.nodes(data=True)
            if a["population"] is not None and a["population"] >= 10
        }
        self.assertEqual(selected, {"Paris", "Berlin"})
        self.assertEqual(
            graph.graph["node_weight_attributes"], ["population", "attractiveness"]
        )
        self.assertEqual(
            graph.graph["weight_attributes"], ["distance_km", "travel_time_minutes"]
        )
        self.assertEqual(graph.graph["cities_without_population"], 1)
        self.assertEqual(graph.graph["default_attractiveness"], 1)
        self.assertEqual(graph.graph["schema_version"], 4)
        for bad in [-1, "1.5", "nan"]:
            self.rows[0][2] = bad
            with self.subTest(population=bad), self.assertRaisesRegex(
                ValueError, "CSV line 2"
            ):
                self.build()

    def test_repeatability_round_trip_and_reordering(self):
        first = self.build()
        self.assertEqual(nx.node_link_data(first), nx.node_link_data(self.build()))
        restored = nx.node_link_graph(json.loads(json.dumps(nx.node_link_data(first))))
        self.assertEqual(nx.node_link_data(restored), nx.node_link_data(first))
        self.rows.reverse()
        second = self.build()
        self.assertEqual(set(first), set(second))
        self.assertEqual(set(first.edges(keys=True)), set(second.edges(keys=True)))
        self.assertNotEqual(first.graph["snapshot_id"], second.graph["snapshot_id"])

    def test_ambiguity_is_quarantined_and_override_is_explicit(self):
        self.rows.append(["Paris", "France", 1, 45, 3])
        graph = self.build()
        self.assertEqual(graph.number_of_edges(), 0)
        self.assertIn(
            {"airport": "CDG", "reason": "ambiguous_city"},
            graph.graph["mapping_issues"],
        )
        city = next(n for n, a in graph.nodes(data=True) if a["name"] == "Paris")
        resolved = self.build(airport_city_overrides={"CDG": city})
        self.assertEqual(resolved.number_of_edges(), 4)
        self.assertNotEqual(resolved.graph["snapshot_id"], graph.graph["snapshot_id"])
        with self.assertRaisesRegex(ValueError, "Invalid airport city override"):
            self.build(airport_city_overrides={"CDG": "missing"})

    def test_invalid_coordinates_and_empty_input(self):
        self.rows[0][3] = "nan"
        with self.assertRaisesRegex(ValueError, "CSV line 2"):
            self.build()
        self.rows = []
        graph = self.build()
        self.assertEqual(len(graph), 0)
        self.assertEqual(graph.number_of_edges(), 0)

    def test_no_carriers_and_country_alias(self):
        self.rows.append(["Bratislava", "Slovak Republic", 1, 48, 17])
        self.airports["BTS"] = self.airport("Bratislava", "Slovakia", ["LHR"])
        self.airports["BTS"]["routes"][0]["carriers"] = []
        graph = self.build()
        edge = next(
            e
            for _, _, e in graph.edges(data=True)
            if e["origin_terminal"] == "airport:BTS"
        )
        self.assertIsNone(edge["operator"])

    def test_cli_json_and_missing_file(self):
        self.build()
        command = [
            sys.executable,
            "-m",
            "backend.presentation.cli.base_graph",
            "--cities",
            str(self.cities),
            "--routes",
            str(self.routes),
            "--air-only",
            "--output",
            str(self.cities.parent / "base_graph.pickle"),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout)["nodes"], 3)
        self.assertEqual(
            len(load_base_graph(self.cities.parent / "base_graph.pickle")), 3
        )
        result = subprocess.run(
            command + ["--cities", str(self.cities.parent / "missing")],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Cannot build base graph", result.stderr)

    def test_malformed_route_inputs_are_rejected(self):
        for bad in (
            [],
            {"CDG": None},
            {"CDG": {"country": "France", "routes": None}},
            {"CDG": {"country": "France", "routes": [{"iata": 3}]}},
            {
                "CDG": {
                    "country": "France",
                    "routes": [{"iata": "LHR", "carriers": [None]}],
                }
            },
        ):
            with self.subTest(payload=bad):
                self.build()
                self.routes.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    build_base_graph(
                        self.cities,
                        self.routes,
                        stations_path=None,
                        schedules_path=None,
                    )


if __name__ == "__main__":
    unittest.main()
