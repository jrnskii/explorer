"""Offline reference-route planning; only provider-verified timetables are returned.

Reference timestamps are internal date requests, never published schedules. The best
city/mode/date path is checked first, then the runner-up if verification fails.
"""

from datetime import datetime, timezone
import math

from backend.application.round_trip_search import verify_selected_route
from backend.application.search_diagnostics import (
    candidate_selected,
    candidate_failed,
    candidate_verified,
)
from backend.application.reference_planning import (
    ReferenceEdge,
    ReferenceCoverageError,
    plan_reference_route,
)
from backend.domain.cities import City
from backend.domain.pricing import ExactPricingUnavailable
from backend.domain.travel import TransportType
from backend.infrastructure.catalog.static_transport import coordinates, distance_km
from backend.infrastructure.graphql.round_trip import serialize_options
from backend.infrastructure.pricing.forecast import name, code
from backend.infrastructure.schedules.store import (
    SearchCoverageError,
    SearchInputError,
    SearchResponse,
)


def project_routes(graph, cities):
    """Map reference identities to unique canonical cities without inventing edges."""
    identities = {}
    for identity, city in cities.items():
        identities.setdefault((name(city["name"]), code(city["country"])), []).append(
            identity
        )
    mapped = {}
    for node, attrs in graph.nodes(data=True):
        matches = identities.get(
            (name(attrs.get("name")), code(attrs.get("country"))), []
        )
        point = coordinates(attrs.get("latitude"), attrs.get("longitude"))
        if len(matches) == 1 and point and distance_km(point, cities[matches[0]]) <= 10:
            mapped[node] = matches[0]
    edges = {}
    for a, b, attrs in graph.edges(data=True):
        origin, destination = mapped.get(a), mapped.get(b)
        mode = attrs.get("mode")
        minutes, distance = attrs.get("travel_time_minutes"), attrs.get("distance_km")
        if (
            not origin
            or not destination
            or origin == destination
            or mode not in ("PLANES", "TRAINS", "BUSSES")
        ):
            continue
        if any(
            type(v) not in (int, float) or not math.isfinite(v) or v <= 0
            for v in (minutes, distance)
        ):
            continue
        edge = ReferenceEdge(
            origin, destination, TransportType(mode), minutes, distance
        )
        key = (origin, destination, mode)
        if key not in edges or minutes < edges[key].minutes:
            edges[key] = edge
    adjacency = {}
    for key in sorted(edges):
        edge = edges[key]
        adjacency.setdefault(edge.origin, []).append(edge)
    return adjacency


class ReferenceSearch:
    def __init__(
        self,
        routes,
        cities,
        forecaster,
        pricer_factory,
        *,
        clock=lambda: datetime.now(timezone.utc),
        max_states=100_000,
        max_legs=8,
    ):
        self.routes, self.cities, self.forecaster = routes, cities, forecaster
        self.pricer_factory, self.clock = pricer_factory, clock
        self.max_states, self.max_legs = max_states, max_legs

    def plan(self, settings, *, excluded_routes=(), max_results=1):
        try:
            return plan_reference_route(
                settings,
                self.routes,
                self.cities,
                self.forecaster,
                clock=self.clock,
                max_states=self.max_states,
                max_legs=self.max_legs,
                excluded_routes=excluded_routes,
                max_results=max_results,
            )
        except ReferenceCoverageError as exc:
            raise SearchCoverageError(str(exc)) from exc
        except ValueError as exc:
            raise SearchInputError(str(exc)) from exc

    def __call__(self, settings):
        planned, limited = self.plan(settings)
        pricer = self.pricer_factory(self.cities)
        attempts = 1
        candidate_selected(planned, settings, attempts, "reference")
        try:
            quote = pricer.quote(planned, settings)
            verified = verify_selected_route(planned, quote, settings, 1800)
        except ExactPricingUnavailable as error:
            candidate_failed(attempts, error)
            try:
                planned, second_limited = self.plan(
                    settings, excluded_routes=(tuple(o.id for o in planned.offers),)
                )
                limited = limited or second_limited
            except SearchCoverageError as exc:
                raise SearchInputError(
                    "The best estimated route could not be verified and no second route has local price coverage. Try different dates or transport modes."
                ) from exc
            attempts += 1
            candidate_selected(planned, settings, attempts, "reference")
            try:
                quote = pricer.quote(planned, settings)
                verified = verify_selected_route(planned, quote, settings, 1800)
            except ExactPricingUnavailable as exc:
                candidate_failed(attempts, exc)
                raise SearchInputError(
                    "Neither of the two best estimated routes could be verified for the selected dates. Try different dates or transport modes."
                ) from exc
        candidate_verified(planned, verified, settings, attempts)
        over_budget = verified.total_price.amount > settings.expenses_tolerance.amount
        markers = {
            identity: City(identity, c["name"], c["latitude"], c["longitude"])
            for identity, c in self.cities.items()
        }
        options = serialize_options((verified,), markers)
        return SearchResponse(
            options,
            {
                "synthetic_schedule": False,
                "schedule_source": "provider",
                "pricing": "forecast_then_provider",
                "price_scope": "adult",
                "price_status": "over_budget" if over_budget else "provider_priced",
                "fees_verified": quote.fees_complete,
                "provider_checked_opportunities": 1,
                "provider_pricing_attempts": attempts,
                "results_limited": limited,
                "truncation_reasons": ["reference_planning_limit"] if limited else [],
                "option_pricing": (
                    [
                        {
                            "price_status": "provider_advertised",
                            "over_budget": over_budget,
                            "approximate_price": str(planned.total_price.amount),
                        }
                    ]
                ),
            },
        )
