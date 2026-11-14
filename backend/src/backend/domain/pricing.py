"""Planning estimates are distinct from purchasable provider quotes."""

from dataclasses import dataclass
from datetime import date
import math

from backend.domain.planning import Money, JourneyOffer, identifier, instant
from datetime import datetime
from backend.domain.travel import TransportType


@dataclass(frozen=True)
class ForecastQuery:
    mode: TransportType
    origin: str
    destination: str
    departure_date: date
    as_of: date
    origin_country: str | None = None
    destination_country: str | None = None
    travelers: int = 1
    feed_id: str | None = None
    route_id: str | None = None
    distance_km: float | None = None

    def __post_init__(self):
        if not isinstance(self.mode, TransportType):
            raise ValueError("Unsupported forecast transport mode")
        if self.distance_km is not None and (
            type(self.distance_km) not in (int, float)
            or not math.isfinite(self.distance_km)
            or self.distance_km < 0
        ):
            raise ValueError("Forecast distance_km must be finite and nonnegative")
        identifier(self.origin)
        identifier(self.destination)
        for value in (
            self.origin_country,
            self.destination_country,
            self.feed_id,
            self.route_id,
        ):
            if value is not None:
                identifier(value)
        if type(self.departure_date) is not date or type(self.as_of) is not date:
            raise ValueError("Forecast dates must be dates, not timestamps")
        if self.departure_date < self.as_of:
            raise ValueError("Forecast departure cannot precede the information date")
        if type(self.travelers) is not int or not 1 <= self.travelers <= 9:
            raise ValueError("Forecast travelers must be an integer from 1 to 9")


@dataclass(frozen=True)
class PriceForecast:
    price: Money
    lower: Money
    upper: Money
    model_id: str
    basis: str
    samples: int
    evidence_start: str | None
    evidence_end: str | None
    warnings: tuple[str, ...]
    distance_km: float | None = None
    distance_source: str | None = None

    def __post_init__(self):
        if (
            self.lower.currency != self.price.currency
            or self.upper.currency != self.price.currency
            or not self.lower.amount <= self.price.amount <= self.upper.amount
        ):
            raise ValueError(
                "Forecast bounds must enclose the estimate in one currency"
            )
        if type(self.samples) is not int or self.samples < 1 or not self.model_id:
            raise ValueError("Forecast requires evidence and model identity")


class ExactPricingUnavailable(ValueError):
    """The selected route could not be matched to usable provider-advertised fares."""


@dataclass(frozen=True)
class QuotedPurchase:
    original_offer_id: str
    offer: JourneyOffer
    response_ids: tuple[str, ...]
    observed_at: datetime
    provider_trip_id: str

    def __post_init__(self):
        instant(self.observed_at)
        if (
            not self.original_offer_id
            or not self.provider_trip_id
            or not self.response_ids
        ):
            raise ValueError(
                "A provider quote requires purchase identity and response provenance"
            )
        if self.offer.synthetic:
            raise ValueError("A provider quote cannot contain a synthetic offer")


@dataclass(frozen=True)
class RoundTripQuote:
    purchases: tuple[QuotedPurchase, ...]
    price_scope: str = "provider_advertised"
    fees_complete: bool = False
    from_cache: bool = False


@dataclass(frozen=True)
class CandidateEstimate:
    offer_ids: tuple[str, ...]
    original_total: Money
    returned_total: Money
    adjustment: Money
    price_status: str


@dataclass(frozen=True)
class PriceReconciliation:
    status: str
    candidates: tuple[CandidateEstimate, ...] = ()
    checked_offer_ids: tuple[str, ...] = ()
    response_ids: tuple[str, ...] = ()
    common_uplift: Money | None = None
    unpriced_offer_ids: tuple[str, ...] = ()
    error: str | None = None
    fees_complete: bool = False
    provider_pricing_attempts: int = 0
