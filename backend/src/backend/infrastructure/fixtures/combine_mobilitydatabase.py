"""Extract bus, rail and ferry GTFS scheduling data into local DuckDB."""

import argparse
import csv
import fcntl
import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from zipfile import ZipFile

import duckdb

from backend.application.telemetry import traced
from backend.infrastructure.logging import cli_entrypoint, configure_logging

DEFAULT_DIRECTORY = Path(__file__).resolve().parent / "data" / "mobilitydatabase"
LOGGER = logging.getLogger(
    __spec__.name if __name__ == "__main__" and __spec__ else __name__
)
DEFAULT_WORKERS = min(4, os.cpu_count() or 1)
# Explicit projection: geometry, bike attributes, media and arbitrary files are excluded.
COLUMNS = {
    "agency": "agency_id agency_name agency_url agency_timezone",
    "routes": "route_id agency_id route_short_name route_long_name route_type route_url",
    "trips": "trip_id route_id service_id trip_headsign direction_id block_id wheelchair_accessible",
    "stops": "stop_id stop_name stop_lat stop_lon location_type parent_station stop_timezone wheelchair_boarding",
    "stop_times": "trip_id stop_id stop_sequence arrival_time departure_time pickup_type drop_off_type timepoint continuous_pickup continuous_drop_off start_pickup_drop_off_window end_pickup_drop_off_window",
    "calendar": "service_id monday tuesday wednesday thursday friday saturday sunday start_date end_date",
    "calendar_dates": "service_id date exception_type",
    "frequencies": "trip_id start_time end_time headway_secs exact_times",
    "transfers": "from_stop_id to_stop_id from_route_id to_route_id from_trip_id to_trip_id transfer_type min_transfer_time",
    "feed_info": "feed_publisher_name feed_publisher_url feed_lang feed_start_date feed_end_date feed_version",
}
REQUIRED = {
    "routes": {"route_id", "route_type"},
    "trips": {"trip_id", "route_id", "service_id"},
    "stops": {"stop_id"},
    "stop_times": {"trip_id", "stop_id", "stop_sequence"},
}
# GTFS base modes plus extended rail, coach, bus and water transport families.
MODE_SQL = "(try_cast(route_type AS INTEGER) IN (2,3,4) OR try_cast(route_type AS INTEGER) BETWEEN 100 AND 199 OR try_cast(route_type AS INTEGER) BETWEEN 200 AND 299 OR try_cast(route_type AS INTEGER) BETWEEN 700 AND 799 OR try_cast(route_type AS INTEGER) BETWEEN 1000 AND 1099 OR try_cast(route_type AS INTEGER)=1200)"


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def initialize(db):
    for table, fields in COLUMNS.items():
        definitions = ", ".join(f'"{field}" VARCHAR' for field in fields.split())
        db.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" (feed_id VARCHAR, {definitions})'
        )
    db.execute(
        "CREATE TABLE IF NOT EXISTS feeds (feed_id VARCHAR PRIMARY KEY, archive VARCHAR, source_sha256 VARCHAR, rows BIGINT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS extraction (version INTEGER, raw_directory VARCHAR)"
    )


