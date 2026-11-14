"""Bounded offline ranking of reference routes, independent of provider transport."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
import heapq
import logging
from itertools import count

from backend.application.round_trip_search import sum_exact
from backend.application.telemetry import event
from backend.domain.planning import JourneyOffer, Money, RoundTrip, TripLeg, instant
from backend.domain.pricing import ForecastQuery
from backend.domain.travel import TransportType


class ReferenceCoverageError(ValueError):
    pass


@dataclass(frozen=True)
class ReferenceEdge:
    origin: str
    destination: str
    mode: TransportType
    minutes: float
    distance: float


def plan_reference_route(
    settings,
    routes,
    cities,
    forecaster,
    *,
    clock,
    max_states=100_000,
    max_legs=8,
    max_transitions=500_000,
    excluded_routes=(),
    max_results=1,
):
    now = clock()
    if instant(settings.departure_date) < now:
        raise ValueError("Departure must be in the future.")
    if settings.expenses_tolerance.currency != "EUR":
        raise ValueError("Reference price estimates require an EUR budget.")
    required = {
        settings.departure_city,
        *settings.mandatory_cities,
        *settings.excluded_cities,
    }
    if required - cities.keys():
        raise ValueError("Choose a city from autocomplete.")
    # Each candidate has a fixed leg count, hence fixed evenly spaced request
    # dates. Forecasts are evaluated on those dates before any provider access.
    # These dates are a planning policy, not claims of scheduled departures.
    start = settings.departure_date
    end = settings.return_window[1] - timedelta(seconds=1)
    if end <= instant(start):
        raise ValueError("The return window must follow departure.")
    candidates = []
    best = None
    states = 0
    transitions = 0
    limited = False
    forecast_cache = {}
    # Use the return timestamp's own offset, including a DST change, to keep
    # date-only provider requests on the user's selected calendar days.
    final_day = end.astimezone(settings.desired_arrival_date.tzinfo).date()
    day_span = (final_day - start.date()).days
    for length in range(
        max(2, settings.min_cities + 1, len(settings.mandatory_cities) + 1),
        max_legs + 1,
    ):
        days = [
            start + timedelta(days=day_span * i // (length - 1)) for i in range(length)
        ]
        sequence = count()
        queue = [
            (
                Decimal(0),
                next(sequence),
                settings.departure_city,
                (),
                frozenset({settings.departure_city}),
            )
        ]
        while queue:
            if states >= max_states or transitions >= max_transitions:
                limited = True
                break
            total, _, city, chosen, visited = heapq.heappop(queue)
            states += 1
            if (
                len(candidates) >= max_results
                and total >= candidates[-1].total_price.amount
            ):
                continue
            for edge in routes.get(city, ()):
                if transitions >= max_transitions:
                    limited = True
                    break
                transitions += 1
                last = len(chosen) == length - 1
                if (
                    edge.mode not in settings.transport_types
                    or edge.destination in settings.excluded_cities
                ):
                    continue
                if last != (edge.destination == settings.departure_city):
                    continue
                if not last and edge.destination in visited:
                    continue
                day = days[len(chosen)]
                cache_key = (edge, day.date())
                if cache_key not in forecast_cache:
                    a, b = cities[edge.origin], cities[edge.destination]
                    forecast_cache[cache_key] = forecaster.predict(
                        ForecastQuery(
                            edge.mode,
                            a["name"],
                            b["name"],
                            day.date(),
                            now.date(),
                            a["country"],
                            b["country"],
                            distance_km=edge.distance,
                        )
                    )
                forecast = forecast_cache[cache_key]
                if forecast is None:
                    continue
                # Internal placeholders carry requested dates into the existing
                # quote boundary. They never escape this service.
                leg = TripLeg(
                    edge.origin,
                    edge.destination,
                    day.replace(microsecond=0),
                    day.replace(microsecond=0)
                    + timedelta(seconds=max(1, round(edge.minutes * 60))),
                    edge.mode,
                )
                offer = JourneyOffer(
                    f"reference:{len(chosen)}:{edge.origin}:{edge.destination}:{edge.mode}",
                    (leg,),
                    forecast.price,
                    "reference-date-request",
                    True,
                )
                amount = sum_exact((total, forecast.price.amount))
                if (
                    len(candidates) >= max_results
                    and amount >= candidates[-1].total_price.amount
                ):
                    continue
                if last:
                    if (
                        set(settings.mandatory_cities) <= visited
                        and tuple(o.id for o in chosen + (offer,))
                        not in excluded_routes
                    ):
                        best = RoundTrip(chosen + (offer,), Money(amount, "EUR"))
                        candidates.append(best)
                        candidates.sort(key=lambda option: option.total_price.amount)
                        del candidates[max_results:]
                else:
                    heapq.heappush(
                        queue,
                        (
                            amount,
                            next(sequence),
                            edge.destination,
                            chosen + (offer,),
                            visited | {edge.destination},
                        ),
                    )
        if limited:
            break
    event(
        logging.getLogger(__name__),
        "search.reference_planned",
        level=logging.INFO,
        states=states,
        transitions=transitions,
        limited=limited,
        forecast_queries=len(forecast_cache),
        unsupported_forecasts=sum(value is None for value in forecast_cache.values()),
        excluded_routes=len(excluded_routes),
        candidate_found=best is not None,
    )
    if best is None:
        raise ReferenceCoverageError(
            "No route with supported local price estimates was found for these cities and transport modes. No provider requests were made."
        )
    return (candidates[0] if max_results == 1 else tuple(candidates)), limited
