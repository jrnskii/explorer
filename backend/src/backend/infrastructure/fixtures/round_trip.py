"""Small, explicitly synthetic multimodal schedule and price overlay.

City IDs are fixture-local canonical IDs, never airport codes. Ground/water
connections below are invented demo services, not accepted reference topology.
"""

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from backend.domain.planning import (
    JourneyOffer,
    Money,
    SearchSettings,
    TripLeg,
    instant,
)
from backend.domain.travel import TransportType
from backend.infrastructure.fixtures.ignav import MockIgnavGenerator

# Reviewed mapping for this demo; production catalog IDs are a separate scope.
CITY_AIRPORTS = {
    "pl-warsaw": "WAW",
    "pl-krakow": "KRK",
    "fr-paris": "CDG",
    "gb-london": "LHR",
    "nl-amsterdam": "AMS",
}
# Explicit synthetic corridor, km and ride minutes. Reverse demos are explicit.
_SURFACE_ROUTES = (
    ("pl-warsaw", "pl-krakow", TransportType.TRAINS, 250, 180),
    ("pl-krakow", "pl-warsaw", TransportType.TRAINS, 250, 180),
    ("fr-paris", "nl-amsterdam", TransportType.BUSSES, 430, 420),
    ("nl-amsterdam", "fr-paris", TransportType.BUSSES, 430, 420),
    ("gb-london", "nl-amsterdam", TransportType.FERRIES, 350, 540),
    ("nl-amsterdam", "gb-london", TransportType.FERRIES, 350, 540),
)


class StaticTransportPrices:
    """Synthetic USD totals for one adult; replace behind the overlay boundary."""

    @staticmethod
    def train(distance_km: int) -> Money:
        return StaticTransportPrices._price(distance_km, "8", "0.08")

    @staticmethod
    def bus(distance_km: int) -> Money:
        return StaticTransportPrices._price(distance_km, "5", "0.04")

    @staticmethod
    def ferry(distance_km: int) -> Money:
        return StaticTransportPrices._price(distance_km, "15", "0.10")

    @staticmethod
    def _price(distance_km: int, base: str, rate: str) -> Money:
        if type(distance_km) is not int or distance_km < 0:
            raise ValueError("distance_km must be a non-negative integer")
        return Money(
            (Decimal(base) + Decimal(rate) * distance_km).quantize(Decimal("0.01")),
            "USD",
        )


def mock_offers(
    settings: SearchSettings, *, seed: int = 0, count: int = 8
) -> tuple[JourneyOffer, ...]:
    """Resolve a finite overlay once, before the solver starts (no network)."""
    cities = {
        settings.departure_city,
        *settings.mandatory_cities,
        *settings.excluded_cities,
    }
    if not cities <= CITY_AIRPORTS.keys():
        raise ValueError(
            f"unsupported fixture city; supported IDs: {', '.join(CITY_AIRPORTS)}"
        )
    if settings.expenses_tolerance.currency != "USD":
        raise ValueError(
            "mock providers support USD only; currency conversion is unsupported"
        )
    start = instant(settings.departure_date).date() - timedelta(days=1)
    end = settings.return_window[1].date()
    if (end - start).days > 32:
        raise ValueError("mock overlay supports a search horizon of at most 31 days")
    generator = MockIgnavGenerator(seed=seed, count=count)
    by_airport = {airport: city for city, airport in CITY_AIRPORTS.items()}
    offers = []
    day = start
    while day <= end:
        for origin, destination, mode, distance, minutes in _SURFACE_ROUTES:
            if mode not in settings.transport_types:
                continue
            price_method = {
                TransportType.TRAINS: StaticTransportPrices.train,
                TransportType.BUSSES: StaticTransportPrices.bus,
                TransportType.FERRIES: StaticTransportPrices.ferry,
            }[mode]
            for hour in (8, 16):
                departure = datetime.combine(day, time(hour), timezone.utc)
                leg = TripLeg(
                    origin,
                    destination,
                    departure,
                    departure + timedelta(minutes=minutes),
                    mode,
                )
                offers.append(
                    JourneyOffer(
                        f"mock:{mode}:{origin}:{destination}:{departure.isoformat()}",
                        (leg,),
                        price_method(distance),
                        "static-transport-demo",
                        True,
                    )
                )
        if TransportType.PLANES in settings.transport_types:
            for origin, airport in CITY_AIRPORTS.items():
                for destination, target in CITY_AIRPORTS.items():
                    if origin == destination or {origin, destination} & set(
                        settings.excluded_cities
                    ):
                        continue
                    # Direct one-way offers avoid inventing terminal access/transfers.
                    response = generator.one_way(
                        {
                            "origin": airport,
                            "destination": target,
                            "departure_date": day.isoformat(),
                            "adults": 1,
                            "max_stops": 0,
                        }
                    )
                    for itinerary in response.itineraries:
                        path = tuple(
                            TripLeg(
                                by_airport[segment.departure_airport],
                                by_airport[segment.arrival_airport],
                                datetime.fromisoformat(segment.departure_time_utc),
                                datetime.fromisoformat(segment.arrival_time_utc),
                                TransportType.PLANES,
                            )
                            for segment in itinerary.outbound.segments
                        )
                        offers.append(
                            JourneyOffer(
                                f"mock-ignav:{day}:{itinerary.ignav_id}",
                                path,
                                Money(
                                    Decimal(str(itinerary.price.amount)),
                                    itinerary.price.currency,
                                ),
                                "mock-ignav",
                                True,
                            )
                        )
        day += timedelta(days=1)
    return tuple(offers)


class MockRoundTripProvider:
    """Offline implementation of the replaceable JourneyOfferProvider port."""

    def __init__(self, *, seed: int = 0, count: int = 8):
        self.seed = seed
        self.count = count

    def offers(self, settings: SearchSettings) -> tuple[JourneyOffer, ...]:
        return mock_offers(settings, seed=self.seed, count=self.count)
