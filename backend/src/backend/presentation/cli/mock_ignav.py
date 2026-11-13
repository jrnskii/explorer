"""Offline, seeded Ignav fixtures. No network requests or real booking links."""

import argparse
import json
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from backend.infrastructure.fixtures.ignav import MockIgnavGenerator


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "health",
            "airports",
            "search",
            "one-way",
            "round-trip",
            "cheapest-dates",
            "booking-links",
            "network",
        ),
    )
    parser.add_argument(
        "--request", type=Path, help="JSON request file; airports accepts q and limit"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--count", type=int, default=8, help="Candidates before filters (1–100)"
    )
    parser.add_argument(
        "--airports", type=int, default=100, help="Network airport count (default 100)"
    )
    parser.add_argument(
        "--routes-per-airport",
        type=int,
        default=4,
        help="Network outgoing routes per airport (default 4)",
    )
    parser.add_argument(
        "--flights-per-route",
        type=int,
        default=2,
        help="Network daily departures per route (default 2)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Network departure date window (default 7 days)",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=date(2026, 1, 1),
        help="Network start date, YYYY-MM-DD (default 2026-01-01)",
    )
    args = parser.parse_args()
    try:
        if args.operation == "network":
            from backend.infrastructure.fixtures.network import generate_network

            if args.request:
                raise ValueError("network uses CLI options, not --request")
            result = generate_network(
                seed=args.seed,
                airport_count=args.airports,
                routes_per_airport=args.routes_per_airport,
                flights_per_route=args.flights_per_route,
                start_date=args.start_date,
                days=args.days,
            )
        else:
            generator = MockIgnavGenerator(seed=args.seed, count=args.count)
            request = json.loads(args.request.read_text()) if args.request else {}
            if not isinstance(request, dict):
                raise ValueError("Request must be a JSON object")
            method = getattr(generator, args.operation.replace("-", "_"))
            if args.operation == "health":
                result = method()
            elif args.operation == "airports":
                result = method(**request)
            else:
                result = method(request)
        payload = (
            [item.model_dump(mode="json") for item in result]
            if isinstance(result, list)
            else result.model_dump(mode="json")
        )
        print(json.dumps(payload, indent=2))
    except (OSError, ValueError, TypeError, ValidationError) as exc:
        parser.exit(2, f"mock-ignav: {exc}\n")


if __name__ == "__main__":
    main()
