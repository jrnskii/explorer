"""Offline estimate-first planning and the single selected provider boundary."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock
import networkx as nx

from backend.domain.planning import Money
from backend.domain.pricing import (
    ExactPricingUnavailable,
    PriceForecast,
    QuotedPurchase,
    RoundTripQuote,
)
from backend.domain.travel import TransportType as Mode
from backend.infrastructure.graphql.search import ScheduleFirstSearch
from backend.infrastructure.schedules.reference import (
    ReferenceEdge,
    ReferenceSearch,
    project_routes,
)
from backend.infrastructure.schedules.store import (
    SearchCoverageError,
    SearchInputError,
    SearchResponse,
)
import test_schedule_serving as schedules
from test_schedule_serving import NOW


class ReferenceSearchTests(TestCase):
    def setUp(self):
        self.cities = {
            f"gn-{i}": dict(
                name=n, country="LT", latitude=54.7 + i / 10, longitude=25.3
            )
            for i, n in enumerate(("Home", "Cheap", "Expensive"), 1)
        }
        self.routes = {
            "gn-1": [
                ReferenceEdge("gn-1", "gn-2", Mode.PLANES, 60, 100),
                ReferenceEdge("gn-1", "gn-3", Mode.PLANES, 60, 200),
            ],
            "gn-2": [ReferenceEdge("gn-2", "gn-1", Mode.PLANES, 60, 100)],
            "gn-3": [ReferenceEdge("gn-3", "gn-1", Mode.PLANES, 60, 200)],
        }
        self.forecaster = Mock()

        def predict(q):
            price = Money(Decimal("10" if q.distance_km == 100 else "20"), "EUR")
            return PriceForecast(price, price, price, "test", "test", 1, None, None, ())

        self.forecaster.predict.side_effect = predict
        self.pricer = Mock()
        self.factory = Mock(return_value=self.pricer)
        self.service = ReferenceSearch(
            self.routes, self.cities, self.forecaster, self.factory, clock=lambda: NOW
        )
        self.settings = schedules.ScheduleServingTests.settings(
            self, transport_types=(Mode.PLANES,)
        )

        def quote(plan, settings):
            # Provider times replace internal reference date placeholders.
            return RoundTripQuote(
                tuple(
                    QuotedPurchase(
                        o.id,
                        replace(
                            o,
                            synthetic=False,
                            path=(
                                replace(
                                    o.path[0],
                                    departure_at=datetime(
                                        2030, 1, 2, 8 + i * 8, tzinfo=timezone.utc
                                    ),
                                    arrival_at=datetime(
                                        2030, 1, 2, 9 + i * 8, tzinfo=timezone.utc
                                    ),
                                ),
                            ),
                            price=Money(Decimal("15"), "EUR"),
                            source="provider",
                        ),
                        ("response",),
                        NOW,
                        f"trip-{i}",
                    )
                    for i, o in enumerate(plan.offers)
                )
            )

        self.pricer.quote.side_effect = quote

    def test_rank_offline_then_quote_only_best_and_publish_actual_times(self):
        result = self.service(self.settings)
        self.factory.assert_called_once()
        self.pricer.quote.assert_called_once()
        selected = self.pricer.quote.call_args.args[0]
        self.assertEqual([leg.destination for leg in selected.path], ["gn-2", "gn-1"])
        self.assertEqual(selected.total_price.amount, Decimal("20"))
        self.assertTrue(all(o.synthetic for o in selected.offers))
        self.assertEqual(result.options[0]["total_price"]["amount"], "30")
        self.assertEqual(
            result.options[0]["path"][0]["departure_at"], "2030-01-02T08:00:00Z"
        )
        self.assertFalse(result.metadata["synthetic_schedule"])
        self.assertEqual(result.metadata["provider_checked_opportunities"], 1)

    def test_failed_candidates_never_return_placeholder_times(self):
        self.pricer.quote.side_effect = ExactPricingUnavailable("private diagnostic")
        with self.assertRaisesRegex(
            SearchInputError, "Neither of the two best"
        ) as error:
            self.service(self.settings)
        self.assertNotIn("private", str(error.exception))
        self.assertEqual(self.pricer.quote.call_count, 2)

    def test_second_best_is_verified_after_first_failure(self):
        quote = self.pricer.quote.side_effect

        def verify(plan, settings):
            if plan.path[0].destination == "gn-2":
                raise ExactPricingUnavailable("no return service")
            return quote(plan, settings)

        self.pricer.quote.side_effect = verify
        result = self.service(self.settings)
        self.assertEqual(
            [
                call.args[0].path[0].destination
                for call in self.pricer.quote.call_args_list
            ],
            ["gn-2", "gn-3"],
        )
        self.assertEqual(result.metadata["provider_pricing_attempts"], 2)
        self.assertEqual(result.options[0]["path"][0]["to"], "gn-3")

    def test_logs_rank_estimate_live_price_and_budget_without_exception_text(self):
        quote = self.pricer.quote.side_effect

        def verify(plan, settings):
            if plan.path[0].destination == "gn-2":
                raise ExactPricingUnavailable("token=private-secret")
            return quote(plan, settings)

        self.pricer.quote.side_effect = verify
        with self.assertLogs(
            "backend.application.search_diagnostics", level="INFO"
        ) as logs:
            result = self.service(
                replace(self.settings, expenses_tolerance=Money(Decimal("25"), "EUR"))
            )
        self.assertEqual(len(result.options), 1)
        self.assertTrue(result.metadata["option_pricing"][0]["over_budget"])
        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [
                "search.candidate_selected",
                "search.candidate_rejected",
                "search.candidate_selected",
                "search.candidate_verified",
            ],
        )
        self.assertEqual(
            logs.records[-1].event_fields,
            {
                "rank": 2,
                "estimated_amount": "40",
                "provider_amount": "30",
                "budget_amount": "25",
                "currency": "EUR",
                "accepted": True,
                "reason": "over_budget",
            },
        )
        self.assertNotIn("private-secret", str([r.__dict__ for r in logs.records]))

    def test_no_second_candidate_does_not_repeat_first_provider_request(self):
        self.pricer.quote.side_effect = ExactPricingUnavailable("no service")
        with self.assertRaisesRegex(SearchInputError, "no second route"):
            self.service(replace(self.settings, mandatory_cities=("gn-2",)))
        self.pricer.quote.assert_called_once()

    def test_missing_forecasts_or_disallowed_modes_make_no_provider_requests(self):
        for settings in (
            replace(self.settings, transport_types=(Mode.TRAINS,)),
            replace(self.settings, excluded_cities=("gn-2", "gn-3")),
        ):
            with self.assertRaises(SearchCoverageError):
                self.service(settings)
        self.forecaster.predict.side_effect = lambda q: None
        with self.assertRaises(SearchCoverageError):
            self.service(self.settings)
        self.factory.assert_not_called()

    def test_required_city_and_over_budget_live_price(self):
        result = self.service(
            replace(
                self.settings,
                mandatory_cities=("gn-3",),
                expenses_tolerance=Money(Decimal("25"), "EUR"),
            )
        )
        self.assertEqual(
            self.pricer.quote.call_args.args[0].path[0].destination, "gn-3"
        )
        self.assertEqual(len(result.options), 1)
        self.assertTrue(result.metadata["option_pricing"][0]["over_budget"])
        self.assertEqual(result.metadata["price_status"], "over_budget")

    def test_projection_requires_existing_edges_and_unique_city_identity(self):
        graph = nx.MultiDiGraph()
        for key, city in self.cities.items():
            graph.add_node(key, **city)
        graph.add_edge(
            "gn-1", "gn-2", mode="PLANES", travel_time_minutes=60, distance_km=100
        )
        self.assertEqual(
            project_routes(graph, self.cities), {"gn-1": [self.routes["gn-1"][0]]}
        )
        duplicate = self.cities | {"duplicate": self.cities["gn-2"]}
        self.assertEqual(project_routes(graph, duplicate), {})

    def test_planning_budget_retains_completed_route_without_provider_access(self):
        self.service.max_states = 2
        route, limited = self.service.plan(self.settings)
        self.assertTrue(limited)
        self.assertEqual(route.total_price.amount, Decimal("20"))
        self.factory.assert_not_called()

    def test_date_requests_preserve_calendar_days_across_offset_change(self):
        settings = replace(
            self.settings,
            departure_date=datetime.fromisoformat("2030-10-26T00:00:00+03:00"),
            desired_arrival_date=datetime.fromisoformat("2030-10-29T00:00:00+02:00"),
            max_trip_duration=3 * 86400 + 3600,
        )
        route, _ = self.service.plan(settings)
        self.assertEqual(
            [leg.departure_at.date().isoformat() for leg in route.path],
            ["2030-10-26", "2030-10-28"],
        )
        self.factory.assert_not_called()

    def test_schedule_first_does_not_verify_another_route_after_provider_attempt(self):
        scheduled = Mock()
        fallback = Mock(return_value=self.service)
        search = ScheduleFirstSearch(scheduled, fallback)
        for response in (
            SearchResponse([{"result": True}], {}),
            SearchResponse([], {"price_status": "over_budget"}),
            SearchResponse([], {"price_status": "unavailable"}),
        ):
            scheduled.return_value = response
            self.assertIs(search(self.settings), response)
        fallback.assert_not_called()
        scheduled.side_effect = SearchCoverageError("no coverage")
        self.assertTrue(search(self.settings).options)
        fallback.assert_called_once()
        self.pricer.quote.assert_called_once()
