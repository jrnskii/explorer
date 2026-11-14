"""Replace purchase-unit demo prices without changing the schedule or solver."""

from dataclasses import replace
from datetime import date

from backend.application.ports import PriceForecaster
from backend.domain.planning import Money, instant
from backend.domain.pricing import ForecastQuery


def reprice_offers(
    offers, forecaster: PriceForecaster, cities, *, as_of: date, travelers=1
):
    """Preserve bundled tickets; mixed-mode bundles require a provider quote."""
    priced, evidence, skipped = [], {}, []
    for offer in offers:
        modes = {leg.transport_type for leg in offer.path}
        if len(modes) != 1:
            skipped.append(
                dict(offer_id=offer.id, reason="mixed_mode_bundle_unsupported")
            )
            continue
        origin = cities.get(offer.path[0].origin)
        destination = cities.get(offer.path[-1].destination)
        if origin is None or destination is None:
            skipped.append(dict(offer_id=offer.id, reason="unresolved_city"))
            continue
        query = ForecastQuery(
            offer.path[0].transport_type,
            origin["name"],
            destination["name"],
            offer.path[0].departure_at.date(),
            as_of,
            origin.get("country"),
            destination.get("country"),
            travelers,
        )
        prediction = forecaster.predict(query)
        if prediction is None:
            skipped.append(dict(offer_id=offer.id, reason="unsupported_model_coverage"))
            continue
        priced.append(
            replace(
                offer, price=prediction.price, source="forecast:" + prediction.model_id
            )
        )
        evidence[offer.id] = prediction
    return tuple(priced), evidence, tuple(skipped)


class ForecastOfferProvider:
    """Forecast prices over an explicitly synthetic schedule provider."""

    def __init__(self, schedule_provider, forecaster, cities, as_of):
        self.schedule_provider, self.forecaster, self.cities, self.as_of = (
            schedule_provider,
            forecaster,
            cities,
            as_of,
        )
        self.evidence, self.skipped = {}, ()

    def offers(self, settings):
        if settings.expenses_tolerance.currency != "EUR":
            raise ValueError(
                "Forecast prices require an EUR budget; no implicit currency conversion is available"
            )
        # The existing timetable fixture requires USD; its monetary values are discarded.
        schedule_settings = replace(
            settings,
            expenses_tolerance=Money(settings.expenses_tolerance.amount, "USD"),
        )
        supplied = tuple(
            o
            for o in self.schedule_provider.offers(schedule_settings)
            if instant(o.path[0].departure_at) >= instant(settings.departure_date)
            and instant(o.path[-1].arrival_at) <= settings.return_window[1]
        )
        priced, self.evidence, self.skipped = reprice_offers(
            supplied, self.forecaster, self.cities, as_of=self.as_of
        )
        return priced


class ForecastOfferEstimator:
    """Local forecasting port consumed directly by find_round_trips."""

    def __init__(self, forecaster, cities, as_of, *, travelers=1):
        self.forecaster, self.cities, self.as_of, self.travelers = (
            forecaster,
            cities,
            as_of,
            travelers,
        )
        self.evidence = {}
        self.skipped = []

    def estimate_offer(self, offer):
        priced, evidence, skipped = reprice_offers(
            (offer,),
            self.forecaster,
            self.cities,
            as_of=self.as_of,
            travelers=self.travelers,
        )
        self.evidence.update(evidence)
        self.skipped.extend(skipped)
        return evidence.get(offer.id)