@traced
def convert_archive(path, feed_id, db):
    """Load selected columns using vectorized CSV ingestion, then filter references."""
    with ZipFile(path) as archive, tempfile.TemporaryDirectory() as directory:
        members = {}
        for entry in archive.infolist():
            name = Path(entry.filename).name.lower()
            if name.endswith(".txt") and name[:-4] in COLUMNS and not entry.is_dir():
                table = name[:-4]
                if table in members:
                    raise ValueError(f"Duplicate GTFS table: {name}")
                members[table] = entry.filename
        if not REQUIRED.keys() <= members.keys():
            raise ValueError("Missing required routes/trips/stops/stop_times tables")
        if not {"calendar", "calendar_dates"} & members.keys():
            raise ValueError("Missing service calendar")
        for table, fields in COLUMNS.items():
            db.execute(
                f'CREATE OR REPLACE TEMP TABLE "stage_{table}" AS SELECT * EXCLUDE(feed_id) FROM "{table}" LIMIT 0'
            )
            if table not in members:
                continue
            target = Path(directory) / f"{table}.txt"
            with archive.open(members[table]) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            with target.open(encoding="utf-8-sig", newline="") as source:
                header = next(csv.reader(source), [])
            if len(header) != len(set(header)) or not REQUIRED.get(table, set()) <= set(
                header
            ):
                raise ValueError(f"Invalid columns in {table}")
            selected = [field for field in fields.split() if field in header]
            if selected:
                projection = ", ".join(f'"{field}"' for field in selected)
                db.execute(
                    f"INSERT INTO \"stage_{table}\" BY NAME SELECT {projection} FROM read_csv(?, header=true, delim=',', all_varchar=true, strict_mode=true)",
                    [str(target)],
                )
            LOGGER.info("Read %s :: %s", feed_id, table)
        db.execute(f"DELETE FROM stage_routes WHERE NOT coalesce({MODE_SQL}, false)")
        db.execute(
            "DELETE FROM stage_trips WHERE route_id NOT IN (SELECT route_id FROM stage_routes) OR route_id IS NULL"
        )
        db.execute(
            "DELETE FROM stage_stop_times WHERE trip_id NOT IN (SELECT trip_id FROM stage_trips) OR trip_id IS NULL"
        )
        # Include station ancestors even if they have no stop_times themselves.
        db.execute("""DELETE FROM stage_stops WHERE stop_id NOT IN (
            WITH RECURSIVE used(id) AS (
                SELECT stop_id FROM stage_stop_times
                UNION
                SELECT s.parent_station FROM stage_stops s JOIN used u ON s.stop_id=u.id WHERE s.parent_station IS NOT NULL
            ) SELECT id FROM used) OR stop_id IS NULL""")
        for table in ("calendar", "calendar_dates"):
            db.execute(
                f"DELETE FROM stage_{table} WHERE service_id NOT IN (SELECT service_id FROM stage_trips) OR service_id IS NULL"
            )
        db.execute(
            "DELETE FROM stage_frequencies WHERE trip_id NOT IN (SELECT trip_id FROM stage_trips) OR trip_id IS NULL"
        )
        for prefix in ("from", "to"):
            for kind, table in (
                ("stop", "stops"),
                ("route", "routes"),
                ("trip", "trips"),
            ):
                key = f"{prefix}_{kind}_id"
                db.execute(
                    f"DELETE FROM stage_transfers WHERE {key} IS NOT NULL AND {key} NOT IN (SELECT {kind}_id FROM stage_{table})"
                )
        if db.execute("SELECT count(*) FROM stage_routes").fetchone()[0] == 0:
            db.execute("DELETE FROM stage_agency")
            db.execute("DELETE FROM stage_feed_info")
        else:
            db.execute(
                "DELETE FROM stage_agency WHERE agency_id NOT IN (SELECT agency_id FROM stage_routes) AND NOT EXISTS (SELECT 1 FROM stage_routes WHERE agency_id IS NULL)"
            )
        rows = 0
        for table in COLUMNS:
            db.execute(f'DELETE FROM "{table}" WHERE feed_id=?', [feed_id])
            db.execute(
                f'INSERT INTO "{table}" SELECT ?, * FROM "stage_{table}"', [feed_id]
            )
            count = db.execute(f'SELECT count(*) FROM "stage_{table}"').fetchone()[0]
            rows += count
            LOGGER.info("Retained %s :: %s rows=%d", feed_id, table, count)
        return rows


@traced
def prepare_archive(job, directory):
    """A worker owns its connection and files; it never writes shared checkpoints."""
    path, feed_id, fingerprint = job
    shard = Path(directory) / (hashlib.sha256(feed_id.encode()).hexdigest() + ".duckdb")
    try:
        with duckdb.connect(
            str(shard), config={"threads": 1, "memory_limit": "256MB"}
        ) as worker:
            initialize(worker)
            rows = convert_archive(path, feed_id, worker)
            if digest(path) != fingerprint:
                raise ValueError("Archive changed during extraction")
        return job, shard, rows, None
    except Exception as error:
        return job, shard, 0, error


@traced
def merge_archive(db, shard, feed_id, relative, fingerprint, rows):
    # ATTACH is outside the transaction; only the coordinator writes staging.
    quoted_path = str(shard).replace("'", "''")
    db.execute(f"ATTACH '{quoted_path}' AS prepared (READ_ONLY)")
    try:
        db.execute("BEGIN TRANSACTION")
        try:
            for table in COLUMNS:
                db.execute(f'DELETE FROM "{table}" WHERE feed_id=?', [feed_id])
                db.execute(f'INSERT INTO "{table}" SELECT * FROM prepared."{table}"')
            db.execute(
                "INSERT OR REPLACE INTO feeds VALUES (?, ?, ?, ?)",
                [feed_id, relative, fingerprint, rows],
            )
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    finally:
        db.execute("DETACH prepared")


