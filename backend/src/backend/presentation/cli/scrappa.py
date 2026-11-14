"""Call Scrappa Omio endpoints with automatic DuckDB caching, or estimate offline."""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

import duckdb

from backend.infrastructure.logging import cli_entrypoint
from backend.infrastructure.scrappa.client import (
    DEFAULT_DATABASE,
    PATHS,
    ScrappaClient,
    ScrappaError,
)


@cli_entrypoint
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser(
        "request", help="Fetch or reuse a complete provider response"
    )
    request.add_argument("endpoint", choices=PATHS)
    request.add_argument(
        "--params", required=True, help="JSON object of documented query parameters"
    )
    policy = request.add_mutually_exclusive_group()
    policy.add_argument(
        "--refresh", action="store_true", help="Bypass cache; consumes API credits"
    )
    policy.add_argument(
        "--cache-only", action="store_true", help="Never make HTTP requests"
    )
    request.add_argument("--max-age-seconds", type=int)
    estimate = commands.add_parser(
        "estimate", help="Estimate from local history without spending credits"
    )
    estimate.add_argument("--origin-id", type=int, required=True)
    estimate.add_argument("--destination-id", type=int, required=True)
    estimate.add_argument("--date", required=True)
    estimate.add_argument("--mode", choices=["train", "bus", "flight"], required=True)
    estimate.add_argument("--currency", default="EUR")
    estimate.add_argument("--adults", type=int, default=1)
    estimate.add_argument("--children", type=int, default=0)
    estimate.add_argument("--infants", type=int, default=0)
    estimate.add_argument("--max-age-days", type=int, default=30)
    estimate.add_argument("--date-window-days", type=int, default=28)
    args = parser.parse_args()
    try:
        with ScrappaClient(
            args.database, api_key=os.environ.get("SCRAPPA_API_KEY")
        ) as client:
            if args.command == "request":
                response = client.request(
                    args.endpoint,
                    json.loads(args.params),
                    refresh=args.refresh,
                    cache_only=args.cache_only,
                    max_age_seconds=args.max_age_seconds,
                )
                output = asdict(response)
                output["fetched_at"] = response.fetched_at.isoformat()
            else:
                output = client.estimate(
                    args.origin_id,
                    args.destination_id,
                    args.date,
                    args.mode,
                    currency=args.currency,
                    adults=args.adults,
                    children=args.children,
                    infants=args.infants,
                    max_age_days=args.max_age_days,
                    date_window_days=args.date_window_days,
                )
        print(json.dumps(output, indent=2))
    except (ScrappaError, ValueError, TypeError) as exc:
        parser.exit(2, f"scrappa: {exc}\n")
    except (OSError, duckdb.Error):
        parser.exit(
            1,
            "scrappa: Cannot read or write the cache database; check its path, permissions and whether another process holds it.\n",
        )


if __name__ == "__main__":
    main()
