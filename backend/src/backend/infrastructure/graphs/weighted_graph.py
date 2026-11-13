"""Directed travel graph with duration and cost as independent edge weights."""

from collections.abc import Hashable
from decimal import Decimal

import networkx as nx
from pydantic import BaseModel, Field

from backend.domain.travel import TransportType


class WeightedEdge(BaseModel):
    source: str
    target: str
    travel_duration: int = Field(ge=0, description="Travel duration in whole seconds.")
    travel_cost: Decimal = Field(
        ge=0, description="Travel cost in major units of the graph's common currency."
    )
    transport_type: TransportType


class WeightedGraph(nx.MultiDiGraph):
    """Directed travel network supporting parallel journeys between locations.

    All costs must use the same currency. Use ``weight="travel_duration"`` or
    ``weight="travel_cost"`` with NetworkX shortest-path algorithms.
    ``add_travel_edge`` validates travel fields; standard NetworkX mutation
    methods remain available but do not perform this validation.
    """

    def add_travel_edge(
        self,
        source: str,
        target: str,
        *,
        travel_duration: int,
        travel_cost: Decimal,
        transport_type: TransportType,
        key: Hashable | None = None,
    ) -> Hashable:
        """Add a validated journey, automatically adding its endpoint nodes.

        Return the edge key. Supplying an existing key updates that journey.
        """
        edge = WeightedEdge(
            source=source,
            target=target,
            travel_duration=travel_duration,
            travel_cost=travel_cost,
            transport_type=transport_type,
        )
        return self.add_edge(
            edge.source,
            edge.target,
            key=key,
            **edge.model_dump(exclude={"source", "target"}),
        )
