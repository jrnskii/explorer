"""Search demonstration schedules using forecast prices by default."""

import argparse
import json
from pathlib import Path
from datetime import date
from dataclasses import asdict, replace
from contextlib import ExitStack
import os

from backend.infrastructure.logging import cli_entrypoint
from backend.application.round_trip_search import SearchLimits, find_round_trips
from backend.domain.planning import Money
from backend.infrastructure.fixtures.round_trip import (
    CITY_AIRPORTS,
    MockRoundTripProvider,
)
from backend.infrastructure.graphql.inputs import parse_settings
from backend.infrastructure.graphql.round_trip import serialize_options
from backend.infrastructure.fixtures.cities import CITY_LOCATIONS
from backend.infrastructure.pricing.forecast import DEFAULT_ARTIFACT, load_forecaster
from backend.infrastructure.pricing.overlay import ForecastOfferEstimator
from backend.infrastructure.scrappa.client import ScrappaClient, DEFAULT_DATABASE
from backend.infrastructure.scrappa.exact_pricing import ScrappaRoundTripPricer

FORECAST_CITIES = {
    "pl-warsaw": dict(name="Warsaw", country="PL"),
    "pl-krakow": dict(name="Krakow", country="PL"),
    "fr-paris": dict(name="Paris", country="FR"),
    "gb-london": dict(name="London", country="GB"),
    "nl-amsterdam": dict(name="Amsterdam", country="NL"),
}


@cli_entrypoint
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--max-states", type=int, default=100_000)
    parser.add_argument("--max-legs", type=int, default=8)
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--pricing", choices=("forecast", "mock"), default="forecast")
    parser.add_argument("--models", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--exact-best",
        action="store_true",
        help="Check the cheapest forecast route, then the runner-up if verification fails",
    )
    parser.add_argument(
        "--scrappa-places",
        type=Path,
        help="Reviewed JSON mapping of application city IDs to Omio position IDs",
    )
    parser.add_argument("--scrappa-cache", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()
    try:
        settings = parse_settings(args.request.read_text())
        limits = SearchLimits(args.max_legs, args.max_states, args.max_results)
        schedule = MockRoundTripProvider(seed=args.seed, count=args.count)
        forecast_provider = None
        if args.exact_best and args.pricing != "forecast":
            raise ValueError("--exact-best requires forecast pricing")
        if args.pricing == "forecast":
            if settings.expenses_tolerance.currency != "EUR":
                raise ValueError("Forecast prices require an EUR budget")
            forecast_provider = ForecastOfferEstimator(
                load_forecaster(args.models),
                FORECAST_CITIES,
                args.as_of or date.today(),
            )
            offers = schedule.offers(
                replace(
                    settings,
                    expenses_tolerance=Money(settings.expenses_tolerance.amount, "USD"),
                )
            )
        else:
            offers = schedule.offers(settings)
        with ExitStack() as resources:
            exact_pricer = None
            if args.exact_best:
                if args.scrappa_places is None:
                    raise ValueError(
                        "--exact-best requires --scrappa-places with reviewed Omio position IDs"
                    )
                places = json.loads(args.scrappa_places.read_text())
                if not isinstance(places, dict):
                    raise ValueError("Scrappa places must be a JSON object")
                client = resources.enter_context(
                    ScrappaClient(
                        args.scrappa_cache, api_key=os.environ.get("SCRAPPA_API_KEY")
                    )
                )
                exact_pricer = ScrappaRoundTripPricer(
                    client, places, cities=FORECAST_CITIES, cache_only=args.cache_only
                )
            result = find_round_trips(
                settings,
                offers,
                limits,
                price_forecaster=forecast_provider,
                exact_pricer=exact_pricer,
            )
        options = serialize_options(result.options, CITY_LOCATIONS)
        print(
            json.dumps(
                {
                    "synthetic": True,
                    "price_status": (
                        result.pricing.status if result.pricing else "unverified"
                    ),
                    "pricing": args.pricing,
                    "synthetic_schedule": True,
                    "forecast_evidence": (
                        {k: asdict(v) for k, v in forecast_provider.evidence.items()}
                        if forecast_provider
                        else {}
                    ),
                    "unpriced_offers": (
                        forecast_provider.skipped if forecast_provider else ()
                    ),
                    "price_reconciliation": (
                        asdict(result.pricing) if result.pricing else None
                    ),
                    "option_pricing": [
                        dict(
                            price_status=o.price_status,
                            approximate_price=(
                                asdict(o.approximate_price)
                                if o.approximate_price
                                else None
                            ),
                            ranking_adjustment=(
                                asdict(o.ranking_adjustment)
                                if o.ranking_adjustment
                                else None
                            ),
                        )
                        for o in result.options
                    ],
                    "scope": (
                        "provider-checked-demo" if args.exact_best else "offline-demo"
                    ),
                    "cities": CITY_AIRPORTS,
                    "states_explored": result.states_explored,
                    "truncation_reasons": result.truncation_reasons,
                    "results_limited": result.results_limited,
                    "options": options,
                },
                indent=2,
                default=str,
            )
        )
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        parser.exit(2, f"round-trip: {exc}\n")


if __name__ == "__main__":
    main()
