"""Fit four independent, deterministic empirical price models from local evidence."""

import argparse
from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext
import hashlib
import json
import logging
from pathlib import Path
from statistics import median
import sys
import tempfile

import duckdb
import networkx as nx

from backend.application.telemetry import event, traced
from backend.infrastructure.logging import cli_entrypoint
from backend.domain.travel import TransportType
from backend.infrastructure.catalog.graph_snapshot import load_base_graph
from backend.infrastructure.pricing.distance import (
    graph_distances,
    resolve_distance,
    fit_distance,
    predict_distance,
    scope,
)
from backend.infrastructure.catalog.static_transport import CityIndex, coordinates
from backend.infrastructure.fixtures.extract_pricing import (
    DEFAULT_DIRECTORY,
    country,
    rows,
)
from backend.infrastructure.pricing.download import digest
from backend.infrastructure.pricing.forecast import DEFAULT_ARTIFACT, route, lead_bucket


def summary(values, lows=None, highs=None, dates=()):
    values = list(values)
    dates = sorted(d for d in dates if d)
    return dict(
        value=str(median(values)),
        lower=str(min(lows if lows is not None else values)),
        upper=str(max(highs if highs is not None else values)),
        samples=len(values),
        evidence_start=dates[0] if dates else None,
        evidence_end=dates[-1] if dates else None,
    )


def fit(points, cell=None):
    grouped = defaultdict(list)
    for point in points:
        grouped[point["route"]].append(point)
    entries = {}
    for identity, group in sorted(grouped.items()):
        baseline = summary(
            [p["price"] for p in group], dates=[p.get("date") for p in group]
        )
        entry = dict(baseline=baseline)
        if cell:
            cells = defaultdict(list)
            for p in group:
                cells[p[cell]].append(p)
            entry["months" if cell == "month" else "lead"] = {
                c: summary(
                    [p["price"] for p in values], dates=[p.get("date") for p in values]
                )
                for c, values in sorted(cells.items())
            }
        entries[identity] = entry
    return entries


def evaluate(train, test, cell=None, distances=None):
    entries = fit(train, cell)
    distance_model = fit_distance(entries, distances or {})
    distance_units = 0
    fallback_errors, fallback_baseline_errors = [], []
    scope_values = defaultdict(list)
    for identity, entry in entries.items():
        if (distances or {}).get(identity) is not None:
            scope_values[scope(identity)].append(Decimal(entry["baseline"]["value"]))
    errors, baseline_errors = [], []
    for point in test:
        entry = entries.get(point["route"])
        if not entry:
            selected = predict_distance(
                distance_model["groups"].get(scope(point["route"])),
                (distances or {}).get(point["route"]),
            )
            if selected is None:
                continue
            distance_units += 1
            fallback_errors.append(abs(Decimal(selected["value"]) - point["price"]))
            fallback_baseline_errors.append(
                abs(median(scope_values[scope(point["route"])]) - point["price"])
            )
            baseline = None
        else:
            baseline = Decimal(entry["baseline"]["value"])
            selected = (
                entry.get("lead", {}).get(point.get("lead"), entry["baseline"])
                if cell == "lead"
                else entry["baseline"]
            )
        errors.append(abs(Decimal(selected["value"]) - point["price"]))
        if baseline is not None:
            baseline_errors.append(abs(baseline - point["price"]))
    return dict(
        test_units=len(test),
        supported_units=len(errors),
        distance_fallback_units=distance_units,
        route_baseline_supported_units=len(baseline_errors),
        distance_fallback_mae_eur=(
            str(sum(fallback_errors) / len(fallback_errors))
            if fallback_errors
            else None
        ),
        same_fallback_units_scope_median_mae_eur=(
            str(sum(fallback_baseline_errors) / len(fallback_baseline_errors))
            if fallback_baseline_errors
            else None
        ),
        mae_eur=str(sum(errors) / len(errors)) if errors else None,
        route_baseline_mae_eur=(
            str(sum(baseline_errors) / len(baseline_errors))
            if baseline_errors
            else None
        ),
    )


