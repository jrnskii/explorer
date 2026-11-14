"""Rank local candidates across three calendar days before spending provider credits."""

from dataclasses import replace
from datetime import timedelta
import logging
from zoneinfo import ZoneInfo

from backend.application.round_trip_search import verify_selected_route
from backend.application.search_diagnostics import (
    candidate_selected,
    candidate_failed,
    candidate_verified,
)
from backend.application.telemetry import event
from backend.domain.planning import instant
from backend.domain.cities import City
from backend.domain.pricing import ExactPricingUnavailable
from backend.infrastructure.graphql.round_trip import serialize_options
from backend.infrastructure.schedules.store import (
    SearchCoverageError,
    SearchInputError,
    SearchResponse,
)


class FlexibleSearch:
    def __init__(self, schedules, reference_factory, pricer_factory):
        self.schedules = schedules
        self.reference_factory = reference_factory
        self.pricer_factory = pricer_factory

    def ready(self):
        return self.schedules.ready()

    def __call__(self, settings):
        zone = (
            ZoneInfo(settings.departure_timezone)
            if settings.departure_timezone
            else settings.departure_date.tzinfo
        )
        departure = settings.departure_date.astimezone(zone)
        arrival = settings.desired_arrival_date.astimezone(zone)
        candidates = []
        reference = None
        limited = False
        failures = []
        for offset in (-1, 0, 1):
            start = departure + timedelta(days=offset)
            end = arrival + timedelta(days=offset)
            if instant(start) < self.schedules.clock():
                continue
            window = replace(
                settings,
                departure_date=start,
                desired_arrival_date=end,
                latest_departure_date=start
                + timedelta(days=1)
                - timedelta(microseconds=1),
                max_trip_duration=(
                    settings.max_trip_duration
                    + int(
                        (
                            (instant(end) - instant(start))
                            - (instant(arrival) - instant(departure))
                        ).total_seconds()
                    )
                    if settings.max_trip_duration
                    else None
                ),
                min_cities=2,
                fuzzy_search=False,
            )
            try:
                result, markers, catalog = self.schedules(window, rank_only=True)
                limited |= result.results_limited
                planned = result.options
                source = "GTFS"
                if not planned:
                    raise SearchCoverageError("No dated candidates")
            except SearchCoverageError:
                try:
                    if reference is None:
                        reference = self.reference_factory()
                    planned, truncated = reference.plan(window, max_results=10)
                    limited |= truncated
                    catalog = reference.cities
                    markers = {
                        key: City(key, c["name"], c["latitude"], c["longitude"])
                        for key, c in catalog.items()
                    }
                    source = "reference"
                except SearchCoverageError as exc:
                    failures.append(str(exc))
                    continue
            for route in planned:
                candidates.append((route, window, markers, catalog, source))
        if not candidates:
            if failures:
                raise SearchCoverageError(failures[0])
            raise SearchInputError("Choose a future departure date.")
        candidates.sort(key=lambda item: item[0].total_price.amount)
        # Keep parallel timetables in the solver, but show distinct city/mode/day
        # opportunities rather than ten copies of the same trip.
        unique = {}
        for item in candidates:
            key = tuple(
                (
                    leg.origin,
                    leg.destination,
                    leg.transport_type,
                    leg.departure_at.astimezone(zone).date(),
                )
                for leg in item[0].path
            )
            unique.setdefault(key, item)
        candidates = list(unique.values())
        event(
            logging.getLogger(__name__),
            "search.flexible_ranked",
            level=logging.INFO,
            candidate_count=len(candidates),
            departure_days=3,
            results_limited=limited,
        )
        attempts = 0
        checked = None
        fees_complete = False
        from_cache = False
        # One instance shares the request/time allowance and cache across attempts.
        catalog = {key: value for item in candidates for key, value in item[3].items()}
        pricer = self.pricer_factory(catalog)
        for index, (route, window, markers, _, source) in enumerate(candidates[:2]):
            attempts += 1
            candidate_selected(route, window, attempts, source, track_budget=False)
            try:
                quote = pricer.quote(route, window)
                verified = verify_selected_route(route, quote, window, 1800)
            except ExactPricingUnavailable as error:
                candidate_failed(attempts, error)
                continue
            candidate_verified(route, verified, window, attempts, track_budget=False)
            candidates[index] = (verified, window, markers, catalog, source)
            checked = verified
            fees_complete = quote.fees_complete
            from_cache = quote.from_cache
            break
        # Keep the successfully checked opportunity visible even after fare uplift.
        candidates.sort(key=lambda item: (item[0] is not checked, item[0].total_price.amount))
        candidates = candidates[:7]
        options, estimates, pricing = [], [], []
        for rank, (route, window, markers, _, source) in enumerate(candidates, 1):
            if route is checked:
                options.extend(serialize_options((route,), markers))
                pricing.append({"price_status": "provider_advertised", "rank": rank})
            else:
                # Reference placeholders are date requests, NEVER real timetables.
                ids = [route.path[0].origin, *(leg.destination for leg in route.path)]
                estimates.append(
                    {
                        "rank": rank,
                        "cities": [
                            {"id": key, "name": markers[key].name} for key in ids
                        ],
                        "departure_date": route.path[0]
                        .departure_at.astimezone(zone)
                        .date()
                        .isoformat(),
                        "return_date": route.path[-1]
                        .departure_at.astimezone(zone)
                        .date()
                        .isoformat(),
                        "total_price": {
                            "amount": str(route.total_price.amount),
                            "currency": route.total_price.currency,
                        },
                        "schedule_source": source,
                        "transport_types": [leg.transport_type.value for leg in route.path],
                    }
                )
        return SearchResponse(
            options,
            {
                "estimated_routes": estimates,
                "option_pricing": pricing,
                "price_scope": "adult",
                "synthetic_schedule": False,
                "price_status": "provider_priced" if checked else "unavailable",
                "provider_pricing_attempts": attempts,
                "provider_checked_opportunities": int(checked is not None),
                "fees_verified": fees_complete,
                "provider_results_cached": from_cache,
                "results_limited": limited,
            },
        )
