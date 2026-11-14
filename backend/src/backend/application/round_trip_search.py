"""Bounded traversal of a finite schedule snapshot with optional fuzzy stay ranking.

No provider calls or shared weight mutations occur during exploration. Price-first
searches find the cheapest supplied offers only when exploration is not truncated.
"""

from collections import defaultdict
import heapq
from itertools import count
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from typing import Iterable
import logging

from backend.application.telemetry import event, traced
from backend.application.search_diagnostics import candidate_selected, candidate_failed, candidate_verified
from backend.application.ports import (
    JourneyOfferIndex,
    OfferLimitReached,
    OfferPriceForecaster,
    RoundTripExactPricer,
)
from backend.domain.pricing import (
    ExactPricingUnavailable,
    CandidateEstimate,
    PriceReconciliation,
    RoundTripQuote,
)

from backend.domain.planning import (
    CityStay,
    JourneyOffer,
    Money,
    RoundTrip,
    SearchSettings,
    instant,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchLimits:
    max_legs: int = 8
    max_states: int = 100_000
    max_results: int = 20

    def __post_init__(self):
        if any(
            type(value) is not int or value < 1
            for value in (self.max_legs, self.max_states, self.max_results)
        ):
            raise ValueError("search limits must be positive integers")


@dataclass(frozen=True)
class SearchResult:
    options: tuple[RoundTrip, ...]
    states_explored: int
    truncation_reasons: tuple[str, ...]
    results_limited: bool
    pricing: PriceReconciliation | None = None


@traced
def find_round_trips(
    settings: SearchSettings,
    offers: Iterable[JourneyOffer],
    limits: SearchLimits = SearchLimits(),
    *,
    allow_city_revisits: bool = False,
    min_connection_seconds: int = 0,
    offer_index: JourneyOfferIndex | None = None,
    max_transitions: int | None = None,
    price_forecaster: OfferPriceForecaster | None = None,
    exact_pricer: RoundTripExactPricer | None = None,
) -> SearchResult:
    """Skip repeated cities per itinerary, except the final return home.

    Internal ticket connections count as visits. Set allow_city_revisits=True
    explicitly to explore schedules that pass through a city more than once.

    Forecast whole purchases before traversal. With exact_pricer, retain candidates
    by estimated price and verify the cheapest retained route after traversal.
    If verification fails, try the second-ranked candidate once; ranking adjustments
    remain separate from genuine fares and original forecasts.
    """
    if max_transitions is not None and (
        type(max_transitions) is not int or max_transitions < 1
    ):
        raise ValueError("max_transitions must be a positive integer")
    if type(min_connection_seconds) is not int or min_connection_seconds < 0:
        raise ValueError("min_connection_seconds must be a non-negative integer")
    if type(allow_city_revisits) is not bool:
        raise ValueError("allow_city_revisits must be a boolean")
    logger.info(
        "Starting search home=%s mandatory=%s budget=%s %s",
        settings.departure_city,
        settings.mandatory_cities,
        settings.expenses_tolerance.amount,
        settings.expenses_tolerance.currency,
    )
    staged = exact_pricer is not None
    rank = (
        (lambda option: (option.total_price.amount, *_rank(option)))
        if staged
        else _rank
    )
    unpriced = []
    adjacency = defaultdict(list)
    identities = {}
    excluded = set(settings.excluded_cities)
    home = settings.departure_city
    earliest, latest = settings.return_window

    def index_offers(supplied):
        for offer in supplied:
            logger.debug(
                "Inspect offer=%s route=%s price=%s %s",
                offer.id,
                " -> ".join(
                    (offer.path[0].origin, *(leg.destination for leg in offer.path))
                ),
                offer.price.amount,
                offer.price.currency,
            )
            if offer.id in identities:
                if identities[offer.id] != offer:
                    raise ValueError(f"conflicting offer identity: {offer.id}")
                logger.debug("Skip duplicate offer=%s", offer.id)
                continue
            identities[offer.id] = offer
            if any(
                leg.transport_type not in settings.transport_types
                or {leg.origin, leg.destination} & excluded
                for leg in offer.path
            ):
                logger.debug(
                    "Reject offer=%s: excluded city or disallowed mode", offer.id
                )
                continue
            # Home inside a purchase would violate the first-return termination rule.
            if any(leg.destination == home for leg in offer.path[:-1]):
                logger.debug("Reject offer=%s: returns home inside ticket", offer.id)
                continue
            if (
                instant(offer.path[0].departure_at) < instant(settings.departure_date)
                or (offer.path[0].origin == home and settings.latest_departure_date is not None
                    and instant(offer.path[0].departure_at) > instant(settings.latest_departure_date))
                or instant(offer.path[-1].arrival_at) > latest
            ):
                logger.debug(
                    "Reject offer=%s: outside departure/return horizon", offer.id
                )
                continue
            if price_forecaster is not None:
                forecast = price_forecaster.estimate_offer(offer)
                if forecast is None:
                    unpriced.append(offer.id)
                    continue
                offer = replace(
                    offer, price=forecast.price, source="forecast:" + forecast.model_id
                )
            if offer.price.currency != settings.expenses_tolerance.currency:
                raise ValueError(
                    "offer currency differs from budget; currency conversion is unsupported"
                )
            adjacency[offer.path[0].origin].append(offer)
            logger.debug("Index offer=%s", offer.id)

    loaded_cities = set()

    def outgoing_for(city):
        if offer_index is not None and city not in loaded_cities:
            index_offers(offer_index.outgoing(city))
            loaded_cities.add(city)
            adjacency[city].sort(
                key=lambda offer: (
                    offer.price.amount,
                    instant(offer.path[0].departure_at),
                    offer.id,
                )
            )
        return adjacency[city]

    if offer_index is None:
        index_offers(offers)
        for outgoing in adjacency.values():
            outgoing.sort(
                key=lambda offer: (
                    offer.price.amount,
                    instant(offer.path[0].departure_at),
                    offer.id,
                )
            )
        reverse = defaultdict(set)
        for city, outgoing in adjacency.items():
            for offer in outgoing:
                reverse[offer.path[-1].destination].add(city)
    else:
        reverse = defaultdict(set, offer_index.reverse_connections())
    reachable, pending = {home}, [home]
    while pending:
        for city in reverse[pending.pop()]:
            if city not in reachable:
                reachable.add(city)
                pending.append(city)
    logger.debug("Cities with a directed route home: %s", sorted(reachable))
    best_first = offer_index is not None and not settings.fuzzy_search
    sequence = count()
    stack = []

    candidates = []
    results_limited = False

    def push(state):
        nonlocal results_limited
        city, ready, chosen, total, visited, _legs = state
        # Completed routes need no more exploration. Retain them before a work
        # limit can stop traversal with cheaper unfinished routes still queued.
        if chosen and city == home:
            if (
                len(visited - {home}) >= settings.min_cities
                and set(settings.mandatory_cities) <= visited
                and earliest <= ready <= latest
            ):
                candidate = RoundTrip(
                    chosen,
                    Money(total, settings.expenses_tolerance.currency),
                    price_status=(
                        "estimated"
                        if (price_forecaster is not None or staged)
                        else "supplied"
                    ),
                )
                stays, fit = city_stays(candidate, settings)
                candidates.append(
                    RoundTrip(
                        candidate.offers,
                        candidate.total_price,
                        stays,
                        fit if settings.fuzzy_search else None,
                        price_status=candidate.price_status,
                    )
                )
                logger.info(
                    "Found round trip price=%s tickets=%s",
                    total,
                    tuple(offer.id for offer in chosen),
                )
                # Bound retained results without stopping exploration.
                candidates.sort(key=rank)
                if len(candidates) > limits.max_results:
                    dropped = candidates.pop()
                    logger.debug(
                        "Discard ranked result beyond max_results: %s",
                        tuple(offer.id for offer in dropped.offers),
                    )
                    results_limited = True
            else:
                logger.debug(
                    "Reject return: required visits or return window not satisfied"
                )
            return
        if best_first:
            heapq.heappush(
                stack,
                (
                    state[3],
                    sum(leg.time_in_travel for offer in state[2] for leg in offer.path),
                    next(sequence),
                    state,
                ),
            )
        else:
            stack.append(state)

    push((home, instant(settings.departure_date), (), Decimal(0), frozenset(), 0))
    reasons = set()
    states = 0
    transitions = 0
    while stack:
        if max_transitions is not None and transitions >= max_transitions:
            reasons.add("max_transitions")
            break
        if best_first and len(candidates) >= limits.max_results:
            worst = candidates[-1]
            bound = (
                worst.total_price.amount,
                sum(leg.time_in_travel for leg in worst.path),
            )
            if stack[0][:2] > bound:
                results_limited = True
                break  # All remaining partial paths have a worse lower bound.
        if states >= limits.max_states:
            logger.info("Stop exploration: max_states=%s", limits.max_states)
            reasons.add("max_states")
            break
        state = heapq.heappop(stack)[3] if best_first else stack.pop()
        city, ready, chosen, total, visited, legs = state
        states += 1
        logger.debug(
            "Explore state=%s city=%s ready=%s total=%s legs=%s tickets=%s",
            states,
            city,
            ready.isoformat(),
            total,
            legs,
            tuple(offer.id for offer in chosen),
        )
        try:
            outgoing = outgoing_for(city)
        except OfferLimitReached:
            reasons.add("max_offers")
            break
        for offer in reversed(outgoing):
            if max_transitions is not None and transitions >= max_transitions:
                break
            transitions += 1
            logger.debug("Consider next ticket=%s from=%s", offer.id, city)
            destination = offer.path[-1].destination
            # Track physical arrivals, including connections within one purchase.
            # The current origin is already visited; leaving it is not a revisit.
            next_visited = set(visited) | {city}
            repeated_city = False
            for index, leg in enumerate(offer.path):
                final_return = leg.destination == home and index == len(offer.path) - 1
                if leg.destination in next_visited and not final_return:
                    repeated_city = True
                    break
                next_visited.add(leg.destination)
            if repeated_city and not allow_city_revisits:
                logger.debug("Skip ticket=%s: city already visited", offer.id)
                continue
            if destination not in reachable or (
                instant(offer.path[0].departure_at) - ready
            ).total_seconds() < (min_connection_seconds if chosen else 0):
                logger.debug(
                    "Skip ticket=%s: missed departure or no directed route home",
                    offer.id,
                )
                continue
            amount = _add_exact(total, offer.price.amount)
            if legs + len(offer.path) > limits.max_legs:
                logger.debug("Skip ticket=%s: max_legs=%s", offer.id, limits.max_legs)
                reasons.add("max_legs")
                continue
            logger.debug(
                "Expand ticket=%s destination=%s arrival=%s total=%s",
                offer.id,
                destination,
                offer.path[-1].arrival_at.isoformat(),
                amount,
            )
            push(
                (
                    destination,
                    instant(offer.path[-1].arrival_at),
                    chosen + (offer,),
                    amount,
                    visited | {leg.destination for leg in offer.path},
                    legs + len(offer.path),
                )
            )
    logger.info(
        "Search finished states=%s results=%s truncation=%s results_limited=%s",
        states,
        len(candidates),
        sorted(reasons),
        results_limited,
    )
    result = SearchResult(
        tuple(candidates), states, tuple(sorted(reasons)), results_limited
    )
    if exact_pricer is not None:
        return _reconcile_ranked(
            result, settings, exact_pricer, tuple(unpriced), min_connection_seconds
        )
    if price_forecaster is not None:
        return replace(
            result,
            pricing=PriceReconciliation(
                "estimated", unpriced_offer_ids=tuple(unpriced)
            ),
        )
    return result


@traced
def _reconcile_ranked(result, settings, pricer, unpriced, min_connection_seconds=0):
    event(logger, "pricing.reconciliation", candidates=len(result.options),
          unpriced_count=len(unpriced))
    if not result.options:
        return replace(
            result,
            pricing=PriceReconciliation("no_candidates", unpriced_offer_ids=unpriced),
        )
    ranked = sorted(result.options, key=lambda o: (o.total_price.amount, *_rank(o)))
    checked = ()
    attempts = 0
    failure = None
    failed = []
    zero = Money(Decimal(0), settings.expenses_tolerance.currency)

    def record(original, returned, status, adjustment=zero):
        return CandidateEstimate(
            tuple(o.id for o in original.offers),
            original.total_price,
            returned,
            adjustment,
            status,
        )

    for chosen in ranked[:2]:
        attempts += 1
        candidate_selected(chosen, settings, attempts, "schedule")
        checked += tuple(o.id for o in chosen.offers)
        try:
            quote = pricer.quote(chosen, settings)
            verified = verify_selected_route(chosen, quote, settings, min_connection_seconds)
            candidate_verified(chosen, verified, settings, attempts)
            break
        except ExactPricingUnavailable as error:
            candidate_failed(attempts, error)
            failure = error
            failed.append(chosen)
            event(logger, "pricing.verification_unavailable", level=logging.WARNING,
                  error_type=type(error).__name__)
    else:
        estimated = result.options
        return replace(
            result,
            options=estimated,
            pricing=PriceReconciliation(
                "unavailable",
                tuple(record(o, o.total_price, "estimated") for o in result.options),
                checked,
                unpriced_offer_ids=unpriced,
                error=str(failure),
                provider_pricing_attempts=attempts,
            ),
        )
    others = [o for o in result.options if o is not chosen and o not in failed]
    # A single observed underestimation calibrates remaining totals. The raw
    # forecast, ticket prices and source graph are preserved, never training labels.
    uplift = zero
    if others and verified.total_price.amount > min(
        o.total_price.amount for o in others
    ):
        uplift = Money(
            _add_exact(
                verified.total_price.amount, chosen.total_price.amount.copy_negate()
            ),
            zero.currency,
        )
    adjusted = [
        replace(
            o,
            total_price=Money(
                _add_exact(o.total_price.amount, uplift.amount), zero.currency
            ),
            approximate_price=o.total_price,
            ranking_adjustment=uplift,
            price_status="adjusted_estimate" if uplift.amount else "estimated",
        )
        for o in others
    ]
    options = [verified, *adjusted]
    options.sort(
        key=lambda o: (
            o.total_price.amount,
            o.price_status != "provider_advertised",
            *_rank(o),
        )
    )
    rows = [record(chosen, verified.total_price, "provider_advertised")]
    rows += [
        record(original, updated.total_price, updated.price_status, uplift)
        for original, updated in zip(others, adjusted, strict=True)
    ]
    status = (
        "provider_priced"
        if verified.total_price.amount <= settings.expenses_tolerance.amount
        else "over_budget"
    )
    event(logger, "pricing.reconciled", level=logging.INFO, status=status,
          candidate_count=len(options), fees_complete=quote.fees_complete)
    response_ids = tuple(
        dict.fromkeys(r for purchase in quote.purchases for r in purchase.response_ids)
    )
    return replace(
        result,
        options=tuple(options),
        pricing=PriceReconciliation(
            status,
            tuple(rows),
            checked,
            response_ids,
            uplift,
            unpriced,
            fees_complete=quote.fees_complete,
            provider_pricing_attempts=attempts,
        ),
    )


def verify_selected_route(original, quote, settings, min_connection_seconds=0):
    if (
        not isinstance(quote, RoundTripQuote)
        or quote.price_scope != "provider_advertised"
    ):
        raise ExactPricingUnavailable(
            "Provider did not return a supported whole-purchase quote"
        )
    purchases = {p.original_offer_id: p for p in quote.purchases}
    if len(purchases) != len(quote.purchases) or set(purchases) != {
        o.id for o in original.offers
    }:
        raise ExactPricingUnavailable(
            "Provider quote does not cover the selected purchases exactly once"
        )
    offers = []
    for previous in original.offers:
        purchase = purchases[previous.id]
        current = purchase.offer
        if (
            current.price.currency != settings.expenses_tolerance.currency
            or current.synthetic
            or [(l.origin, l.destination, l.transport_type) for l in current.path]
            != [(l.origin, l.destination, l.transport_type) for l in previous.path]
        ):
            raise ExactPricingUnavailable(
                "Provider changed the selected route, modes or price currency"
            )
        offers.append(replace(current, id=previous.id))
    # Quote matching preserves city/mode sequence. Recheck actual times in order,
    # not by exploring a second set of alternatives or invoking the provider again.
    if settings.latest_departure_date is not None and instant(offers[0].path[0].departure_at) > instant(settings.latest_departure_date):
        raise ExactPricingUnavailable("Provider timetable violates the departure window")
    ready = instant(settings.departure_date)
    for index, offer in enumerate(offers):
        if (instant(offer.path[0].departure_at) - ready).total_seconds() < (
            min_connection_seconds if index else 0
        ):
            raise ExactPricingUnavailable("Provider timetable breaks a connection")
        ready = instant(offer.path[-1].arrival_at)
    earliest, latest = settings.return_window
    if not earliest <= ready <= latest:
        raise ExactPricingUnavailable("Provider timetable violates the return window")
    total = Money(
        sum_exact(o.price.amount for o in offers), settings.expenses_tolerance.currency
    )
    candidate = RoundTrip(tuple(offers), total)
    stays, fit = city_stays(candidate, settings)
    return replace(
        candidate,
        city_stays=stays,
        stay_fit=fit if settings.fuzzy_search else None,
        price_status="provider_advertised",
        approximate_price=original.total_price,
    )


def sum_exact(values):
    total = Decimal(0)
    for value in values:
        total = _add_exact(total, value)
    return total


def _rank(option: RoundTrip):
    return (
        -(option.stay_fit if option.stay_fit is not None else 0),
        option.total_price.amount,
        sum(leg.time_in_travel for leg in option.path),
        tuple(offer.id for offer in option.offers),
    )


def _add_exact(left: Decimal, right: Decimal) -> Decimal:
    # Align every digit, plus a carry, independently of ambient Decimal precision.
    with localcontext() as context:
        context.prec = (
            max(left.adjusted(), right.adjusted(), 0)
            - min(left.as_tuple().exponent, right.as_tuple().exponent, 0)
            + 2
        )
        return left + right


def city_stays(
    option: RoundTrip, settings: SearchSettings
) -> tuple[tuple[CityStay, ...], float]:
    """Soft weighted targets; observed gaps never change the supplied schedule.

    Aggregate revisits and internal ticket connections. These are elapsed city
    times, not a guarantee of usable sightseeing time or terminal access.
    """
    path = option.path
    if not path:
        return (), 0.0
    home = settings.departure_city
    spent = {leg.destination: 0.0 for leg in path if leg.destination != home}
    for previous, following in zip(path, path[1:]):
        if previous.destination != home:
            spent[previous.destination] += (
                instant(following.departure_at) - instant(previous.arrival_at)
            ).total_seconds()
    if not spent:
        return (), 0.0
    # Initial waiting at home is not city exploration time. Travel, including
    # all physical legs of bundled tickets, consumes the available stay budget.
    target_return = min(
        instant(settings.desired_arrival_date), settings.return_window[1]
    )
    available = max(
        0.0,
        (target_return - instant(path[0].departure_at)).total_seconds()
        - sum(leg.time_in_travel for leg in path),
    )
    weights = {item.city: item.weight for item in settings.city_attractiveness}
    # Scale before summation to avoid overflow for large valid weights.
    scale = max(weights.get(city, 1.0) for city in spent)
    normalized = {city: weights.get(city, 1.0) / scale for city in spent}
    total_weight = sum(normalized.values())
    stays = tuple(
        CityStay(
            city,
            seconds,
            available * normalized[city] / total_weight,
            weights.get(city, 1.0),
        )
        for city, seconds in spent.items()
    )
    difference = sum(abs(stay.time_spent - stay.target_time) for stay in stays)
    denominator = sum(spent.values()) + available
    fit = max(0.0, min(1.0, 1.0 - difference / denominator)) if denominator else 0.0
    return stays, fit
