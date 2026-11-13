"""CLI coverage for synthetic optimization datasets."""

import json
import subprocess
import sys
import unittest

from backend.infrastructure.fixtures.network import MockFlightNetwork


class MockNetworkCLITests(unittest.TestCase):
    def run_cli(self, *options):
        return subprocess.run(
            [sys.executable, "-m", "backend.presentation.cli.mock_ignav", "network", *options],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_defaults_generate_one_hundred_airports(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        network = MockFlightNetwork.model_validate_json(result.stdout)
        self.assertEqual(len(network.airports), 100)
        self.assertEqual(len(network.flights), 5600)
        self.assertEqual(network.routes_per_airport, 4)
        self.assertEqual(network.flights_per_route, 2)
        self.assertEqual(network.days, 7)

    def test_custom_network_and_seed_repeatability(self):
        options = (
            "--seed",
            "42",
            "--airports",
            "6",
            "--routes-per-airport",
            "2",
            "--flights-per-route",
            "3",
            "--days",
            "2",
            "--start-date",
            "2026-12-01",
        )
        first = self.run_cli(*options)
        second = self.run_cli(*options)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        payload = json.loads(first.stdout)
        self.assertEqual(payload["seed"], 42)
        self.assertEqual(payload["start_date"], "2026-12-01")
        self.assertEqual(len(payload["airports"]), 6)
        self.assertEqual(len(payload["flights"]), 72)

    def test_invalid_network_options_fail_cleanly(self):
        cases = (
            ("--airports", "1"),
            ("--airports", "5", "--routes-per-airport", "5"),
            ("--flights-per-route", "0"),
            ("--days", "0"),
            ("--start-date", "not-a-date"),
            ("--request", "unused.json"),
        )
        for options in cases:
            with self.subTest(options=options):
                result = self.run_cli(*options)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
