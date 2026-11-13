"""Build static multimodal city topology from local reference snapshots.

This is an offline reference import, not an assertion of current service availability.
Airport associations require a unique normalized city/country match or an explicit
reviewed mapping. Airports never use geographic nearest-neighbour inference.
"""

import csv
import hashlib
import io
import json
import math
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Mapping

import networkx as nx

from backend.infrastructure.catalog.static_transport import (
    EU_COUNTRIES,
    add_schedules,
    add_stations,
    distance_km,
)

DATA = Path(__file__).resolve().parents[1] / "fixtures" / "data"
SCHEMA_VERSION = 4
# Retained for callers that imported the original constant. Default scope is EU-27.
EUROPE_COUNTRIES = EU_COUNTRIES
COUNTRY_ALIASES = {
    "Republic of Moldova": "Moldova",
    "Republic of Serbia": "Serbia",
    "Slovakia": "Slovak Republic",
    "Turkiye": "Turkey",
}


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _identity(prefix: str, values: object) -> str:
    return (
        prefix
        + hashlib.sha256(
            json.dumps(values, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
    )


def _route_minutes(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None


def build_base_graph(
    cities_path: Path = DATA / "cities" / "Cities.csv",
    routes_path: Path = DATA / "airline_routes.json",
    *,
    countries: frozenset[str] = EU_COUNTRIES,
    stations_path: Path | None = DATA / "train-stations" / "train_stations_europe.csv",
    schedules_path: Path | None = DATA
    / "mobilitydatabase"
    / "schedules.staging.duckdb",
    airport_city_overrides: Mapping[str, str] | None = None,
) -> nx.MultiDiGraph:
    """Return a structurally frozen graph with stable content-derived identifiers.

    Every city has a source population (None when unknown) and attractiveness=1.
    Overrides map airport IATA codes to city node IDs returned by this importer.
    Metadata includes checksums and diagnostics. Source dates, rights, and current
    availability are unknown; this snapshot is not approved for live searches.
    Node/edge attribute dictionaries remain mutable under NetworkX freeze.
    """
    city_bytes, route_bytes = (
        Path(cities_path).read_bytes(),
        Path(routes_path).read_bytes(),
    )
    graph = nx.MultiDiGraph()
    lookup = defaultdict(list)
    reader = csv.DictReader(io.StringIO(city_bytes.decode("utf-8-sig")))
    required = {"city", "country", "latitude", "longitude", "population"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("City CSV is missing required columns")
    for line, row in enumerate(reader, 2):
        if row["country"] not in countries:
            continue
        try:
            name, country = row["city"].strip(), row["country"].strip()
            lat, lon = float(row["latitude"]), float(row["longitude"])
            population = int(row["population"]) if row["population"] else None
            if (
                not name
                or not math.isfinite(lat)
                or not math.isfinite(lon)
                or not -90 <= lat <= 90
                or not -180 <= lon <= 180
                or (population is not None and population < 0)
            ):
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError(f"Invalid city record at CSV line {line}") from error
        city_id = _identity("city:", [country, name, lat, lon])
        if city_id not in graph:
            graph.add_node(
                city_id,
                name=name,
                country=country,
                latitude=lat,
                longitude=lon,
                population=population,
                timezone=None,
                source="Cities.csv",
            )
            lookup[(_normalize(country), _normalize(name))].append(city_id)

    extra_checksums = {}
    station_terminals = {}
    if stations_path is not None:
        checksum, station_terminals = add_stations(
            graph, stations_path, countries, _normalize, _identity
        )
        extra_checksums["stations"] = checksum
        lookup.clear()
        for node, attrs in graph.nodes(data=True):
            lookup[(_normalize(attrs["country"]), _normalize(attrs["name"]))].append(
                node
            )

    airports = json.loads(route_bytes)
    if not isinstance(airports, dict):
        raise ValueError("Airline routes must be an airport-keyed object")
    for code, airport in airports.items():
        if not isinstance(airport, dict) or not isinstance(airport.get("country"), str):
            raise ValueError(f"Invalid airport record: {code}")
        if not isinstance(airport.get("routes", []), list):
            raise ValueError(f"Invalid routes list: {code}")
        for route in airport.get("routes", []):
            if not isinstance(route, dict) or not isinstance(route.get("iata"), str):
                raise ValueError(f"Invalid route destination: {code}")
            carriers = route.get("carriers", [])
            if not isinstance(carriers, list) or any(
                not isinstance(carrier, dict)
                or any(
                    value is not None and not isinstance(value, str)
                    for value in (carrier.get("iata"), carrier.get("name"))
                )
                for carrier in carriers
            ):
                raise ValueError(f"Invalid route carriers: {code}")
    overrides = dict(airport_city_overrides or {})
    for code, city_id in overrides.items():
        if code not in airports or city_id not in graph:
            raise ValueError(f"Invalid airport city override: {code}")
    mapped, terminals, issues = {}, dict(station_terminals), []
    for code, airport in sorted(airports.items()):
        country = COUNTRY_ALIASES.get(airport.get("country"), airport.get("country"))
        if country not in countries and code not in overrides:
            continue
        if airport.get("iata") != code:
            raise ValueError(f"Airport key/IATA mismatch: {code}")
        candidates = lookup.get(
            (_normalize(country), _normalize(airport.get("city_name") or "")), []
        )
        city_id = overrides.get(code)
        if city_id is None and len(candidates) == 1:
            city_id = candidates[0]
        if city_id is None:
            issues.append(
                {
                    "airport": code,
                    "reason": "ambiguous_city" if candidates else "unmatched_city",
                }
            )
            continue
        mapped[code] = city_id
        terminals[code] = {
            "id": f"airport:{code}",
            "city_id": city_id,
            "name": airport.get("name"),
            "timezone": airport.get("timezone"),
            "source": "airline_routes.json",
        }

    skipped = []
    for code in sorted(mapped):
        airport = airports[code]
        for index, route in enumerate(airport.get("routes", [])):
            destination = route.get("iata")
            if destination not in mapped:
                skipped.append(
                    {
                        "source_record": f"{code}/routes/{index}",
                        "destination": destination,
                        "reason": "unmapped_destination",
                    }
                )
                continue
            if mapped[code] == mapped[destination]:
                continue
            minutes = _route_minutes(route.get("min"))
            carriers = route.get("carriers", [])
            # A carrier list denotes parallel operator alternatives, not fares.
            for carrier in carriers or [None]:
                operator = (
                    carrier.get("iata") or carrier.get("name") if carrier else None
                )
                key = _identity("connection:", [code, destination, operator])
                u, v = mapped[code], mapped[destination]
                source_record = f"{code}/routes/{index}"
                if graph.has_edge(u, v, key):
                    records = graph[u][v][key]["source_records"]
                    if source_record not in records:
                        records.append(source_record)
                        if minutes is not None:
                            edge = graph[u][v][key]
                            previous = edge["travel_time_minutes"]
                            edge["travel_time_minutes"] = (
                                minutes if previous is None else min(previous, minutes)
                            )
                            edge["travel_time_basis"] = (
                                "airline_route_reference_minutes"
                            )
                            edge["travel_time_samples"] += 1
                    continue
                graph.add_edge(
                    u,
                    v,
                    key=key,
                    connection_id=key,
                    origin_terminal=f"airport:{code}",
                    destination_terminal=f"airport:{destination}",
                    mode="PLANES",
                    operator=operator,
                    data_source="airline_routes.json",
                    travel_time_minutes=minutes,
                    travel_time_basis=(
                        "airline_route_reference_minutes"
                        if minutes is not None
                        else "unknown"
                    ),
                    travel_time_samples=int(minutes is not None),
                    source_records=[source_record],
                    status="reference_unverified",
                    distance_km=distance_km(graph.nodes[u], graph.nodes[v]),
                    distance_basis="city_centres_great_circle",
                )
    if schedules_path is not None:
        extra_checksums["schedules"] = add_schedules(graph, schedules_path, _identity)
    # Apply city defaults after every source has contributed its nodes, including
    # station-only and isolated cities. Population remains unknown when absent.
    for _, attributes in graph.nodes(data=True):
        attributes.setdefault("population", None)
        attributes.setdefault("attractiveness", 1)
    checksums = {
        "cities": hashlib.sha256(city_bytes).hexdigest(),
        "routes": hashlib.sha256(route_bytes).hexdigest(),
        **extra_checksums,
    }
    graph.graph.update(
        schema_version=SCHEMA_VERSION,
        node_weight_attributes=["population", "attractiveness"],
        default_attractiveness=1,
        cities_without_population=sum(
            a["population"] is None for _, a in graph.nodes(data=True)
        ),
        scope="EU-27" if countries == EU_COUNTRIES else "custom_countries",
        static_only=True,
        weight_attributes=["distance_km", "travel_time_minutes"],
        travel_time_aggregation="minimum_valid_source_duration",
        travel_time_includes_waiting=False,
        connections_without_travel_time=sum(
            e["travel_time_minutes"] is None for _, _, e in graph.edges(data=True)
        ),
        distance_basis="city_centres_great_circle",
        stop_mapping_radius_km=10,
        snapshot_id=_identity(
            "snapshot:", [SCHEMA_VERSION, checksums, sorted(countries), overrides]
        ),
        checksums=checksums,
        countries=sorted(countries),
        terminals=terminals,
        publication_date=None,
        rights=None,
        live_search_eligible=False,
        mapping_issues=issues,
        skipped_routes=skipped,
        transport_modes=sorted({e["mode"] for _, _, e in graph.edges(data=True)}),
        isolated_cities=sorted(nx.isolates(graph)),
        missing_reverse_connections=sorted(
            [u, v, k] for u, v, k in graph.edges(keys=True) if not graph.has_edge(v, u)
        ),
    )
    return nx.freeze(graph)
