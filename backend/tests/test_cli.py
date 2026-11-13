"""Canonical presentation CLIs expose stable stdout and stderr contracts."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CanonicalCLITests(unittest.TestCase):
    def run_module(self, module, *arguments):
        return subprocess.run(
            [sys.executable, "-m", module, *arguments],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_ignav_health_emits_json_on_stdout(self):
        actual = self.run_module("backend.presentation.cli.mock_ignav", "health")
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(
            json.loads(actual.stdout), {"ok": True, "release": "mock-ignav-0.1.0"}
        )
        self.assertEqual(actual.stderr, "")

    def test_ignav_invalid_requests_report_errors_only_on_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / "request.json"
            for payload in ("{invalid", "null", "[]", "{}"):
                with self.subTest(payload=payload):
                    request.write_text(payload)
                    actual = self.run_module(
                        "backend.presentation.cli.mock_ignav",
                        "one-way",
                        "--request",
                        str(request),
                    )
                    self.assertEqual(actual.returncode, 2)
                    self.assertEqual(actual.stdout, "")
                    self.assertIn("mock-ignav:", actual.stderr)
                    self.assertNotIn("Traceback", actual.stderr)

    def test_ignav_missing_request_reports_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / "missing.json"
            actual = self.run_module(
                "backend.presentation.cli.mock_ignav",
                "one-way",
                "--request",
                str(request),
            )
        self.assertEqual(actual.returncode, 2)
        self.assertEqual(actual.stdout, "")
        self.assertIn("mock-ignav:", actual.stderr)
        self.assertIn("missing.json", actual.stderr)
        self.assertNotIn("Traceback", actual.stderr)

    def test_eu_network_emits_deterministic_synthetic_json(self):
        actual = self.run_module("backend.presentation.cli.eu_network")
        self.assertEqual(actual.returncode, 0, actual.stderr)
        payload = json.loads(actual.stdout)
        self.assertEqual(len(payload["airports"]), 81)
        self.assertEqual(len(payload["flights"]), 648)
        self.assertIs(payload["synthetic"], True)
        self.assertEqual(payload["start_date"], "2026-01-01")
        self.assertEqual(actual.stderr, "")

        repeated = self.run_module("backend.presentation.cli.eu_network")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(repeated.stdout, actual.stdout)
        self.assertEqual(repeated.stderr, "")

    def test_default_presentation_command_emits_greeting(self):
        actual = self.run_module("backend.presentation.cli.backend")
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, "Hello from backend!\n")
        self.assertEqual(actual.stderr, "")


if __name__ == "__main__":
    unittest.main()