def station_cities(directory):
    graph = nx.MultiDiGraph()
    cities_path = directory / "cities/Cities.csv"
    stations_path = directory / "train-stations/train_stations_europe.csv"
    if not cities_path.exists() or not stations_path.exists():
        return {}
    for r in rows(cities_path):
        point = coordinates(r["latitude"], r["longitude"])
        if point:
            graph.add_node(
                (r["city"], country(r["country"])),
                name=r["city"],
                country=country(r["country"]),
                **point,
            )
    index = CityIndex(graph)
    candidates = defaultdict(set)
    for r in rows(stations_path):
        code = r.get("uic", "")
        if not code or code == "NA":
            continue
        nearest = index.nearest(
            coordinates(r.get("latitude"), r.get("longitude")), country=r["country"]
        )
        if nearest:
            candidates[code[:7]].add(nearest[0])
    return {
        code: next(iter(names)) for code, names in candidates.items() if len(names) == 1
    }


def ferry_entries(db):
    # A fare_id with any geographic constraint is never interpreted as route-flat.
    records = db.execute("""WITH rules AS (
        SELECT source_id,raw_json->>'fare_id' fare_id,raw_json->>'route_id' route_id,
          coalesce(raw_json->>'origin_id','')<>'' OR coalesce(raw_json->>'destination_id','')<>''
          OR coalesce(raw_json->>'contains_id','')<>'' constrained
        FROM gtfs_fare_records WHERE table_name='fare_rules'
    ), safe AS (
        SELECT source_id,fare_id FROM rules GROUP BY ALL HAVING NOT bool_or(constrained)
    ), routes AS (
        SELECT source_id,raw_json->>'route_id' route_id,
          min(try_cast(raw_json->>'route_type' AS INT)) route_type
        FROM gtfs_context WHERE table_name='routes' GROUP BY ALL
        HAVING count(DISTINCT raw_json->>'route_type')=1
    ), raw_fares AS (
        SELECT source_id,raw_json->>'fare_id' fare_id,
          try_cast(raw_json->>'price' AS DECIMAL(38,18)) price,
          raw_json->>'currency_type' currency
        FROM gtfs_fare_records WHERE table_name='fare_attributes'
    ), fares AS (
        SELECT source_id,fare_id,min(price) price,min(currency) currency
        FROM raw_fares GROUP BY source_id,fare_id
        HAVING count(DISTINCT currency)=1 AND count(DISTINCT price)=1
        AND bool_and(price IS NOT NULL AND price>=0 AND currency IS NOT NULL)
    ) SELECT DISTINCT r.source_id,r.route_id,f.fare_id,f.price
      FROM rules r JOIN safe s USING(source_id,fare_id)
      JOIN fares f USING(source_id,fare_id) JOIN routes t USING(source_id,route_id)
      WHERE f.currency='EUR' AND f.price>=0 AND (t.route_type=4 OR t.route_type=1200
      OR t.route_type BETWEEN 1000 AND 1099) ORDER BY 1,2,3,4""").fetchall()
    grouped = defaultdict(list)
    for source, route_id, fare_id, price in records:
        grouped[
            json.dumps(
                [source.removeprefix("gtfs:"), route_id, "", ""], separators=(",", ":")
            )
        ].append(price)
    return {
        identity: dict(baseline=summary(prices))
        for identity, prices in sorted(grouped.items())
    }


def blocked_ferry_routes(db):
    # Distance generalization must not bypass products explicitly excluded for
    # zone constraints, unknown/conflicting prices or non-EUR currencies.
    records = db.execute("""WITH rules AS (
        SELECT source_id,raw_json->>'fare_id' fare_id,raw_json->>'route_id' route_id,
          coalesce(raw_json->>'origin_id','')<>'' OR coalesce(raw_json->>'destination_id','')<>''
          OR coalesce(raw_json->>'contains_id','')<>'' constrained
        FROM gtfs_fare_records WHERE table_name='fare_rules'
    ), unsafe AS (
        SELECT source_id,fare_id FROM rules GROUP BY source_id,fare_id HAVING bool_or(constrained)
        UNION
        SELECT source_id,raw_json->>'fare_id' fare_id FROM gtfs_fare_records
        WHERE table_name='fare_attributes' GROUP BY source_id,fare_id
        HAVING bool_or(coalesce(raw_json->>'currency_type','')<>'EUR')
          OR count(DISTINCT raw_json->>'currency_type')<>1
          OR count(DISTINCT raw_json->>'price')<>1
          OR bool_or(try_cast(raw_json->>'price' AS DECIMAL(38,18)) IS NULL)
          OR min(try_cast(raw_json->>'price' AS DECIMAL(38,18)))<0
    ), ferries AS (
        SELECT DISTINCT source_id,raw_json->>'route_id' route_id FROM gtfs_context
        WHERE table_name='routes' AND (try_cast(raw_json->>'route_type' AS INT) IN (4,1200)
        OR try_cast(raw_json->>'route_type' AS INT) BETWEEN 1000 AND 1099)
    ) SELECT DISTINCT r.source_id,r.route_id FROM rules r JOIN unsafe u USING(source_id,fare_id)
      JOIN ferries f USING(source_id,route_id) ORDER BY 1,2""").fetchall()
    return [
        json.dumps(
            [source.removeprefix("gtfs:"), route_id, "", ""], separators=(",", ":")
        )
        for source, route_id in records
    ]


