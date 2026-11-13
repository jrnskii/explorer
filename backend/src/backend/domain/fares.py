"""Normalized fare-search data, independent of provider contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FlightSegment:
    marketing_carrier_code: str | None
    flight_number: str | None
    operating_carrier_name: str | None
    departure_airport: str
    departure_time_local: str
    departure_timezone: str | None
    departure_time_utc: str | None
    arrival_airport: str
    arrival_time_local: str
    arrival_timezone: str | None
    arrival_time_utc: str | None
    duration_minutes: int
    aircraft: str | None


@dataclass(frozen=True)
class FarePrice:
    # Retain provider amounts without rounding or allocating fares to segments.
    amount: float
    currency: str
    status: str


@dataclass(frozen=True)
class FareOffer:
    legs: tuple[tuple[FlightSegment, ...], ...]
    price: FarePrice
    offer_id: str | None
    cabin_class: str | None


@dataclass(frozen=True)
class FareSearch:
    requested_routes: tuple[tuple[str, str], ...]
    offers: tuple[FareOffer, ...]
    observed_at: str | None
