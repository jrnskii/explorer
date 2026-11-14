"""Extract local Schengen pricing into an independently published DuckDB database."""

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import io
import json
import shutil
from pathlib import Path
import sys
import tempfile
import unicodedata
import zipfile

import duckdb
import pandas as pd

from backend.infrastructure.pricing.download import SCHENGEN, digest

DEFAULT_DIRECTORY = Path(__file__).resolve().parent / "data"
COUNTRIES = dict(
    zip(
        "Austria|Belgium|Bulgaria|Croatia|Czech Republic|Denmark|Estonia|Finland|France|Germany|Greece|Hungary|Iceland|Italy|Latvia|Liechtenstein|Lithuania|Luxembourg|Malta|Netherlands|Norway|Poland|Portugal|Romania|Slovakia|Slovenia|Spain|Sweden|Switzerland".split(
            "|"
        ),
        SCHENGEN,
        strict=True,
    )
)
COUNTRIES["Czechia"] = "CZ"
ALIASES = {
    "brunswick": "braunschweig",
    "hanover": "hannover",
    "nuremberg": "nurnberg",
    "munich": "munchen",
    "milan": "milano",
    "tuebingen": "tubingen",
    "duesseldorf": "dusseldorf",
    "cracow": "krakow",
}
FARE_TABLES = set(
    "fare_attributes fare_rules fare_products fare_leg_rules fare_leg_join_rules fare_transfer_rules fare_media rider_categories timeframes areas stop_areas networks route_networks".split()
)

CONTEXT_COLUMNS = {
    "agency": "agency_id agency_name agency_timezone",
    "routes": "route_id agency_id route_type route_short_name route_long_name network_id",
    "stops": "stop_id stop_name zone_id parent_station stop_lat stop_lon stop_timezone",
    "calendar": "service_id monday tuesday wednesday thursday friday saturday sunday start_date end_date",
    "calendar_dates": "service_id date exception_type",
}


def key(value):
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(value)).casefold() if c.isalnum()
    )


def country(value):
    return COUNTRIES.get(value, value)


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        yield from csv_records(stream)


def csv_records(stream):
    reader = csv.DictReader(stream)
    names = reader.fieldnames
    if not names or len(names) != len(set(names)):
        raise ValueError("CSV must have unique named columns")
    for row in reader:
        if None in row:
            raise ValueError("CSV row has more values than columns")
        yield row


class Locations:
    """Exact normalized matches only; ambiguous names never pick the first result."""

    def __init__(self, directory):
        self.cities = defaultdict(set)
        self.airports = defaultdict(set)
        self.stations = defaultdict(set)
        self.uic = defaultdict(set)
        self.references = []
        self.fingerprints = {}
        p = directory / "cities/Cities.csv"
        if p.exists():
            self.references.append(p)
            self.fingerprints[p] = digest(p)
            for r in rows(p):
                self.cities[key(r["city"])].add(country(r["country"]))
        p = directory / "airline_routes.json"
        if not p.exists():
            p = directory / "airlines/airline_routes.json"
        if p.exists():
            self.references.append(p)
            self.fingerprints[p] = digest(p)
            for code, r in json.loads(p.read_text()).items():
                c = r["country_code"]
                # Explicitly exclude overseas locations classified outside Europe.
                if c in SCHENGEN and r.get("continent") not in (None, "EU"):
                    c = "outside_schengen_territory"
                self.airports[key(code)].add(c)
                self.airports[key(r["city_name"])].add(c)
        p = directory / "train-stations/train_stations_europe.csv"
        if p.exists():
            self.references.append(p)
            self.fingerprints[p] = digest(p)
            for r in rows(p):
                c = r["country"]
                for name in (r["name"], r.get("name_norm", "")):
                    if name:
                        self.stations[key(name)].add(c)
                code = r.get("uic", "")
                if code and code != "NA":
                    # Seven-digit catalogue UIC omits the eighth check digit.
                    self.uic[code[:7]].add(c)

    def resolve(self, name, uic=None, rail=False, air=False):
        if uic:
            found = self.uic.get(str(uic)[:7], set())
            if found:
                return next(iter(found)) if len(found) == 1 else None
        if air:
            found = self.airports.get(key(name), set())
            if found:
                return next(iter(found)) if len(found) == 1 else None
        elif str(name).casefold() in ALIASES:
            canonical = key(ALIASES[str(name).casefold()])
            found = self.stations.get(canonical, set()) or self.cities.get(
                canonical, set()
            )
            if found:
                return next(iter(found)) if len(found) == 1 else None
        found = (self.stations if rail else self.cities).get(key(name), set())
        if not found:
            found = self.cities.get(key(name), set()) or self.airports.get(
                key(name), set()
            )
        return next(iter(found)) if len(found) == 1 else None


