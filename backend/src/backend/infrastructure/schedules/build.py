"""Compile published GTFS calendars into an indexed, dated staging search snapshot.

No departures, terminals or fares are generated. Prices are explicit model estimates.
Only adjacent, mapped, unrestricted boarding/alighting points are served. Frequency
services and uncertain stop times are excluded and counted in coverage diagnostics.
"""

import argparse
from contextlib import closing
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import itertools
from functools import lru_cache
import sys
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import fcntl
from zoneinfo import ZoneInfo

import duckdb
import networkx as nx

from backend.application.telemetry import event, traced
from backend.infrastructure.logging import cli_entrypoint
from backend.domain.pricing import ForecastQuery
from backend.domain.travel import TransportType
from backend.infrastructure.catalog.static_transport import (
    CityIndex,
    coordinates,
    distance_km,
    gtfs_mode,
)
from backend.infrastructure.pricing.forecast import load_forecaster

DDL = """
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE cities(id TEXT PRIMARY KEY,name TEXT NOT NULL,latitude REAL NOT NULL,longitude REAL NOT NULL,country TEXT NOT NULL);
CREATE TABLE offers(id TEXT PRIMARY KEY,origin TEXT NOT NULL,destination TEXT NOT NULL,departure INTEGER NOT NULL,
 arrival INTEGER NOT NULL,mode TEXT NOT NULL,amount TEXT NOT NULL,currency TEXT NOT NULL,source TEXT NOT NULL,timezone TEXT NOT NULL);
CREATE INDEX offer_origin_time ON offers(origin,departure);
CREATE INDEX offer_time_mode ON offers(mode,departure,arrival);
"""


def gtfs_seconds(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{1,3}:[0-5]\d:[0-5]\d", value
    ):
        raise ValueError("Invalid GTFS time")
    h, m, s = map(int, value.split(":"))
    if h > 71:
        raise ValueError("GTFS time exceeds supported three-day service interval")
    return h * 3600 + m * 60 + s


def service_instant(day, seconds, zone):
    # GTFS offsets are measured from noon minus 12 elapsed hours, including DST days.
    noon = datetime.combine(day, time(12), ZoneInfo(zone)).astimezone(timezone.utc)
    return noon + timedelta(seconds=seconds - 43200)


def active_dates(calendar, exceptions, start, end):
    active = set()
    day = start
    while day < end:
        key = day.strftime("%Y%m%d")
        if (
            calendar
            and calendar[7] <= key <= calendar[8]
            and calendar[day.weekday()] == "1"
        ):
            active.add(day)
        override = exceptions.get(key)
        if override == "1":
            active.add(day)
        elif override == "2":
            active.discard(day)
        day += timedelta(days=1)
    return sorted(active)


def prepare_query_indexes(db):
    # Static connectivity is only a pruning index. Dated departures remain authoritative.
    db.execute(
        "CREATE TABLE IF NOT EXISTS connections AS SELECT DISTINCT origin,destination,mode FROM offers"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS connections_mode ON connections(mode,destination,origin)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS offer_outgoing_cover ON offers(origin,departure,id,arrival,mode,destination,amount,currency,source,timezone)"
    )


@traced
def build_snapshot(source, catalog, models, output, *, start, days=31, now=None):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.with_suffix(output.suffix + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "A schedule compiler is already writing this snapshot."
            ) from exc
        return _build_snapshot(
            source, catalog, models, output, start=start, days=days, now=now
        )


