"""Independent empirical models loaded from safe, versioned JSON artifacts."""

from datetime import date
from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from functools import lru_cache
import json
import logging
from pathlib import Path

from backend.application.telemetry import event, traced
from backend.domain.planning import Money
from backend.domain.pricing import ForecastQuery, PriceForecast
from backend.domain.travel import TransportType
from backend.infrastructure.fixtures.extract_pricing import ALIASES, country, key
from backend.infrastructure.pricing.download import SCHENGEN
from backend.infrastructure.pricing.distance import (
    predict_distance,
    scope,
    validate_distance_model,
    valid_distance,
    resolve_distance,
)

DEFAULT_ARTIFACT = (
    Path(__file__).resolve().parents[1] / "fixtures/data/pricing/forecast_models.json"
)

logger = logging.getLogger(__name__)


def name(value):
    return key(ALIASES.get(str(value).casefold(), value))


def code(value):
    return "SK" if value == "Slovak Republic" else country(value)


def route(origin, destination, oc, dc):
    return json.dumps([name(origin), name(destination), oc, dc], separators=(",", ":"))


def lead_bucket(days):
    for boundary in (3, 7, 14, 30, 60):
        if days <= boundary:
            return str(boundary)
    return "over60"


class EmpiricalModel:
    mode = None
    label = ""

    def __init__(self, entries, information_date, model_id, distance=None):
        self.entries = entries
        self.distance = distance or {}
        self.blocked_distance_routes = set(self.distance.get("blocked_routes", []))
        self.information_date = information_date
        self.model_id = model_id
        self.routes = {}
        for identity in entries:
            parts = json.loads(identity)
            if len(parts) != 4:
                raise ValueError("Invalid model route identity")
            self.routes.setdefault((parts[0], parts[1]), []).append(identity)

    def identity(self, query):
        candidates = self.routes.get((name(query.origin), name(query.destination)), [])
        candidates = [
            r
            for r in candidates
            if (
                query.origin_country is None
                or json.loads(r)[2] == code(query.origin_country)
            )
            and (
                query.destination_country is None
                or json.loads(r)[3] == code(query.destination_country)
            )
        ]
        return candidates[0] if len(candidates) == 1 else None

    def select(self, entry, query):
        return entry["baseline"], "route_baseline"

    def distance_forecast(self, query):
        if self.mode == TransportType.FERRIES:
            if not query.feed_id or not query.route_id:
                return None
            identity = json.dumps(
                [query.feed_id, query.route_id, "", ""], separators=(",", ":")
            )
            if identity in self.blocked_distance_routes:
                return None
            group = json.dumps([query.feed_id], separators=(",", ":"))
        else:
            if query.origin_country is None or query.destination_country is None:
                return None
            group = json.dumps(
                [code(query.origin_country), code(query.destination_country)],
                separators=(",", ":"),
            )
        return predict_distance(
            self.distance.get("groups", {}).get(group), query.distance_km
        )

    def predict(self, query, distance_source=None):
        identity = self.identity(query)
        if identity is None:
            selected = self.distance_forecast(query)
            if selected is None:
                return None
            basis = "distance_regression"
        else:
            selected, basis = self.select(self.entries[identity], query)
        warnings = [
            self.label,
            "Planning estimate, not live availability. Ranges are descriptive, not calibrated prediction intervals.",
        ]
        end = selected.get("evidence_end")
        if end and (query.as_of - date.fromisoformat(end[:10])).days > 365:
            warnings.append(
                "Evidence is more than one year old; no inflation adjustment is applied."
            )
        if basis == "distance_regression":
            warnings.append(
                "Unseen route estimated from distance within its trained country pair or ferry feed. No extrapolation beyond fitted distances."
            )
            warnings.append(
                "Distance is between city centres, not road, rail or waterway mileage; ranges use in-sample residuals and are not calibrated."
            )
            if self.mode in (TransportType.TRAINS, TransportType.FERRIES):
                warnings.append(
                    "Distance regression targets published tariffs/products, not observed ticket prices."
                )
        if basis == "route_baseline":
            warnings.append(
                "Requested date/lead-time cell is unsupported; using this observed route baseline."
            )
        if basis == "distance_regression" and selected["samples"] < 10:
            warnings.append(
                "Distance fit has fewer than ten independent routes; regional coverage is sparse."
            )
        if selected["samples"] < 2:
            warnings.append(
                "Only one fitted evidence unit; observed variation does not measure forecast uncertainty."
            )
        if query.travelers > 1:
            warnings.append(
                "Adult unit estimate multiplied by travelers; no group discounts are modeled."
            )
        count = query.travelers
        amount = Decimal(selected["value"]) * count
        low = Decimal(selected["lower"]) * count
        high = Decimal(selected["upper"]) * count
        cents = Decimal("0.01")
        return PriceForecast(
            Money(amount.quantize(cents, rounding=ROUND_HALF_UP), "EUR"),
            Money(low.quantize(cents, rounding=ROUND_FLOOR), "EUR"),
            Money(high.quantize(cents, rounding=ROUND_CEILING), "EUR"),
            self.model_id,
            basis,
            selected["samples"],
            selected.get("evidence_start"),
            end,
            tuple(warnings),
            query.distance_km,
            distance_source,
        )


class FlightModel(EmpiricalModel):
    mode = TransportType.PLANES
    label = "Observed route/month medians; no learned annual seasonality or booking-time effects."

    def select(self, entry, query):
        cell = entry.get("months", {}).get(query.departure_date.strftime("%Y-%m"))
        return (cell, "route_departure_month") if cell else super().select(entry, query)


