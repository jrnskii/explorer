"""Execute the self-contained notebook and exercise mock APIs and reactive search."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import builtins
import json
from pathlib import Path
import random
import pickle
import tempfile
from compression import zstd

import networkx as nx
import unittest
from unittest.mock import patch

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks/02_algo_demo_visualization.ipynb"


def fixture_graph():
    graph = nx.MultiDiGraph()
    for city, name, country in (("lt-vilnius", "Vilnius", "Lithuania"),
                                ("pl-warsaw", "Warsaw", "Poland"),
                                ("pl-krakow", "Cracow", "Poland")):
        graph.add_node(city, name=name, country=country)
    for a in graph:
        for b in graph:
            if a != b:
                for mode in ("PLANES", "TRAINS", "BUSSES", "FERRIES"):
                    graph.add_edge(a, b, key=f"{a}:{b}:{mode}", mode=mode,
                                   travel_time_minutes=60, distance_km=100, operator="fixture")
    return graph


def execute_notebook():
    scope = {}
    with patch("IPython.display.display"):
        for index, cell in enumerate(json.loads(NOTEBOOK.read_text())["cells"]):
            if cell["cell_type"] == "code":
                if index == len(json.loads(NOTEBOOK.read_text())["cells"]) - 1:
                    scope["fixture_source"] = scope["BaseGraphSource"](fixture_graph())
                    scope["real_load_graph_source"] = scope["load_graph_source"]
                    scope["load_graph_source"] = lambda path: scope["fixture_source"]
                exec(compile("".join(cell["source"]), f"{NOTEBOOK}:cell{index}", "exec"), scope)
    return scope


class AlgorithmNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = execute_notebook()

    @classmethod
    def tearDownClass(cls):
        cls.scope["demo"].close()

    def demo(self):
        demo = self.scope["ReactiveTripDemo"](self.scope["fixture_source"])
        self.addCleanup(demo.close)
        return demo

    def request(self, **changes):
        return replace(self.scope["MockFareRequest"](
            "lt-vilnius", "pl-krakow", datetime(2026, 12, 1, tzinfo=timezone.utc),
            datetime(2026, 12, 3, 16, tzinfo=timezone.utc),
        ), **changes)

    def fixture_trip(self):
        # Small fixed assertion fixture, independent of random generated fares.
        s = self.scope
        rows = [("lt-vilnius", "pl-warsaw", 8, 16),
                ("pl-warsaw", "pl-krakow", 30, 33),
                ("pl-krakow", "pl-warsaw", 40, 43),
                ("pl-warsaw", "lt-vilnius", 56, 64)]
        start = datetime(2026, 12, 1, tzinfo=timezone.utc)
        price = s["Money"](Decimal("10.00"), "USD")
        offers = tuple(s["JourneyOffer"](f"ticket-{i}", (s["TripLeg"](
            a, b, start + timedelta(hours=d), start + timedelta(hours=r), s["Mode"].TRAINS,
        ),), price, "test", True) for i, (a, b, d, r) in enumerate(rows))
        return s["RoundTrip"](offers, s["Money"](Decimal("40.00"), "USD"))

    def test_notebook_runs_without_backend_or_network_imports(self):
        original = builtins.__import__

        def isolated(name, *args, **kwargs):
            if name == "backend" or name.startswith("backend."):
                self.fail(f"Imported backend implementation: {name}")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", isolated), patch("socket.create_connection", side_effect=AssertionError("Network call")):
            scope = execute_notebook()
        self.addCleanup(scope["demo"].close)
        demo = scope["demo"]
        self.assertFalse(demo.controls["revisits"].value)
        self.assertTrue(demo.result.options)
        self.assertFalse(demo.result.truncation_reasons)
        self.assertNotIn("schedule", demo.controls)
        self.assertIn("mock API requests", demo.status.value)

    def test_every_mock_provider_is_deterministic_and_obeys_request(self):
        for name in ("MockFlightAPI", "MockTrainAPI", "MockBusAPI", "MockFerryAPI"):
            with self.subTest(provider=name):
                provider = self.scope[name](self.scope["fixture_source"])
                req = self.request()
                before = random.getstate()
                response = provider.search(req)
                self.assertEqual(response, provider.search(req))
                self.assertEqual(random.getstate(), before)
                self.assertNotEqual(response, provider.search(replace(req, seed=43)))
                self.assertTrue(response.synthetic)
                self.assertTrue(response.offers)
                self.assertEqual(len({o.id for o in response.offers}), len(response.offers))
                for offer in response.offers:
                    self.assertTrue(offer.synthetic)
                    self.assertEqual(offer.source, provider.source)
                    self.assertEqual(offer.price.currency, "USD")
                    self.assertIsInstance(offer.price.amount, Decimal)
                    leg = offer.path[0]
                    self.assertEqual((leg.origin, leg.destination), (req.origin, req.destination))
                    self.assertEqual(leg.transport_type, provider.mode)
                    self.assertGreaterEqual(leg.departure_at, req.earliest_departure)
                    self.assertLessEqual(leg.arrival_at, req.latest_arrival)
                    self.assertGreater(leg.time_in_travel, 0)

    def test_mock_filters_preserve_existing_services_and_parallel_modes(self):
        api = self.scope["MockTrainAPI"](self.scope["fixture_source"])
        request = self.request()
        original = api.search(request).offers
        expanded = api.search(replace(request, services_per_day=3)).offers
        self.assertTrue(set(original) <= set(expanded))
        narrowed = api.search(replace(request, earliest_departure=request.earliest_departure + timedelta(days=1))).offers
        self.assertTrue(set(narrowed) <= set(original))
        demo = self.demo()
        offers, calls = self.scope["collect_mock_offers"](
            demo.settings, source=demo.graph_source, seed=42, services_per_day=1,
        )
        self.assertEqual(offers, demo.offers)
        self.assertEqual(len(calls), len(demo.api_calls))
        self.assertEqual(len({o.id for o in offers}), len(offers))
        self.assertEqual({o.path[0].transport_type for o in offers}, set(demo.settings.transport_types))

    def test_base_graph_direction_modes_parallel_connections_and_scope_are_preserved(self):
        graph = fixture_graph()
        graph.remove_edges_from(list(graph.edges(keys=True)))
        graph.add_edge("lt-vilnius", "pl-krakow", key="flight-1", mode="PLANES", operator="one", travel_time_minutes=120)
        graph.add_edge("lt-vilnius", "pl-krakow", key="flight-2", mode="PLANES", operator="two", distance_km=700)
        graph.add_edge("pl-krakow", "lt-vilnius", key="train-back", mode="TRAINS", operator="rail")
        # A connection through another city must also be sent to the mocks.
        graph.add_edge("lt-vilnius", "pl-warsaw", key="outside", mode="PLANES")
        source = self.scope["BaseGraphSource"](graph)
        before = nx.node_link_data(graph)
        api = self.scope["MockFlightAPI"](source)
        response = api.search(self.request())
        self.assertEqual({o.connection_id for o in response.offers}, {"flight-1", "flight-2"})
        self.assertEqual({o.operator for o in response.offers}, {"one", "two"})
        self.assertEqual(len(response.offers), 6)
        self.assertTrue(all(o.path[0].time_in_travel >= 120 * 60
                            for o in response.offers if o.connection_id == "flight-1"))
        reverse = api.search(self.request(origin="pl-krakow", destination="lt-vilnius"))
        self.assertEqual(reverse.offers, ())  # A reverse train does not imply a reverse flight.
        missing = api.search(self.request(origin="missing", destination="pl-krakow"))
        self.assertEqual(missing.offers, ())
        demo = self.demo()
        offers, calls = self.scope["collect_mock_offers"](
            demo.settings, source=source, seed=42, services_per_day=1,
        )
        self.assertEqual({o.connection_id for o in offers}, {"flight-1", "flight-2", "train-back", "outside"})
        self.assertEqual(len(calls), 3)
        self.assertEqual(nx.node_link_data(graph), before)

    def test_whole_graph_lookup_includes_unselected_interchanges_and_components(self):
        graph = fixture_graph()
        graph.remove_edges_from(list(graph.edges(keys=True)))
        graph.add_node("de-berlin", name="Berlin", country="Germany")
        graph.add_node("fr-paris", name="Paris", country="France")
        graph.add_node("es-madrid", name="Madrid", country="Spain")
        # The only feasible round trip needs Berlin, outside the UI defaults.
        for origin, destination in (("lt-vilnius", "de-berlin"),
                                    ("de-berlin", "pl-krakow"),
                                    ("pl-krakow", "lt-vilnius"),
                                    ("fr-paris", "es-madrid")):
            graph.add_edge(origin, destination, key=f"{origin}:{destination}",
                           mode="TRAINS", travel_time_minutes=60)
        source = self.scope["BaseGraphSource"](graph)
        demo = self.scope["ReactiveTripDemo"](source)
        self.addCleanup(demo.close)
        self.assertNotIn("de-berlin", source.default_cities)
        self.assertNotIn("network_cities", demo.controls)
        self.assertIs(demo.graph_source.graph, graph)
        self.assertIsNone(demo.error)
        self.assertTrue(demo.result.options)
        self.assertEqual({(request.origin, request.destination) for _, request in demo.api_calls},
                         set(graph.edges()))
        self.assertTrue(all("de-berlin" in {leg.destination for leg in option.path}
                            for option in demo.result.options))
        original_offers, original_calls, original_result = demo.offers, demo.api_calls, demo.result
        demo.controls["city_filter"].value = "Paris"
        self.assertEqual(demo.offers, original_offers)
        self.assertEqual(demo.api_calls, original_calls)
        self.assertEqual(demo.result, original_result)
        for key in ("home", "required", "excluded", "weighted_cities"):
            self.assertIn("fr-paris", dict(demo.controls[key].options).values())
        demo.controls["weighted_cities"].value = ("fr-paris",)
        self.assertIn("weight:fr-paris", demo.controls)
        self.assertIsNone(demo.error)

    def test_snapshot_loader_validates_format_and_caches_uncompressed_and_zstd(self):
        load = self.scope["real_load_graph_source"]
        graph = fixture_graph()
        envelope = {"format": "explorer.base_graph", "format_version": 1,
                    "networkx_version": nx.__version__, "graph": graph}
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".pickle", ".pickle.zst"):
                path = Path(directory) / ("graph" + suffix)
                if suffix.endswith(".zst"):
                    with zstd.open(path, "wb") as stream:
                        pickle.dump(envelope, stream)
                else:
                    path.write_bytes(pickle.dumps(envelope))
                source = load(str(path))
                self.assertIs(source, load(str(path)))
                self.assertEqual(set(source.graph.edges(keys=True)), set(graph.edges(keys=True)))
                self.assertTrue(nx.is_frozen(source.graph))
                self.assertEqual(source.default_cities, ("lt-vilnius", "pl-warsaw", "pl-krakow"))
            bad = Path(directory) / "bad.pickle"
            for payload in ({}, {**envelope, "networkx_version": "old"},
                            {**envelope, "graph": nx.Graph()}, {**envelope, "graph": None}):
                bad.write_bytes(pickle.dumps(payload))
                with self.assertRaises(ValueError):
                    load(str(bad))
            with self.assertRaises(ValueError):
                load(str(Path(directory) / "missing.pickle"))
            with self.assertRaises(ValueError):
                load(str(Path(directory) / "graph.json"))

    def test_graph_city_search_and_missing_snapshot_error_recover(self):
        demo = self.demo()
        self.assertIn("Vilnius (Lithuania)", demo.report.value)
        demo.controls["city_filter"].value = "Warsaw"
        options = dict(demo.controls["required"].options)
        self.assertIn("pl-warsaw", options.values())
        self.assertEqual(demo.controls["home"].value, "lt-vilnius")
        self.assertEqual(demo.controls["required"].value, ("pl-krakow",))
        demo.injected_source = None
        original = self.scope["load_graph_source"]
        with patch.dict(self.scope, load_graph_source=lambda path: (_ for _ in ()).throw(ValueError("Base graph snapshot not found"))):
            demo.refresh()
        self.assertIsNone(demo.result)
        self.assertEqual(demo.report.value, "")
        self.assertIn("Base graph snapshot not found", demo.status.value)
        self.assertIs(self.scope["load_graph_source"], original)
        demo.refresh()
        self.assertIsNone(demo.error)
        self.assertTrue(demo.result.options)

    def test_mock_request_rejects_invalid_and_excessive_generation(self):
        for changes in ({"origin": []}, {"destination": "lt-vilnius"},
                        {"earliest_departure": "2026-12-01"},
                        {"seed": True}, {"seed": -1}, {"services_per_day": 0},
                        {"services_per_day": 4}, {"services_per_day": True},
                        {"earliest_departure": datetime(2026, 12, 1)},
                        {"latest_arrival": datetime(2026, 12, 1, tzinfo=timezone.utc)},
                        {"latest_arrival": datetime(2026, 12, 16, tzinfo=timezone.utc)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.request(**changes)
        boundary = self.request(latest_arrival=datetime(2026, 12, 15, tzinfo=timezone.utc), services_per_day=3)
        generated = self.scope["MockFlightAPI"](self.scope["fixture_source"]).search(boundary)
        self.assertLessEqual(len(generated.offers), 15 * 3)  # Stable generation-size bound.
        api = self.scope["MockBusAPI"](self.scope["fixture_source"])
        with self.assertRaises(ValueError):
            api.search({})
        empty = api.search(self.request(
            earliest_departure=datetime(2026, 12, 1, 23, tzinfo=timezone.utc),
            latest_arrival=datetime(2026, 12, 1, 23, 30, tzinfo=timezone.utc),
        ))
        self.assertEqual(empty.offers, ())

    def test_adapter_rejects_invalid_mock_responses(self):
        demo = self.demo()
        provider = self.scope["MockTrainAPI"](self.scope["fixture_source"])
        bad_offer = replace(demo.offers[0], synthetic=False)
        for response in (None, self.scope["MockFareResponse"]("bad", (), False),
                         self.scope["MockFareResponse"](provider.source, (bad_offer,))):
            with self.subTest(response=response), patch.object(provider, "search", return_value=response):
                with self.assertRaises(ValueError):
                    self.scope["collect_mock_offers"](
                        demo.settings, source=demo.graph_source, seed=42, services_per_day=1,
                        providers=(provider,),
                    )

    def test_all_feasible_generated_options_match_independent_enumeration(self):
        demo = self.demo()
        settings, offers = demo.settings, demo.offers
        expected = set()

        def visit(city, ready, chosen, visited, total):
            if chosen and city == settings.departure_city:
                if (settings.return_window[0] <= ready <= settings.return_window[1]
                    and set(settings.mandatory_cities) <= visited):
                    expected.add(tuple(o.id for o in chosen))
                return
            for offer in offers:
                leg = offer.path[0]
                if (leg.origin != city or leg.departure_at < ready
                    or (leg.destination in visited and leg.destination != settings.departure_city)
                    or total + offer.price.amount > settings.expenses_tolerance.amount):
                    continue
                visit(leg.destination, leg.arrival_at, chosen + (offer,), visited | {leg.destination}, total + offer.price.amount)

        visit(settings.departure_city, settings.departure_date, (), {settings.departure_city}, Decimal(0))
        self.assertEqual({tuple(o.id for o in r.offers) for r in demo.result.options}, expected)
        self.assertGreater(len(expected), 5)
        self.assertEqual(demo.report.value.count("<table"), len(expected))
        self.assertFalse(demo.result.results_limited)
        for option in demo.result.options:
            cities = [leg.destination for leg in option.path[:-1]]
            self.assertEqual(len(cities), len(set(cities)))

    def test_tables_preserve_every_leg_stay_and_bundled_fare(self):
        option = self.fixture_trip()
        rows = self.scope["itinerary_table"](option)
        stops = rows[rows["Activity"] == "City stop / interchange"]
        self.assertEqual(stops["From / city"].tolist(), ["pl-warsaw", "pl-krakow", "pl-warsaw"])
        self.assertEqual(stops["Time spent"].tolist(), ["14h 00m", "7h 00m", "13h 00m"])
        self.assertEqual(len(rows), 7)
        self.assertFalse(rows.isna().any().any())
        path = (option.path[0], replace(option.path[1], departure_at=option.path[0].arrival_at), *option.path[2:])
        bundle = replace(option.offers[0], id="bundle<&>", path=path, price=option.total_price)
        rows = self.scope["itinerary_table"](replace(option, offers=(bundle,)))
        self.assertEqual(rows.loc[rows["Activity"] == "Travel", "Fare charged"].tolist(),
                         ["USD 40.00", *(["included in ticket"] * 3)])
        self.assertIn("0h 00m", rows["Time spent"].tolist())
        self.assertIn("bundle&lt;&amp;&gt;", self.scope["table_html"](rows))

    def test_generation_button_seed_and_dates_recompute_reproducibly(self):
        demo = self.demo()
        original = demo.offers
        demo.generate.click()
        self.assertEqual(demo.controls["seed"].value, 43)
        self.assertNotEqual(demo.offers, original)
        demo.controls["seed"].value = 42
        self.assertEqual(demo.offers, original)
        demo.controls["services"].value = 2
        self.assertGreater(len(demo.offers), len(original))
        self.assertTrue(set(original) <= set(demo.offers))
        demo.controls["departure"].value += timedelta(days=7)
        demo.controls["return"].value += timedelta(days=7)
        self.assertIsNone(demo.error)
        self.assertTrue(demo.result.options)
        self.assertTrue(all(o.path[0].departure_at >= demo.settings.departure_date for o in demo.offers))
        self.assertTrue(all(o.path[-1].arrival_at <= demo.settings.return_window[1] for o in demo.offers))

    def test_budget_boundary_and_invalid_controls_clear_then_recover(self):
        demo = self.demo()
        cheapest = demo.result.options[0].total_price.amount
        demo.controls["budget"].value = str(cheapest)
        self.assertTrue(demo.result.options)
        self.assertTrue(all(o.total_price.amount == cheapest for o in demo.result.options))
        demo.controls["budget"].value = str(cheapest - Decimal("0.01"))
        self.assertEqual(demo.result.options, ())
        self.assertIn("No feasible round trips", demo.report.value)
        demo.controls["budget"].value = "200.00"
        for key, invalid in (("budget", "<script>"), ("budget", "NaN"), ("budget", "-1"),
                             ("departure", None), ("modes", ()), ("excluded", ("pl-krakow",))):
            with self.subTest(key=key):
                old = demo.controls[key].value
                demo.controls[key].value = invalid
                self.assertIsNone(demo.result)
                self.assertEqual(demo.report.value, "")
                self.assertIn('role="alert"', demo.status.value)
                self.assertNotIn("<script>", demo.status.value)
                demo.controls[key].value = old
                self.assertIsNone(demo.error)
                self.assertTrue(demo.result.options)

    def test_provider_timeout_clears_results_and_recovers(self):
        demo = self.demo()
        with patch.dict(self.scope, collect_mock_offers=unavailable):
            demo.refresh()
        self.assertIsNone(demo.result)
        self.assertEqual(demo.report.value, "")
        self.assertIn("Mock API unavailable", demo.status.value)
        demo.refresh()
        self.assertIsNone(demo.error)
        self.assertTrue(demo.result.options)

    def test_limits_modes_preferences_and_revisits_are_reactive(self):
        demo = self.demo()
        for key in ("max_states", "max_results", "max_legs"):
            old = demo.controls[key].value
            demo.controls[key].value = 1
            self.assertIn("Incomplete search", demo.report.value)
            self.assertIn(key, demo.report.value)
            demo.controls[key].value = old
        demo.controls["modes"].value = (self.scope["Mode"].TRAINS,)
        self.assertTrue(demo.result.options)
        self.assertTrue(all(o.path[0].transport_type == self.scope["Mode"].TRAINS for o in demo.offers))
        demo.controls["weighted_cities"].value = ("pl-krakow",)
        demo.controls["weight:pl-krakow"].value = 3
        demo.controls["fuzzy"].value = True
        self.assertTrue(all(o.stay_fit is not None for o in demo.result.options))
        demo.controls["weight:pl-krakow"].value = 0
        self.assertIsNone(demo.result)
        demo.controls["weight:pl-krakow"].value = 3
        demo.controls["return"].value += timedelta(days=2)
        count = len(demo.result.options)
        demo.controls["revisits"].value = True
        self.assertGreater(len(demo.result.options), count)
        demo.controls["max_duration"].value = 3600
        self.assertEqual(demo.result.options, ())

    def test_rerun_detaches_observers_and_generation_button(self):
        scope = execute_notebook()
        previous = scope["demo"]
        cell = json.loads(NOTEBOOK.read_text())["cells"][-1]
        with patch("IPython.display.display"):
            exec("".join(cell["source"]), scope)
        self.addCleanup(scope["demo"].close)
        self.assertTrue(previous.closed)
        before = previous.result
        seed = previous.controls["seed"].value
        previous.generate.click()
        self.assertEqual(previous.controls["seed"].value, seed)
        previous.controls["seed"].value += 1
        self.assertIs(previous.result, before)
        self.assertFalse(scope["demo"].closed)


def unavailable(*args, **kwargs):
    raise TimeoutError("Mock API unavailable; try again.")


if __name__ == "__main__":
    unittest.main()
