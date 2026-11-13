"""Offline, seeded Ignav fixtures. No network requests or real booking links."""

from __future__ import annotations

import json
import random
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from backend.infrastructure.ignav import models as api

# Coordinates and IANA zones let local times remain correct across DST and dates.
_AIRPORTS = (
    (
        "JFK",
        "John F. Kennedy International Airport",
        "New York",
        "US",
        "America/New_York",
        40.64,
        -73.78,
    ),
    (
        "LAX",
        "Los Angeles International Airport",
        "Los Angeles",
        "US",
        "America/Los_Angeles",
        33.94,
        -118.41,
    ),
    (
        "ORD",
        "O'Hare International Airport",
        "Chicago",
        "US",
        "America/Chicago",
        41.97,
        -87.90,
    ),
    ("LHR", "Heathrow Airport", "London", "GB", "Europe/London", 51.47, -0.45),
    ("CDG", "Charles de Gaulle Airport", "Paris", "FR", "Europe/Paris", 49.01, 2.55),
    (
        "AMS",
        "Amsterdam Airport Schiphol",
        "Amsterdam",
        "NL",
        "Europe/Amsterdam",
        52.31,
        4.76,
    ),
    ("FRA", "Frankfurt Airport", "Frankfurt", "DE", "Europe/Berlin", 50.03, 8.57),
    ("WAW", "Warsaw Chopin Airport", "Warsaw", "PL", "Europe/Warsaw", 52.17, 20.97),
    ("WMI", "Warsaw Modlin Airport", "Warsaw", "PL", "Europe/Warsaw", 52.45, 20.65),
    (
        "KRK",
        "John Paul II International Airport",
        "Krakow",
        "PL",
        "Europe/Warsaw",
        50.08,
        19.78,
    ),
    (
        "BCN",
        "Josep Tarradellas Barcelona-El Prat Airport",
        "Barcelona",
        "ES",
        "Europe/Madrid",
        41.30,
        2.08,
    ),
    (
        "FCO",
        "Leonardo da Vinci-Fiumicino Airport",
        "Rome",
        "IT",
        "Europe/Rome",
        41.80,
        12.25,
    ),
    ("DXB", "Dubai International Airport", "Dubai", "AE", "Asia/Dubai", 25.25, 55.36),
    ("HND", "Tokyo Haneda Airport", "Tokyo", "JP", "Asia/Tokyo", 35.55, 139.78),
    (
        "SIN",
        "Singapore Changi Airport",
        "Singapore",
        "SG",
        "Asia/Singapore",
        1.36,
        103.99,
    ),
)
_AIRPORT_BY_CODE = {airport[0]: airport for airport in _AIRPORTS}
_CARRIERS = {
    "LO": "LOT Polish Airlines",
    "LH": "Lufthansa",
    "BA": "British Airways",
    "AF": "Air France",
    "KL": "KLM",
    "AA": "American Airlines",
    "FR": "Ryanair",
    "W6": "Wizz Air",
}
_UTC = timezone.utc


def _request(
    model: type[BaseModel], value: BaseModel | dict[str, Any]
) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return model.model_validate(value).model_dump(mode="json")


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _airport(code: str) -> tuple:
    try:
        return _AIRPORT_BY_CODE[code.upper()]
    except KeyError:
        raise ValueError(
            f"Unsupported mock airport: {code!r}; use airports() to list supported codes"
        ) from None


def _duration(origin: str, destination: str) -> int:
    a, b = _airport(origin), _airport(destination)
    lat1, lon1, lat2, lon2 = map(radians, (a[5], a[6], b[5], b[6]))
    distance = 12742 * asin(
        min(
            1,
            sqrt(
                sin((lat2 - lat1) / 2) ** 2
                + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
            ),
        )
    )
    return max(45, round(distance / 800 * 60 + 30))


def _in_hours(leg: dict, bounds: dict | None) -> bool:
    if not bounds:
        return True
    for prefix, timestamp in (
        ("", leg["segments"][0]["departure_time_local"]),
        ("arrival_", leg["segments"][-1]["arrival_time_local"]),
    ):
        hour = datetime.fromisoformat(timestamp).hour
        earliest = bounds.get(prefix + "earliest_hour")
        latest = bounds.get(prefix + "latest_hour")
        if (
            earliest is not None
            and hour < earliest
            or latest is not None
            and hour > latest
        ):
            return False
    return True