@traced
def train(
    database=DEFAULT_DIRECTORY / "pricing/schengen_pricing.duckdb",
    output=DEFAULT_ARTIFACT,
    information_date=None,
    fixtures_dir=DEFAULT_DIRECTORY,
    graph_path="auto",
):
    database, output, fixtures_dir = map(
        lambda p: Path(p).expanduser().resolve(), (database, output, fixtures_dir)
    )
    if not database.is_file():
        raise ValueError("Pricing DuckDB not found; run just extract-pricing")
    if output == database or output.suffix != ".json":
        raise ValueError("Model output must be a separate JSON artifact")
    graph_path = (
        fixtures_dir / "base_graph.pickle"
        if graph_path == "auto"
        else (
            Path(graph_path).expanduser().resolve() if graph_path is not None else None
        )
    )
    if graph_path is not None and not graph_path.is_file():
        raise ValueError(
            "Base graph not found; run just build-base-graph or pass --graph"
        )
    graph_sha = digest(graph_path) if graph_path else None
    graph_features = (
        graph_distances(load_base_graph(graph_path))
        if graph_path
        else dict(edges={}, ferry_routes={}, diagnostics={})
    )
    reference_hashes = {
        str(p.relative_to(fixtures_dir)): digest(p)
        for p in (
            fixtures_dir / "cities/Cities.csv",
            fixtures_dir / "train-stations/train_stations_europe.csv",
        )
        if p.is_file()
    }
    fingerprint = digest(database)
    with duckdb.connect(str(database), read_only=True, config={"threads": 1}) as db:
        extraction = json.loads(
            db.execute("SELECT metadata FROM extraction").fetchone()[0]
        )
        snapshot_date = date.fromisoformat(extraction["extracted_at"][:10])
        information_date = information_date or snapshot_date
        if information_date < snapshot_date:
            raise ValueError(
                "Cannot train with an information date earlier than the extracted snapshot"
            )
        points = []
        for origin, destination, oc, dc, month, price in db.execute(
            """SELECT origin,destination,
            origin_country,destination_country,departure_month,price FROM pricing
            WHERE mode='air' AND kind='route_month_aggregate' AND currency='EUR'
            AND price IS NOT NULL AND price>=0 ORDER BY source_id,row_number"""
        ).fetchall():
            date.fromisoformat(month + "-01")
            points.append(
                dict(
                    route=route(origin, destination, oc, dc),
                    month=month,
                    price=price,
                    date=snapshot_date.isoformat(),
                )
            )
        for point in points:
            distance, _ = resolve_distance(graph_features, "PLANES", point["route"])
            if distance is not None:
                graph_features.setdefault("derived", {}).setdefault("PLANES", {})[
                    point["route"]
                ] = distance
        # A cross-month diagnostic, not an as-of booking-time backtest.
        latest = {}
        for p in points:
            latest[p["route"]] = max(latest.get(p["route"], ""), p["month"])
        held = [p for p in points if p["month"] == latest[p["route"]]]
        training = [p for p in points if p["month"] != latest[p["route"]]]
        flight_metrics = dict(
            split="last_departure_month_per_route",
            limitation="Aggregated collection timestamps unavailable; this is not historical as-of validation.",
            **evaluate(
                training,
                held,
                "month",
                dict(
                    graph_features["edges"].get("PLANES", {}),
                    **graph_features.get("derived", {}).get("PLANES", {}),
                ),
            ),
        )
        flights = fit(points, "month")
        bus_groups = defaultdict(list)
        for origin, destination, oc, dc, price, observed, departure, raw in db.execute(
            """SELECT
            origin,destination,origin_country,destination_country,price,observed_date,departure_date,raw_json
            FROM pricing WHERE mode='bus' AND currency='EUR' AND price>=0
            AND try_cast(raw_json->>'seat' AS INT)=1 ORDER BY source_id,row_number"""
        ).fetchall():
            observed, departure = date.fromisoformat(observed[:10]), date.fromisoformat(
                departure[:10]
            )
            if observed > information_date or departure < observed:
                continue
            raw = json.loads(raw)
            identity = route(origin, destination, oc, dc)
            bus_groups[
                (
                    identity,
                    observed.isoformat(),
                    departure.isoformat(),
                    str(raw.get("dep")),
                )
            ].append(price)
        bus = [
            dict(
                route=r,
                date=observed,
                price=median(prices),
                lead=lead_bucket(
                    (date.fromisoformat(departure) - date.fromisoformat(observed)).days
                ),
            )
            for (r, observed, departure, dep), prices in sorted(bus_groups.items())
        ]
        bus_distances = dict(graph_features["edges"].get("BUSSES", {}))
        for point in bus:
            distance, _ = resolve_distance(graph_features, "BUSSES", point["route"])
            if distance is not None:
                bus_distances[point["route"]] = distance
        days = sorted({p["date"] for p in bus})
        cutoff = days[max(0, int(len(days) * 0.8))] if len(days) > 1 else None
        bus_metrics = dict(
            split="latest_query_dates_service_grouped",
            cutoff=cutoff,
            **evaluate(
                [p for p in bus if cutoff and p["date"] < cutoff],
                [p for p in bus if cutoff and p["date"] >= cutoff],
                "lead",
                bus_distances,
            ),
        )
        buses = fit(bus, "lead")
        station_map = station_cities(fixtures_dir)
        rail_groups = defaultdict(list)
        for origin, destination, oc, dc, low, high, raw in db.execute(
            """SELECT origin,destination,
            origin_country,destination_country,price_min,price_max,raw_json FROM pricing
            WHERE mode='rail' AND kind='published_tariff_bounds' AND currency='EUR'
            AND price_min>=0 AND price_max>=price_min AND raw_json->>'classe'='2'
            AND raw_json->>'profil_tarifaire'='Tarif Normal' ORDER BY source_id,row_number"""
        ).fetchall():
            raw = json.loads(raw)
            origin = station_map.get(
                str(raw.get("gare_origine_code_uic", ""))[:7], origin
            )
            destination = station_map.get(
                str(raw.get("gare_destination_code_uic", ""))[:7], destination
            )
            with localcontext() as ctx:
                ctx.prec = 40
                midpoint = (low + high) / 2
            rail_groups[route(origin, destination, oc, dc)].append(
                (midpoint, low, high)
            )
        rails = {
            r: dict(
                baseline=summary(
                    [p[0] for p in values],
                    [p[1] for p in values],
                    [p[2] for p in values],
                    [snapshot_date.isoformat()],
                )
            )
            for r, values in sorted(rail_groups.items())
        }
        ferries = ferry_entries(db)
        blocked_ferries = blocked_ferry_routes(db)
        provenance = db.execute(
            "SELECT source_id,sha256,metadata,status FROM sources ORDER BY source_id"
        ).fetchall()
    if graph_path and digest(graph_path) != graph_sha:
        raise ValueError("Base graph changed during price model training")
    if any(digest(fixtures_dir / p) != sha for p, sha in reference_hashes.items()):
        raise ValueError("Station/city reference changed during training")
    if digest(database) != fingerprint:
        raise ValueError("Pricing database changed during training")
    mode_fit_distances = {}
    for mode, entries in [("PLANES", flights), ("TRAINS", rails), ("BUSSES", buses)]:
        mode_fit_distances[mode] = {}
        for identity in entries:
            distance, _ = resolve_distance(graph_features, mode, identity)
            if distance is not None:
                mode_fit_distances[mode][identity] = distance
    # Training-only derived values need not duplicate the serving city-coordinate index.
    graph_features.pop("derived", None)
    models = {}
    for mode, entries, validation in (
        (TransportType.PLANES, flights, flight_metrics),
        (TransportType.BUSSES, buses, bus_metrics),
        (
            TransportType.TRAINS,
            rails,
            dict(
                status="not_available",
                reason="Static tariff bounds are not observed ticket prices",
            ),
        ),
        (
            TransportType.FERRIES,
            ferries,
            dict(
                status="not_available",
                reason="Published products are not observed ticket prices",
            ),
        ),
    ):
        distances = (
            graph_features["ferry_routes"]
            if mode == TransportType.FERRIES
            else mode_fit_distances[mode.value]
        )
        distance_model = fit_distance(
            entries, distances, ferry=mode == TransportType.FERRIES
        )
        if mode == TransportType.FERRIES:
            distance_model["blocked_routes"] = blocked_ferries
        distance_model["target"] = {
            TransportType.PLANES: "advertised_route_month_median",
            TransportType.BUSSES: "advertised_first_seat_route_median",
            TransportType.TRAINS: "published_tariff_midpoint",
            TransportType.FERRIES: "published_flat_ferry_product",
        }[mode]
        identity = hashlib.sha256(
            json.dumps(
                dict(entries=entries, distance=distance_model, graph_sha256=graph_sha),
                sort_keys=True,
            ).encode()
        ).hexdigest()[:16]
        models[mode.value] = dict(
            model_id=f"{mode.value.lower()}-distance-v2:{identity}",
            distance=distance_model,
            entries=entries,
            validation=validation,
            routes=len(entries),
        )
    artifact = dict(
        format="explorer.price_forecasts",
        version=2,
        models=models,
        distance_index=graph_features,
        metadata=dict(
            information_date=information_date.isoformat(),
            reference_sha256=reference_hashes,
            graph_sha256=graph_sha,
            graph_path=str(graph_path) if graph_path else None,
            distance_policy="Graph edge distance preferred, otherwise the same great-circle metric from unique graph city endpoints; price inference does not establish a service.",
            database_sha256=fingerprint,
            sources=[
                dict(source_id=s, sha256=sha, metadata=json.loads(meta), status=status)
                for s, sha, meta, status in provenance
            ],
            station_reference_sha256=(
                digest(fixtures_dir / "train-stations/train_stations_europe.csv")
                if (fixtures_dir / "train-stations/train_stations_europe.csv").exists()
                else None
            ),
            forecast_status="estimated_not_bookable",
            traveler_policy="One-adult estimate multiplied by traveler count; no group discounts",
            exclusions="No synthetic labels, overlapping whole-route air aggregates, seat ladders, or constrained GTFS products",
        ),
    )
    # Verify the artifact before replacing any previous serving artifact.
    from backend.infrastructure.pricing.forecast import ForecastService

    ForecastService(artifact)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=output.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(artifact, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.close()
            temporary.replace(output)
            event(logging.getLogger("backend.infrastructure.pricing.train"),
                  "forecast.artifact_published", level=logging.INFO,
                  model_count=len(artifact["models"]))
        finally:
            temporary.unlink(missing_ok=True)
    return dict(
        output=str(output),
        information_date=information_date.isoformat(),
        models={
            m: dict(
                routes=v["routes"],
                validation=v["validation"],
                distance_mapped_routes=v["distance"]["mapped_routes"],
                distance_groups=len(v["distance"]["groups"]),
                enabled_distance_groups=sum(
                    g["enabled"] for g in v["distance"]["groups"].values()
                ),
                distance_validation={
                    scope: g["validation"]
                    for scope, g in v["distance"]["groups"].items()
                },
            )
            for m, v in models.items()
        },
    )


@cli_entrypoint
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DIRECTORY / "pricing/schengen_pricing.duckdb",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--fixtures-dir", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--information-date", type=date.fromisoformat)
    parser.add_argument(
        "--graph",
        type=Path,
        help="Local base graph snapshot (default: fixtures-dir/base_graph.pickle)",
    )
    args = parser.parse_args(argv)
    try:
        print(
            json.dumps(
                train(
                    args.database,
                    args.output,
                    args.information_date,
                    args.fixtures_dir,
                    args.graph or "auto",
                )
            )
        )
    except (OSError, ValueError, KeyError, duckdb.Error) as error:
        print(f"Price model training failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