def money(value):
    if value is None or str(value).strip().lower() in ("", "nan", "none", "null"):
        return None
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result >= Decimal("1e20"):
            raise ValueError("invalid_price")
        with localcontext() as ctx:
            ctx.prec = 38
            if result != result.quantize(Decimal("0.000000000000000001")):
                raise ValueError("price_precision_exceeds_18_decimals")
        return str(result)
    except InvalidOperation:
        raise ValueError("invalid_price") from None


def initialize(db):
    db.execute("""CREATE TABLE sources(source_id VARCHAR PRIMARY KEY, path VARCHAR,
        sha256 VARCHAR, metadata JSON, input_rows BIGINT, accepted_rows BIGINT,
        outside_rows BIGINT, review_rows BIGINT, status VARCHAR)""")
    db.execute(
        """CREATE TABLE pricing(source_id VARCHAR, row_number BIGINT, mode VARCHAR,
        kind VARCHAR, origin VARCHAR, destination VARCHAR, origin_country VARCHAR,
        destination_country VARCHAR, currency VARCHAR, price DECIMAL(38,18),
        price_min DECIMAL(38,18), price_max DECIMAL(38,18), p10 DECIMAL(38,18),
        observations BIGINT, departure_month VARCHAR, observed_date VARCHAR,
        departure_date VARCHAR, raw_json JSON)"""
    )
    db.execute(
        """CREATE TABLE review(source_id VARCHAR, row_number BIGINT, reason VARCHAR,
        origin VARCHAR, destination VARCHAR, raw_json JSON)"""
    )
    db.execute("""CREATE TABLE gtfs_fare_records(source_id VARCHAR, table_name VARCHAR,
        row_number BIGINT, raw_json JSON)""")
    db.execute(
        "CREATE TABLE gtfs_context(source_id VARCHAR, table_name VARCHAR, row_number BIGINT, raw_json JSON)"
    )
    db.execute(
        "CREATE TABLE country_summaries(source_id VARCHAR, country_code VARCHAR, median_eur DECIMAL(38,18), routes BIGINT, raw_json JSON)"
    )
    db.execute("CREATE TABLE extraction(metadata JSON)")


def insert(db, table, records):
    if not records:
        return
    frame = pd.DataFrame(records)
    db.register("incoming_batch", frame)
    try:
        db.execute(f"INSERT INTO {table} SELECT * FROM incoming_batch")
    finally:
        db.unregister("incoming_batch")


class Sink:
    def __init__(self, db, source_id, locations):
        self.db, self.source_id, self.locations = db, source_id, locations
        self.counts = [0, 0, 0, 0]
        self.accepted, self.review = [], []

    def add(
        self,
        raw,
        mode,
        kind,
        origin,
        destination,
        *,
        currency="EUR",
        price=None,
        low=None,
        high=None,
        p10=None,
        observations=None,
        month=None,
        observed=None,
        departure=None,
        origin_uic=None,
        destination_uic=None,
    ):
        self.counts[0] += 1
        number = self.counts[0]
        oc = self.locations.resolve(
            origin, origin_uic, mode in ("rail", "bus"), mode == "air"
        )
        dc = self.locations.resolve(
            destination, destination_uic, mode in ("rail", "bus"), mode == "air"
        )
        reason = None
        if (oc is not None and oc not in SCHENGEN) or (
            dc is not None and dc not in SCHENGEN
        ):
            self.counts[2] += 1
            return
        elif oc is None or dc is None:
            reason = "unresolved_or_ambiguous_endpoint"
        else:
            try:
                amounts = [money(v) for v in (price, low, high, p10)]
                if all(v is None for v in amounts):
                    raise ValueError("missing_price")
                if (
                    low is not None
                    and high is not None
                    and Decimal(amounts[1]) > Decimal(amounts[2])
                ):
                    raise ValueError("inverted_price_bounds")
                if observations is not None and (
                    int(observations) <= 0
                    or str(int(observations)) != str(observations)
                ):
                    raise ValueError("invalid_observation_count")
            except (ValueError, TypeError, InvalidOperation) as error:
                reason = (
                    str(error)
                    if str(error)
                    in (
                        "invalid_price",
                        "missing_price",
                        "inverted_price_bounds",
                        "price_precision_exceeds_18_decimals",
                        "invalid_observation_count",
                    )
                    else "invalid_value"
                )
        payload = json.dumps(raw, ensure_ascii=False, default=str, allow_nan=False)
        if reason:
            self.counts[3] += 1
            self.review.append(
                [self.source_id, number, reason, origin, destination, payload]
            )
        else:
            self.counts[1] += 1
            self.accepted.append(
                [
                    self.source_id,
                    number,
                    mode,
                    kind,
                    origin,
                    destination,
                    oc,
                    dc,
                    currency,
                    *amounts,
                    observations,
                    month,
                    observed,
                    departure,
                    payload,
                ]
            )
        if len(self.accepted) + len(self.review) >= 10000:
            self.flush()

    def flush(self):
        insert(self.db, "pricing", self.accepted)
        insert(self.db, "review", self.review)
        self.accepted.clear()
        self.review.clear()