@traced
def combine(raw_directory: Path, output_path: Path, workers: int = DEFAULT_WORKERS):
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
    raw_directory, output_path = (
        raw_directory.expanduser().resolve(),
        output_path.expanduser().resolve(),
    )
    if not raw_directory.is_dir():
        raise ValueError(f"Raw directory does not exist: {raw_directory}")
    archives = sorted(
        p
        for p in raw_directory.rglob("*")
        if p.is_file() and p.suffix.lower() == ".zip"
    )
    if output_path in archives:
        raise ValueError("Output must not replace an input archive")
    if output_path.suffix.lower() != ".duckdb":
        raise ValueError("Output must have a .duckdb extension")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging = output_path.with_suffix(".staging.duckdb")
    with output_path.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another conversion is using this output") from None
        failed = resumed = 0
        with duckdb.connect(str(staging), config={"threads": 1}) as db:
            initialize(db)
            context = db.execute("SELECT * FROM extraction").fetchall()
            if context and context != [(1, str(raw_directory))]:
                raise ValueError(
                    "Checkpoint source/version mismatch; use another output path"
                )
            if not context:
                db.execute("INSERT INTO extraction VALUES (1, ?)", [str(raw_directory)])
            selected = set()
            LOGGER.info("Found %d archives", len(archives))
            jobs = []
            for path in archives:
                relative = path.relative_to(raw_directory).as_posix()
                feed_id = Path(relative).with_suffix("").as_posix()
                if feed_id in selected:
                    raise ValueError("Multiple archives have the same feed identifier")
                selected.add(feed_id)
                fingerprint = digest(path)
                previous = db.execute(
                    "SELECT source_sha256 FROM feeds WHERE feed_id=?", [feed_id]
                ).fetchone()
                if previous == (fingerprint,):
                    resumed += 1
                else:
                    jobs.append((path, feed_id, fingerprint))
            LOGGER.info("Extracting %d feeds with %d workers", len(jobs), workers)
            with tempfile.TemporaryDirectory(prefix="gtfs-workers-") as directory:
                with ThreadPoolExecutor(
                    max_workers=workers, thread_name_prefix="gtfs"
                ) as pool:
                    # Bound both submitted work and completed shards awaiting merge.
                    results = pool.map(
                        lambda item: item[1].run(prepare_archive, item[0], directory),
                        ((job, copy_context()) for job in jobs),
                        buffersize=workers,
                    )
                    for (path, feed_id, fingerprint), shard, rows, error in results:
                        relative = path.relative_to(raw_directory).as_posix()
                        try:
                            if error is not None:
                                raise error
                            if digest(path) != fingerprint:
                                raise ValueError(
                                    "Archive changed before checkpoint commit"
                                )
                            merge_archive(
                                db, shard, feed_id, relative, fingerprint, rows
                            )
                            LOGGER.info(
                                "Checkpoint committed: %s rows=%d", feed_id, rows
                            )
                        except Exception as error:
                            failed += 1
                            LOGGER.error(
                                "Archive failed: %s (%s)",
                                relative,
                                type(error).__name__,
                            )
                        finally:
                            shard.unlink(missing_ok=True)
            if failed:
                raise ValueError(
                    f"{failed} archives failed; completed feeds saved in {staging}. Rerun to resume"
                )
            for (feed_id,) in db.execute("SELECT feed_id FROM feeds").fetchall():
                if feed_id not in selected:
                    for table in (*COLUMNS, "feeds"):
                        db.execute(f'DELETE FROM "{table}" WHERE feed_id=?', [feed_id])
            total = db.execute("SELECT coalesce(sum(rows),0) FROM feeds").fetchone()[0]
            db.execute("CHECKPOINT")
        # Publish only a closed, complete database. The staging DB remains resumable.
        temporary = output_path.with_suffix(".duckdb.part")
        try:
            shutil.copyfile(staging, temporary)
            with temporary.open("rb") as source:
                os.fsync(source.fileno())
            temporary.replace(output_path)
        finally:
            temporary.unlink(missing_ok=True)
        LOGGER.info(
            "Conversion completed: feeds=%d rows=%d resumed=%d",
            len(archives),
            total,
            resumed,
        )
        return {
            "output": str(output_path),
            "feeds": len(archives),
            "rows": total,
            "resumed": resumed,
        }


@cli_entrypoint
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_DIRECTORY / "raw")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_DIRECTORY / "schedules.duckdb"
    )
    parser.add_argument(
        "--log-level",
        choices=("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=None,
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Parallel feed workers (default: up to 4; use 1 for serial extraction)",
    )
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")
    configure_logging(level=args.log_level)
    try:
        result = combine(args.raw_dir, args.output, workers=args.workers)
    except Exception as error:
        LOGGER.error("Schedule conversion failed (%s)", type(error).__name__)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
