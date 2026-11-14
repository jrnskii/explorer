"""Compose Ignav input and NetworkX output around the graph use case."""

import networkx as nx

from backend.application.telemetry import traced
from backend.application.fare_graph import populate_fare_graph
from backend.infrastructure.graphs.fare_graph import NetworkXFareGraphWriter
from backend.infrastructure.ignav.fare_search import IgnavResponse, read_fare_search


@traced
def ignav_to_graph(response: IgnavResponse) -> nx.MultiDiGraph:
    """Convert search, one-way, or round-trip output into a detached multigraph.

    Accept a generated model, mapping, or JSON text/bytes. Occurrence keys preserve
    parallel flights even with missing/repeated offer IDs. Weight is duration in
    minutes, not price; itinerary fares remain bundled. Static graph paths do not
    enforce time feasibility or ticket compatibility.
    """
    search = read_fare_search(response)
    graph = nx.MultiDiGraph(
        source="ignav", observed_at=search.observed_at, weight_unit="minutes"
    )
    populate_fare_graph(search, NetworkXFareGraphWriter(graph))
    return graph
