"""Static, fare-free station associations and GTFS topology extraction."""

import csv
import hashlib
import logging
import math
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path

import duckdb
import networkx as nx

LOGGER = logging.getLogger(__name__)
EU_CODES = dict(
    zip(
        "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split(),
        [
            "Austria",
            "Belgium",
            "Bulgaria",
            "Croatia",
            "Cyprus",
            "Czech Republic",
            "Denmark",
            "Estonia",
            "Finland",
            "France",
            "Germany",
            "Greece",
            "Hungary",
            "Ireland",
            "Italy",
            "Latvia",
            "Lithuania",
            "Luxembourg",
            "Malta",
            "Netherlands",
            "Poland",
            "Portugal",
            "Romania",
            "Slovak Republic",
            "Slovenia",
            "Spain",
            "Sweden",
        ],
        strict=True,
    )
)
EU_COUNTRIES = frozenset(EU_CODES.values())


def distance_km(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    """Great-circle distance, not track/road length or journey duration."""
    lat1, lon1, lat2, lon2 = map(
        math.radians, [a["latitude"], a["longitude"], b["latitude"], b["longitude"]]
    )
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return round(6371.0088 * 2 * math.asin(math.sqrt(min(1, h))), 6)


def coordinates(lat: str | None, lon: str | None) -> dict[str, float] | None:
    try:
        lat, lon = float(lat), float(lon)
        if (
            math.isfinite(lat)
            and math.isfinite(lon)
            and -90 <= lat <= 90
            and -180 <= lon <= 180
        ):
            return {"latitude": lat, "longitude": lon}
    except (TypeError, ValueError):
        pass
    return None


class CityIndex:
    """Grid index avoids comparing every stop against every city."""

    def __init__(self, graph: "nx.MultiDiGraph") -> None:
        self.graph = graph
        self.cells = defaultdict(list)
        for node, attrs in graph.nodes(data=True):
            self.cells[self.cell(attrs)].append(node)

    @staticmethod
    def cell(point: Mapping[str, float]) -> tuple[int, int]:
        return (math.floor(point["latitude"] * 4), math.floor(point["longitude"] * 4))

    def nearest(
        self,
        point: Mapping[str, float] | None,
        radius: float = 10,
        country: str | None = None,
    ) -> str | None:
        if point is None:
            return None
        lat, lon = self.cell(point)
        # Longitude range grows near the poles; wrap across the date line.
        dx = (
            math.ceil(
                radius / (27.7 * max(0.001, math.cos(math.radians(point["latitude"]))))
            )
            + 1
        )
        dy = math.ceil(radius / 27.7) + 1
        candidates = []
        for y in range(lat - dy, lat + dy + 1):
            for x in range(lon - dx, lon + dx + 1):
                for node in self.cells.get((y, (x + 720) % 1440 - 720), ()):
                    attrs = self.graph.nodes[node]
                    if country is None or attrs["country"] == country:
                        distance = distance_km(point, attrs)
                        if distance <= radius:
                            candidates.append((distance, node))
        if not candidates:
            return None
        candidates.sort()
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            return None
        return candidates[0][1]


def add_stations(
    graph: "nx.MultiDiGraph",
    path: Path,
    countries: frozenset[str],
    normalize: Callable[[str], str],
    identity: Callable[[str, object], str],
) -> tuple[str, dict[str, dict[str, object]]]:
    """Supplement explicit city rows, then map actual stations within their country."""
    raw = Path(path).read_bytes()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {
            "id",
            "name",
            "country",
            "latitude",
            "longitude",
            "is_city",
            "parent_station_id",
        } <= set(reader.fieldnames or []):
            raise ValueError("Station CSV is missing required columns")
        rows = sorted(reader, key=lambda r: r["id"])
    names = defaultdict(list)
    for node, attrs in graph.nodes(data=True):
        names[(attrs["country"], normalize(attrs["name"]))].append(node)
    city_rows = {}
    issues = defaultdict(int)
    for row in rows:
        country = EU_CODES.get(row["country"], row["country"])
        if country not in countries or row["is_city"].upper() != "TRUE":
            continue
        point = coordinates(row["latitude"], row["longitude"])
        if point is None or not row["name"].strip():
            issues["invalid_city_coordinates_or_name"] += 1
            continue
        matches = names.get((country, normalize(row["name"])), [])
        if len(matches) == 1:
            node = matches[0]
        elif matches:
            issues["ambiguous_city"] += 1
            continue
        else:
            node = identity(
                "city:", [country, row["name"], point["latitude"], point["longitude"]]
            )
            graph.add_node(
                node,
                name=row["name"],
                country=country,
                **point,
                population=None,
                timezone=row.get("time_zone"),
                source="train_stations_europe.csv",
            )
            names[(country, normalize(row["name"]))].append(node)
        city_rows[row["id"]] = node
    index = CityIndex(graph)
    terminals = {}
    for row in rows:
        country = EU_CODES.get(row["country"], row["country"])
        if country not in countries or row["is_city"].upper() == "TRUE":
            continue
        point = coordinates(row["latitude"], row["longitude"])
        node = city_rows.get(row["parent_station_id"])
        method = "explicit_parent_city"
        if node is None:
            node = index.nearest(point, country=country)
            method = "nearest_city_within_10km"
        if node is None:
            issues["unmapped_station"] += 1
            continue
        key = "station:" + row["id"]
        terminals[key] = dict(
            id=key,
            city_id=node,
            name=row["name"],
            timezone=row.get("time_zone"),
            source="train_stations_europe.csv",
            mapping_method=method,
        )
    graph.graph["station_mapping_counts"] = dict(sorted(issues.items()))
    return hashlib.sha256(raw).hexdigest(), terminals


def gtfs_mode(route_type: str | int | None) -> str | None:
    try:
        value = int(route_type)
    except (TypeError, ValueError):
        return None
    if value == 2 or 100 <= value <= 199:
        return "TRAINS"
    if value == 3 or 200 <= value <= 299 or 700 <= value <= 799:
        return "BUSSES"
    if value in (4, 1200) or 1000 <= value <= 1099:
        return "FERRIES"
    return None


# GTFS times are service-day offsets, not SQL TIME values. Preserve 24+ hours;
# malformed fields and arithmetic overflow produce unknown durations.
GTFS_SECONDS_MACRO = """CREATE OR REPLACE TEMP MACRO gtfs_seconds(value) AS (
    CASE WHEN regexp_full_match(trim(value), '[0-9]+:[0-5][0-9]:[0-5][0-9]')
    THEN TRY(try_cast(split_part(trim(value), ':', 1) AS BIGINT) * 3600
           + try_cast(split_part(trim(value), ':', 2) AS BIGINT) * 60
           + try_cast(split_part(trim(value), ':', 3) AS BIGINT)) END
)"""


def add_schedules(
    graph: "nx.MultiDiGraph",
    path: Path,
    identity: Callable[[str, object], str],
) -> str:
    """Extract static per-feed topology and minimum scheduled ride durations.

    Each trip is ordered by numeric stop_sequence. Unmapped stops remain in the
    sequence so they cannot create invented shortcuts. Repeated services collapse
    into one static edge per route and directed city pair.
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Schedule database does not exist: {path}")
    index = CityIndex(graph)
    totals = defaultdict(int)
    with duckdb.connect(
        str(path), read_only=True, config={"threads": 2, "memory_limit": "1GB"}
    ) as db:
        db.execute(GTFS_SECONDS_MACRO)
        feeds = db.execute(
            "SELECT feed_id, source_sha256 FROM feeds ORDER BY feed_id"
        ).fetchall()
        fingerprint = identity("gtfs:", feeds)
        for number, (feed, _) in enumerate(feeds, 1):
            LOGGER.info("Static GTFS topology: %s (%d/%d)", feed, number, len(feeds))
            routes = {
                r[0]: r[1:]
                for r in db.execute(
                    "SELECT route_id, route_type, agency_id FROM routes WHERE feed_id=? ORDER BY route_id",
                    [feed],
                ).fetchall()
            }
            if not routes:
                continue
            # Map only distinct coordinates in Python, then join to feed-local stops.
            points = db.execute(
                "SELECT DISTINCT stop_lat, stop_lon FROM stops WHERE feed_id=?", [feed]
            ).fetchall()
            mappings = []
            for lat, lon in points:
                node = index.nearest(coordinates(lat, lon))
                totals["mapped_coordinates" if node else "unmapped_coordinates"] += 1
                mappings.append((lat, lon, node))
            if not any(node for _, _, node in mappings):
                totals["feeds_without_mapped_cities"] += 1
                continue
            with tempfile.NamedTemporaryFile(
                mode="w+", suffix=".csv", newline=""
            ) as mapping_file:
                writer = csv.writer(mapping_file)
                writer.writerow(["lat", "lon", "city"])
                writer.writerows(mappings)
                mapping_file.flush()
                db.execute(
                    """CREATE OR REPLACE TEMP TABLE city_points AS
                    SELECT * FROM read_csv(?, header=true, all_varchar=true)""",
                    [mapping_file.name],
                )
            db.execute(
                """CREATE OR REPLACE TEMP TABLE city_stops AS
                SELECT DISTINCT s.stop_id, p.city FROM stops s LEFT JOIN city_points p
                ON s.stop_lat=p.lat AND s.stop_lon=p.lon WHERE s.feed_id=?""",
                [feed],
            )
            # Duplicate stop IDs or sequences cannot define a reliable ordered path.
            db.execute("""CREATE OR REPLACE TEMP TABLE unique_stops AS
                SELECT stop_id, CASE WHEN count(*)=1 THEN min(city) END AS city
                FROM city_stops GROUP BY stop_id""")
            result = db.execute(
                """WITH ordered AS (
                SELECT trip_id, try_cast(stop_sequence AS BIGINT) AS seq,
                       CASE WHEN count(*)=1 THEN min(stop_id) END AS stop_id,
                       CASE WHEN count(*)=1 THEN min(coalesce(nullif(trim(arrival_time), ''), departure_time)) END AS arrival,
                       CASE WHEN count(*)=1 THEN min(coalesce(nullif(trim(departure_time), ''), arrival_time)) END AS departure
                FROM stop_times WHERE feed_id=? GROUP BY trip_id, seq
            ), mapped AS (
                SELECT o.trip_id, o.seq, s.city, o.arrival, o.departure,
                       bool_and(o.seq IS NOT NULL AND o.seq >= 0)
                           OVER (PARTITION BY o.trip_id) AS valid_sequence FROM ordered o
                LEFT JOIN unique_stops s USING(stop_id)
            ), pairs AS (
                SELECT trip_id, city, departure,
                       lead(arrival) OVER (PARTITION BY trip_id ORDER BY seq) AS destination_arrival,
                       lead(city) OVER (PARTITION BY trip_id ORDER BY seq) AS destination
                FROM mapped WHERE valid_sequence
            ), timed AS (
                SELECT *, gtfs_seconds(destination_arrival) - gtfs_seconds(departure) AS seconds
                FROM pairs WHERE city IS NOT NULL AND destination IS NOT NULL AND city<>destination
            ), durations AS (
                SELECT *, CASE WHEN seconds >= 0 THEN seconds / 60.0 END AS minutes FROM timed
            )
            SELECT t.route_id, p.city, p.destination, min(p.minutes), count(p.minutes)
            FROM durations p JOIN trips t ON t.feed_id=? AND t.trip_id=p.trip_id
            GROUP BY t.route_id, p.city, p.destination
            ORDER BY t.route_id, p.city, p.destination""",
                [feed, feed],
            )
            while batch := result.fetchmany(4096):
                for route, origin, destination, minutes, samples in batch:
                    route_type, agency = routes.get(route, (None, None))
                    mode = gtfs_mode(route_type)
                    if mode is None:
                        totals["unsupported_mode_connections"] += 1
                        continue
                    key = identity(
                        "connection:", ["gtfs", feed, route, origin, destination]
                    )
                    graph.add_edge(
                        origin,
                        destination,
                        key=key,
                        connection_id=key,
                        mode=mode,
                        operator=agency,
                        route_id=route,
                        feed_id=feed,
                        data_source="GTFS",
                        travel_time_minutes=minutes,
                        travel_time_basis=(
                            "gtfs_min_scheduled_stop_pair"
                            if minutes is not None
                            else "unknown"
                        ),
                        travel_time_samples=samples,
                        source_records=[f"{feed}/routes/{route}"],
                        status="reference_unverified",
                        mapping_method="nearest_city_within_10km",
                        distance_km=distance_km(
                            graph.nodes[origin], graph.nodes[destination]
                        ),
                        distance_basis="city_centres_great_circle",
                    )
                    totals["connections"] += 1
                    totals[
                        (
                            "connections_with_travel_time"
                            if minutes is not None
                            else "connections_without_travel_time"
                        )
                    ] += 1
    graph.graph["gtfs_mapping_counts"] = dict(sorted(totals.items()))
    graph.graph["gtfs_feed_count"] = len(feeds)
    return fingerprint
