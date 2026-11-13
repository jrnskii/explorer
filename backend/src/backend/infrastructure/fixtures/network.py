"""Random, explicitly synthetic flight networks for graph optimization experiments.

Codes, names, carriers and fares are invented, not an airport catalog or API
fixture. Coordinates are jittered around regional templates; timezones are real
IANA zones. No claim is made about actual service, fares or operational feasibility.
"""

import math
import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from backend.infrastructure.ignav.models import AirportModel, PriceModel, SegmentModel

_UTC = timezone.utc
_MAX_FLIGHTS = 1_000_000
# Country, regional center, and a zone appropriate to that center. Small jitter
# keeps locations geographically plausible without implying real airport sites.
_REGIONS = (
    ("US", 40.7, -74.0, "America/New_York"),
    ("US", 34.0, -118.2, "America/Los_Angeles"),
    ("CA", 43.7, -79.4, "America/Toronto"),
    ("GB", 51.5, -0.1, "Europe/London"),
    ("FR", 48.9, 2.4, "Europe/Paris"),
    ("DE", 52.5, 13.4, "Europe/Berlin"),
    ("JP", 35.7, 139.7, "Asia/Tokyo"),
    ("KR", 37.6, 127.0, "Asia/Seoul"),
    ("IN", 28.6, 77.2, "Asia/Kolkata"),
    ("AE", 25.2, 55.3, "Asia/Dubai"),
    ("AU", -33.9, 151.2, "Australia/Sydney"),
    ("NZ", -36.8, 174.8, "Pacific/Auckland"),
    ("BR", -23.6, -46.6, "America/Sao_Paulo"),
    ("ZA", -26.2, 28.0, "Africa/Johannesburg"),
)
_SYLLABLES = (
    "ba",
    "cor",
    "den",
    "el",
    "fen",
    "gal",
    "hal",
    "jor",
    "kel",
    "lin",
    "mor",
    "nor",
    "pel",
    "rin",
    "sol",
    "tor",
    "val",
    "wen",
)
_CARRIERS = (
    ("X1", "Synthetic Cirrus Air"),
    ("X2", "Synthetic Meridian Air"),
    ("X3", "Synthetic Horizon Air"),
    ("X4", "Synthetic Nimbus Air"),
)


class AirportLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str


class MockNetworkFlight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    segment: SegmentModel
    price: PriceModel


class MockFlightNetwork(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int
    airports: list[AirportModel]
    locations: dict[str, AirportLocation]
    flights: list[MockNetworkFlight]
    synthetic: Literal[True] = True
    start_date: date
    days: int
    routes_per_airport: int
    flights_per_route: int

    def to_graph(self) -> nx.MultiDiGraph:
        """Return a fresh graph, one edge per flight keyed by its unique ID.

        ``price`` and ``weight`` are the numeric USD fare; ``segment`` is a
        detached dictionary containing all generated segment fields. UTC/local
        timestamps are ISO 8601 strings, as in the generated API models.
        """
        graph = nx.MultiDiGraph(seed=self.seed, synthetic=True)
        for airport in self.airports:
            graph.add_node(
                airport.code,
                **airport.model_dump(),
                **self.locations[airport.code].model_dump(),
            )
        for flight in self.flights:
            segment = flight.segment
            graph.add_edge(
                segment.departure_airport,
                segment.arrival_airport,
                key=flight.id,
                id=flight.id,
                flight_id=flight.id,
                price=flight.price.amount,
                weight=flight.price.amount,
                currency=flight.price.currency,
                duration_minutes=segment.duration_minutes,
                departure_time_utc=segment.departure_time_utc,
                arrival_time_utc=segment.arrival_time_utc,
                segment=segment.model_dump(),
            )
        return graph


def _integer(name: str, value: int, minimum: int, maximum: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")


def _distance(a: AirportLocation, b: AirportLocation) -> float:
    """Great-circle distance in kilometers, stable even for near-antipodes."""
    lat_a, lat_b = math.radians(a.latitude), math.radians(b.latitude)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(b.longitude - a.longitude)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return 12_742 * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))


