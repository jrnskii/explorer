"""Binary snapshots preserve graph contracts, publish atomically, and reject globals."""

import json
import pickle
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import networkx as nx

from backend.infrastructure.catalog.graph_snapshot import (
    FORMAT,
    FORMAT_VERSION,
    load_base_graph,
    load_base_graph_json,
    save_base_graph,
)


class GraphSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.graph = nx.MultiDiGraph(
            schema_version=4,
            node_weight_attributes=["population", "attractiveness"],
            snapshot_id="fixed",
            weight_attributes=["distance_km", "travel_time_minutes"],
        )
        self.graph.add_node(
            "a", name="Łódź", population=0, attractiveness=1, timezone=None
        )
        self.graph.add_node("b", name="Other", population=100000, attractiveness=2.5)
        self.graph.add_node(
            "isolated", name="Isolated", population=None, attractiveness=1
        )
        self.graph.add_edge(
            "a",
            "b",
            key="rail",
            mode="TRAINS",
            distance_km=2.5,
            travel_time_minutes=0,
            data_source="GTFS",
            source_records=["one"],
        )
        self.graph.add_edge(
            "a",
            "b",
            key="bus",
            mode="BUSSES",
            distance_km=2.5,
            travel_time_minutes=None,
            data_source="GTFS",
            source_records=["two"],
        )
        # Populate common views cached on NetworkX instances before serialization.
        list(self.graph.edges(data=True))
        list(self.graph.nodes(data=True))
        list(nx.isolates(self.graph))

    def assert_graph_equal(self, restored):
        self.assertEqual(restored.graph, self.graph.graph)
        self.assertEqual(
            dict(restored.nodes(data=True)), dict(self.graph.nodes(data=True))
        )
        self.assertEqual(
            set(restored.edges(keys=True)), set(self.graph.edges(keys=True))
        )
        for u, v, key, attrs in self.graph.edges(keys=True, data=True):
            self.assertEqual(restored[u][v][key], attrs)
        # NetworkX predecessor and successor maps must share each edge dictionary.
        self.assertIs(restored["a"]["b"]["rail"], restored.pred["b"]["a"]["rail"])
        self.assertTrue(nx.is_frozen(restored))
        self.assertFalse(restored.has_edge("b", "a"))

    def test_plain_and_compressed_round_trip_preserve_weights_and_parallel_edges(self):
        for suffix in [".pickle", ".pickle.zst"]:
            with self.subTest(suffix=suffix):
                path = self.root / ("graph" + suffix)
                self.assertEqual(save_base_graph(self.graph, path), path)
                self.assertFalse(nx.is_frozen(self.graph))
                before = path.read_bytes()
                save_base_graph(self.graph, path)
                self.assertEqual(before, path.read_bytes())
                self.assert_graph_equal(load_base_graph(path))
                nx.freeze(self.graph)
                save_base_graph(self.graph, path)
                self.assert_graph_equal(load_base_graph(path))
                # Restore a mutable input for the next iteration.
                self.graph = nx.MultiDiGraph(self.graph)

    def test_empty_graph_and_repeatable_bytes(self):
        for suffix in [".pickle", ".pickle.zst"]:
            path = self.root / ("empty" + suffix)
            save_base_graph(nx.MultiDiGraph(), path)
            before = path.read_bytes()
            save_base_graph(nx.MultiDiGraph(), path)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(len(load_base_graph(path)), 0)

    def test_failed_publication_preserves_existing_snapshot_and_cleans_staging(self):
        path = self.root / "graph.pickle"
        save_base_graph(self.graph, path)
        original = path.read_bytes()
        with patch(
            "backend.infrastructure.catalog.graph_snapshot.os.replace",
            side_effect=OSError("disk error"),
        ):
            with self.assertRaises(OSError):
                save_base_graph(self.graph, path)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_corrupt_truncated_and_wrong_format_snapshots_are_rejected(self):
        path = self.root / "bad.pickle"
        envelope = dict(
            format=FORMAT,
            format_version=FORMAT_VERSION,
            networkx_version=nx.__version__,
            graph=self.graph,
        )
        for payload in [
            b"",
            b"not a pickle",
            pickle.dumps([]),
            pickle.dumps(dict(envelope, format_version=999)),
            pickle.dumps(dict(envelope, networkx_version="old")),
            pickle.dumps(dict(envelope, graph=nx.DiGraph())),
        ]:
            path.write_bytes(payload)
            with self.assertRaises(ValueError):
                load_base_graph(path)
        compressed = self.root / "bad.pickle.zst"
        compressed.write_bytes(b"not zstandard")
        with self.assertRaises(ValueError):
            load_base_graph(compressed)
        with self.assertRaises(FileNotFoundError):
            load_base_graph(self.root / "missing.pickle")
        with self.assertRaises(ValueError):
            save_base_graph(self.graph, self.root / "wrong.json")
        with self.assertRaises(ValueError):
            save_base_graph(nx.DiGraph(), path)

    def test_disallowed_pickle_globals_cannot_execute(self):
        marker = self.root / "must-not-exist"

        class Malicious:
            def __reduce__(self):
                return eval, (f"__import__('pathlib').Path({str(marker)!r}).touch()",)

        path = self.root / "malicious.pickle"
        path.write_bytes(pickle.dumps(Malicious(), protocol=5))
        with self.assertRaises(ValueError):
            load_base_graph(path)
        self.assertFalse(marker.exists())

    def test_json_migration_cli_uses_no_source_data_and_preserves_graph(self):
        source = self.root / "old.json"
        source.write_text(json.dumps(nx.node_link_data(self.graph)))
        self.assert_graph_equal(load_base_graph_json(source))
        output = self.root / "new.pickle"
        command = [
            sys.executable,
            "-m",
            "backend.presentation.cli.base_graph",
            "--from-json",
            str(source),
            "--output",
            str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout)["edges"], 2)
        self.assert_graph_equal(load_base_graph(output))
        source.write_text('{"directed": false, "multigraph": false}')
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assert_graph_equal(load_base_graph(output))
        for flags in [
            ["--air-only"],
            ["--cities", "missing"],
            ["--output", str(source)],
        ]:
            result = subprocess.run(
                command + flags, capture_output=True, text=True, timeout=20
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
