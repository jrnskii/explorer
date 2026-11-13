"""Run a small Vilnius round-trip demo; trace actions on stderr, JSON on stdout."""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging

from backend.application.round_trip_search import SearchLimits, find_round_trips
from backend.domain.planning import Money, SearchSettings
from backend.domain.travel import TransportType as Mode
from backend.infrastructure.fixtures.vilnius_demo import demo_offers
from backend.infrastructure.fixtures.cities import CITY_LOCATIONS
from backend.infrastructure.graphql.round_trip import serialize_options

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s"
    )
    try:
        logger.info(
            "Loading deterministic demo settings; all services and prices are synthetic"
        )
        settings = SearchSettings(
            "lt-vilnius",
            datetime(2026, 12, 1, tzinfo=timezone.utc),
            datetime(2026, 12, 3, 16, tzinfo=timezone.utc),
            0,
            Money(Decimal("200.00"), "USD"),
            (Mode.BUSSES, Mode.TRAINS, Mode.PLANES),
            mandatory_cities=("pl-krakow",),
        )
        logger.info(
            "Settings home=Vilnius (%s) mandatory=%s departure=%s target_return=%s budget=%s %s",
            settings.departure_city,
            settings.mandatory_cities,
            settings.departure_date.isoformat(),
            settings.desired_arrival_date.isoformat(),
            settings.expenses_tolerance.amount,
            settings.expenses_tolerance.currency,
        )
        offers = demo_offers(args.seed)
        logger.info(
            "Pinned snapshot of %s synthetic offers; invoking solver", len(offers)
        )
        result = find_round_trips(
            settings, offers, SearchLimits(max_legs=5, max_states=1000, max_results=5)
        )
        logger.info("Serializing %s ranked results to JSON stdout", len(result.options))
        print(
            json.dumps(
                {
                    "synthetic": True,
                    "departure_city": settings.departure_city,
                    "states_explored": result.states_explored,
                    "truncation_reasons": result.truncation_reasons,
                    "results_limited": result.results_limited,
                    "options": serialize_options(result.options, CITY_LOCATIONS),
                },
                indent=2,
            )
        )
        logger.info("Demo complete")
    except (ValueError, TypeError, OverflowError) as exc:
        parser.exit(2, f"round-trip-demo: {exc}\n")


if __name__ == "__main__":
    main()
