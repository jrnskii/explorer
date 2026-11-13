"""Static EU-27 flight fixture; no randomness, live data, or current-date inputs.

Each member state has its capital and two major non-capital cities. Selection
uses city/municipality populations rather than metropolitan areas where practical;
rankings depend on boundaries and census year (especially Belgium, Malta, and
Portugal). This is a representative mock, not an authoritative population table.

Coordinates are city centers, NOT airport sites. Familiar airport codes identify
cities where practical; codes containing digits are explicitly fictional airport
stand-ins (e.g. Espoo, Ghent, and Nicosia). No real airport, airline, domestic
service, or international route availability is implied, including in Cyprus.

Use ``generate_network().to_graph()`` for a fresh NetworkX MultiDiGraph, or run
``python -m backend.presentation.cli.eu_network`` to emit the fixed dataset as JSON.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo

from backend.infrastructure.ignav.models import AirportModel, PriceModel, SegmentModel
from backend.infrastructure.fixtures.network import (
    AirportLocation,
    MockFlightNetwork,
    MockNetworkFlight,
    _distance,
)


class City(NamedTuple):
    code: str
    city: str
    country: str
    latitude: float
    longitude: float
    timezone: str


# Capital first, followed by two major non-capital cities in each country.
# Entries and their order are part of the fixed fixture, not a population ranking.
EU_CITIES: tuple[City, ...] = (
    City("VIE", "Vienna", "AT", 48.2082, 16.3738, "Europe/Vienna"),
    City("GRZ", "Graz", "AT", 47.0707, 15.4395, "Europe/Vienna"),
    City("LNZ", "Linz", "AT", 48.3069, 14.2858, "Europe/Vienna"),
    City("BRU", "Brussels", "BE", 50.8503, 4.3517, "Europe/Brussels"),
    City("ANR", "Antwerp", "BE", 51.2194, 4.4025, "Europe/Brussels"),
    City("BE3", "Ghent", "BE", 51.0543, 3.7174, "Europe/Brussels"),
    City("SOF", "Sofia", "BG", 42.6977, 23.3219, "Europe/Sofia"),
    City("PDV", "Plovdiv", "BG", 42.1354, 24.7453, "Europe/Sofia"),
    City("VAR", "Varna", "BG", 43.2141, 27.9147, "Europe/Sofia"),
    City("ZAG", "Zagreb", "HR", 45.8150, 15.9819, "Europe/Zagreb"),
    City("SPU", "Split", "HR", 43.5081, 16.4402, "Europe/Zagreb"),
    City("RJK", "Rijeka", "HR", 45.3271, 14.4422, "Europe/Zagreb"),
    City("CY1", "Nicosia", "CY", 35.1856, 33.3823, "Asia/Nicosia"),
    City("CY2", "Limassol", "CY", 34.6786, 33.0413, "Asia/Nicosia"),
    City("LCA", "Larnaca", "CY", 34.9182, 33.6201, "Asia/Nicosia"),
    City("PRG", "Prague", "CZ", 50.0755, 14.4378, "Europe/Prague"),
    City("BRQ", "Brno", "CZ", 49.1951, 16.6068, "Europe/Prague"),
    City("OSR", "Ostrava", "CZ", 49.8209, 18.2625, "Europe/Prague"),
    City("CPH", "Copenhagen", "DK", 55.6761, 12.5683, "Europe/Copenhagen"),
    City("AAR", "Aarhus", "DK", 56.1629, 10.2039, "Europe/Copenhagen"),
    City("ODE", "Odense", "DK", 55.4038, 10.4024, "Europe/Copenhagen"),
    City("TLL", "Tallinn", "EE", 59.4370, 24.7536, "Europe/Tallinn"),
    City("TAY", "Tartu", "EE", 58.3780, 26.7290, "Europe/Tallinn"),
    City("EE3", "Narva", "EE", 59.3772, 28.1903, "Europe/Tallinn"),
    City("HEL", "Helsinki", "FI", 60.1699, 24.9384, "Europe/Helsinki"),
    City("FI2", "Espoo", "FI", 60.2055, 24.6559, "Europe/Helsinki"),
    City("TMP", "Tampere", "FI", 61.4978, 23.7610, "Europe/Helsinki"),
    City("CDG", "Paris", "FR", 48.8566, 2.3522, "Europe/Paris"),
    City("MRS", "Marseille", "FR", 43.2965, 5.3698, "Europe/Paris"),
    City("LYS", "Lyon", "FR", 45.7640, 4.8357, "Europe/Paris"),
    City("BER", "Berlin", "DE", 52.5200, 13.4050, "Europe/Berlin"),
    City("HAM", "Hamburg", "DE", 53.5511, 9.9937, "Europe/Berlin"),
    City("MUC", "Munich", "DE", 48.1351, 11.5820, "Europe/Berlin"),
    City("ATH", "Athens", "GR", 37.9838, 23.7275, "Europe/Athens"),
    City("SKG", "Thessaloniki", "GR", 40.6401, 22.9444, "Europe/Athens"),
    City("GPA", "Patras", "GR", 38.2466, 21.7346, "Europe/Athens"),
    City("BUD", "Budapest", "HU", 47.4979, 19.0402, "Europe/Budapest"),
    City("DEB", "Debrecen", "HU", 47.5316, 21.6273, "Europe/Budapest"),
    City("HU3", "Szeged", "HU", 46.2530, 20.1414, "Europe/Budapest"),
    City("DUB", "Dublin", "IE", 53.3498, -6.2603, "Europe/Dublin"),
    City("ORK", "Cork", "IE", 51.8985, -8.4756, "Europe/Dublin"),
    City("IE3", "Limerick", "IE", 52.6638, -8.6267, "Europe/Dublin"),
    City("FCO", "Rome", "IT", 41.9028, 12.4964, "Europe/Rome"),
    City("MXP", "Milan", "IT", 45.4642, 9.1900, "Europe/Rome"),
    City("NAP", "Naples", "IT", 40.8518, 14.2681, "Europe/Rome"),
    City("RIX", "Riga", "LV", 56.9496, 24.1052, "Europe/Riga"),
    City("DGP", "Daugavpils", "LV", 55.8747, 26.5362, "Europe/Riga"),
    City("LPX", "Liepāja", "LV", 56.5047, 21.0108, "Europe/Riga"),
    City("VNO", "Vilnius", "LT", 54.6872, 25.2797, "Europe/Vilnius"),
    City("KUN", "Kaunas", "LT", 54.8985, 23.9036, "Europe/Vilnius"),
    City("LT3", "Klaipėda", "LT", 55.7033, 21.1443, "Europe/Vilnius"),
    City("LUX", "Luxembourg", "LU", 49.6116, 6.1319, "Europe/Luxembourg"),
    City("LU2", "Esch-sur-Alzette", "LU", 49.4958, 5.9806, "Europe/Luxembourg"),
    City("LU3", "Differdange", "LU", 49.5242, 5.8914, "Europe/Luxembourg"),
    City("MLA", "Valletta", "MT", 35.8992, 14.5141, "Europe/Malta"),
    City("MT2", "St. Paul's Bay", "MT", 35.9483, 14.4017, "Europe/Malta"),
    City("MT3", "Birkirkara", "MT", 35.8972, 14.4611, "Europe/Malta"),
    City("AMS", "Amsterdam", "NL", 52.3676, 4.9041, "Europe/Amsterdam"),
    City("RTM", "Rotterdam", "NL", 51.9244, 4.4777, "Europe/Amsterdam"),
    City("NL3", "The Hague", "NL", 52.0705, 4.3007, "Europe/Amsterdam"),
    City("WAW", "Warsaw", "PL", 52.2297, 21.0122, "Europe/Warsaw"),
    City("KRK", "Kraków", "PL", 50.0647, 19.9450, "Europe/Warsaw"),
    City("WRO", "Wrocław", "PL", 51.1079, 17.0385, "Europe/Warsaw"),
    City("LIS", "Lisbon", "PT", 38.7223, -9.1393, "Europe/Lisbon"),
    City("OPO", "Porto", "PT", 41.1579, -8.6291, "Europe/Lisbon"),
    City("PT3", "Vila Nova de Gaia", "PT", 41.1336, -8.6174, "Europe/Lisbon"),
    City("OTP", "Bucharest", "RO", 44.4268, 26.1025, "Europe/Bucharest"),
    City("CLJ", "Cluj-Napoca", "RO", 46.7712, 23.6236, "Europe/Bucharest"),
    City("IAS", "Iași", "RO", 47.1585, 27.6014, "Europe/Bucharest"),
    City("BTS", "Bratislava", "SK", 48.1486, 17.1077, "Europe/Bratislava"),
    City("KSC", "Košice", "SK", 48.7164, 21.2611, "Europe/Bratislava"),
    City("POV", "Prešov", "SK", 48.9984, 21.2339, "Europe/Bratislava"),
    City("LJU", "Ljubljana", "SI", 46.0569, 14.5058, "Europe/Ljubljana"),
    City("MBX", "Maribor", "SI", 46.5547, 15.6459, "Europe/Ljubljana"),
    City("SI3", "Celje", "SI", 46.2397, 15.2677, "Europe/Ljubljana"),
    City("MAD", "Madrid", "ES", 40.4168, -3.7038, "Europe/Madrid"),
    City("BCN", "Barcelona", "ES", 41.3874, 2.1686, "Europe/Madrid"),
    City("VLC", "Valencia", "ES", 39.4699, -0.3763, "Europe/Madrid"),
    City("ARN", "Stockholm", "SE", 59.3293, 18.0686, "Europe/Stockholm"),
    City("GOT", "Gothenburg", "SE", 57.7089, 11.9746, "Europe/Stockholm"),
    City("MMX", "Malmö", "SE", 55.6050, 13.0038, "Europe/Stockholm"),
)

# A fixed capital backbone guarantees route-level strong connectivity. Each city
# also reaches both domestic peers and its closest remaining foreign city.
_CAPITAL_RING = (
    "DUB",
    "CDG",
    "BRU",
    "AMS",
    "LUX",
    "BER",
    "CPH",
    "ARN",
    "HEL",
    "TLL",
    "RIX",
    "VNO",
    "WAW",
    "PRG",
    "VIE",
    "BTS",
    "BUD",
    "OTP",
    "SOF",
    "ATH",
    "CY1",
    "MLA",
    "FCO",
    "ZAG",
    "LJU",
    "MAD",
    "LIS",
)
_START_DATE = date(2026, 1, 1)
_DEPARTURE_HOURS = (8, 17)


def generate_network() -> MockFlightNetwork:
    """Return a detached copy of the fixed 81-city, 324-route, 648-flight fixture.

    Two departures per directed route on 2026-01-01, in origin-local time.
    All fares are synthetic USD amounts for consistency with MockFlightNetwork.
    Connectivity does not imply time-feasible connections in this one-day fixture.
    """
    locations = {
        city.code: AirportLocation(
            latitude=city.latitude, longitude=city.longitude, timezone=city.timezone
        )
        for city in EU_CITIES
    }
    by_code = {city.code: city for city in EU_CITIES}
    next_capital = dict(zip(_CAPITAL_RING, _CAPITAL_RING[1:] + _CAPITAL_RING[:1]))
    capitals = {by_code[code].country: code for code in _CAPITAL_RING}
    airports = [
        AirportModel(
            code=city.code,
            name=f"Mock {city.city} Airport",
            city=city.city,
            country=city.country,
        )
        for city in EU_CITIES
    ]
    flights = []
    for city in EU_CITIES:
        destinations = [
            peer.code
            for peer in EU_CITIES
            if peer.country == city.country and peer.code != city.code
        ]
        destinations.append(next_capital[capitals[city.country]])
        nearest = min(
            (
                peer
                for peer in EU_CITIES
                if peer.country != city.country and peer.code not in destinations
            ),
            key=lambda peer: (
                _distance(locations[city.code], locations[peer.code]),
                peer.code,
            ),
        )
        destinations.append(nearest.code)
        origin_zone = ZoneInfo(city.timezone)
        for destination in destinations:
            arrival_zone = ZoneInfo(by_code[destination].timezone)
            distance = _distance(locations[city.code], locations[destination])
            duration = max(35, round(25 + distance / 780 * 60))
            for slot, hour in enumerate(_DEPARTURE_HOURS):
                departure = datetime.combine(
                    _START_DATE, time(hour), origin_zone
                ).astimezone(timezone.utc)
                arrival = departure + timedelta(minutes=duration)
                flights.append(
                    MockNetworkFlight(
                        id=f"mock-eu-{city.code}-{destination}-{_START_DATE}-{slot}",
                        segment=SegmentModel(
                            marketing_carrier_code="X1",
                            flight_number=str(len(flights) + 1),
                            operating_carrier_name="Synthetic Europe Air",
                            departure_airport=city.code,
                            departure_time_local=departure.astimezone(
                                origin_zone
                            ).isoformat(),
                            departure_timezone=origin_zone.key,
                            departure_time_utc=departure.isoformat(),
                            arrival_airport=destination,
                            arrival_time_local=arrival.astimezone(
                                arrival_zone
                            ).isoformat(),
                            arrival_timezone=arrival_zone.key,
                            arrival_time_utc=arrival.isoformat(),
                            duration_minutes=duration,
                            aircraft="A320",
                        ),
                        price=PriceModel(
                            amount=round(35 + distance * 0.09 + slot * 15, 2),
                            currency="USD",
                            status="unverified",
                        ),
                    )
                )
    return MockFlightNetwork(
        seed=0,
        airports=airports,
        locations=locations,
        flights=flights,
        start_date=_START_DATE,
        days=1,
        routes_per_airport=4,
        flights_per_route=2,
    )
