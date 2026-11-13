"""NetworkX output adapter retaining the public Ignav graph attributes."""

from dataclasses import asdict

import networkx as nx

from backend.domain.fares import FareOffer, FlightSegment


class NetworkXFareGraphWriter:
    def __init__(self, graph: nx.MultiDiGraph) -> None:
        self.graph = graph

    def add_airport(self, code: str) -> None:
        self.graph.add_node(code, code=code)

    def add_segment(
        self,
        segment: FlightSegment,
        offer: FareOffer,
        *,
        itinerary_index: int,
        leg_index: int,
        segment_index: int,
    ) -> None:
        attributes = asdict(segment)
        self.graph.add_edge(
            segment.departure_airport,
            segment.arrival_airport,
            key=(itinerary_index, leg_index, segment_index),
            **attributes,
            segment=dict(attributes),
            weight=segment.duration_minutes,
            itinerary_index=itinerary_index,
            leg_index=leg_index,
            segment_index=segment_index,
            ignav_id=offer.offer_id,
            itinerary_price=asdict(offer.price),
            cabin_class=offer.cabin_class,
        )
