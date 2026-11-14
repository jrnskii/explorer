"""Batch forecast boundary for local application servers; JSON stdin/stdout only."""

import argparse
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import sys

from backend.application.telemetry import traced
from backend.infrastructure.logging import cli_entrypoint
from backend.domain.pricing import ForecastQuery
from backend.domain.travel import TransportType
from backend.infrastructure.pricing.forecast import DEFAULT_ARTIFACT, load_forecaster


@traced
def forecast_batch(payload, forecaster, as_of=None):
    if not isinstance(payload, dict) or set(payload) != {"queries"}:
        raise ValueError("Expected an object containing queries only")
    queries = payload["queries"]
    if not isinstance(queries, list) or not 1 <= len(queries) <= 64:
        raise ValueError("Supply between 1 and 64 forecast queries")
    results = []
    allowed = {
        "mode",
        "origin",
        "destination",
        "departure_date",
        "origin_country",
        "destination_country",
        "travelers",
        "feed_id",
        "route_id",
        "distance_km",
    }
    for row in queries:
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError("Invalid forecast query fields")
        query = ForecastQuery(
            TransportType(row["mode"]),
            row["origin"],
            row["destination"],
            date.fromisoformat(row["departure_date"]),
            as_of or date.today(),
            row.get("origin_country"),
            row.get("destination_country"),
            row.get("travelers", 1),
            row.get("feed_id"),
            row.get("route_id"),
            row.get("distance_km"),
        )
        prediction = forecaster.predict(query)
        results.append(asdict(prediction) if prediction else None)
    return dict(
        forecasts=results,
        price_status="estimated",
        information_date=forecaster.information_date.isoformat(),
    )


@cli_entrypoint
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValueError("Forecast batch exceeds input limit")
        result = forecast_batch(json.loads(raw), load_forecaster(args.models))
        print(json.dumps(result, default=str))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Forecast request failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