def extract_file(path, sink):
    name = path.name
    if name in ("fares-by-month.csv", "routes.csv"):
        for r in rows(path):
            sink.add(
                r,
                "air",
                (
                    "route_month_aggregate"
                    if name.startswith("fares-")
                    else "route_aggregate"
                ),
                r["origin_city"],
                r["destination_city"],
                price=r["median_eur"],
                low=r["min_eur"],
                p10=r.get("p10_eur"),
                observations=r["observations"],
                month=r.get("departure_month"),
                observed=r.get("last_observed"),
            )
    elif name == "tariffs.json":
        for r in json.loads(path.read_text()):
            sink.add(
                r,
                "rail",
                "published_tariff_bounds",
                r["gare_origine"],
                r["gare_destination"],
                low=r["prix_minimum"],
                high=r["prix_maximum"],
                origin_uic=r["gare_origine_code_uic"],
                destination_uic=r["gare_destination_code_uic"],
            )
    elif path.suffix == ".dta":
        with pd.read_stata(path, chunksize=10000, convert_categoricals=False) as reader:
            for frame in reader:
                for r in frame.to_dict("records"):
                    # Preserve nulls and original labels without emitting JSON NaN.
                    r = {
                        k: (
                            None
                            if pd.isna(v)
                            else str(v) if isinstance(v, pd.Timestamp) else v
                        )
                        for k, v in r.items()
                    }
                    sink.add(
                        r,
                        "bus",
                        "advertised_seat_fare",
                        r["o"],
                        r["d"],
                        price=r["fare"],
                        observed=r["qdate"],
                        departure=r["ddate"],
                    )
    else:
        for r in rows(path):
            origin = r.get("origin", r.get("source_city"))
            destination = r.get("destination", r.get("destination_city"))
            if origin is None or destination is None or "price" not in r:
                raise ValueError(f"Unsupported pricing schema: {path.name}")
            sink.add(
                r,
                "rail",
                "historical_advertised_quote",
                origin,
                destination,
                price=r["price"],
                observed=r.get("insert_date"),
                departure=r.get("start_date", r.get("departure")),
            )
    sink.flush()


def source_metadata(pricing, name):
    path = pricing / "manifest.json"
    return (
        json.loads(path.read_text()).get("sources", {}).get(name, {})
        if path.exists()
        else {}
    )


def add_source(
    db,
    source_id,
    path,
    metadata,
    counts=(0, 0, 0, 0),
    status="extracted",
    fingerprint=None,
):
    db.execute(
        "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?)",
        [
            source_id,
            str(path),
            fingerprint or (digest(path) if path.is_file() else None),
            json.dumps(metadata),
            *counts,
            status,
        ],
    )


