import unittest
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import networkx as nx
from backend.infrastructure.fixtures.eu_network import EU_CITIES, generate_network
from backend.infrastructure.fixtures.network import MockFlightNetwork

EU_COUNTRIES = {
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",
}
CAPITALS = {
    "Vienna",
    "Brussels",
    "Sofia",
    "Zagreb",
    "Nicosia",
    "Prague",
    "Copenhagen",
    "Tallinn",
    "Helsinki",
    "Paris",
    "Berlin",
    "Athens",
    "Budapest",
    "Dublin",
    "Rome",
    "Riga",
    "Vilnius",
    "Luxembourg",
    "Valletta",
    "Amsterdam",
    "Warsaw",
    "Lisbon",
    "Bucharest",
    "Bratislava",
    "Ljubljana",
    "Madrid",
    "Stockholm",
}


class MockEUFlightsNetworkTests(unittest.TestCase):
    def test_catalog_covers_every_member_and_capital(self):
        network = generate_network()
        self.assertEqual(
            Counter(a.country for a in network.airports),
            Counter({country: 3 for country in EU_COUNTRIES}),
        )
        self.assertTrue(CAPITALS <= {a.city for a in network.airports})
        self.assertEqual(len({a.code for a in network.airports}), 81)
        self.assertEqual(len({(a.country, a.city) for a in network.airports}), 81)
        self.assertEqual(set(network.locations), {a.code for a in network.airports})
        for city in EU_CITIES:
            ZoneInfo(city.timezone)
            self.assertEqual(network.locations[city.code].latitude, city.latitude)
            self.assertEqual(network.locations[city.code].longitude, city.longitude)

    def test_fixed_topology_and_parallel_departures(self):
        network = generate_network()
        graph = network.to_graph()
        routes = nx.DiGraph(graph)
        self.assertEqual(graph.number_of_nodes(), 81)
        self.assertEqual(routes.number_of_edges(), 324)
        self.assertEqual(graph.number_of_edges(), 648)
        self.assertTrue(nx.is_strongly_connected(graph))
        self.assertFalse(list(nx.selfloop_edges(graph)))
        countries = {a.code: a.country for a in network.airports}
        for origin in routes:
            destinations = list(routes.successors(origin))
            self.assertEqual(len(destinations), network.routes_per_airport)
            self.assertEqual(
                sum(countries[d] == countries[origin] for d in destinations), 2
            )
            for destination in destinations:
                self.assertEqual(graph.number_of_edges(origin, destination), 2)

    def test_fixed_schedule_prices_and_timezones(self):
        network = generate_network()
        departures = Counter()
        self.assertEqual(len({f.id for f in network.flights}), 648)
        for flight in network.flights:
            segment = flight.segment
            departure = datetime.fromisoformat(segment.departure_time_utc)
            arrival = datetime.fromisoformat(segment.arrival_time_utc)
            local = datetime.fromisoformat(segment.departure_time_local)
            self.assertEqual(local.date(), network.start_date)
            self.assertIn(local.hour, (8, 17))
            self.assertEqual(local.minute, 0)
            self.assertEqual(
                arrival - departure, timedelta(minutes=segment.duration_minutes)
            )
            for prefix in ("departure", "arrival"):
                utc = datetime.fromisoformat(getattr(segment, f"{prefix}_time_utc"))
                zone = ZoneInfo(getattr(segment, f"{prefix}_timezone"))
                self.assertEqual(
                    utc.astimezone(zone).isoformat(),
                    getattr(segment, f"{prefix}_time_local"),
                )
            self.assertGreater(flight.price.amount, 0)
            self.assertEqual(flight.price.currency, "USD")
            self.assertEqual(flight.price.status, "unverified")
            departures[
                (segment.departure_airport, segment.arrival_airport, local.hour)
            ] += 1
        self.assertEqual(set(departures.values()), {1})

    def test_repeatability_detachment_and_json_roundtrip(self):
        first, second = generate_network(), generate_network()
        self.assertEqual(first.model_dump_json(), second.model_dump_json())
        self.assertEqual(
            MockFlightNetwork.model_validate_json(first.model_dump_json()), first
        )
        first.airports[0].city = "Changed"
        first.locations[first.airports[0].code].latitude = 0
        first.flights[0].price.amount = 0
        self.assertEqual(second, generate_network())
        graph = second.to_graph()
        graph.nodes[second.airports[0].code]["city"] = "Changed"
        self.assertNotEqual(second.airports[0].city, "Changed")


if __name__ == "__main__":
    unittest.main()
