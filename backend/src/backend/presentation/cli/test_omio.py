"""Manually fetch and cache actual Omio departures from Vilnius (uses API credits)."""

import argparse
from datetime import date, datetime
import json
import math
import os
from pathlib import Path
import signal
from zoneinfo import ZoneInfo

import duckdb
from dotenv import load_dotenv

from backend.infrastructure.logging import cli_entrypoint
from backend.infrastructure.scrappa.client import DEFAULT_DATABASE, ScrappaClient, ScrappaError
from backend.infrastructure.scrappa.route_probe import MAJOR_DESTINATIONS, fetch_routes

ROOT = Path(__file__).resolve().parents[5]


@cli_entrypoint
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat,
                        help="Departure date YYYY-MM-DD; reuse the same date to resume")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--destination", nargs=2, action="append", metavar=("CITY", "COUNTRY"),
                        help="Override defaults; repeat e.g. --destination Warsaw PL")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--refresh", action="store_true",
                        help="Refetch successful cached pages too (spends credits)")
    args = parser.parse_args()
    days = (args.date - datetime.now(ZoneInfo("Europe/Vilnius")).date()).days
    if not 0 <= days <= 364:
        parser.error("--date must be today or within the next 364 days")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    destinations = MAJOR_DESTINATIONS if args.destination is None else tuple(
        (city.strip(), country.upper()) for city, country in args.destination
    )
    if any(not city or len(country) != 2 or not country.isalpha()
           for city, country in destinations):
        parser.error("--destination requires a city and two-letter country code")
    load_dotenv(args.env_file, override=False)

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        with ScrappaClient(args.database, api_key=os.environ.get("SCRAPPA_API_KEY"),
                           timeout=args.timeout) as client:
            report = fetch_routes(client, args.date.isoformat(), destinations, refresh=args.refresh)
        print(json.dumps({"database": str(args.database), **report}, indent=2))
        if any(r["status"] == "failed" for r in report["destinations"]):
            parser.exit(1, "Some destinations failed; cached responses retained. Rerun to resume.\n")
    except KeyboardInterrupt:
        parser.exit(130, "Interrupted; committed responses retained. Rerun with the same date to resume.\n")
    except (ScrappaError, ValueError) as exc:
        parser.exit(1, f"test-omio: {exc}\n")
    except (OSError, duckdb.Error):
        parser.exit(1, "test-omio: Cache unavailable; check disk space, permissions and other writers.\n")
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()
