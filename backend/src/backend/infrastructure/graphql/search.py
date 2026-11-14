"""Staging search composition uses only the published dated schedule snapshot."""

import os
import logging
from pathlib import Path
from functools import lru_cache

from backend.application.telemetry import traced, event
from backend.infrastructure.scrappa.best_route import configured_pricer
from backend.infrastructure.schedules.store import (
    ScheduleSearch,
    SearchUnavailable,
    SearchCoverageError,
)
from backend.infrastructure.schedules.reference import ReferenceSearch, project_routes
from backend.infrastructure.catalog.graph_snapshot import (
    DEFAULT_GRAPH_PATH,
    load_base_graph,
)
from backend.infrastructure.pricing.forecast import DEFAULT_ARTIFACT, load_forecaster

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def reference_routes(graph_path, modified, size, catalog):
    return project_routes(
        load_base_graph(Path(graph_path)),
        {
            row[0]: dict(name=row[1], latitude=row[2], longitude=row[3], country=row[4])
            for row in catalog
        },
    )


class ScheduleFirstSearch:
    """Prefer dated local services; use reference estimates only for missing results."""

    def __init__(self, schedules, reference_factory):
        self.schedules, self.reference_factory = schedules, reference_factory

    def ready(self):
        return self.schedules.ready()

    def __call__(self, settings):
        try:
            result = self.schedules(settings)
        except SearchCoverageError:
            reason = "missing_schedule_coverage"
        else:
            # Scheduled reconciliation already checks up to two candidates. Do not
            # start a separate reference fallback after those attempts.
            if result.options or result.metadata.get("price_status") != "no_candidates":
                return result
            reason = "no_schedule_candidates"
        event(logger, "search.reference_fallback", level=logging.INFO, reason=reason)
        return self.reference_factory()(settings)


@traced
def configured_search():
    path = os.environ.get("SCHEDULE_SNAPSHOT_PATH")
    if not path:
        raise SearchUnavailable(
            "SCHEDULE_SNAPSHOT_PATH must identify a prepared schedule snapshot."
        )
    if os.environ.get("SCRAPPA_API_KEY", "").strip() in ("", "change_in_prod"):
        raise SearchUnavailable(
            "SCRAPPA_API_KEY is required for best-opportunity verification."
        )
    schedules = ScheduleSearch(
        Path(path),
        max_age_seconds=int(os.environ.get("SCHEDULE_MAX_AGE_SECONDS", "86400")),
        pricer_factory=configured_pricer,
    )

    def reference():
        graph = Path(os.environ.get("REFERENCE_GRAPH_PATH", DEFAULT_GRAPH_PATH))
        models = Path(os.environ.get("FORECAST_MODELS_PATH", DEFAULT_ARTIFACT))
        if not graph.is_file() or not models.is_file():
            raise SearchCoverageError(
                "Local schedules do not cover this search. Prepare the reference graph and forecast models to enable estimated-route planning."
            )
        with schedules.connect() as db:
            catalog = tuple(
                db.execute(
                    "SELECT id,name,latitude,longitude,country FROM cities ORDER BY id"
                )
            )
        cities = {
            r[0]: dict(name=r[1], latitude=r[2], longitude=r[3], country=r[4])
            for r in catalog
        }
        stat = graph.stat()
        return ReferenceSearch(
            reference_routes(
                str(graph.resolve()), stat.st_mtime_ns, stat.st_size, catalog
            ),
            cities,
            load_forecaster(models),
            configured_pricer,
        )

    from backend.infrastructure.schedules.flexible import FlexibleSearch
    return FlexibleSearch(schedules, reference, configured_pricer)
