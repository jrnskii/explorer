"""Output boundary for building a graph without choosing a graph library."""

from typing import Protocol

from backend.domain.fares import FareOffer, FlightSegment


class FareGraphWriter(Protocol):
    def add_airport(self, code: str) -> None: ...

    def add_segment(
        self,
        segment: FlightSegment,
        offer: FareOffer,
        *,
        itinerary_index: int,
        leg_index: int,
        segment_index: int,
    ) -> None: ...
