"""Bounded exhaustive traversal of a finite, priced schedule snapshot.

No provider calls or shared weight mutations occur during exploration. Cheapest
means cheapest among supplied offers, and only exhaustive when not truncated.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Iterable
import logging

logger = logging.getLogger(__name__)

from backend.domain.planning import (
    JourneyOffer,
    Money,
    RoundTrip,
    SearchSettings,
    instant,
)


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


def find_round_trips(
    settings: SearchSettings,
    offers: Iterable[JourneyOffer],
    limits: SearchLimits = SearchLimits(),
) -> SearchResult:
    logger.info(
        "Starting search home=%s mandatory=%s budget=%s %s",
        settings.departure_city,
        settings.mandatory_cities,
        settings.expenses_tolerance.amount,
        settings.expenses_tolerance.currency,
    )
    adjacency = defaultdict(list)
    identities = {}
    excluded = set(settings.excluded_cities)
    home = settings.departure_city
    earliest, latest = settings.return_window
    for offer in offers:
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
        if offer.price.currency != settings.expenses_tolerance.currency:
            raise ValueError(
                "offer currency differs from budget; currency conversion is unsupported"
            )
        if any(
            leg.transport_type not in settings.transport_types
            or {leg.origin, leg.destination} & excluded
            for leg in offer.path
        ):
            logger.debug("Reject offer=%s: excluded city or disallowed mode", offer.id)
            continue
        # Home inside a purchase would violate the first-return termination rule.
        if any(leg.destination == home for leg in offer.path[:-1]):
            logger.debug("Reject offer=%s: returns home inside ticket", offer.id)
            continue
        if (
            instant(offer.path[0].departure_at) < instant(settings.departure_date)
            or instant(offer.path[-1].arrival_at) > latest
        ):
            logger.debug("Reject offer=%s: outside departure/return horizon", offer.id)
            continue
        adjacency[offer.path[0].origin].append(offer)
        logger.debug("Index offer=%s", offer.id)
    for outgoing in adjacency.values():
        outgoing.sort(
            key=lambda offer: (
                offer.price.amount,
                instant(offer.path[0].departure_at),
                offer.id,
            )
        )
    # Directed reachability prunes dead ends without assumptions about prices/time.
    reverse = defaultdict(set)
    for city, outgoing in adjacency.items():
        for offer in outgoing:
            reverse[offer.path[-1].destination].add(city)
    reachable, pending = {home}, [home]
    while pending:
        for city in reverse[pending.pop()]:
            if city not in reachable:
                reachable.add(city)
                pending.append(city)
    logger.debug("Cities with a directed route home: %s", sorted(reachable))
    stack = [(home, instant(settings.departure_date), (), Decimal(0), frozenset(), 0)]
    candidates = []
    reasons = set()
    states = 0
    results_limited = False
    while stack:
        if states >= limits.max_states:
            logger.info("Stop exploration: max_states=%s", limits.max_states)
            reasons.add("max_states")
            break
        city, ready, chosen, total, visited, legs = stack.pop()
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
        if chosen and city == home:
            if (
                visited - {home}
                and set(settings.mandatory_cities) <= visited
                and earliest <= ready <= latest
            ):
                candidates.append(
                    RoundTrip(
                        chosen, Money(total, settings.expenses_tolerance.currency)
                    )
                )
                logger.info(
                    "Found round trip price=%s tickets=%s",
                    total,
                    tuple(offer.id for offer in chosen),
                )
                # Bound retained results without stopping exploration.
                candidates.sort(key=_rank)
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
            continue
        for offer in reversed(adjacency[city]):
            logger.debug("Consider next ticket=%s from=%s", offer.id, city)
            destination = offer.path[-1].destination
            if (
                destination not in reachable
                or instant(offer.path[0].departure_at) < ready
            ):
                logger.debug(
                    "Skip ticket=%s: missed departure or no directed route home",
                    offer.id,
                )
                continue
            amount = _add_exact(total, offer.price.amount)
            if amount > settings.expenses_tolerance.amount:
                logger.debug(
                    "Skip ticket=%s: price=%s exceeds budget", offer.id, amount
                )
                continue  # These are fixed purchase prices, not historical estimates.
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
            stack.append(
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
    return SearchResult(
        tuple(candidates), states, tuple(sorted(reasons)), results_limited
    )


def _rank(option: RoundTrip):
    return (
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
