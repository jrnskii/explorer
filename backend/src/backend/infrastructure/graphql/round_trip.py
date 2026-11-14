"""Serialize solver results with resolved city markers using the shared schema."""

from collections.abc import Iterable, Mapping
from dataclasses import asdict

from backend.domain.cities import City
from backend.domain.planning import RoundTrip
from backend.infrastructure.graphql.models import RoundTripOption


def serialize_options(
    options: Iterable[RoundTrip], cities: Mapping[str, City]
) -> list[dict[str, object]]:
    def city_payload(city_id: str) -> dict[str, object]:
        city = cities.get(city_id)
        if city is None:
            raise ValueError(f"missing map coordinates for city: {city_id}")
        if city.id != city_id:
            raise ValueError(f"city catalog identity mismatch: {city_id}")
        return asdict(city)

    return [
        RoundTripOption.model_validate(
            {
                "city_stays": [asdict(stay) for stay in option.city_stays],
                "stay_fit": option.stay_fit,
                "total_price": {
                    "amount": option.total_price.amount,
                    "currency": option.total_price.currency,
                },
                "path": [
                    {
                        "from": leg.origin,
                        "to": leg.destination,
                        "from_city": city_payload(leg.origin),
                        "to_city": city_payload(leg.destination),
                        "departure_at": leg.departure_at,
                        "arrival_at": leg.arrival_at,
                        "time_in_travel": leg.time_in_travel,
                        "transport_type": leg.transport_type.value,
                    }
                    for leg in option.path
                ],
            }
        ).model_dump(mode="json", by_alias=True)
        for option in options
    ]
