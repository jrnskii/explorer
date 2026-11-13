"""Small deterministic synthetic Vilnius corridor for the logged CLI demo."""

from datetime import datetime
from decimal import Decimal
import logging

from backend.domain.planning import JourneyOffer, Money, TripLeg
from backend.domain.travel import TransportType as Mode
from backend.infrastructure.fixtures.ignav import MockIgnavGenerator
from backend.infrastructure.fixtures.round_trip import StaticTransportPrices

logger = logging.getLogger(__name__)


def demo_offers(seed: int) -> tuple[JourneyOffer, ...]:
    """Tiny synthetic corridor; no claim of real services or availability."""
    offers = []
    for id, origin, destination, start, finish, mode, distance in (
        (
            "vilnius-warsaw-bus",
            "lt-vilnius",
            "pl-warsaw",
            "01T08",
            "01T16",
            Mode.BUSSES,
            400,
        ),
        (
            "vilnius-warsaw-train",
            "lt-vilnius",
            "pl-warsaw",
            "01T06",
            "01T14",
            Mode.TRAINS,
            450,
        ),
        (
            "warsaw-krakow-train",
            "pl-warsaw",
            "pl-krakow",
            "02T06",
            "02T09",
            Mode.TRAINS,
            250,
        ),
        (
            "krakow-warsaw-train",
            "pl-krakow",
            "pl-warsaw",
            "02T16",
            "02T19",
            Mode.TRAINS,
            250,
        ),
        (
            "warsaw-vilnius-bus",
            "pl-warsaw",
            "lt-vilnius",
            "03T08",
            "03T16",
            Mode.BUSSES,
            400,
        ),
    ):
        logger.info(
            "Mock %s price lookup: %s -> %s distance=%skm",
            mode,
            origin,
            destination,
            distance,
        )
        price = (
            StaticTransportPrices.bus
            if mode == Mode.BUSSES
            else StaticTransportPrices.train
        )(distance)
        leg = TripLeg(
            origin,
            destination,
            datetime.fromisoformat(f"2026-12-{start}:00:00+00:00"),
            datetime.fromisoformat(f"2026-12-{finish}:00:00+00:00"),
            mode,
        )
        offers.append(JourneyOffer(id, (leg,), price, "vilnius-demo", True))
        logger.info(
            "Created synthetic service=%s departure=%s arrival=%s price=%s %s",
            id,
            leg.departure_at.isoformat(),
            leg.arrival_at.isoformat(),
            price.amount,
            price.currency,
        )
    generator = MockIgnavGenerator(seed=seed, count=4)
    cities = {"WAW": "pl-warsaw", "KRK": "pl-krakow"}
    for origin, destination in (("WAW", "KRK"), ("KRK", "WAW")):
        request = {
            "origin": origin,
            "destination": destination,
            "departure_date": "2026-12-02",
            "adults": 1,
            "max_stops": 0,
        }
        logger.info("Mock Ignav lookup: %s", request)
        response = generator.one_way(request)
        logger.info("Mock Ignav returned %s offers", len(response.itineraries))
        for itinerary in response.itineraries:
            path = tuple(
                TripLeg(
                    cities[segment.departure_airport],
                    cities[segment.arrival_airport],
                    datetime.fromisoformat(segment.departure_time_utc),
                    datetime.fromisoformat(segment.arrival_time_utc),
                    Mode.PLANES,
                )
                for segment in itinerary.outbound.segments
            )
            price = Money(
                Decimal(str(itinerary.price.amount)), itinerary.price.currency
            )
            offers.append(
                JourneyOffer(
                    f"flight:{itinerary.ignav_id}", path, price, "mock-ignav", True
                )
            )
            logger.info(
                "Created synthetic flight=%s price=%s %s",
                offers[-1].id,
                price.amount,
                price.currency,
            )
    return tuple(offers)
