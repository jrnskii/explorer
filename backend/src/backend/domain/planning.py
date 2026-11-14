"""Provider-independent, immutable scheduled purchase units and v1 constraints."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import math

from backend.domain.travel import TransportType


def instant(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include an explicit UTC offset")
    return value.astimezone(timezone.utc)


def identifier(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(
            "city identifiers must be non-empty without surrounding whitespace"
        )


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self):
        if (
            not isinstance(self.amount, Decimal)
            or not self.amount.is_finite()
            or self.amount < 0
        ):
            raise ValueError("amount must be a finite non-negative Decimal")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError(
                "currency must be an uppercase three-letter ISO currency code"
            )


@dataclass(frozen=True)
class CityAttractiveness:
    city: str
    weight: float

    def __post_init__(self):
        identifier(self.city)
        if (
            type(self.weight) not in (int, float)
            or not math.isfinite(self.weight)
            or self.weight <= 0
        ):
            raise ValueError("attractiveness must be finite and strictly positive")


@dataclass(frozen=True)
class SearchSettings:
    departure_city: str
    departure_date: datetime
    desired_arrival_date: datetime
    time_tolerance: int
    expenses_tolerance: Money
    transport_types: tuple[TransportType, ...]
    mandatory_cities: tuple[str, ...] = ()
    excluded_cities: tuple[str, ...] = ()
    max_trip_duration: int | None = None
    city_attractiveness: tuple[CityAttractiveness, ...] = ()
    fuzzy_search: bool = False
    min_cities: int = 1
    latest_departure_date: datetime | None = None
    departure_timezone: str | None = None

    def __post_init__(self):
        identifier(self.departure_city)
        if self.latest_departure_date is not None and instant(self.latest_departure_date) < instant(self.departure_date):
            raise ValueError("latest departure must follow earliest departure")
        if type(self.min_cities) is not int or not 1 <= self.min_cities <= 2**31 - 1:
            raise ValueError("min_cities must be a positive GraphQL Int")
        if type(self.fuzzy_search) is not bool:
            raise ValueError("fuzzy_search must be a boolean")
        if self.max_trip_duration is not None and (
            type(self.max_trip_duration) is not int
            or not 1 <= self.max_trip_duration <= 2**31 - 1
        ):
            raise ValueError("max_trip_duration must be positive GraphQL Int seconds")
        weighted_cities = [item.city for item in self.city_attractiveness]
        if len(set(weighted_cities)) != len(weighted_cities):
            raise ValueError("attractiveness cities must be distinct")
        if set(weighted_cities) & {self.departure_city, *self.excluded_cities}:
            raise ValueError("attractiveness cannot refer to home or excluded cities")
        for cities in (self.mandatory_cities, self.excluded_cities):
            for city in cities:
                identifier(city)
            if len(cities) != len(set(cities)):
                raise ValueError("city lists must contain distinct identifiers")
        if self.departure_city in (*self.mandatory_cities, *self.excluded_cities):
            raise ValueError("home must not be mandatory or excluded")
        if set(self.mandatory_cities) & set(self.excluded_cities):
            raise ValueError("mandatory and excluded cities must not overlap")
        if not self.transport_types or len(set(self.transport_types)) != len(
            self.transport_types
        ):
            raise ValueError("transport_types must be non-empty and distinct")
        if any(not isinstance(mode, TransportType) for mode in self.transport_types):
            raise ValueError("unsupported transport mode")
        if (
            type(self.time_tolerance) is not int
            or not 0 <= self.time_tolerance <= 2**31 - 1
        ):
            raise ValueError("time_tolerance must be a non-negative GraphQL Int")
        if instant(self.desired_arrival_date) <= instant(self.departure_date):
            raise ValueError("desired_arrival_date must be after departure_date")
        # Check arithmetic range at the boundary, before exploring any states.
        self.return_window

    @property
    def return_window(self) -> tuple[datetime, datetime]:
        try:
            target = instant(self.desired_arrival_date)
            tolerance = timedelta(minutes=self.time_tolerance)
            latest = target + tolerance
            if self.max_trip_duration is not None:
                latest = min(
                    latest,
                    instant(self.departure_date)
                    + timedelta(seconds=self.max_trip_duration),
                )
            return target - tolerance, latest
        except OverflowError as exc:
            raise ValueError("return window exceeds supported datetime range") from exc


@dataclass(frozen=True)
class TripLeg:
    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime
    transport_type: TransportType

    def __post_init__(self):
        identifier(self.origin)
        identifier(self.destination)
        if not isinstance(self.transport_type, TransportType):
            raise ValueError("unsupported transport mode")
        seconds = (
            instant(self.arrival_at) - instant(self.departure_at)
        ).total_seconds()
        if seconds <= 0 or not seconds.is_integer() or seconds > 2**31 - 1:
            raise ValueError("leg duration must be positive whole GraphQL Int seconds")

    @property
    def time_in_travel(self) -> int:
        return int(
            (instant(self.arrival_at) - instant(self.departure_at)).total_seconds()
        )


@dataclass(frozen=True)
class JourneyOffer:
    """One independently purchasable ticket, possibly with multiple segments."""

    id: str
    path: tuple[TripLeg, ...]
    price: Money
    source: str
    synthetic: bool

    def __post_init__(self):
        if not self.id or not self.path or not self.source:
            raise ValueError("offer requires identity, source and a non-empty path")
        for previous, following in zip(self.path, self.path[1:]):
            if previous.destination != following.origin or instant(
                following.departure_at
            ) < instant(previous.arrival_at):
                raise ValueError("offer segments must be connected and chronological")


@dataclass(frozen=True)
class CityStay:
    city: str
    time_spent: float
    target_time: float
    attractiveness: float


@dataclass(frozen=True)
class RoundTrip:
    offers: tuple[JourneyOffer, ...]
    total_price: Money
    city_stays: tuple[CityStay, ...] = ()
    stay_fit: float | None = None
    price_status: str = "supplied"
    approximate_price: Money | None = None
    ranking_adjustment: Money | None = None

    @property
    def path(self) -> tuple[TripLeg, ...]:
        return tuple(leg for offer in self.offers for leg in offer.path)
