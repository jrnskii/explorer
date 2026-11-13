"""Map-ready output contract: bounded coordinates, endpoint identity and timing."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import unittest

from backend.domain.cities import City
from backend.domain.planning import JourneyOffer, Money, RoundTrip, TripLeg
from backend.domain.travel import TransportType
from backend.infrastructure.fixtures.cities import CITY_LOCATIONS
from backend.infrastructure.graphql.models import RoundTripOption
from backend.infrastructure.graphql.round_trip import serialize_options


class CityTests(unittest.TestCase):
    def test_finite_coordinate_bounds_preserve_zero_and_negative(self):
        for latitude, longitude in ((0, 0), (-90, -180), (90, 180), (-45.5, 23.2)):
            city = City("test", "Test", latitude, longitude)
            self.assertEqual(city.latitude, latitude)
            self.assertEqual(city.longitude, longitude)
        for field, value in (
            ("latitude", 90.01),
            ("latitude", -90.01),
            ("longitude", 180.01),
            ("longitude", -180.01),
            ("latitude", float("nan")),
            ("longitude", float("inf")),
            ("longitude", True),
            ("latitude", "54"),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                replace(City("test", "Test", 0, 0), **{field: value})
        for changes in ({"id": ""}, {"name": " "}):
            with self.assertRaises(ValueError):
                replace(City("test", "Test", 0, 0), **changes)


class MapOutputTests(unittest.TestCase):
    def option(self):
        departure = datetime(2026, 12, 1, tzinfo=timezone.utc)
        return RoundTrip(
            (
                JourneyOffer(
                    "one",
                    (
                        TripLeg(
                            "lt-vilnius",
                            "pl-warsaw",
                            departure,
                            departure + timedelta(hours=8),
                            TransportType.BUSSES,
                        ),
                    ),
                    Money(Decimal("21.000000000000000001"), "USD"),
                    "test",
                    True,
                ),
            ),
            Money(Decimal("21.000000000000000001"), "USD"),
        )

    def test_serialization_and_generated_contract_round_trip(self):
        result = serialize_options([self.option()], CITY_LOCATIONS)[0]
        self.assertEqual(result["total_price"]["amount"], "21.000000000000000001")
        leg = result["path"][0]
        self.assertEqual(
            leg["from_city"],
            {
                "id": "lt-vilnius",
                "name": "Vilnius",
                "latitude": 54.6833333,
                "longitude": 25.3166667,
            },
        )
        self.assertEqual(leg["from"], leg["from_city"]["id"])
        self.assertEqual(leg["to"], leg["to_city"]["id"])
        self.assertEqual(leg["time_in_travel"], 28800)
        self.assertNotIn("from_", leg)
        self.assertEqual(
            RoundTripOption.model_validate(result).model_dump(
                mode="json", by_alias=True
            ),
            result,
        )
        self.assertEqual(serialize_options([], {}), [])

    def test_missing_or_mismatched_coordinates_are_errors(self):
        with self.assertRaisesRegex(ValueError, "missing map coordinates.*lt-vilnius"):
            serialize_options([self.option()], {})
        wrong = dict(CITY_LOCATIONS) | {"lt-vilnius": CITY_LOCATIONS["pl-warsaw"]}
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            serialize_options([self.option()], wrong)

    def test_both_cli_outputs_support_animation_without_geocoding(self):
        request = Path(__file__).parents[1] / "examples" / "round_trip.json"
        commands = (
            [sys.executable, "-m", "backend.presentation.cli.round_trip_demo"],
            [
                sys.executable,
                "-m",
                "backend.presentation.cli.round_trip",
                "--request",
                str(request),
            ],
        )
        for command in commands:
            with self.subTest(command=command):
                completed = subprocess.run(
                    command, capture_output=True, text=True, timeout=30
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertTrue(result["options"])
                for option in result["options"]:
                    RoundTripOption.model_validate(option)
                    for index, leg in enumerate(option["path"]):
                        self.assertEqual(leg["from"], leg["from_city"]["id"])
                        self.assertEqual(leg["to"], leg["to_city"]["id"])
                        for city in (leg["from_city"], leg["to_city"]):
                            self.assertTrue(-90 <= city["latitude"] <= 90)
                            self.assertTrue(-180 <= city["longitude"] <= 180)
                        departure = datetime.fromisoformat(leg["departure_at"])
                        arrival = datetime.fromisoformat(leg["arrival_at"])
                        self.assertEqual(
                            (arrival - departure).total_seconds(), leg["time_in_travel"]
                        )
                        if index:
                            self.assertEqual(
                                option["path"][index - 1]["to_city"], leg["from_city"]
                            )