class MockIgnavGenerator:
    """Generate typed Ignav responses reproducibly for a seed and request.

    `count` is the candidate count before filtering, not a guaranteed result count.
    IDs can be resolved by booking_links on this same generator instance.
    """

    def __init__(
        self, seed: int = 0, count: int = 8, observed_at: datetime | None = None
    ):
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= 100
        ):
            raise ValueError("count must be an integer between 1 and 100")
        observed_at = observed_at or datetime(2026, 1, 1, tzinfo=_UTC)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        self.seed = seed
        self.count = count
        self.observed_at = observed_at.astimezone(_UTC)
        self._itineraries: dict[str, tuple[dict, bool]] = {}

    def health(self) -> api.HealthResponseModel:
        return api.HealthResponseModel(ok=True, release="mock-ignav-0.1.0")

    def airports(self, q: str, limit: int = 10) -> list[api.AirportModel]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 20
        ):
            raise ValueError("limit must be an integer between 1 and 20")
        query = q.strip().casefold()
        matches = [
            a for a in _AIRPORTS if any(query in field.casefold() for field in a[:4])
        ]
        matches.sort(key=lambda a: (a[0].casefold() != query, a[0]))
        return [
            api.AirportModel(code=a[0], name=a[1], city=a[2], country=a[3])
            for a in matches[:limit]
        ]

    def _leg(
        self, leg: dict, index: int, rng: random.Random, carrier: str, mixed: bool
    ) -> dict:
        origin, destination = leg["origin"], leg["destination"]
        stops = index % 3
        hubs = [a[0] for a in _AIRPORTS if a[0] not in (origin, destination)]
        route = [origin, *rng.sample(hubs, stops), destination]
        local = datetime.combine(
            date.fromisoformat(leg["departure_date"]),
            time(rng.randrange(24), rng.choice((0, 15, 30, 45))),
            ZoneInfo(_airport(origin)[4]),
        )
        departure = local.astimezone(_UTC)
        start = departure
        arrival = departure
        segments = []
        for n, (a, b) in enumerate(zip(route, route[1:])):
            code = (
                rng.choice([c for c in _CARRIERS if c != carrier])
                if mixed and n
                else carrier
            )
            duration = _duration(a, b)
            arrival = departure + timedelta(minutes=duration)
            departure_zone, arrival_zone = _airport(a)[4], _airport(b)[4]
            segments.append(
                dict(
                    marketing_carrier_code=code,
                    flight_number=str(rng.randrange(100, 9999)),
                    operating_carrier_name=_CARRIERS[code],
                    departure_airport=a,
                    departure_time_local=departure.astimezone(ZoneInfo(departure_zone))
                    .replace(tzinfo=None)
                    .isoformat(),
                    departure_timezone=departure_zone,
                    departure_time_utc=departure.isoformat(),
                    arrival_airport=b,
                    arrival_time_local=arrival.astimezone(ZoneInfo(arrival_zone))
                    .replace(tzinfo=None)
                    .isoformat(),
                    arrival_timezone=arrival_zone,
                    arrival_time_utc=arrival.isoformat(),
                    duration_minutes=duration,
                    aircraft="Airbus A320" if duration < 300 else "Boeing 787-9",
                )
            )
            departure = arrival + timedelta(minutes=90)
        return dict(
            carrier=_CARRIERS[carrier]
            if not mixed or not stops
            else "Multiple airlines",
            duration_minutes=int((arrival - start).total_seconds() / 60),
            segments=segments,
        )

    def search(self, request: api.FareSearchRequest | dict) -> api.FareSearchModel:
        data = _request(api.FareSearchRequest, request)
        for key in ("carry_on_bags", "checked_bags"):
            data[key] = data[key] or None
        seats = data["adults"] + data["children"] + data["infants_in_seat"]
        if any((data[key] or 0) > seats for key in ("carry_on_bags", "checked_bags")):
            raise ValueError(
                "Requested bags cannot exceed the number of travelers with seats"
            )
        legs = data["legs"]
        for leg in legs:
            leg["origin"] = _airport(leg["origin"])[0]
            leg["destination"] = _airport(leg["destination"])[0]
            if leg["origin"] == leg["destination"]:
                raise ValueError("origin and destination must differ")
            bounds = leg["departure_time_range"] or {}
            for prefix in ("", "arrival_"):
                low, high = (
                    bounds.get(prefix + "earliest_hour"),
                    bounds.get(prefix + "latest_hour"),
                )
                if low is not None and high is not None and low > high:
                    raise ValueError(
                        "Time range earliest hour must not exceed latest hour"
                    )
        if len(legs) == 2 and legs[1]["departure_date"] < legs[0]["departure_date"]:
            raise ValueError("Second departure date must not precede the first")
        # Filters do not perturb candidate generation, so narrowing a search only removes results.
        identity = {
            k: v
            for k, v in data.items()
            if k
            not in (
                "max_price",
                "airlines_include",
                "airlines_exclude",
                "allow_mixed_carriers",
                "legs",
            )
        }
        identity["legs"] = [
            {
                k: v
                for k, v in leg.items()
                if k not in ("max_stops", "departure_time_range")
            }
            for leg in legs
        ]
        rng = random.Random(_digest([self.seed, identity]))
        include = {c.upper() for c in data["airlines_include"] or []}
        exclude = {c.upper() for c in data["airlines_exclude"] or []}
        results = []
        for index in range(self.count):
            carrier = list(_CARRIERS)[index % len(_CARRIERS)]
            mixed = index % 4 == 3
            generated = [self._leg(leg, index, rng, carrier, mixed) for leg in legs]
            price = round(
                (
                    sum(l["duration_minutes"] for l in generated) * 0.35
                    + rng.uniform(30, 120)
                )
                * {"economy": 1, "premium_economy": 1.7, "business": 3, "first": 5}[
                    data["cabin_class"]
                ]
                * seats
                + data["infants_on_lap"] * 20
                + ((data["carry_on_bags"] or 0) * 15 + (data["checked_bags"] or 0) * 30)
                * len(legs),
                2,
            )
            codes = {
                s["marketing_carrier_code"] for l in generated for s in l["segments"]
            }
            has_mixed = any(
                len({s["marketing_carrier_code"] for s in l["segments"]}) > 1
                for l in generated
            )
            if (
                (include and not codes <= include)
                or codes & exclude
                or (has_mixed and not data["allow_mixed_carriers"])
            ):
                continue
            if data["max_price"] is not None and price > data["max_price"]:
                continue
            if any(
                (
                    leg["max_stops"] is not None
                    and len(result["segments"]) - 1 > leg["max_stops"]
                )
                or not _in_hours(result, leg["departure_time_range"])
                for leg, result in zip(legs, generated)
            ):
                continue
            if len(generated) == 2 and datetime.fromisoformat(
                generated[1]["segments"][0]["departure_time_utc"]
            ) <= datetime.fromisoformat(
                generated[0]["segments"][-1]["arrival_time_utc"]
            ):
                continue
            itinerary = dict(
                price=dict(amount=price, currency="USD", status="unverified"),
                legs=generated,
                cabin_class=data["cabin_class"],
                bags=dict(carry_on=1, checked=0),
                baggage_pricing=dict(
                    carry_on_bags=data["carry_on_bags"] or 0,
                    checked_bags=data["checked_bags"] or 0,
                    status="estimated",
                ),
                has_mixed_carriers=has_mixed,
            )
            itinerary["ignav_id"] = "mock_" + _digest(itinerary)[:24]
            results.append(itinerary)
            self._itineraries[itinerary["ignav_id"]] = (deepcopy(itinerary), True)
        return api.FareSearchModel.model_validate(
            dict(
                legs=[
                    {k: l[k] for k in ("origin", "destination", "departure_date")}
                    for l in legs
                ],
                itineraries=sorted(results, key=lambda i: i["price"]["amount"]),
                observed_at=self.observed_at,
            )
        )

    def _directional(self, data: dict, round_trip: bool) -> api.FareSearchResponseModel:
        outbound = {k: data.pop(k) for k in ("origin", "destination", "departure_date")}
        outbound["max_stops"] = data.pop("max_stops")
        outbound["departure_time_range"] = data.pop("departure_time_range")
        return_date = data.pop("return_date", None)
        return_time = data.pop("return_time_range", None)
        legs = [outbound]
        if round_trip:
            legs.append(
                dict(
                    origin=outbound["destination"],
                    destination=outbound["origin"],
                    departure_date=return_date,
                    max_stops=outbound["max_stops"],
                    departure_time_range=return_time,
                )
            )
        result = self.search(dict(data, legs=legs))
        itineraries = []
        for item in result.itineraries:
            raw = item.model_dump(mode="json")
            directions = raw.pop("legs")
            raw.update(
                outbound=directions[0], inbound=directions[1] if round_trip else None
            )
            # Keep IDs distinct between the two booking-response shapes.
            raw["ignav_id"] = "mock_" + _digest(raw)[:24]
            self._itineraries[raw["ignav_id"]] = (deepcopy(raw), False)
            itineraries.append(raw)
        return api.FareSearchResponseModel.model_validate(
            dict(
                origin=result.legs[0].origin,
                destination=result.legs[0].destination,
                departure_date=outbound["departure_date"],
                return_date=return_date,
                itineraries=itineraries,
                observed_at=self.observed_at,
            )
        )

    def one_way(self, request: api.OneWayRequest | dict) -> api.FareSearchResponseModel:
        return self._directional(_request(api.OneWayRequest, request), False)

    def round_trip(
        self, request: api.RoundTripRequest | dict
    ) -> api.FareSearchResponseModel:
        return self._directional(_request(api.RoundTripRequest, request), True)

    def cheapest_dates(
        self, request: api.CheapestDatesRequest | dict
    ) -> api.CheapestDatesResponseModel:
        data = _request(api.CheapestDatesRequest, request)
        window = data.pop("departure_date_range")
        start, end = (
            date.fromisoformat(window["start"]),
            date.fromisoformat(window["end"]),
        )
        if end < start or (end - start).days > 365:
            raise ValueError(
                "Departure window must be ordered and at most 366 inclusive dates"
            )
        stay = data.pop("stay_days")
        dates = []
        for offset in range((end - start).days + 1):
            departure = start + timedelta(days=offset)
            query = dict(data, departure_date=departure.isoformat())
            return_date = None
            if stay is None:
                query.pop("return_time_range")
                result = self.one_way(query)
            else:
                return_date = (departure + timedelta(days=stay)).isoformat()
                result = self.round_trip(dict(query, return_date=return_date))
            dates.append(
                dict(
                    departure_date=departure.isoformat(),
                    return_date=return_date,
                    price=result.itineraries[0].price if result.itineraries else None,
                )
            )
        return api.CheapestDatesResponseModel(
            origin=_airport(data["origin"])[0],
            destination=_airport(data["destination"])[0],
            dates=dates,
            observed_at=self.observed_at,
        )

    def booking_links(
        self, request: api.BookingLinksRequest | dict
    ) -> api.BookingOptionsResponseModel | api.SearchBookingOptionsResponseModel:
        data = _request(api.BookingLinksRequest, request)
        if data["ignav_id"]:
            try:
                itinerary, search_shape = deepcopy(self._itineraries[data["ignav_id"]])
            except KeyError:
                raise ValueError(
                    "Unknown mock ignav_id; search with this generator instance first"
                ) from None
        else:
            if not all(data[k] for k in ("origin", "destination", "departure_date")):
                raise ValueError(
                    "Provide ignav_id or origin, destination and departure_date"
                )
            query = {
                k: data[k]
                for k in (
                    "origin",
                    "destination",
                    "departure_date",
                    "adults",
                    "children",
                    "infants_in_seat",
                    "infants_on_lap",
                    "market",
                )
                if data[k] is not None
            }
            query["max_stops"] = 0
            if data["return_date"] is not None:
                query["return_date"] = data["return_date"]
                result = self.round_trip(query)
            else:
                result = self.one_way(query)
            if not result.itineraries:
                raise ValueError("No mock itinerary matches the booking request")
            itinerary = result.itineraries[0].model_dump(mode="json")
            search_shape = False
            for direction in ("outbound", "inbound"):
                carrier, number = (
                    data[direction + "_carrier_code"],
                    data[direction + "_flight_number"],
                )
                if bool(carrier) != bool(number):
                    raise ValueError(
                        "Carrier code and flight number must be supplied together"
                    )
                if carrier:
                    carrier = carrier.upper()
                    if carrier not in _CARRIERS or itinerary.get(direction) is None:
                        raise ValueError(
                            f"Unsupported mock {direction} carrier or missing leg"
                        )
                    leg = itinerary[direction]
                    leg["carrier"] = _CARRIERS[carrier]
                    leg["segments"][0].update(
                        marketing_carrier_code=carrier,
                        operating_carrier_name=_CARRIERS[carrier],
                        flight_number=number,
                    )
        ignav_id = itinerary.pop("ignav_id")
        links = [
            dict(
                provider_name="Mock travel provider",
                provider_type="third_party",
                specificity="search_results",
                fare_name="Mock fare",
                price=itinerary["price"],
                baggage_pricing=itinerary["baggage_pricing"],
                url=f"https://booking.example/itineraries/{ignav_id}",
            )
        ]
        if search_shape:
            return api.SearchBookingOptionsResponseModel.model_validate(
                dict(
                    itinerary=itinerary,
                    booking_options=[
                        dict(
                            leg_indexes=list(range(len(itinerary["legs"]))), links=links
                        )
                    ],
                )
            )
        return api.BookingOptionsResponseModel.model_validate(
            dict(
                itinerary=itinerary,
                booking_options=[
                    dict(
                        legs=["outbound", "inbound"]
                        if itinerary.get("inbound")
                        else ["outbound"],
                        links=links,
                    )
                ],
            )
        )
