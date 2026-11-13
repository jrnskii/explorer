"""Validate Ignav wire data and translate it into domain fare-search values."""

import json
from collections.abc import Mapping
from typing import Any

from backend.domain.fares import FareOffer, FarePrice, FareSearch, FlightSegment
from backend.infrastructure.ignav.models import FareSearchModel, FareSearchResponseModel

type IgnavResponse = (
    Mapping[str, Any] | str | bytes | FareSearchModel | FareSearchResponseModel
)


def read_fare_search(response: IgnavResponse) -> FareSearch:
    if isinstance(response, (str, bytes)):
        response = json.loads(response)
    if isinstance(response, (FareSearchModel, FareSearchResponseModel)):
        result = response
    elif isinstance(response, Mapping):
        model = FareSearchModel if "legs" in response else FareSearchResponseModel
        result = model.model_validate(dict(response))
    else:
        raise TypeError(
            "response must be an Ignav fare response, mapping, or JSON object"
        )

    payload = result.model_dump(mode="json")
    requested_legs = (
        payload["legs"] if isinstance(result, FareSearchModel) else [payload]
    )
    offers = []
    for itinerary in payload["itineraries"]:
        if "legs" in itinerary:
            legs = itinerary["legs"]
        else:
            legs = [itinerary["outbound"]]
            if itinerary["inbound"] is not None:
                legs.append(itinerary["inbound"])
        offers.append(
            FareOffer(
                legs=tuple(
                    tuple(FlightSegment(**segment) for segment in leg["segments"])
                    for leg in legs
                ),
                price=FarePrice(**itinerary["price"]),
                offer_id=itinerary["ignav_id"],
                cabin_class=itinerary["cabin_class"],
            )
        )
    return FareSearch(
        requested_routes=tuple(
            (leg["origin"], leg["destination"]) for leg in requested_legs
        ),
        offers=tuple(offers),
        observed_at=payload["observed_at"],
    )