def generate_network(
    *,
    seed: int = 0,
    airport_count: int = 100,
    routes_per_airport: int = 4,
    flights_per_route: int = 2,
    start_date: date = date(2026, 1, 1),
    days: int = 7,
) -> MockFlightNetwork:
    """Generate a reproducible, strongly connected synthetic route network.

    Each origin has exactly ``routes_per_airport`` distinct nonself destinations
    and ``flights_per_route`` departures per route per origin-local calendar day.
    Independent random streams keep airports and topology unchanged when the
    scheduling parameters change. Output is capped at one million flights;
    sparse requests take O(airports + routes + flights) space, not O(airports²).
    All invalid arguments raise ValueError before allocating the network.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    _integer("airport_count", airport_count, 2, 26**3)
    _integer("routes_per_airport", routes_per_airport, 1, airport_count - 1)
    _integer("flights_per_route", flights_per_route, 1, 24)
    _integer("days", days, 1, 366)
    if not isinstance(start_date, date) or isinstance(start_date, datetime):
        raise ValueError("start_date must be a date, not a datetime or string")
    if airport_count * routes_per_airport * flights_per_route * days > _MAX_FLIGHTS:
        raise ValueError("requested network exceeds the 1,000,000 flights limit")
    # Leave room for timezone conversion and long-haul arrivals at date.max.
    if start_date.toordinal() + days + 2 > date.max.toordinal():
        raise ValueError(
            "start_date and days leave insufficient room for flight arrivals"
        )
    if start_date == date.min:
        raise ValueError("start_date must leave room for UTC timezone conversion")

    airport_rng = random.Random(f"mock-network:airports:{seed}")
    route_rng = random.Random(f"mock-network:routes:{seed}")
    flight_rng = random.Random(f"mock-network:flights:{seed}")
    airports = []
    locations = {}
    zones = {}
    for number in airport_rng.sample(range(26**3), airport_count):
        code = "".join(
            chr(65 + digit) for digit in (number // 676, number // 26 % 26, number % 26)
        )
        country, latitude, longitude, zone = airport_rng.choice(_REGIONS)
        name = "".join(airport_rng.choices(_SYLLABLES, k=3)).capitalize()
        airports.append(
            AirportModel(
                code=code,
                name=f"Synthetic {name} {code} Airport",
                city=f"Synthetic {name} {code}",
                country=country,
            )
        )
        locations[code] = AirportLocation(
            latitude=round(latitude + airport_rng.uniform(-0.35, 0.35), 6),
            longitude=round(longitude + airport_rng.uniform(-0.35, 0.35), 6),
            timezone=zone,
        )
        zones[code] = ZoneInfo(zone)

    ring = list(range(airport_count))
    route_rng.shuffle(ring)
    successors = dict(zip(ring, ring[1:] + ring[:1]))
    routes = []
    for origin in range(airport_count):
        successor = successors[origin]
        destinations = [successor]
        # Sample compressed indices excluding self and the ring successor. This
        # avoids constructing an n-element candidate list for each sparse origin.
        excluded = sorted((origin, successor))
        for candidate in route_rng.sample(
            range(airport_count - 2), routes_per_airport - 1
        ):
            destination = candidate
            for forbidden in excluded:
                if destination >= forbidden:
                    destination += 1
            destinations.append(destination)
        routes.extend(
            (airports[origin].code, airports[destination].code)
            for destination in destinations
        )

    flights = []
    for origin, destination in routes:
        origin_zone, destination_zone = zones[origin], zones[destination]
        distance = _distance(locations[origin], locations[destination])
        for day in range(days):
            local_date = start_date + timedelta(days=day)
            midnight = datetime.combine(local_date, time(), origin_zone).astimezone(
                _UTC
            )
            next_midnight = datetime.combine(
                local_date + timedelta(days=1), time(), origin_zone
            ).astimezone(_UTC)
            minutes_in_day = int((next_midnight - midnight).total_seconds() // 60)
            for slot in range(flights_per_route):
                # Partition the actual 23/24/25-hour day into non-overlapping
                # slots. UTC arithmetic never creates imaginary local DST times.
                minute = flight_rng.randrange(
                    slot * minutes_in_day // flights_per_route,
                    (slot + 1) * minutes_in_day // flights_per_route,
                )
                departure = midnight + timedelta(minutes=minute)
                duration = max(
                    35, round(25 + distance / 780 * 60 * flight_rng.uniform(0.92, 1.10))
                )
                arrival = departure + timedelta(minutes=duration)
                carrier, carrier_name = flight_rng.choice(_CARRIERS)
                flights.append(
                    MockNetworkFlight(
                        id=f"synthetic-{seed}-{origin}-{destination}-{local_date.isoformat()}-{slot}",
                        segment=SegmentModel(
                            marketing_carrier_code=carrier,
                            flight_number=str(flight_rng.randint(1, 9999)),
                            operating_carrier_name=carrier_name,
                            departure_airport=origin,
                            departure_time_local=departure.astimezone(
                                origin_zone
                            ).isoformat(),
                            departure_timezone=origin_zone.key,
                            departure_time_utc=departure.isoformat(),
                            arrival_airport=destination,
                            arrival_time_local=arrival.astimezone(
                                destination_zone
                            ).isoformat(),
                            arrival_timezone=destination_zone.key,
                            arrival_time_utc=arrival.isoformat(),
                            duration_minutes=duration,
                            aircraft=flight_rng.choice(
                                ("A320", "B737", "A350", "B787")
                            ),
                        ),
                        price=PriceModel(
                            amount=round(
                                30
                                + distance * flight_rng.uniform(0.045, 0.16)
                                + flight_rng.uniform(5, 80),
                                2,
                            ),
                            currency="USD",
                            status="unverified",
                        ),
                    )
                )

    return MockFlightNetwork(
        seed=seed,
        airports=airports,
        locations=locations,
        flights=flights,
        start_date=start_date,
        days=days,
        routes_per_airport=routes_per_airport,
        flights_per_route=flights_per_route,
    )
