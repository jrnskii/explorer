"""Read-only, indexed serving snapshot of dated, forecast-priced GTFS services."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from backend.application.telemetry import event, traced
from backend.application.round_trip_search import SearchLimits, find_round_trips
from backend.application.ports import OfferLimitReached
from backend.domain.cities import City
from backend.domain.planning import (
    JourneyOffer,
    Money,
    SearchSettings,
    TripLeg,
    instant,
)
from backend.domain.travel import TransportType
from backend.infrastructure.graphql.round_trip import serialize_options

logger = logging.getLogger(__name__)


class SearchUnavailable(Exception):
    pass


class SearchInputError(ValueError):
    pass


class SearchCoverageError(SearchInputError):
    """The loaded data cannot establish coverage for the requested route."""


@dataclass(frozen=True)
class SearchResponse:
    options: list[dict[str, object]]
    metadata: dict[str, object]


class ScheduleSearch:
    def __init__(
        self,
        path: Path,
        *,
        max_offers=100_000,
        max_age_seconds=86400,
        clock=lambda: datetime.now(timezone.utc),
        pricer_factory=None,
    ):
        self.path = Path(path).resolve()
        self.max_offers, self.max_age_seconds, self.clock = (
            max_offers,
            max_age_seconds,
            clock,
        )
        self.pricer_factory = pricer_factory
        self.ready()

    @contextmanager
    def connect(self):
        try:
            db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=2)
            db.execute("PRAGMA query_only=ON")
        except sqlite3.Error as exc:
            raise SearchUnavailable("Schedule snapshot is unavailable.") from exc
        try:
            yield db
        finally:
            db.close()

    @traced
    def metadata(self, db):
        try:
            metadata = json.loads(
                db.execute(
                    "SELECT value FROM metadata WHERE key='snapshot'"
                ).fetchone()[0]
            )
            if (
                metadata["format"] != "explorer.schedules.v1"
                or metadata["synthetic"] is not False
            ):
                raise ValueError("Invalid schedule format")
            if metadata.get("query_index_version") != 2:
                raise SearchUnavailable(
                    "Schedule snapshot requires serving indexes. Run optimize-schedules."
                )
            db.execute(
                "SELECT origin,destination,mode FROM connections LIMIT 1"
            ).fetchone()
            built = datetime.fromisoformat(metadata["built_at"])
            age = (self.clock() - instant(built)).total_seconds()
            event(logger, "snapshot.age", age_seconds=round(age, 3),
                  max_age_seconds=self.max_age_seconds)
            if age < -300 or age > self.max_age_seconds:
                raise SearchUnavailable(
                    "Schedule snapshot is stale. Rebuild it before serving searches."
                )
            if (
                db.execute(
                    "SELECT id,origin,destination,departure,arrival,mode,amount,currency,source,timezone FROM offers LIMIT 1"
                ).fetchone()
                is None
            ):
                raise SearchUnavailable("Schedule snapshot has no priced services.")
            start = instant(datetime.fromisoformat(metadata["window_start"]))
            end = instant(datetime.fromisoformat(metadata["window_end"]))
            if end <= start or end <= self.clock():
                raise SearchUnavailable("Schedule snapshot has expired.")
            return metadata
        except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            raise SearchUnavailable("Schedule snapshot is invalid.") from exc

    @traced
    def ready(self):
        with self.connect() as db:
            return self.metadata(db)

    @traced
    def __call__(self, settings: SearchSettings, *, rank_only=False):
        earliest, latest = instant(settings.departure_date), instant(
            settings.return_window[1]
        )
        if earliest < self.clock():
            raise SearchInputError("Departure must be in the future.")
        with self.connect() as db:
            metadata = self.metadata(db)
            deadline = time.monotonic() + 30
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            if earliest < datetime.fromisoformat(
                metadata["window_start"]
            ) or latest > datetime.fromisoformat(metadata["window_end"]):
                raise SearchCoverageError(
                    "The requested dates are outside the loaded schedule window."
                )
            if settings.expenses_tolerance.currency != metadata["currency"]:
                raise SearchInputError(
                    "The budget currency must match the schedule pricing currency."
                )
            catalog = db.execute(
                "SELECT id,name,latitude,longitude,country FROM cities"
            ).fetchall()
            cities = {row[0]: City(*row[:4]) for row in catalog}
            pricing_cities = {
                row[0]: {"name": row[1], "country": row[4]} for row in catalog
            }
            requested = {
                settings.departure_city,
                *settings.mandatory_cities,
                *settings.excluded_cities,
            }
            if requested - cities.keys():
                raise SearchInputError(
                    "A city identifier is not in the city catalog. Choose a city from autocomplete."
                )
            modes = [mode.value for mode in settings.transport_types]
            available = set(
                metadata.get("transport_types")
                or [row[0] for row in db.execute("SELECT DISTINCT mode FROM offers")]
            )
            if not available.intersection(modes):
                raise SearchCoverageError(
                    "The selected transport modes have no published schedules in the loaded data."
                )
            placeholders = ",".join("?" for _ in modes)
            for city in (settings.departure_city, *settings.mandatory_cities):
                if any(
                    db.execute(
                        f"SELECT 1 FROM connections WHERE {endpoint}=? AND mode IN ({placeholders}) LIMIT 1",
                        [city, *modes],
                    ).fetchone() is None
                    for endpoint in ("origin", "destination")
                ):
                    raise SearchCoverageError(
                        f"{cities[city].name} has no round-trip schedule and price coverage "
                        "for the selected transport modes in the loaded data."
                    )
            offer_index = ScheduleOfferIndex(db, settings, self.max_offers)
            pricer = (
                self.pricer_factory(pricing_cities) if self.pricer_factory and not rank_only else None
            )
            result = find_round_trips(
                settings,
                (),
                SearchLimits(),
                min_connection_seconds=1800,
                exact_pricer=pricer,
                offer_index=offer_index,
                max_transitions=500_000,
            )
        if rank_only:
            return result, cities, pricing_cities
        return SearchResponse(
            serialize_options(result.options, cities),
            {
                "synthetic_schedule": False,
                "pricing": "forecast",
                "price_scope": "adult",
                "schedule_source": "GTFS",
                "snapshot_built_at": metadata["built_at"],
                "window_start": metadata["window_start"],
                "window_end": metadata["window_end"],
                "results_limited": result.results_limited,
                "truncation_reasons": result.truncation_reasons,
                "coverage": metadata.get("coverage", {}),
                "min_connection_seconds": 1800,
                "unavailable_transport_types": sorted(set(modes) - available),
                "price_status": (
                    result.pricing.status if result.pricing else "estimated"
                ),
                "fees_verified": (
                    result.pricing.fees_complete if result.pricing else False
                ),
                "option_pricing": [
                    {
                        "price_status": (
                            option.price_status if result.pricing else "estimated"
                        ),
                        "over_budget": option.total_price.amount > settings.expenses_tolerance.amount,
                        "approximate_price": (
                            str(option.approximate_price.amount)
                            if option.approximate_price
                            else None
                        ),
                    }
                    for option in result.options
                ],
                "provider_error": result.pricing.error if result.pricing else None,
                "provider_checked_opportunities": (
                    1
                    if result.pricing
                    and result.pricing.status in ("provider_priced", "over_budget")
                    else 0
                ),
                "provider_pricing_attempts": (
                    result.pricing.provider_pricing_attempts if result.pricing else 0
                ),
            },
        )


class ScheduleOfferIndex:
    """Read only the timetables needed by traversal; parallel services stay distinct."""

    def __init__(self, db, settings, max_offers):
        self.db, self.settings, self.max_offers = db, settings, max_offers
        self.loaded = 0
        self.modes = tuple(mode.value for mode in settings.transport_types)
        self.placeholders = ",".join("?" for _ in self.modes)
        self.start = instant(settings.departure_date).timestamp()
        self.end = instant(settings.return_window[1]).timestamp()

    @traced
    def reverse_connections(self):
        reverse = {}
        for origin, destination in self.db.execute(
            f"""SELECT origin,destination FROM connections WHERE mode IN ({self.placeholders})""",
            list(self.modes),
        ):
            reverse.setdefault(destination, set()).add(origin)
        return reverse

    @traced
    def outgoing(self, city):
        remaining = self.max_offers - self.loaded
        rows = self.db.execute(
            f"""SELECT id,origin,destination,departure,arrival,mode,amount,currency,source,timezone
            FROM offers INDEXED BY offer_outgoing_cover WHERE origin=? AND departure>=? AND arrival<=? AND mode IN ({self.placeholders})
            ORDER BY departure,id LIMIT ?""",
            [city, self.start, self.end, *self.modes, remaining + 1],
        ).fetchall()
        if len(rows) > remaining:
            event(logger, "schedule.offer_limit", level=logging.WARNING,
                  loaded=self.loaded, max_offers=self.max_offers)
            raise OfferLimitReached("The schedule service limit was reached.")
        self.loaded += len(rows)
        event(logger, "schedule.offers_loaded", row_count=len(rows),
              total_loaded=self.loaded)
        return tuple(
            JourneyOffer(
                row[0],
                (
                    TripLeg(
                        row[1],
                        row[2],
                        datetime.fromtimestamp(row[3], ZoneInfo(row[9])),
                        datetime.fromtimestamp(row[4], ZoneInfo(row[9])),
                        TransportType(row[5]),
                    ),
                ),
                Money(Decimal(row[6]), row[7]),
                row[8],
                False,
            )
            for row in rows
        )
