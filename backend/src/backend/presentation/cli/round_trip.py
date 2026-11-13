"""Search synthetic multimodal round trips using schema_v1 JSON settings."""

import argparse
import json
from pathlib import Path

from backend.application.round_trip_search import SearchLimits, find_round_trips
from backend.domain.planning import Money, SearchSettings
from backend.domain.travel import TransportType
from backend.infrastructure.fixtures.round_trip import (
    CITY_AIRPORTS,
    MockRoundTripProvider,
)
from backend.infrastructure.graphql.models import RoundTripSearchInput
from backend.infrastructure.graphql.round_trip import serialize_options
from backend.infrastructure.fixtures.cities import CITY_LOCATIONS


def parse_settings(payload: str) -> SearchSettings:
    wire = RoundTripSearchInput.model_validate_json(
        payload, strict=True, extra="forbid"
    )
    raw = json.loads(payload)
    if not isinstance(raw["expenses_tolerance"]["amount"], str):
        raise ValueError("Decimal amounts must be encoded as JSON strings")
    return SearchSettings(
        departure_city=wire.departure_city,
        departure_date=wire.departure_date,
        desired_arrival_date=wire.desired_arrival_date,
        time_tolerance=wire.time_tolerance,
        expenses_tolerance=Money(
            wire.expenses_tolerance.amount, wire.expenses_tolerance.currency
        ),
        transport_types=tuple(
            TransportType(mode.value) for mode in wire.transport_types
        ),
        mandatory_cities=tuple(wire.mandatory_cities),
        excluded_cities=tuple(wire.excluded_cities),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--max-states", type=int, default=100_000)
    parser.add_argument("--max-legs", type=int, default=8)
    parser.add_argument("--max-results", type=int, default=20)
    args = parser.parse_args()
    try:
        settings = parse_settings(args.request.read_text())
        limits = SearchLimits(args.max_legs, args.max_states, args.max_results)
        offers = MockRoundTripProvider(seed=args.seed, count=args.count).offers(
            settings
        )
        result = find_round_trips(settings, offers, limits)
        options = serialize_options(result.options, CITY_LOCATIONS)
        print(
            json.dumps(
                {
                    "synthetic": True,
                    "price_status": "unverified",
                    "scope": "offline-demo",
                    "cities": CITY_AIRPORTS,
                    "states_explored": result.states_explored,
                    "truncation_reasons": result.truncation_reasons,
                    "results_limited": result.results_limited,
                    "options": options,
                },
                indent=2,
            )
        )
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        parser.exit(2, f"round-trip: {exc}\n")


if __name__ == "__main__":
    main()