class BusModel(EmpiricalModel):
    mode = TransportType.BUSSES
    label = "Historical first-seat advertised fare model; operator coverage is limited to the training data."

    def select(self, entry, query):
        lead = (query.departure_date - query.as_of).days
        cell = entry.get("lead", {}).get(lead_bucket(lead))
        return (cell, "route_lead_time") if cell else super().select(entry, query)


class RailModel(EmpiricalModel):
    mode = TransportType.TRAINS
    label = "Second-class normal tariff midpoint; not a model fitted to observed paid/advertised ticket prices."

    def select(self, entry, query):
        return entry["baseline"], "published_tariff_midpoint"


class FerryModel(EmpiricalModel):
    mode = TransportType.FERRIES
    label = "Published EUR ferry route-product estimate; zone/rider/time-constrained products excluded."

    def identity(self, query):
        if not query.feed_id or not query.route_id:
            return None
        # Ferry coverage is feed/route-specific, never pooled across operators/countries.
        identity = json.dumps(
            [query.feed_id, query.route_id, "", ""], separators=(",", ":")
        )
        return identity if identity in self.entries else None

    def select(self, entry, query):
        return entry["baseline"], "published_ferry_product"


MODELS = (FlightModel, RailModel, BusModel, FerryModel)


class ForecastService:
    @traced
    def __init__(self, artifact):
        if artifact.get("format") != "explorer.price_forecasts" or artifact.get(
            "version"
        ) not in (1, 2):
            raise ValueError(
                "Unsupported forecast artifact format; run just train-pricing"
            )
        self.metadata = artifact["metadata"]
        self.information_date = date.fromisoformat(self.metadata["information_date"])
        self.distance_index = artifact.get("distance_index", {})
        if artifact["version"] == 2 and "distance_index" not in artifact:
            raise ValueError("Distance artifact must contain graph feature provenance")
        for point in self.distance_index.get("cities", {}).values():
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(type(v) not in (int, float) for v in point)
                or not -90 <= point[0] <= 90
                or not -180 <= point[1] <= 180
            ):
                raise ValueError("Invalid graph city coordinate index")
        for mode_distances in self.distance_index.get("edges", {}).values():
            if not isinstance(mode_distances, dict) or any(
                not valid_distance(v) for v in mode_distances.values()
            ):
                raise ValueError("Invalid graph distance index")
        if any(
            not valid_distance(v)
            for v in self.distance_index.get("ferry_routes", {}).values()
        ):
            raise ValueError("Invalid ferry distance index")
        self.models = {}
        for cls in MODELS:
            data = artifact["models"][cls.mode.value]
            entries = data["entries"]
            validate_distance_model(data.get("distance", {}))
            for entry in entries.values():
                cells = [
                    entry["baseline"],
                    *entry.get("months", {}).values(),
                    *entry.get("lead", {}).values(),
                ]
                for cell in cells:
                    amounts = [Decimal(cell[k]) for k in ("lower", "value", "upper")]
                    if (
                        any(not a.is_finite() or a < 0 for a in amounts)
                        or not amounts[0] <= amounts[1] <= amounts[2]
                        or type(cell["samples"]) is not int
                        or cell["samples"] < 1
                    ):
                        raise ValueError("Invalid forecast artifact evidence")
            self.models[cls.mode] = cls(
                entries, self.information_date, data["model_id"], data.get("distance")
            )

    @traced
    def predict(self, query):
        if not isinstance(query, ForecastQuery):
            raise ValueError("Expected a ForecastQuery")
        if query.as_of < self.information_date:
            raise ValueError(
                "Forecast information date precedes the fitted artifact; historical backtesting would leak information"
            )
        if any(
            c is not None and code(c) not in SCHENGEN
            for c in (query.origin_country, query.destination_country)
        ):
            return None
        source = "request" if query.distance_km is not None else None
        if query.distance_km is None:
            if (
                query.origin_country is not None
                and query.destination_country is not None
            ):
                identity = route(
                    query.origin,
                    query.destination,
                    code(query.origin_country),
                    code(query.destination_country),
                )
            else:
                identity = self.models[query.mode].identity(query)
            distance, resolved_source = resolve_distance(
                self.distance_index, query.mode.value, identity
            )
            # A ferry's median segment length is a training feature only. Never
            # substitute it for a requested segment's actual distance.
            if distance is not None:
                query = replace(query, distance_km=distance)
                source = resolved_source
        prediction = self.models[query.mode].predict(query, source)
        event(logger, "forecast.predicted", mode=query.mode.value,
              supported=prediction is not None, distance_source=source)
        return prediction


@lru_cache(maxsize=2)
@traced
def _load(path, modified, size):
    event(logger, "forecast.artifact_read", level=logging.DEBUG, bytes=size)
    try:
        return ForecastService(json.loads(Path(path).read_text()))
    except (KeyError, TypeError, ArithmeticError, json.JSONDecodeError) as error:
        raise ValueError(
            "Invalid forecast artifact; rerun just train-pricing"
        ) from error


@traced
def load_forecaster(path=DEFAULT_ARTIFACT):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(
            "Forecast artifact not found. Run just extract-pricing then just train-pricing; mock fallback is disabled."
        )
    stat = path.stat()
    return _load(str(path), stat.st_mtime_ns, stat.st_size)