def extract_gtfs(directory, db):
    catalogue = directory / "mobilitydatabase/catalog.json"
    raw = directory / "mobilitydatabase/raw"
    if not catalogue.exists() or not raw.exists():
        return
    for feed in json.loads(catalogue.read_text()):
        codes = {loc.get("country_code") for loc in feed.get("locations", [])}
        if not codes.intersection(SCHENGEN):
            continue
        if Path(feed["id"]).name != feed["id"]:
            raise ValueError("Invalid GTFS feed identifier")
        path = raw / (feed["id"] + ".zip")
        if not path.exists():
            add_source(db, "gtfs:" + feed["id"], path, feed, status="missing_archive")
            continue
        initial_stat = path.stat()
        with zipfile.ZipFile(path) as archive:
            selected = [
                n
                for n in archive.namelist()
                if Path(n).stem in FARE_TABLES and n.endswith(".txt")
            ]
            if not selected:
                continue
            selected += [
                n
                for n in archive.namelist()
                if Path(n).stem in CONTEXT_COLUMNS and n.endswith(".txt")
            ]
            if len({Path(n).name for n in selected}) != len(selected):
                raise ValueError(f'Duplicate GTFS fare tables: {feed["id"]}')
            source_id = "gtfs:" + feed["id"]
            print(f"Extracting {source_id}", file=sys.stderr)
            count = 0
            for member in selected:
                batch = []
                with archive.open(member) as content, io.TextIOWrapper(
                    content, encoding="utf-8-sig", newline=""
                ) as stream:
                    for i, row in enumerate(csv_records(stream), 1):
                        table = Path(member).stem
                        if table in CONTEXT_COLUMNS:
                            row = {
                                k: row.get(k) for k in CONTEXT_COLUMNS[table].split()
                            }
                        batch.append([source_id, table, i, json.dumps(row)])
                        if table in FARE_TABLES:
                            count += 1
                        if len(batch) >= 10000:
                            insert(
                                db,
                                (
                                    "gtfs_context"
                                    if Path(member).stem in CONTEXT_COLUMNS
                                    else "gtfs_fare_records"
                                ),
                                batch,
                            )
                            batch.clear()
                insert(
                    db,
                    (
                        "gtfs_context"
                        if Path(member).stem in CONTEXT_COLUMNS
                        else "gtfs_fare_records"
                    ),
                    batch,
                )
            fingerprint = digest(path)
            if (path.stat().st_size, path.stat().st_mtime_ns) != (
                initial_stat.st_size,
                initial_stat.st_mtime_ns,
            ):
                raise ValueError("GTFS input changed during extraction")
            add_source(
                db,
                source_id,
                path,
                dict(
                    feed=feed,
                    scope="Schengen-related feed; endpoint scope unverified. Rules are not standalone payable fares.",
                ),
                (count, 0, 0, 0),
                "fare_rules_only",
                fingerprint=fingerprint,
            )


def extract_summaries(pricing, db):
    path = pricing / "flights/research__europe-countries.csv"
    if not path.exists():
        return
    source_id = "flights/" + path.name
    accepted = []
    total = 0
    for row in rows(path):
        total += 1
        code = country(row["country"])
        if code in SCHENGEN:
            accepted.append(
                [
                    source_id,
                    code,
                    money(row["median_eur"]),
                    int(row["routes"]),
                    json.dumps(row),
                ]
            )
    insert(db, "country_summaries", accepted)
    add_source(
        db,
        source_id,
        path,
        dict(
            source_metadata(pricing, "flights"),
            scope="Destination-country summary; origins may be outside Schengen; do not combine with route fares",
        ),
        (total, len(accepted), total - len(accepted), 0),
        "country_summary",
    )