@traced
def _build_snapshot(source, catalog, models, output, *, start, days=31, now=None):
    if not 1 <= days <= 366:
        raise ValueError("days must be between 1 and 366")
    now = now or datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    rows = json.loads(Path(catalog).read_text())
    graph = nx.MultiDiGraph()
    cities = {}
    for identity, name, country, lat, lon in rows:
        point = coordinates(lat, lon)
        if point is None or not name or not isinstance(identity, int):
            raise ValueError("Invalid GeoNames city catalog")
        key = f"gn-{identity}"
        if key in cities:
            raise ValueError("Duplicate city identity")
        cities[key] = {"name": name, "country": country, **point}
        graph.add_node(key, **cities[key])
    index = CityIndex(graph)
    forecaster = load_forecaster(models)
    predict = lru_cache(maxsize=50000)(forecaster.predict)
    nearest = lru_cache(maxsize=50000)(
        lambda lat, lon: index.nearest(coordinates(lat, lon))
    )
    counts = Counter()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name("." + output.name + ".building")
    fresh = not staging.exists()
    signature = json.dumps(
        {
            "start": str(start),
            "days": days,
            "as_of": str(now.date()),
            "source": str(Path(source).resolve()),
            "source_size": Path(source).stat().st_size,
            "source_mtime": Path(source).stat().st_mtime_ns,
            "catalog": hashlib.sha256(Path(catalog).read_bytes()).hexdigest(),
            "models": hashlib.sha256(Path(models).read_bytes()).hexdigest(),
        },
        sort_keys=True,
    )
    with closing(sqlite3.connect(staging)) as target, duckdb.connect(
        str(source), read_only=True, config={"threads": 2, "memory_limit": "512MB"}
    ) as db:
        if fresh:
            target.executescript(
                DDL + "CREATE TABLE completed_feeds(feed_id TEXT PRIMARY KEY);"
            )
            target.executemany(
                "INSERT INTO cities VALUES (?,?,?,?,?)",
                [
                    (key, c["name"], c["latitude"], c["longitude"], c["country"])
                    for key, c in cities.items()
                ],
            )
            target.execute(
                "INSERT INTO metadata VALUES ('build_request',?)", [signature]
            )
            target.execute("INSERT INTO metadata VALUES ('counts','{}')")
            target.commit()
        else:
            previous = target.execute(
                "SELECT value FROM metadata WHERE key='build_request'"
            ).fetchone()
            if previous is None or previous[0] != signature:
                raise ValueError(
                    "Checkpoint inputs changed. Remove the incomplete .building checkpoint or choose another output path."
                )
            counts.update(
                json.loads(
                    target.execute(
                        "SELECT value FROM metadata WHERE key='counts'"
                    ).fetchone()[0]
                )
            )
        completed = {
            row[0] for row in target.execute("SELECT feed_id FROM completed_feeds")
        }

        def checkpoint(feed):
            target.execute("INSERT INTO completed_feeds VALUES (?)", [feed])
            target.execute(
                "UPDATE metadata SET value=? WHERE key='counts'",
                [json.dumps(dict(counts))],
            )
            target.commit()

        feeds = db.execute(
            "SELECT feed_id,source_sha256 FROM feeds ORDER BY feed_id"
        ).fetchall()
        for number, (feed, _) in enumerate(feeds, 1):
            if feed in completed:
                continue
            print(
                f"Preparing schedule feed {number}/{len(feeds)}; priced services: {counts['priced_services']}",
                file=sys.stderr,
                flush=True,
            )
            counts["feeds"] += 1
            agencies = dict(
                db.execute(
                    "SELECT agency_id,agency_timezone FROM agency WHERE feed_id=?",
                    [feed],
                ).fetchall()
            )
            routes = {}
            for route, mode, agency in db.execute(
                "SELECT route_id,route_type,agency_id FROM routes WHERE feed_id=?",
                [feed],
            ).fetchall():
                zone = agencies.get(agency) or (
                    next(iter(agencies.values())) if len(agencies) == 1 else None
                )
                if zone and gtfs_mode(mode):
                    try:
                        ZoneInfo(zone)
                        routes[route] = (gtfs_mode(mode), zone)
                    except (ValueError, KeyError):
                        counts["invalid_timezone"] += 1
            calendars = {}
            invalid_services = set()
            for row in db.execute(
                "SELECT service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date FROM calendar WHERE feed_id=?",
                [feed],
            ).fetchall():
                if not all(value in ("0", "1") for value in row[1:8]) or not all(
                    isinstance(value, str) and re.fullmatch(r"\d{8}", value)
                    for value in row[8:10]
                ):
                    invalid_services.add(row[0])
                    counts["invalid_calendars"] += 1
                    continue
                if row[0] in calendars and calendars[row[0]] != row[1:]:
                    invalid_services.add(row[0])
                    counts["conflicting_calendars"] += 1
                calendars[row[0]] = row[1:]
            exceptions = {}
            for service, day, kind in db.execute(
                "SELECT service_id,date,exception_type FROM calendar_dates WHERE feed_id=?",
                [feed],
            ).fetchall():
                previous = exceptions.setdefault(service, {}).get(day)
                if kind not in ("1", "2") or previous is not None and previous != kind:
                    invalid_services.add(service)
                    counts["conflicting_calendar_exceptions"] += 1
                exceptions[service][day] = kind
            services = {
                service: active_dates(
                    calendars.get(service),
                    exceptions.get(service, {}),
                    start - timedelta(days=3),
                    end,
                )
                for (service,) in db.execute(
                    "SELECT DISTINCT service_id FROM trips WHERE feed_id=?", [feed]
                ).fetchall()
            }
            if not any(
                dates
                for service, dates in services.items()
                if service not in invalid_services
            ):
                counts["feeds_without_active_services"] += 1
                checkpoint(feed)
                continue
            stops = {}
            for stop, lat, lon in db.execute(
                "SELECT stop_id,stop_lat,stop_lon FROM stops WHERE feed_id=?", [feed]
            ).fetchall():
                stops[stop] = nearest(lat, lon)
            # Frequency schedules lack exact individual departures; do not invent them.
            frequency_trips = {
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT trip_id FROM frequencies WHERE feed_id=?", [feed]
                ).fetchall()
            }
            trip_routes = dict(
                db.execute(
                    "SELECT trip_id,route_id FROM trips WHERE feed_id=?", [feed]
                ).fetchall()
            )
            trip_services = dict(
                db.execute(
                    "SELECT trip_id,service_id FROM trips WHERE feed_id=?", [feed]
                ).fetchall()
            )
            cursor = db.execute(
                """SELECT trip_id,stop_id,stop_sequence,arrival_time,departure_time,pickup_type,drop_off_type,timepoint
                    FROM stop_times WHERE feed_id=? ORDER BY trip_id,try_cast(stop_sequence AS BIGINT)""",
                [feed],
            )

            def stream():
                while batch := cursor.fetchmany(4096):
                    yield from batch

            for trip, group in itertools.groupby(stream(), key=lambda row: row[0]):
                calls = list(group)
                route = trip_routes.get(trip)
                if trip in frequency_trips or route not in routes:
                    counts["frequency_or_unsupported_trips"] += 1
                    continue
                dates = (
                    []
                    if trip_services.get(trip) in invalid_services
                    else services.get(trip_services.get(trip), [])
                )
                if not dates:
                    continue
                mode, zone = routes[route]
                try:
                    sequences = [int(call[2]) for call in calls]
                    if len(set(sequences)) != len(sequences) or any(
                        seq < 0 for seq in sequences
                    ):
                        raise ValueError()
                except (ValueError, TypeError):
                    counts["invalid_trip_sequences"] += 1
                    continue
                for before, after in itertools.pairwise(calls):
                    origin, destination = stops.get(before[1]), stops.get(after[1])
                    if not origin or not destination or origin == destination:
                        counts["unmapped_or_internal_pairs"] += 1
                        continue
                    if (
                        before[5] not in (None, "", "0")
                        or after[6] not in (None, "", "0")
                        or before[7] == "0"
                        or after[7] == "0"
                    ):
                        counts["restricted_or_approximate_pairs"] += 1
                        continue
                    try:
                        departure_seconds, arrival_seconds = gtfs_seconds(
                            before[4]
                        ), gtfs_seconds(after[3])
                    except ValueError:
                        counts["invalid_times"] += 1
                        continue
                    if arrival_seconds <= departure_seconds:
                        counts["invalid_times"] += 1
                        continue
                    a, b = cities[origin], cities[destination]
                    for day in dates:
                        departure, arrival = service_instant(
                            day, departure_seconds, zone
                        ), service_instant(day, arrival_seconds, zone)
                        if departure < datetime.combine(
                            start, time(), timezone.utc
                        ) or arrival >= datetime.combine(end, time(), timezone.utc):
                            continue
                        forecast = predict(
                            ForecastQuery(
                                TransportType(mode),
                                a["name"],
                                b["name"],
                                departure.date(),
                                now.date(),
                                a["country"],
                                b["country"],
                                feed_id=feed,
                                route_id=route,
                                distance_km=distance_km(a, b),
                            )
                        )
                        if forecast is None:
                            counts["unpriced_services"] += 1
                            continue
                        key = hashlib.sha256(
                            json.dumps(
                                [feed, trip, before[2], after[2], str(day)]
                            ).encode()
                        ).hexdigest()
                        target.execute(
                            "INSERT INTO offers VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (
                                key,
                                origin,
                                destination,
                                int(departure.timestamp()),
                                int(arrival.timestamp()),
                                mode,
                                str(forecast.price.amount),
                                forecast.price.currency,
                                f"gtfs:{feed}:{trip}",
                                zone,
                            ),
                        )
                        counts["priced_services"] += 1
            checkpoint(feed)
        if not counts["priced_services"]:
            raise ValueError(
                "No dated, forecast-priced services in the selected window. Check GTFS calendar dates and model coverage."
            )
        prepare_query_indexes(target)
        metadata = dict(
            query_index_version=2,
            format="explorer.schedules.v1",
            synthetic=False,
            currency="EUR",
            built_at=now.isoformat(),
            window_start=datetime.combine(start, time(), timezone.utc).isoformat(),
            window_end=datetime.combine(end, time(), timezone.utc).isoformat(),
            coverage=dict(counts),
            source_feeds=feeds,
            transport_types=[
                row[0]
                for row in target.execute(
                    "SELECT DISTINCT mode FROM offers ORDER BY mode"
                )
            ],
            models_sha256=hashlib.sha256(Path(models).read_bytes()).hexdigest(),
            catalog_sha256=hashlib.sha256(Path(catalog).read_bytes()).hexdigest(),
        )
        target.execute(
            "INSERT INTO metadata VALUES ('snapshot',?)", [json.dumps(metadata)]
        )
        target.commit()
    os.replace(staging, output)
    event(logging.getLogger("backend.infrastructure.schedules.build"),
          "snapshot.published", level=logging.INFO,
          priced_services=counts["priced_services"], days=days, source_feeds=len(feeds))
    return metadata


@cli_entrypoint
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date.today())
    parser.add_argument("--days", type=int, default=31)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                build_snapshot(
                    args.source,
                    args.catalog,
                    args.models,
                    args.output,
                    start=args.start,
                    days=args.days,
                )
            )
        )
    except (OSError, ValueError, sqlite3.Error, duckdb.Error) as exc:
        parser.exit(2, f"prepare-schedules: {exc}\n")


if __name__ == "__main__":
    main()
