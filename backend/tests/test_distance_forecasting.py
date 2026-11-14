"""Distance features must come from the directed graph, never invented fares."""

from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
import math
from pathlib import Path
import tempfile
import unittest

import networkx as nx

from backend.domain.pricing import ForecastQuery
from backend.domain.travel import TransportType as M
from backend.infrastructure.catalog.graph_snapshot import save_base_graph
from backend.infrastructure.pricing.distance import (
    BASIS,
    fit_distance,
    graph_distances,
    predict_distance,
    resolve_distance,
    scope,
    validate_distance_model,
)
from backend.infrastructure.pricing.forecast import ForecastService, route
from backend.infrastructure.pricing.train import summary, evaluate
from test_price_forecasting import fixture_artifact, DAY
import test_price_forecasting as pricing_tests


def fixture_graph():
    graph = nx.MultiDiGraph()
    for node in ["a", "b", "c", "d", "e", "new"]:
        graph.add_node(node, name=node, country="France")
    for i, destination in enumerate(["b", "c", "d", "e"]):
        for mode in M:
            graph.add_edge(
                "a",
                destination,
                key=mode.value,
                mode=mode.value,
                distance_km=[100, 200, 400, 800][i],
                distance_basis=BASIS,
                feed_id="feed",
                route_id=destination,
            )
    graph.add_edge(
        "a", "new", key="new", mode="PLANES", distance_km=300, distance_basis=BASIS
    )
    return graph


def distance_entries():
    return {
        route("a", node, "FR", "FR"): dict(
            baseline=summary([Decimal(2 * (1 + distance) - 1)], dates=["2026-11-14"])
        )
        for node, distance in zip(
            ["b", "c", "d", "e"], [100, 200, 400, 800], strict=True
        )
    }


