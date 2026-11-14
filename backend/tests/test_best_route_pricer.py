"""No provider call may be made for unselected route alternatives."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from backend.domain.travel import TransportType
from backend.domain.pricing import ExactPricingUnavailable
from backend.infrastructure.scrappa.best_route import BestRoutePricer, configured_pricer
from backend.infrastructure.graphql.search import configured_search
from backend.infrastructure.schedules.store import SearchUnavailable


class BestRoutePricerTests(TestCase):
    def setUp(self):
        self.cities = {
            "gn-1": {"name": "Vilnius", "country": "LT"},
            "gn-2": {"name": "Riga", "country": "LV"},
            "gn-3": {"name": "Paris", "country": "FR"},
        }
        self.client = Mock()
        self.client.__enter__ = Mock(return_value=self.client)
        self.client.__exit__ = Mock(return_value=False)

        def lookup(endpoint, params, **kwargs):
            city = next(c for c in self.cities.values() if c["name"] == params["query"])
            return SimpleNamespace(
                payload={
                    "data": {
                        "results": [
                            dict(
                                type="location",
                                position_id=1 if city["name"] == "Vilnius" else 2,
                                name=city["name"],
                                country_code=city["country"],
                            )
                        ]
                    }
                }
            )

        self.client.request.side_effect = lookup
        self.option = SimpleNamespace(
            offers=[
                SimpleNamespace(
                    path=[
                        SimpleNamespace(
                            origin="gn-1",
                            destination="gn-2",
                            transport_type=TransportType.BUSSES,
                        )
                    ]
                ),
                SimpleNamespace(
                    path=[
                        SimpleNamespace(
                            origin="gn-2",
                            destination="gn-1",
                            transport_type=TransportType.BUSSES,
                        )
                    ]
                ),
            ]
        )
        self.pricer = BestRoutePricer(
            self.cities,
            database="unused",
            api_key="unit-key",
            client_factory=lambda *a, **kw: self.client,
        )

    def test_only_selected_cities_and_one_route_quote(self):
        with patch(
            "backend.infrastructure.scrappa.best_route.ScrappaRoundTripPricer"
        ) as factory:
            result = self.pricer.quote(self.option, "settings")
            factory.return_value.quote.assert_called_once_with(self.option, "settings")
            self.assertEqual(result, factory.return_value.quote.return_value)
            self.assertEqual(
                [call.args[1]["query"] for call in self.client.request.call_args_list],
                ["Vilnius", "Riga"],
            )
            self.assertEqual(factory.call_args.args[1], {"gn-1": 1, "gn-2": 2})
            self.assertEqual(factory.call_args.kwargs["min_connection_seconds"], 1800)
            self.assertFalse(factory.call_args.kwargs["refresh"])

    def test_ambiguous_place_failure_does_not_quote_or_try_another_route(self):
        self.client.request.side_effect = None
        self.client.request.return_value = SimpleNamespace(
            payload={"data": {"results": []}}
        )
        with patch(
            "backend.infrastructure.scrappa.best_route.ScrappaRoundTripPricer"
        ) as factory:
            with self.assertRaises(ExactPricingUnavailable):
                self.pricer.quote(self.option, "settings")
            factory.assert_not_called()
            self.assertEqual(self.client.request.call_count, 1)

    def test_fallback_quotes_share_network_call_and_time_limits(self):
        transports = []

        def client_factory(*args, **kwargs):
            transports.append(kwargs["transport"])
            return self.client

        self.pricer.client_factory = client_factory
        with patch(
            "backend.infrastructure.scrappa.best_route.ScrappaRoundTripPricer"
        ), patch(
            "backend.infrastructure.scrappa.best_route.time.monotonic", return_value=10
        ), patch(
            "backend.infrastructure.scrappa.best_route.http_get",
            return_value=(200, "{}"),
        ) as http:
            self.pricer.quote(self.option, "settings")
            for _ in range(13):
                transports[0]("url", "key", 60)
            self.pricer.quote(self.option, "settings")
            for _ in range(12):
                transports[1]("url", "key", 60)
            with self.assertRaises(ExactPricingUnavailable):
                transports[1]("url", "key", 60)
            self.assertEqual(http.call_count, 25)
        with patch(
            "backend.infrastructure.scrappa.best_route.time.monotonic", return_value=191
        ), patch("backend.infrastructure.scrappa.best_route.http_get") as http:
            with self.assertRaises(ExactPricingUnavailable):
                transports[0]("url", "key", 60)
            http.assert_not_called()

    def test_application_pricer_ignores_legacy_cache_only_environment(self):
        with patch.dict("os.environ", {"SCRAPPA_CACHE_ONLY": "1", "SCRAPPA_API_KEY": "unit-key"}):
            pricer = configured_pricer(self.cities)
        pricer.client_factory = lambda *a, **kw: self.client
        with patch("backend.infrastructure.scrappa.best_route.ScrappaRoundTripPricer") as factory:
            pricer.quote(self.option, "settings")
            self.assertFalse(factory.call_args.kwargs["refresh"])
            self.assertFalse(factory.call_args.kwargs.get("cache_only", False))

    def test_cache_only_environment_cannot_bypass_required_live_credentials(self):
        for key in ("", " ", "change_in_prod"):
            with self.subTest(key=key), patch.dict("os.environ", {
                "SCHEDULE_SNAPSHOT_PATH": "unused",
                "SCRAPPA_CACHE_ONLY": "1",
                "SCRAPPA_API_KEY": key,
            }):
                with self.assertRaisesRegex(SearchUnavailable, "SCRAPPA_API_KEY is required"):
                    configured_search()
