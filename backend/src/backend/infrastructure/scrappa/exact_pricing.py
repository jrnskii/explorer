"""Provider-advertised prices for one selected route, using the persistent cache.

Scrappa does not expose a guaranteed checkout-fee total. No booking is started.
"""

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
import hashlib
import logging

from backend.application.telemetry import traced, event
from backend.application.round_trip_search import sum_exact
from backend.domain.planning import JourneyOffer, Money, TripLeg, instant
from backend.domain.pricing import (
    ExactPricingUnavailable,
    QuotedPurchase,
    RoundTripQuote,
)
from backend.domain.travel import TransportType
from backend.infrastructure.scrappa.client import ScrappaError, matches_one_way_search, normalize

MODES = {
    TransportType.PLANES: "flight",
    TransportType.TRAINS: "train",
    TransportType.BUSSES: "bus",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Service:
    offer: JourneyOffer
    trip_id: str
    raw: dict


def _time(value):
    if not isinstance(value, str):
        raise ValueError("Missing provider timestamp")
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    instant(value)
    return value


def _parse(raw, planned, mode, currency, day):
    """Only direct independently purchasable one-way services can be mapped safely."""
    if (
        not isinstance(raw, dict)
        or raw.get("mode") != mode
        or raw.get("is_bookable") is not True
    ):
        return None
    if (
        raw.get("is_split_ticket") is not False
        or raw.get("is_routed_connection") is not False
    ):
        return None
    legs = raw.get("legs")
    if (
        not isinstance(legs, list)
        or len(legs) != 1
        or not isinstance(legs[0], dict)
        or legs[0].get("mode") != mode
    ):
        return None
    try:
        start, end = _time(raw.get("departure_time")), _time(raw.get("arrival_time"))
        if (
            start.date().isoformat() != day
            or instant(start) != instant(_time(legs[0].get("departure_time")))
            or instant(end) != instant(_time(legs[0].get("arrival_time")))
        ):
            return None
        leg = TripLeg(
            planned.path[0].origin,
            planned.path[-1].destination,
            start,
            end,
            planned.path[0].transport_type,
        )
    except (ValueError, TypeError, OverflowError):
        return None
    prices = []
    for fare in raw.get("offers", []) if isinstance(raw.get("offers"), list) else []:
        if (
            not isinstance(fare, dict)
            or fare.get("type") != "ONE_WAY"
            or fare.get("is_available") is not True
        ):
            continue
        if fare.get("discount_cards") != [] or fare.get("unavailability_reasons", []):
            continue
        price = fare.get("price")
        if not isinstance(price, dict) or price.get("currency") != currency:
            continue
        minor = price.get("amount_minor")
        if type(minor) is int and minor >= 0:
            prices.append(Decimal(f"{minor // 100}.{minor % 100:02d}"))
    trip_id = raw.get("trip_id")
    if not prices or not isinstance(trip_id, str) or not trip_id:
        return None
    offer = JourneyOffer(
        planned.id, (leg,), Money(min(prices), currency), "scrappa:" + trip_id, False
    )
    return _Service(offer, trip_id, raw)


class ScrappaRoundTripPricer:
    def __init__(self, client, place_ids, *, cities=None, cache_only=False, min_connection_seconds=0, refresh=False):
        if type(min_connection_seconds) is not int or min_connection_seconds < 0:
            raise ValueError("min_connection_seconds must be a non-negative integer")
        self.refresh = refresh
        self.min_connection_seconds = min_connection_seconds
        self.client, self.place_ids, self.cities, self.cache_only = (
            client,
            dict(place_ids),
            cities or {},
            cache_only,
        )
        if any(
            not isinstance(k, str) or not k or type(v) is not int or v < 1
            for k, v in self.place_ids.items()
        ):
            raise ValueError(
                "Scrappa place mapping requires city IDs and positive integer position IDs"
            )
        self.client.db.execute("""CREATE TABLE IF NOT EXISTS fare_observations (
            observation_id VARCHAR PRIMARY KEY, response_id VARCHAR, search_response_id VARCHAR,
            provider_trip_id VARCHAR, origin_city_id VARCHAR, destination_city_id VARCHAR,
            origin_name VARCHAR, destination_name VARCHAR, origin_country VARCHAR, destination_country VARCHAR,
            origin_position_id BIGINT, destination_position_id BIGINT, mode VARCHAR,
            departure_at TIMESTAMPTZ, arrival_at TIMESTAMPTZ, observed_at TIMESTAMPTZ,
            amount DECIMAL(38,18), currency VARCHAR, adults INTEGER, children INTEGER, infants INTEGER,
            price_scope VARCHAR, fees_complete BOOLEAN)""")

    @traced
    def quote(self, option, settings):
        # Validate all purchase scopes and mappings before spending any API credit.
        planned = []
        for offer in option.offers:
            if len(offer.path) != 1 or offer.path[0].transport_type not in MODES:
                raise ExactPricingUnavailable(
                    "Scrappa verification supports direct train, bus and flight purchases; bundled connections and ferries require another provider"
                )
            leg = offer.path[0]
            if (
                leg.origin not in self.place_ids
                or leg.destination not in self.place_ids
            ):
                raise ExactPricingUnavailable(
                    "Selected route is missing reviewed Scrappa place IDs"
                )
            params = normalize(
                "search",
                dict(
                    origin_id=self.place_ids[leg.origin],
                    destination_id=self.place_ids[leg.destination],
                    date=leg.departure_at.date().isoformat(),
                    travel_mode=MODES[leg.transport_type],
                    currency=settings.expenses_tolerance.currency,
                    adults=1,
                    children=0,
                    infants=0,
                    sort="price",
                    limit=100,
                    page=1,
                ),
            )
            planned.append((offer, params))
        searches = []
        try:
            for offer, params in planned:
                response = self.client.request(
                    "search", params, cache_only=self.cache_only, max_age_seconds=3600, refresh=self.refresh
                )
                data = response.payload["data"]
                if not matches_one_way_search(data, params):
                    raise ExactPricingUnavailable(
                        "Provider search does not match the selected one-way cohort"
                    )
                search_id = (
                    (data.get("search_meta") or {}).get("search_id")
                    if isinstance(data.get("search_meta"), dict)
                    else None
                )
                if not isinstance(search_id, str) or not search_id:
                    raise ExactPricingUnavailable(
                        "Provider search omitted its search identity"
                    )
                services = []
                for raw in (
                    data.get("results", [])
                    if isinstance(data.get("results"), list)
                    else []
                ):
                    service = _parse(
                        raw,
                        offer,
                        params["travel_mode"],
                        params["currency"],
                        params["date"],
                    )
                    if service is not None:
                        services.append(service)
                event(logger, "provider.services_filtered", level=logging.INFO,
                      origin=offer.path[0].origin, destination=offer.path[-1].destination,
                      date=params["date"], mode=params["travel_mode"], source=response.source,
                      returned_count=len(data["results"]) if isinstance(data.get("results"), list) else 0,
                      usable_direct_services=len(services),
                      lowest_amount=str(min(s.offer.price.amount for s in services)) if services else None,
                      currency=params["currency"])
                if not services:
                    raise ExactPricingUnavailable(
                        "No available direct service matched the selected route date and mode"
                    )
                searches.append((response, search_id, services))
            chosen = self._choose_services(searches, settings, self.min_connection_seconds)
            quotes = []
            from_cache = all(response.source == "cache" for response, _, _ in searches)
            for (original, params), (search, search_id, services), service in zip(
                planned, searches, chosen, strict=True
            ):
                response = self.client.request(
                    "trip",
                    dict(search_id=search_id, trip_id=service.trip_id),
                    cache_only=self.cache_only,
                    max_age_seconds=3600,
                    refresh=self.refresh,
                )
                from_cache = from_cache and response.source == "cache"
                data = response.payload["data"]
                if data.get("search_id") != search_id or data.get("currency") != params["currency"]:
                    raise ExactPricingUnavailable(
                        "Provider trip belongs to another search"
                    )
                current = _parse(
                    data.get("trip"),
                    original,
                    params["travel_mode"],
                    params["currency"],
                    params["date"],
                )
                if current is None or current.trip_id != service.trip_id:
                    raise ExactPricingUnavailable(
                        "Selected service is unavailable or changed identity in trip details"
                    )
                observed = min(search.fetched_at, response.fetched_at)
                self._observe(original, current, params, search, response, observed)
                event(logger, "provider.purchase_verified", level=logging.INFO,
                      origin=current.offer.path[0].origin, destination=current.offer.path[-1].destination,
                      amount=str(current.offer.price.amount), currency=current.offer.price.currency,
                      source=response.source)
                quotes.append(
                    QuotedPurchase(
                        original.id,
                        current.offer,
                        (search.response_id, response.response_id),
                        observed,
                        current.trip_id,
                    )
                )
            return RoundTripQuote(tuple(quotes), from_cache=from_cache)
        except ScrappaError as error:
            raise ExactPricingUnavailable(
                "Scrappa verification failed; cached outcomes are retained. Check credentials, freshness and provider availability before retrying explicitly."
            ) from error

    @staticmethod
    @traced
    def _choose_services(searches, settings, min_connection_seconds=0):
        # Dynamic programming varies actual services on the ONE selected city/mode
        # path, never quotes another candidate route. At most 100 services per stage.
        states = [(Decimal(0), instant(settings.departure_date), ())]
        earliest, latest = settings.return_window
        for index, (_, _, services) in enumerate(searches):
            next_states = []
            for service in services:
                if instant(service.offer.path[-1].arrival_at) > latest:
                    continue
                compatible = [
                    s
                    for s in states
                    if (instant(service.offer.path[0].departure_at) - s[1]).total_seconds() >= (min_connection_seconds if index else 0)
                ]
                if not compatible:
                    continue
                previous = min(
                    compatible,
                    key=lambda s: (s[0], s[1], tuple(p.trip_id for p in s[2])),
                )
                amount = sum_exact((previous[0], service.offer.price.amount))
                next_states.append(
                    (
                        amount,
                        instant(service.offer.path[-1].arrival_at),
                        previous[2] + (service,),
                    )
                )
            states = next_states
            if not states:
                raise ExactPricingUnavailable(
                    "Selected route has no feasible provider timetable"
                )
        states = [s for s in states if earliest <= s[1] <= latest]
        if not states:
            raise ExactPricingUnavailable(
                "Selected route has no provider service in the return window"
            )
        return min(states, key=lambda s: (s[0], s[1], tuple(p.trip_id for p in s[2])))[
            2
        ]

    @traced
    def _observe(self, original, service, params, search, response, observed):
        origin = self.cities.get(original.path[0].origin, {})
        destination = self.cities.get(original.path[-1].destination, {})
        identity = hashlib.sha256(
            (response.response_id + ":" + service.trip_id).encode()
        ).hexdigest()
        leg = service.offer.path[0]
        self.client.db.execute(
            """INSERT INTO fare_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (observation_id) DO NOTHING""",
            [
                identity,
                response.response_id,
                search.response_id,
                service.trip_id,
                leg.origin,
                leg.destination,
                origin.get("name"),
                destination.get("name"),
                origin.get("country"),
                destination.get("country"),
                params["origin_id"],
                params["destination_id"],
                params["travel_mode"],
                leg.departure_at,
                leg.arrival_at,
                observed,
                service.offer.price.amount,
                service.offer.price.currency,
                1,
                0,
                0,
                "provider_advertised",
                False,
            ],
        )
