"""Output boundary for building a graph without choosing a graph library."""

from typing import Protocol

from backend.domain.fares import FareOffer, FlightSegment
from backend.domain.planning import JourneyOffer, SearchSettings


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


class JourneyOfferProvider(Protocol):
    """Resolve a finite dated/fully priced overlay before route exploration.

    Failures and unsupported coverage raise errors rather than masquerading as
    an exhaustive empty schedule. Providers retain purchase-unit price scope.
    """

    def offers(self, settings: SearchSettings) -> tuple[JourneyOffer, ...]: ...
