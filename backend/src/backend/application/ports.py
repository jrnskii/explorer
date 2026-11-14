"""Output boundary for building a graph without choosing a graph library."""

from typing import Protocol

from backend.domain.pricing import ForecastQuery, PriceForecast, RoundTripQuote
from backend.domain.fares import FareOffer, FlightSegment
from backend.domain.planning import JourneyOffer, RoundTrip, SearchSettings


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


class PriceForecaster(Protocol):
    """Return a planning estimate or None for unsupported evidence coverage."""

    def predict(self, query: "ForecastQuery") -> "PriceForecast | None": ...


class OfferPriceForecaster(Protocol):
    """Forecast an entire purchase unit locally; unsupported coverage returns None."""

    def estimate_offer(self, offer: JourneyOffer) -> PriceForecast | None: ...


class RoundTripExactPricer(Protocol):
    """Resolve provider fares for exactly one chosen city/mode/date path."""

    def quote(self, option: RoundTrip, settings: SearchSettings) -> RoundTripQuote: ...