def extract(directory=DEFAULT_DIRECTORY, output=None):
    directory = Path(directory).expanduser().resolve()
    output = (
        Path(output or directory / "pricing/schengen_pricing.duckdb")
        .expanduser()
        .resolve()
    )
    if not directory.is_dir():
        raise ValueError("Fixture directory does not exist")
    pricing = directory / "pricing"
    locations = Locations(directory)
    candidates = [
        p
        for name in (
            "flights/fares-by-month.csv",
            "flights/routes.csv",
            "sncf/tariffs.json",
            "flixbus/data_flixbus.dta",
        )
        if (p := pricing / name).exists()
    ]
    candidates += sorted((pricing / "renfe").glob("*.csv"))
    archives = sorted((pricing / "renfe").glob("*.zip"))
    if (
        not candidates
        and not archives
        and not (directory / "mobilitydatabase/catalog.json").exists()
    ):
        raise ValueError("No supported pricing inputs found")
    if output in candidates or output.suffix != ".duckdb":
        raise ValueError("Output must be a separate .duckdb file")
    if output.exists():
        try:
            with duckdb.connect(str(output), read_only=True) as existing:
                metadata = json.loads(
                    existing.execute("SELECT metadata FROM extraction").fetchone()[0]
                )
                if metadata.get("schema_version") != 1 or "route_scope" not in metadata:
                    raise ValueError("Unrecognized database")
        except Exception as error:
            raise ValueError(
                "Output already exists and is not a pricing extraction database"
            ) from error
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.with_suffix(".lock")
    # Exclusive lock also prevents two writers from publishing competing snapshots.
    with lock.open("x"):
        try:
            with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
                staging = Path(temporary) / "pricing.duckdb"
                with duckdb.connect(
                    str(staging), config={"threads": 1, "memory_limit": "512MB"}
                ) as db:
                    initialize(db)
                    for p in candidates:
                        source_id = p.relative_to(pricing).as_posix()
                        print(f"Extracting {source_id}", file=sys.stderr)
                        before = digest(p)
                        sink = Sink(db, source_id, locations)
                        extract_file(p, sink)
                        if digest(p) != before:
                            raise ValueError("Pricing input changed during extraction")
                        add_source(
                            db,
                            source_id,
                            p,
                            source_metadata(pricing, p.parent.name),
                            sink.counts,
                            fingerprint=before,
                        )
                    for archive_path in archives:
                        with zipfile.ZipFile(archive_path) as archive:
                            for member in archive.namelist():
                                if not member.endswith(".csv"):
                                    continue
                                # Stream to a controlled temporary name; never extract archive paths.
                                p = Path(temporary) / "renfe.csv"
                                with archive.open(member) as source, p.open(
                                    "wb"
                                ) as target:
                                    shutil.copyfileobj(source, target)
                                source_id = "renfe/" + archive_path.name + ":" + member
                                sink = Sink(db, source_id, locations)
                                extract_file(p, sink)
                                add_source(
                                    db,
                                    source_id,
                                    archive_path,
                                    dict(
                                        source_metadata(pricing, "renfe"), member=member
                                    ),
                                    sink.counts,
                                )
                    extract_summaries(pricing, db)
                    extract_gtfs(directory, db)
                    for p in sorted(pricing.glob("*/report.pdf")):
                        add_source(
                            db,
                            p.parent.name + "/report.pdf",
                            p,
                            source_metadata(pricing, p.parent.name),
                            status="report_only_not_parsed",
                        )
                    for p in locations.references:
                        if digest(p) != locations.fingerprints[p]:
                            raise ValueError(
                                "Location reference changed during extraction"
                            )
                        add_source(
                            db,
                            "reference:" + p.relative_to(directory).as_posix(),
                            p,
                            {},
                            status="location_reference",
                            fingerprint=locations.fingerprints[p],
                        )
                    db.execute(
                        "INSERT INTO extraction VALUES (?)",
                        [
                            json.dumps(
                                dict(
                                    schema_version=1,
                                    extracted_at=datetime.now(timezone.utc).isoformat(),
                                    fixture_directory=str(directory),
                                    schengen_countries=SCHENGEN,
                                    endpoint_resolution="Flight airport-city/IATA catalogue first; rail UIC/name; European coach station/city names and explicit language aliases. Ambiguity quarantined.",
                                    excluded_inputs={
                                        "airlines/airlines_flights_data.csv": "Indian domestic fares, outside Schengen",
                                        "airline_routes.json": "Location reference only; no observed pricing",
                                        "base_graph": "Synthetic weights are not observed fares",
                                        "research__booking-window.csv": "Global booking-window aggregate cannot be Schengen-filtered",
                                    },
                                    route_scope="Both resolved endpoints in Schengen; geography follows source country/territory metadata.",
                                    gtfs_scope="Schengen-related feed, not endpoint-verified",
                                    missing_sources=[
                                        s
                                        for s in ("flights", "sncf", "flixbus", "renfe")
                                        if not (pricing / s).exists()
                                    ],
                                )
                            )
                        ],
                    )
                    result = dict(
                        output=str(output),
                        pricing_rows=db.execute(
                            "SELECT count(*) FROM pricing"
                        ).fetchone()[0],
                        review_rows=db.execute(
                            "SELECT count(*) FROM review"
                        ).fetchone()[0],
                        country_summary_rows=db.execute(
                            "SELECT count(*) FROM country_summaries"
                        ).fetchone()[0],
                        gtfs_context_rows=db.execute(
                            "SELECT count(*) FROM gtfs_context"
                        ).fetchone()[0],
                        gtfs_fare_rows=db.execute(
                            "SELECT count(*) FROM gtfs_fare_records"
                        ).fetchone()[0],
                    )
                    db.execute("CHECKPOINT")
                staging.replace(output)
        finally:
            lock.unlink(missing_ok=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures-dir", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = extract(args.fixtures_dir, args.output)
    except Exception as error:
        print(f"Pricing extraction failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
