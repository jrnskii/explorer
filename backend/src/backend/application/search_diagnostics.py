"""Explicit search decision logs; no provider payloads or exception messages."""

import logging

from backend.application.telemetry import event

logger = logging.getLogger(__name__)


def candidate_selected(option, settings, rank, source, *, track_budget=True):
    event(
        logger,
        "search.candidate_selected",
        level=logging.INFO,
        rank=rank,
        source=source,
        estimated_amount=str(option.total_price.amount),
        **(
            {"budget_amount": str(settings.expenses_tolerance.amount)}
            if track_budget
            else {}
        ),
        currency=option.total_price.currency,
        legs=[
            dict(
                origin=leg.origin,
                destination=leg.destination,
                date=leg.departure_at.date().isoformat(),
                mode=leg.transport_type.value,
            )
            for leg in option.path
        ],
    )


def candidate_failed(rank, error):
    event(
        logger,
        "search.candidate_rejected",
        level=logging.WARNING,
        rank=rank,
        reason="verification_unavailable",
        error_type=type(error).__name__,
    )


def candidate_verified(option, verified, settings, rank, *, track_budget=True):
    over_budget = verified.total_price.amount > settings.expenses_tolerance.amount
    event(
        logger,
        "search.candidate_verified",
        level=logging.INFO,
        rank=rank,
        estimated_amount=str(option.total_price.amount),
        provider_amount=str(verified.total_price.amount),
        **(
            {"budget_amount": str(settings.expenses_tolerance.amount)}
            if track_budget
            else {}
        ),
        currency=verified.total_price.currency,
        accepted=True,
        reason=(
            ("over_budget" if over_budget else "within_budget")
            if track_budget
            else "provider_priced"
        ),
    )
