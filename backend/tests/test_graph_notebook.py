"""Exercise the standalone graph notebook without external data or a browser."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import networkx as nx
from IPython.display import HTML
import tinycss2

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks/01_eu_graph_visualization.ipynb"


class GraphNotebookTests(unittest.TestCase):
    def test_fullscreen_widget_and_scoped_styles(self):
        graph = nx.MultiDiGraph()
        for city, longitude in (("a", 20), ("b", 25)):
            graph.add_node(city, name=city, country="LT", latitude=54,
                           longitude=longitude, population=1000)
        for mode in ("BUSSES", "TRAINS"):
            graph.add_edge("a", "b", mode=mode, distance_km=100,
                           travel_time_minutes=60)
        scope = {}
        with patch("pathlib.Path.is_file", return_value=True), patch(
            "backend.infrastructure.catalog.graph_snapshot.load_base_graph",
            return_value=graph,
        ), patch("IPython.display.display") as display:
            for cell in json.loads(NOTEBOOK.read_text())["cells"]:
                if cell["cell_type"] == "code":
                    exec(compile("".join(cell["source"]), str(NOTEBOOK), "exec"), scope)
        widget = scope["cosmograph"]
        self.addCleanup(widget.close)
        self.assertIn("eu-graph-app", widget._dom_classes)
        self.assertEqual(widget.layout.width, "100%")
        self.assertEqual(widget.layout.height, "100%")
        self.assertEqual(scope["links"]["connections"].tolist(), [2])
        self.assertIs(display.call_args_list[-1].args[0], widget)
        html = display.call_args_list[0].args[0]
        self.assertIsInstance(html, HTML)
        css = html.data.split("<style>")[1].split("</style>")[0]
        rules = {}
        for rule in tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True):
            self.assertEqual(rule.type, "qualified-rule")
            selector = tinycss2.serialize(rule.prelude).strip()
            self.assertTrue(selector.startswith(".eu-graph-app"), selector)
            rules[selector] = {
                item.name: tinycss2.serialize(item.value).strip()
                for item in tinycss2.parse_declaration_list(rule.content)
                if item.type == "declaration"
            }
        self.assertEqual(rules[".eu-graph-app"]["position"], "fixed")
        self.assertEqual(rules[".eu-graph-app"]["inset"], "0")
        self.assertEqual(rules[".eu-graph-app"]["height"], "100dvh")
        self.assertEqual(rules[".eu-graph-app .wrapper"]["height"], "100%")
        self.assertEqual(rules[".eu-graph-app .wrapper"]["position"], "relative")

    def test_missing_snapshot_has_actionable_error(self):
        with patch("pathlib.Path.is_file", return_value=False):
            with self.assertRaisesRegex(FileNotFoundError, "generating the snapshot"):
                for cell in json.loads(NOTEBOOK.read_text())["cells"]:
                    if cell["cell_type"] == "code":
                        exec(compile("".join(cell["source"]), str(NOTEBOOK), "exec"), {})
