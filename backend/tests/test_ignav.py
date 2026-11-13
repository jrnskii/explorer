import json
import unittest
from copy import deepcopy

import networkx as nx
from backend.infrastructure.ignav.graph import ignav_to_graph
from backend.infrastructure.fixtures.ignav import MockIgnavGenerator
from pydantic import ValidationError


class IgnavToGraphTests(unittest.TestCase):
    def setUp(self):
        self.ignav = MockIgnavGenerator(seed=42, count=4)
        self.request = {
            "origin": "WAW",
            "destination": "LHR",
            "departure_date": "2026-12-10",
        }

    def test_one_way_preserves_all_segments_and_parallel_offers(self):
        response = self.ignav.one_way(self.request)
        graph = ignav_to_graph(response.model_dump(mode="json"))
        self.assertIsInstance(graph, nx.MultiDiGraph)
        self.assertTrue(graph.is_directed())
        expected = sum(len(i.outbound.segments) for i in response.itineraries)
        self.assertEqual(graph.number_of_edges(), expected)
        self.assertEqual(graph.graph["weight_unit"], "minutes")
        self.assertEqual(
            graph.graph["observed_at"], response.model_dump(mode="json")["observed_at"]
        )
        for i, itinerary in enumerate(response.itineraries):
            for s, segment in enumerate(itinerary.outbound.segments):
                edge = graph.edges[
                    segment.departure_airport, segment.arrival_airport, (i, 0, s)
                ]
                self.assertEqual(edge["segment"], segment.model_dump(mode="json"))
                self.assertEqual(edge["weight"], segment.duration_minutes)
                self.assertEqual(edge["departure_time_utc"], segment.departure_time_utc)
                self.assertEqual(edge["ignav_id"], itinerary.ignav_id)
                self.assertEqual(edge["itinerary_price"], itinerary.price.model_dump())
                self.assertNotIn("price", edge)
        self.assertEqual(graph.nodes["WAW"]["code"], "WAW")

    def test_round_trip_includes_inbound_segments(self):
        response = self.ignav.round_trip(dict(self.request, return_date="2026-12-17"))
        graph = ignav_to_graph(response)
        expected = sum(
            len(i.outbound.segments) + len(i.inbound.segments)
            for i in response.itineraries
        )
        self.assertEqual(graph.number_of_edges(), expected)
        for i, itinerary in enumerate(response.itineraries):
            for s, segment in enumerate(itinerary.inbound.segments):
                self.assertIn(
                    (segment.departure_airport, segment.arrival_airport, (i, 1, s)),
                    graph.edges,
                )

    def test_search_supports_ordered_legs_and_missing_ids(self):
        response = self.ignav.search(
            {
                "legs": [
                    self.request,
                    {
                        "origin": "LHR",
                        "destination": "CDG",
                        "departure_date": "2026-12-17",
                    },
                ]
            }
        )
        payload = response.model_dump(mode="json")
        for itinerary in payload["itineraries"]:
            itinerary.pop("ignav_id")
        graph = ignav_to_graph(payload)
        self.assertEqual(
            graph.number_of_edges(),
            sum(len(leg.segments) for i in response.itineraries for leg in i.legs),
        )
        self.assertTrue(all(e["ignav_id"] is None for *_, e in graph.edges(data=True)))
        self.assertEqual(set(graph), set(ignav_to_graph(response)))

    def test_equivalent_input_formats(self):
        response = self.ignav.one_way(self.request)
        expected = ignav_to_graph(response)
        for value in (
            response.model_dump(),
            response.model_dump(mode="json"),
            response.model_dump_json(),
            response.model_dump_json().encode(),
        ):
            with self.subTest(input_type=type(value)):
                self.assertTrue(nx.utils.graphs_equal(expected, ignav_to_graph(value)))

    def test_empty_results_keep_requested_airports(self):
        responses = [
            self.ignav.one_way(dict(self.request, max_price=0)),
            self.ignav.search({"legs": [self.request], "max_price": 0}),
        ]
        for response in responses:
            graph = ignav_to_graph(response)
            self.assertEqual(set(graph), {"WAW", "LHR"})
            self.assertEqual(graph.number_of_edges(), 0)

    def test_duplicate_ids_and_identical_segments_do_not_overwrite_edges(self):
        payload = self.ignav.one_way(self.request).model_dump(mode="json")
        payload["itineraries"] = [payload["itineraries"][0]] * 2
        graph = ignav_to_graph(payload)
        self.assertEqual(
            graph.number_of_edges(),
            2 * len(payload["itineraries"][0]["outbound"]["segments"]),
        )

    def test_graph_is_detached_from_input_and_other_calls(self):
        payload = self.ignav.one_way(self.request).model_dump(mode="json")
        original = deepcopy(payload)
        graph = ignav_to_graph(payload)
        edge = next(iter(graph.edges(data=True)))[2]
        edge["segment"]["flight_number"] = "changed"
        edge["itinerary_price"]["amount"] = -1
        self.assertEqual(payload, original)
        fresh_edge = next(iter(ignav_to_graph(payload).edges(data=True)))[2]
        self.assertNotEqual(fresh_edge["segment"]["flight_number"], "changed")
        self.assertGreater(fresh_edge["itinerary_price"]["amount"], 0)
        prices = [e["itinerary_price"] for *_, e in graph.edges(data=True)]
        self.assertTrue(
            all(price is not edge["itinerary_price"] for price in prices[1:])
        )

    def test_invalid_inputs_fail_explicitly(self):
        for value in (None, [], 42, "[]"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                ignav_to_graph(value)
        with self.assertRaises(json.JSONDecodeError):
            ignav_to_graph("not json")
        with self.assertRaises(ValidationError):
            ignav_to_graph({"itineraries": []})


if __name__ == "__main__":
    unittest.main()
