"""Dependency direction and canonical contracts for the layered backend."""

import ast
import importlib
import subprocess
import sys
import textwrap
import unittest
from importlib.util import find_spec, resolve_name
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src"
PACKAGE = SOURCE / "backend"
RETIRED_MODULES = (
    "generated",
    "graphutils",
    "models",
    "mock",
    "ignav",
    "weighted_graph",
    "mock_ignav",
    "mock_network",
    "mock_eu_flights_network",
)
LAYERS = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "infrastructure": {"domain", "application", "infrastructure"},
    "presentation": {"domain", "application", "infrastructure", "presentation"},
}


def imported_modules(source: str, package: str):
    """Include relative imports and `from backend import legacy` spellings."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            # The base can execute its __init__ even when a child is imported.
            if module != "backend":
                yield node.lineno, module
            for alias in node.names:
                if alias.name != "*":
                    yield node.lineno, f"{module}.{alias.name}"
                elif module == "backend":
                    yield node.lineno, module


def allowed_dependency(layer: str, module: str) -> bool:
    parts = module.split(".")
    if parts[0] == "backend":
        return len(parts) > 1 and parts[1] in LAYERS[layer]
    if layer in {"domain", "application"}:
        return parts[0] in sys.stdlib_module_names
    return True


class DependencyRulesTests(unittest.TestCase):
    def test_layer_imports_point_inward_and_avoid_legacy_paths(self):
        for layer in LAYERS:
            files = sorted((PACKAGE / layer).rglob("*.py"))
            with self.subTest(layer=layer):
                self.assertTrue(files, f"No Python sources found for {layer}")
            for path in files:
                relative = path.relative_to(SOURCE)
                module_parts = list(relative.with_suffix("").parts)
                package = ".".join(module_parts[:-1])
                for line, module in imported_modules(path.read_text(), package):
                    with self.subTest(path=str(relative), line=line, dependency=module):
                        self.assertTrue(
                            allowed_dependency(layer, module),
                            f"{relative}:{line}: {layer} must not import {module}",
                        )

    def test_import_analysis_covers_aliases_relative_and_nested_imports(self):
        source = textwrap.dedent("""\
            import backend.generated.ignav as api
            from backend import mock_network
            from ...models import ignav
            from . import models
            if True:
                from backend.presentation.cli import mock_ignav
            from backend.domain.fares import FareSearch
        """)
        dependencies = set(imported_modules(source, "backend.infrastructure.ignav"))
        self.assertIn((1, "backend.generated.ignav"), dependencies)
        self.assertIn((2, "backend.mock_network"), dependencies)
        self.assertIn((3, "backend.models.ignav"), dependencies)
        self.assertIn((4, "backend.infrastructure.ignav.models"), dependencies)
        self.assertIn((6, "backend.presentation.cli.mock_ignav"), dependencies)
        self.assertIn((7, "backend.domain.fares.FareSearch"), dependencies)

    def test_dependency_policy_rejects_outward_and_third_party_core_imports(self):
        cases = (
            ("domain", "datetime", True),
            ("domain", "backend.domain.travel", True),
            ("domain", "backend.application.ports", False),
            ("application", "backend.domain.fares", True),
            ("application", "backend.application.ports", True),
            ("application", "backend.infrastructure.ignav.models", False),
            ("infrastructure", "backend.application.ports", True),
            ("infrastructure", "backend.infrastructure.ignav.models", True),
            ("infrastructure", "networkx", True),
            ("infrastructure", "backend.presentation.cli", False),
            ("presentation", "backend.infrastructure.fixtures.ignav", True),
            ("presentation", "backend.application.fare_graph", True),
            ("presentation", "backend.domain.fares", True),
        )
        for layer in ("domain", "application"):
            for dependency in ("networkx", "pydantic", "fastapi", "requests"):
                cases += ((layer, dependency, False),)
        for layer in LAYERS:
            for legacy in RETIRED_MODULES + (
                "graphutils.ignav",
                "mock.mock_network",
                "models.ignav",
                "generated.schema_v1",
            ):
                cases += ((layer, f"backend.{legacy}", False),)
        for layer, module, expected in cases:
            with self.subTest(layer=layer, module=module):
                self.assertEqual(allowed_dependency(layer, module), expected)

    def test_core_imports_without_graph_provider_or_web_dependencies(self):
        script = textwrap.dedent("""\
            import importlib
            import importlib.abc
            import sys

            blocked = {"networkx", "pydantic", "fastapi"}

            class BlockDependencies(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split(".")[0] in blocked:
                        raise ImportError(f"Core attempted forbidden import: {fullname}")
                    return None

            if blocked.intersection(sys.modules):
                raise AssertionError("Subprocess was not dependency-isolated")
            sys.meta_path.insert(0, BlockDependencies())
            sys.path.insert(0, sys.argv[1])
            for name in (
                "backend.domain", "backend.domain.fares", "backend.domain.travel",
                "backend.application", "backend.application.ports",
                "backend.application.fare_graph",
            ):
                importlib.import_module(name)
            unexpected = [
                name for name in sys.modules
                if name.split(".")[0] in blocked
                or name.startswith(("backend.infrastructure", "backend.presentation"))
            ]
            if unexpected:
                raise AssertionError(f"Core loaded outward dependencies: {unexpected}")
            print("core imports isolated")
        """)
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, str(SOURCE)],
            cwd=SOURCE.parent,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "core imports isolated")
        self.assertEqual(result.stderr, "")


class CanonicalContractsTests(unittest.TestCase):
    def test_public_symbols_are_defined_in_their_canonical_modules(self):
        contracts = {
            "backend.infrastructure.ignav.models": (
                "AirportModel",
                "PriceModel",
                "SegmentModel",
                "FareSearchResponseModel",
            ),
            "backend.infrastructure.graphql.models": (
                "Money",
                "TripLeg",
                "TransportType",
            ),
            "backend.infrastructure.ignav.graph": ("ignav_to_graph",),
            "backend.infrastructure.graphs.weighted_graph": (
                "WeightedGraph",
                "WeightedEdge",
            ),
            "backend.infrastructure.fixtures.ignav": ("MockIgnavGenerator",),
            "backend.infrastructure.fixtures.network": (
                "AirportLocation",
                "MockNetworkFlight",
                "MockFlightNetwork",
                "generate_network",
            ),
            "backend.infrastructure.fixtures.eu_network": ("City", "generate_network"),
            "backend.domain.travel": ("TransportType",),
            "backend.presentation.cli.backend": ("main",),
            "backend.presentation.cli.mock_ignav": ("main",),
            "backend.presentation.cli.eu_network": ("main",),
        }
        for module_name, symbols in contracts.items():
            module = importlib.import_module(module_name)
            for symbol in symbols:
                with self.subTest(module=module_name, symbol=symbol):
                    self.assertEqual(getattr(module, symbol).__module__, module_name)

    def test_retired_modules_are_not_importable(self):
        for name in RETIRED_MODULES:
            with self.subTest(module=name):
                self.assertIsNone(find_spec(f"backend.{name}"))
                self.assertFalse((PACKAGE / name).exists())
                self.assertFalse((PACKAGE / f"{name}.py").exists())
        self.assertEqual(list(PACKAGE.glob("mock_*.py")), [])

    def test_package_root_has_no_legacy_cli_shim(self):
        import backend

        self.assertFalse(hasattr(backend, "main"))

    def test_package_contains_only_implemented_layers(self):
        directories = {
            path.name
            for path in PACKAGE.iterdir()
            if path.is_dir() and path.name != "__pycache__"
        }
        self.assertEqual(directories, set(LAYERS))

    def test_backend_sources_and_tests_do_not_import_retired_paths(self):
        roots = ((PACKAGE, SOURCE), (SOURCE.parent / "tests", SOURCE.parent))
        for root, relative_to in roots:
            for path in sorted(root.rglob("*.py")):
                relative = path.relative_to(relative_to)
                package = ".".join(relative.with_suffix("").parts[:-1])
                for line, module in imported_modules(path.read_text(), package):
                    parts = module.split(".")
                    if len(parts) < 2 or parts[0] != "backend":
                        continue
                    with self.subTest(path=str(relative), line=line, dependency=module):
                        self.assertNotIn(parts[1], RETIRED_MODULES)
                        self.assertFalse(parts[1].startswith("mock_"))

    def test_domain_transport_enum_matches_graphql_wire_values(self):
        from backend.domain.travel import TransportType
        from backend.infrastructure.graphql.models import (
            TransportType as GraphQLTransportType,
        )

        domain_values = {member.value for member in TransportType}
        graphql_values = {member.value for member in GraphQLTransportType}
        self.assertEqual(domain_values, {"BUSSES", "PLANES", "TRAINS"})
        self.assertEqual(domain_values, graphql_values)
        for value in graphql_values:
            with self.subTest(value=value):
                self.assertEqual(str(TransportType(value)), value)
                self.assertEqual(
                    GraphQLTransportType(TransportType(value).value).value, value
                )

    def test_graphql_models_preserve_decimal_datetime_and_field_aliases(self):
        from decimal import Decimal

        from backend.infrastructure.graphql.models import Money, TripLeg

        money = Money(amount=Decimal("149.950000000000000001"), currency="EUR")
        payload = money.model_dump(mode="json")
        self.assertEqual(payload["amount"], "149.950000000000000001")
        self.assertEqual(Money.model_validate(payload), money)
        leg = TripLeg.model_validate(
            {
                "from": "WAW",
                "to": "LHR",
                "departure_at": "2026-12-10T09:00:00Z",
                "arrival_at": "2026-12-10T11:00:00Z",
                "time_in_travel": 7200,
                "transport_type": "PLANES",
            }
        )
        serialized = leg.model_dump(mode="json", by_alias=True)
        self.assertEqual(serialized["from"], "WAW")
        self.assertNotIn("from_", serialized)
        self.assertIsNotNone(leg.departure_at.utcoffset())
        self.assertEqual(TripLeg.model_validate(serialized), leg)

    def test_weighted_graph_accepts_generated_transport_enum(self):
        from decimal import Decimal

        from backend.domain.travel import TransportType
        from backend.infrastructure.graphql.models import (
            TransportType as GraphQLTransportType,
        )
        from backend.infrastructure.graphs.weighted_graph import WeightedGraph

        graph = WeightedGraph()
        key = graph.add_travel_edge(
            "WAW",
            "LHR",
            travel_duration=7200,
            travel_cost=Decimal("149.950000000000000001"),
            transport_type=GraphQLTransportType.PLANES,
        )
        edge = graph.edges["WAW", "LHR", key]
        self.assertEqual(edge["travel_cost"], Decimal("149.950000000000000001"))
        self.assertIs(edge["transport_type"], TransportType.PLANES)


if __name__ == "__main__":
    unittest.main()
