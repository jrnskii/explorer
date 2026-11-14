"""Validate the shared wire contract and map it to domain settings."""

import json
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.application.telemetry import traced
from backend.domain.planning import CityAttractiveness, Money, SearchSettings
from backend.domain.travel import TransportType
from backend.infrastructure.graphql.models import RoundTripSearchInput


@traced
def parse_settings(payload: str) -> SearchSettings:
    wire = RoundTripSearchInput.model_validate_json(
        payload, strict=True, extra="forbid"
    )
    raw = json.loads(payload)
    if raw.get("expenses_tolerance") is not None and not isinstance(
        raw["expenses_tolerance"]["amount"], str
    ):
        raise ValueError("Decimal amounts must be encoded as JSON strings")
    if wire.departure_timezone is not None:
        try:
            ZoneInfo(wire.departure_timezone)
        except (KeyError, ValueError) as exc:
            raise ValueError("Invalid departure timezone") from exc
    return SearchSettings(
        departure_timezone=wire.departure_timezone,
        departure_city=wire.departure_city,
        departure_date=wire.departure_date,
        desired_arrival_date=wire.desired_arrival_date,
        time_tolerance=wire.time_tolerance,
        expenses_tolerance=(
            Money(wire.expenses_tolerance.amount, wire.expenses_tolerance.currency)
            if wire.expenses_tolerance
            else Money(Decimal(0), "EUR")
        ),
        transport_types=tuple(
            TransportType(mode.value) for mode in wire.transport_types
        ),
        mandatory_cities=tuple(wire.mandatory_cities),
        excluded_cities=tuple(wire.excluded_cities),
        max_trip_duration=wire.max_trip_duration,
        min_cities=wire.min_cities,
        fuzzy_search=wire.fuzzy_search,
        city_attractiveness=tuple(
            CityAttractiveness(item.city, item.weight)
            for item in wire.city_attractiveness
        ),
    )