class DistanceTests(unittest.TestCase):
    def test_graph_preserves_direction_modes_and_collapses_only_identical_parallel_features(
        self,
    ):
        graph = fixture_graph()
        graph.add_edge(
            "a",
            "b",
            key="parallel",
            mode="PLANES",
            distance_km=100,
            distance_basis=BASIS,
        )
        before = nx.node_link_data(graph)
        features = graph_distances(graph)
        identity = route("a", "b", "FR", "FR")
        self.assertEqual(features["edges"]["PLANES"][identity], 100)
        self.assertNotIn(route("b", "a", "FR", "FR"), features["edges"]["PLANES"])
        self.assertEqual(len(features["edges"]["BUSSES"]), 4)
        self.assertEqual(nx.node_link_data(graph), before)
        graph["a"]["b"]["parallel"]["distance_km"] = 999
        features = graph_distances(graph)
        self.assertNotIn(identity, features["edges"]["PLANES"])
        self.assertIn(identity, features["edges"]["TRAINS"])

    def test_ambiguous_names_bad_distances_and_wrong_basis_are_excluded(self):
        graph = fixture_graph()
        graph.add_node("duplicate", name="b", country="France")
        for value in [None, float("nan"), float("inf"), -1, True, "100"]:
            graph["a"]["c"]["PLANES"]["distance_km"] = value
            features = graph_distances(graph)
            self.assertNotIn(route("a", "b", "FR", "FR"), features["edges"]["PLANES"])
            self.assertNotIn(route("a", "c", "FR", "FR"), features["edges"]["PLANES"])
        graph["a"]["c"]["PLANES"].update(distance_km=100, distance_basis="road_length")
        self.assertNotIn(
            route("a", "c", "FR", "FR"), graph_distances(graph)["edges"]["PLANES"]
        )

    def test_regression_is_route_balanced_monotone_and_bounded(self):
        entries = distance_entries()
        index = graph_distances(fixture_graph())["edges"]["PLANES"]
        model = fit_distance(entries, index)["groups"][scope(next(iter(entries)))]
        self.assertAlmostEqual(model["slope"], 1)
        self.assertTrue(model["enabled"])
        self.assertEqual(model["samples"], 4)
        self.assertGreater(model["validation"]["supported_routes"], 0)
        predictions = [
            Decimal(predict_distance(model, d)["value"]) for d in [100, 200, 300, 800]
        ]
        self.assertEqual(predictions, sorted(predictions))
        self.assertAlmostEqual(float(predictions[2]), 601)
        self.assertIsNone(predict_distance(model, 99))
        self.assertIsNone(predict_distance(model, 801))
        self.assertIsNone(predict_distance(model, float("nan")))
        duplicate = deepcopy(entries)
        for entry in duplicate.values():
            entry["months"] = {"2026-01": deepcopy(entry["baseline"])}
        self.assertEqual(
            fit_distance(duplicate, index)["groups"],
            fit_distance(entries, index)["groups"],
        )

    def test_graph_endpoint_geometry_uses_same_metric_without_inventing_an_edge(self):
        graph = fixture_graph()
        graph.nodes["a"].update(latitude=48.0, longitude=2.0)
        graph.nodes["new"].update(latitude=49.0, longitude=3.0)
        identity = route("a", "new", "FR", "FR")
        graph.remove_edge("a", "new", "new")
        features = graph_distances(graph)
        self.assertNotIn(identity, features["edges"]["PLANES"])
        distance, source = resolve_distance(features, "PLANES", identity)
        self.assertGreater(distance, 100)
        self.assertEqual(source, "base_graph_city_centres")
        self.assertFalse(graph.has_edge("a", "new"))

    def test_nearby_reference_aliases_prefer_city_source_and_distant_names_stay_ambiguous(
        self,
    ):
        graph = nx.MultiDiGraph()
        graph.add_node(
            "city",
            name="Munich",
            country="Germany",
            source="Cities.csv",
            latitude=48.15,
            longitude=11.58,
        )
        graph.add_node(
            "station",
            name="München",
            country="Germany",
            source="train_stations_europe.csv",
            latitude=48.14,
            longitude=11.56,
        )
        graph.add_node(
            "target",
            name="Bremen",
            country="Germany",
            source="Cities.csv",
            latitude=53.08,
            longitude=8.8,
        )
        identity = route("Munich", "Bremen", "DE", "DE")
        features = graph_distances(graph)
        distance, source = resolve_distance(features, "BUSSES", identity)
        self.assertIsNotNone(distance)
        self.assertEqual(source, "base_graph_city_centres")
        self.assertEqual(
            features["diagnostics"]["nearby_reference_alias_groups_resolved"], 1
        )
        graph.nodes["station"]["latitude"] = 50
        self.assertIsNone(
            resolve_distance(graph_distances(graph), "BUSSES", identity)[0]
        )

    def test_regression_with_no_holdout_support_is_not_enabled(self):
        entries = dict(list(distance_entries().items())[:3])
        model = next(
            iter(
                fit_distance(
                    entries, graph_distances(fixture_graph())["edges"]["PLANES"]
                )["groups"].values()
            )
        )
        self.assertFalse(model["enabled"])
        self.assertEqual(model["validation"]["supported_routes"], 0)
        self.assertIsNone(predict_distance(model, 200))

    def test_sparse_constant_distance_and_decreasing_data(self):
        entries = distance_entries()
        distances = graph_distances(fixture_graph())["edges"]["PLANES"]
        small = dict(list(entries.items())[:2])
        self.assertEqual(fit_distance(small, distances)["groups"], {})
        self.assertEqual(fit_distance(entries, {r: 100 for r in entries})["groups"], {})
        for i, entry in enumerate(entries.values()):
            entry["baseline"] = summary([Decimal(1000 - i * 100)])
        model = next(iter(fit_distance(entries, distances)["groups"].values()))
        self.assertEqual(model["slope"], 0)

    def test_service_infers_graph_distance_for_unseen_route_and_keeps_known_evidence(
        self,
    ):
        artifact = fixture_artifact()
        artifact["version"] = 2
        entries = distance_entries()
        features = graph_distances(fixture_graph())
        artifact["distance_index"] = features
        distance = fit_distance(entries, features["edges"]["PLANES"])
        artifact["models"]["PLANES"].update(entries=entries, distance=distance)
        service = ForecastService(artifact)
        request = ForecastQuery(
            M.PLANES, "a", "new", date(2026, 12, 1), DAY, "FR", "FR"
        )
        prediction = service.predict(request)
        self.assertEqual(prediction.price.amount, Decimal("601"))
        self.assertEqual(prediction.basis, "distance_regression")
        self.assertEqual(prediction.distance_km, 300)
        self.assertEqual(prediction.distance_source, "base_graph_edge")
        self.assertIsNone(service.predict(replace(request, mode=M.TRAINS)))
        self.assertIsNone(
            service.predict(replace(request, origin="new", destination="a"))
        )
        self.assertIsNone(service.predict(replace(request, origin_country="DE")))
        known = service.predict(replace(request, destination="b"))
        self.assertEqual(known.price.amount, Decimal("201"))
        self.assertEqual(known.basis, "route_baseline")
        explicit = service.predict(replace(request, distance_km=200))
        self.assertEqual(explicit.price.amount, Decimal("401"))
        self.assertEqual(explicit.distance_source, "request")
        self.assertTrue(
            explicit.lower.amount <= explicit.price.amount <= explicit.upper.amount
        )

    def test_distance_validation_and_legacy_artifact_compatibility(self):
        query = ForecastQuery(M.PLANES, "a", "b", date(2026, 12, 1), DAY)
        for value in [-1, float("nan"), float("inf"), True, "100"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(query, distance_km=value)
        self.assertIsNone(ForecastService(fixture_artifact()).predict(query))
        model = fit_distance(
            distance_entries(), graph_distances(fixture_graph())["edges"]["PLANES"]
        )
        invalid = deepcopy(model)
        next(iter(invalid["groups"].values()))["slope"] = float("nan")
        with self.assertRaises(ValueError):
            validate_distance_model(invalid)

    def test_temporal_evaluation_does_not_fit_with_held_out_prices(self):
        entries = distance_entries()
        features = graph_distances(fixture_graph())["edges"]["PLANES"]
        training = [
            dict(route=r, price=Decimal(e["baseline"]["value"]), month="2026-10")
            for r, e in entries.items()
        ]
        held = [
            dict(
                route=route("a", "new", "FR", "FR"),
                price=Decimal("100000"),
                month="2026-11",
            )
        ]
        result = evaluate(training, held, "month", features)
        self.assertEqual(result["distance_fallback_units"], 1)
        self.assertGreater(Decimal(result["mae_eur"]), Decimal("99000"))

    def test_ferry_regression_cannot_bypass_excluded_product_rules(self):
        entries = distance_entries()
        distances = graph_distances(fixture_graph())["edges"]["PLANES"]
        fitted = fit_distance(entries, distances)
        curve = next(iter(fitted["groups"].values()))
        artifact = fixture_artifact()
        blocked = json.dumps(["feed", "blocked", "", ""], separators=(",", ":"))
        artifact["models"]["FERRIES"]["distance"] = dict(
            groups={json.dumps(["feed"], separators=(",", ":")): curve},
            blocked_routes=[blocked],
        )
        service = ForecastService(artifact)
        query = ForecastQuery(
            M.FERRIES,
            "a",
            "new",
            date(2026, 12, 1),
            DAY,
            "FR",
            "FR",
            feed_id="feed",
            route_id="blocked",
            distance_km=300,
        )
        self.assertIsNone(service.predict(query))
        self.assertIsNotNone(service.predict(replace(query, route_id="unknown")))

    def test_independent_ferry_feed_support(self):
        graph = fixture_graph()
        entries = {}
        for node, distance in zip(
            ["b", "c", "d", "e"], [100, 200, 400, 800], strict=True
        ):
            identity = json.dumps(["feed", node, "", ""], separators=(",", ":"))
            entries[identity] = dict(
                baseline=summary([Decimal(2 * (1 + distance) - 1)])
            )
        feature = graph_distances(graph)
        artifact = fixture_artifact()
        artifact["distance_index"] = feature
        artifact["models"]["FERRIES"].update(
            entries=entries,
            distance=fit_distance(entries, feature["ferry_routes"], ferry=True),
        )
        service = ForecastService(artifact)
        request = ForecastQuery(
            M.FERRIES,
            "a",
            "new",
            date(2026, 12, 1),
            DAY,
            "FR",
            "FR",
            feed_id="feed",
            route_id="new",
            distance_km=300,
        )
        self.assertEqual(service.predict(request).price.amount, Decimal("601"))
        self.assertIsNone(service.predict(replace(request, feed_id="other")))
        # Flat products are not multiplied by distance even when a graph segment differs.
        self.assertEqual(
            service.predict(replace(request, route_id="b")).price.amount, Decimal("201")
        )


class GraphTrainingTests(unittest.TestCase):
    setUp = pricing_tests.TrainingTests.setUp
    add = pricing_tests.TrainingTests.add

    # Reuse the small pricing fixture builder, but keep the inherited baseline
    # tests in their original suite rather than executing them a second time.
    def test_graph_training_provenance_and_missing_graph_error(self):
        from backend.infrastructure.pricing.train import train

        graph = nx.MultiDiGraph()
        graph.add_node("Paris", name="Paris", country="France")
        graph.add_node("Berlin", name="Berlin", country="Germany")
        graph.add_edge(
            "Paris", "Berlin", mode="PLANES", distance_km=900, distance_basis=BASIS
        )
        path = save_base_graph(graph, self.root / "graph.pickle")
        result = train(
            self.database, self.output, fixtures_dir=self.root, graph_path=path
        )
        data = json.loads(self.output.read_text())
        self.assertEqual(data["version"], 2)
        self.assertEqual(len(data["metadata"]["graph_sha256"]), 64)
        self.assertEqual(result["models"]["PLANES"]["distance_mapped_routes"], 1)
        self.assertEqual(
            data["distance_index"]["edges"]["PLANES"][
                route("Paris", "Berlin", "FR", "DE")
            ],
            900,
        )
        before = self.output.read_bytes()
        with self.assertRaisesRegex(ValueError, "Base graph not found"):
            train(
                self.database,
                self.output,
                fixtures_dir=self.root,
                graph_path=self.root / "missing.pickle",
            )
        self.assertEqual(self.output.read_bytes(), before)
