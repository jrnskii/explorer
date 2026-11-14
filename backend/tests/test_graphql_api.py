"""Offline HTTP/auth/schema integration; no forecast artifact or provider needed."""

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.presentation.api import create_app

QUERY = """query Search($input: RoundTripSearchInput!) {
  round_trip_options(input: $input) {
    total_price { amount currency } stay_fit city_stays { city time_spent }
    path { from to from_city { id latitude longitude } departure_at arrival_at transport_type }
  }
}"""
INPUT = dict(
    departure_city="pl-warsaw",
    departure_date="2027-01-01T00:00:00+02:00",
    desired_arrival_date="2027-01-04T00:00:00+02:00",
    time_tolerance=1440,
    expenses_tolerance=dict(amount="200.01", currency="EUR"),
    transport_types=["TRAINS"],
)


class GraphQLApiTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"APP_ACCESS_TOKEN": "test-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.search = Mock(return_value=[])
        self.client = TestClient(create_app(self.search))

    def post(self, input=None, query=QUERY, token="test-secret"):
        return self.client.post(
            "/graphql",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "query": query,
                "variables": {"input": INPUT if input is None else input},
            },
        )

    def test_authentication(self):
        self.assertEqual(
            self.client.post("/graphql", json={"query": "{ __typename }"}).status_code,
            401,
        )
        self.assertEqual(self.post(token="wrong").status_code, 401)
        with patch.dict("os.environ", {"APP_ACCESS_TOKEN": ""}):
            self.assertEqual(self.post().status_code, 503)
        self.search.assert_not_called()

    def test_empty_search_and_exact_wire_mapping(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["round_trip_options"], [])
        self.assertNotIn("extensions", response.json())
        settings = self.search.call_args.args[0]
        self.assertEqual(str(settings.expenses_tolerance.amount), "200.01")
        self.assertEqual(settings.departure_date.utcoffset().total_seconds(), 7200)
        self.assertEqual(settings.mandatory_cities, ())
        self.assertFalse(settings.fuzzy_search)
        self.assertEqual(settings.min_cities, 1)

    def test_minimum_cities_maps_to_domain(self):
        self.assertNotIn("errors", self.post(INPUT | {"min_cities": 3}).json())
        self.assertEqual(self.search.call_args.args[0].min_cities, 3)

    def test_omitted_minimum_returns_routes_with_different_city_counts(self):
        from test_round_trip import offer, START
        from datetime import timedelta
        from backend.application.round_trip_search import find_round_trips
        from backend.infrastructure.graphql.round_trip import serialize_options
        from backend.domain.cities import City

        offers = (offer("ab", "A", "B", 0, 1), offer("ba", "B", "A", 9, 10),
                  offer("bc", "B", "C", 2, 3), offer("ca", "C", "A", 9, 10))
        cities = {identity: City(identity, identity, 0, 0) for identity in ("A", "B", "C")}
        self.search.side_effect = lambda settings: serialize_options(find_round_trips(settings, offers).options, cities)
        request = INPUT | {"departure_city": "A", "departure_date": START.isoformat(),
                           "desired_arrival_date": (START + timedelta(hours=10)).isoformat(),
                           "time_tolerance": 0, "expenses_tolerance": {"amount": "100", "currency": "USD"}}
        self.assertNotIn("min_cities", request)
        payload = self.post(request).json()
        self.assertNotIn("errors", payload)
        self.assertEqual(sorted(len(option["path"]) for option in payload["data"]["round_trip_options"]), [2, 3])
        filtered = self.post(request | {"min_cities": 2}).json()
        self.assertEqual([len(option["path"]) for option in filtered["data"]["round_trip_options"]], [3])

    def test_invalid_inputs_are_graphql_errors_before_search(self):
        for changes in (
            {"expenses_tolerance": {"amount": 200, "currency": "EUR"}},
            {"expenses_tolerance": {"amount": "-1", "currency": "EUR"}},
            {"departure_date": "2027-01-01T00:00:00"},
            {"desired_arrival_date": INPUT["departure_date"]},
            {"transport_types": []},
            {"transport_types": ["BOATS"]},
            *({"min_cities": value} for value in (0, -1, True, None, 1.5, "2", 2**31)),
            {"time_tolerance": -1},
            {"time_tolerance": None},
            {"mandatory_cities": ["pl-warsaw"]},
            {"unknown": True},
        ):
            with self.subTest(changes=changes):
                self.assertIn("errors", self.post(INPUT | changes).json())
        self.search.assert_not_called()

    def test_contract_aliases_and_decimal_output(self):
        self.search.return_value = [
            dict(
                total_price=dict(amount="123.4567890123456789", currency="EUR"),
                stay_fit=None,
                city_stays=[],
                path=[
                    dict(
                        **{"from": "pl-warsaw"},
                        to="pl-krakow",
                        from_city=dict(id="pl-warsaw", latitude=52.25, longitude=21.0),
                        departure_at="2027-01-01T09:00:00Z",
                        arrival_at="2027-01-01T12:00:00Z",
                        transport_type="TRAINS",
                    )
                ],
            )
        ]
        payload = self.post().json()
        self.assertNotIn("errors", payload)
        option = payload["data"]["round_trip_options"][0]
        self.assertEqual(option["total_price"]["amount"], "123.4567890123456789")
        self.assertEqual(option["path"][0]["from"], "pl-warsaw")
        self.assertIsNone(option["stay_fit"])

    def test_internal_errors_are_sanitized(self):
        self.search.side_effect = OSError("private/path secret")
        with self.assertLogs("backend.presentation.api", level="ERROR"):
            response = self.post()
        self.assertNotIn("private/path", response.text)
        self.assertIn("errors", response.json())

    def test_frontend_query_matches_shared_schema(self):
        source = (
            Path(__file__).resolve().parents[2] / "frontend/lib/round-trip-search.ts"
        ).read_text()
        query = source.split("ROUND_TRIP_QUERY = `", 1)[1].split("`", 1)[0]
        payload = self.post(query=query).json()
        self.assertNotIn("errors", payload)

    def test_malformed_http_body(self):
        response = self.client.post(
            "/graphql",
            headers={"Authorization": "Bearer test-secret"},
            json={"query": 42},
        )
        self.assertEqual(response.status_code, 400)

    def test_multiple_search_aliases_are_rejected_without_duplicate_execution(self):
        query = "query($input: RoundTripSearchInput!) { a: round_trip_options(input:$input) { stay_fit } b: round_trip_options(input:$input) { stay_fit } }"
        self.assertIn("errors", self.post(query=query).json())
        self.assertEqual(self.search.call_count, 0)

    def test_body_size_and_malformed_json(self):
        headers = {"Authorization": "Bearer test-secret"}
        self.assertEqual(
            self.client.post(
                "/graphql", headers=headers, content="x" * 65537
            ).status_code,
            413,
        )
        self.assertEqual(
            self.client.post("/graphql", headers=headers, content="{").status_code, 400
        )

    def test_liveness_and_readiness(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/readyz").status_code, 200)
        with patch.dict("os.environ", {"APP_ACCESS_TOKEN": ""}):
            self.assertEqual(self.client.get("/readyz").status_code, 503)

    def test_staging_refuses_weak_or_missing_authentication(self):
        with patch.dict("os.environ", {"APP_ENV": "staging"}):
            with self.assertRaises(Exception):
                with TestClient(create_app(self.search)):
                    pass
