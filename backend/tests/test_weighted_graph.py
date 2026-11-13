import unittest
from decimal import Decimal

import networkx as nx
from pydantic import ValidationError

from backend.infrastructure.graphs.weighted_graph import WeightedGraph
from backend.domain.travel import TransportType


class WeightedGraphTests(unittest.TestCase):
    def test_parallel_journeys_preserve_weights_and_include_endpoints(self):
        graph = WeightedGraph()
        graph.add_node("LHR")
        for mode, duration in (
            (TransportType.PLANES, 3600),
            (TransportType.BUSSES, 25200),
            (TransportType.TRAINS, 18000),
        ):
            key = graph.add_travel_edge(
                "WAW",
                "BER",
                travel_duration=duration,
                travel_cost=Decimal("25.50"),
                transport_type=mode,
            )
            self.assertEqual(
                graph.edges["WAW", "BER", key],
                dict(
                    travel_duration=duration,
                    travel_cost=Decimal("25.50"),
                    transport_type=mode,
                ),
            )
        self.assertIsInstance(graph, nx.MultiDiGraph)
        self.assertEqual(set(graph.nodes), {"WAW", "BER", "LHR"})
        self.assertEqual(graph.number_of_edges("WAW", "BER"), 3)
        self.assertFalse(graph.has_edge("BER", "WAW"))

    def test_invalid_weights_and_transport_are_rejected_before_mutation(self):
        graph = WeightedGraph()
        values = dict(
            travel_duration=3600,
            travel_cost=Decimal("25.50"),
            transport_type=TransportType.PLANES,
        )
        for field, value in (
            ("travel_duration", -1),
            ("travel_cost", Decimal("-0.01")),
            ("transport_type", "boat"),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                graph.add_travel_edge("WAW", "BER", **{**values, field: value})
        self.assertEqual(graph.number_of_nodes(), 0)
        self.assertEqual(graph.number_of_edges(), 0)

    def test_networkx_shortest_paths_use_either_weight(self):
        graph = WeightedGraph()
        for source, target, duration, cost in (
            ("WAW", "BER", 3600, "100"),
            ("WAW", "BER", 18000, "20"),
            ("BER", "LHR", 7200, "30"),
            ("WAW", "LHR", 5400, "200"),
        ):
            graph.add_travel_edge(
                source,
                target,
                travel_duration=duration,
                travel_cost=Decimal(cost),
                transport_type=TransportType.PLANES,
            )
        self.assertEqual(
            nx.shortest_path(graph, "WAW", "LHR", weight="travel_duration"),
            ["WAW", "LHR"],
        )
        self.assertEqual(
            nx.shortest_path(graph, "WAW", "LHR", weight="travel_cost"),
            ["WAW", "BER", "LHR"],
        )
        self.assertEqual(
            nx.shortest_path_length(graph, "WAW", "LHR", weight="travel_cost"),
            Decimal("50"),
        )

    def test_explicit_key_updates_journey(self):
        graph = WeightedGraph()
        for cost in ("25.50", "30.00"):
            key = graph.add_travel_edge(
                "WAW",
                "BER",
                key="train-1",
                travel_duration=18000,
                travel_cost=Decimal(cost),
                transport_type=TransportType.TRAINS,
            )
            self.assertEqual(key, "train-1")
        self.assertEqual(graph.number_of_edges(), 1)
        self.assertEqual(
            graph.edges["WAW", "BER", "train-1"]["travel_cost"], Decimal("30.00")
        )

    def test_empty_graphs_do_not_share_collections(self):
        first = WeightedGraph()
        second = WeightedGraph()
        first.add_node("WAW")
        self.assertEqual(second.number_of_nodes(), 0)
        self.assertEqual(second.number_of_edges(), 0)
