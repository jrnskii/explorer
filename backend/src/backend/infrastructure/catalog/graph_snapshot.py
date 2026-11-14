"""Fast native snapshots for local Python/NetworkX graph consumers.

Pickle snapshots are local caches, not an interchange format for untrusted data.
Only the NetworkX globals used by our graph snapshots may be reconstructed.
"""

import json
import os
import pickle
import tempfile
from compression import zstd
from pathlib import Path

import networkx as nx

from backend.application.telemetry import traced
from backend.infrastructure.catalog.base_graph import DATA

DEFAULT_GRAPH_PATH = DATA / "base_graph.pickle"
FORMAT = "explorer.base_graph"
FORMAT_VERSION = 1
_ALLOWED_GLOBALS = {
    ("networkx.classes.multidigraph", "MultiDiGraph"),
    ("networkx.classes.function", "frozen"),
    *{
        ("networkx.classes.coreviews", name)
        for name in (
            "AtlasView",
            "AdjacencyView",
            "MultiAdjacencyView",
        )
    },
    *{
        ("networkx.classes.reportviews", name)
        for name in (
            "NodeView",
            "NodeDataView",
            "OutMultiEdgeView",
            "InMultiEdgeView",
            "OutMultiEdgeDataView",
            "InMultiEdgeDataView",
            "DiMultiDegreeView",
            "InMultiDegreeView",
            "OutMultiDegreeView",
        )
    },
}


class _SnapshotUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if (module, name) not in _ALLOWED_GLOBALS:
            raise pickle.UnpicklingError(
                f"Unsupported snapshot object: {module}.{name}"
            )
        return super().find_class(module, name)


def _compressed(path: Path) -> bool:
    if path.name.endswith(".pickle.zst"):
        return True
    if path.suffix == ".pickle":
        return False
    raise ValueError("Graph snapshot path must end with .pickle or .pickle.zst")


@traced
def save_base_graph(graph: nx.MultiDiGraph, path: Path = DEFAULT_GRAPH_PATH) -> Path:
    """Atomically save a graph without building an intermediate node-link tree.

    Protocol 5 stores the native graph's shared adjacency/attribute references.
    Optional Zstandard level 1 compression trades some load time for disk space.
    The supplied graph is not mutated. Concurrent readers see a complete snapshot.
    """
    if type(graph) is not nx.MultiDiGraph:
        raise ValueError("A base graph snapshot must contain a NetworkX MultiDiGraph")
    path = Path(path)
    compressed = _compressed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = dict(
        format=FORMAT,
        format_version=FORMAT_VERSION,
        networkx_version=nx.__version__,
        graph=graph,
    )
    staging = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as raw:
            staging = Path(raw.name)
            if compressed:
                with zstd.open(raw, "wb", level=1) as stream:
                    pickle.dump(envelope, stream, protocol=5)
            else:
                pickle.dump(envelope, raw, protocol=5)
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(staging, path)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)
    return path


@traced
def load_base_graph(path: Path = DEFAULT_GRAPH_PATH) -> nx.MultiDiGraph:
    """Load our local binary cache directly into a structurally frozen graph.

    Rebuild caches after a NetworkX upgrade. The allowlist blocks arbitrary pickle
    globals; nevertheless this API is for trusted, locally produced snapshots.
    """
    path = Path(path)
    compressed = _compressed(path)
    try:
        with zstd.open(path, "rb") if compressed else path.open("rb") as stream:
            envelope = _SnapshotUnpickler(stream).load()
    except (
        pickle.UnpicklingError,
        EOFError,
        zstd.ZstdError,
        AttributeError,
        TypeError,
    ) as error:
        raise ValueError(
            "Invalid or unsupported graph snapshot; regenerate it"
        ) from error
    if not isinstance(envelope, dict) or envelope.get("format") != FORMAT:
        raise ValueError("Invalid graph snapshot format")
    if envelope.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported graph snapshot format version; regenerate it")
    if envelope.get("networkx_version") != nx.__version__:
        raise ValueError("Graph snapshot NetworkX version mismatch; regenerate it")
    graph = envelope.get("graph")
    if type(graph) is not nx.MultiDiGraph:
        raise ValueError("Graph snapshot does not contain a MultiDiGraph")
    return nx.freeze(graph)


@traced
def load_base_graph_json(path: Path) -> nx.MultiDiGraph:
    """Read the legacy node-link JSON once when migrating existing snapshots."""
    with Path(path).open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if (
        not isinstance(payload, dict)
        or payload.get("directed") is not True
        or payload.get("multigraph") is not True
    ):
        raise ValueError("Legacy graph JSON must be a directed multigraph")
    return nx.freeze(nx.node_link_graph(payload))
