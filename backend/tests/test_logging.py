"""Offline tracing contracts: correlation, privacy, concurrency and CLI stdout."""

import asyncio
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from backend.application.telemetry import (
    TRACE,
    event,
    operation,
    span_id,
    trace_id,
    traced,
)
from backend.infrastructure.fixtures.combine_mobilitydatabase import combine
from backend.infrastructure.logging import cli_entrypoint, configure_logging
from backend.infrastructure.scrappa.client import ScrappaClient, ScrappaError
from backend.presentation.api import create_app
from backend.presentation.tracing import RequestTracingMiddleware


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("backend")
        self.previous = (
            self.logger.handlers[:],
            self.logger.level,
            self.logger.propagate,
        )
        self.addCleanup(self.restore_logging)
        self.output = io.StringIO()
        self.stderr = self.enterContext(redirect_stderr(self.output))
        self.enterContext(
            patch.dict(os.environ, {"LOG_LEVEL": "TRACE", "LOG_FORMAT": "json"})
        )
        configure_logging()
        self.log = logging.getLogger("backend.tests.logging")

    def restore_logging(self):
        for handler in self.logger.handlers:
            if handler not in self.previous[0]:
                handler.close()
        self.logger.handlers, self.logger.level, self.logger.propagate = self.previous

    def records(self):
        return [json.loads(line) for line in self.output.getvalue().splitlines()]

    def test_optional_rotating_file_records_correlated_events_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "logs" / "search.jsonl"
            with patch.dict(os.environ, {"LOG_FILE": str(path)}):
                configure_logging(level="INFO", output_format="json")
                configure_logging(level="INFO", output_format="json")
                with operation(self.log, "test.search", level=logging.INFO):
                    event(self.log, "search.completed", level=logging.INFO, result_count=0, price_status="over_budget")
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual([row["event"] for row in rows], ["test.search.started", "search.completed", "test.search.completed"])
                self.assertEqual(len({row["trace_id"] for row in rows}), 1)
                self.assertIsNotNone(rows[0]["trace_id"])
                file_handler = next(h for h in self.logger.handlers if hasattr(h, "maxBytes"))
                self.assertEqual(file_handler.maxBytes, 5_000_000)
                self.assertEqual(file_handler.backupCount, 3)
            configure_logging()

    def test_nested_operations_share_trace_with_distinct_parented_spans(self):
        with operation(self.log, "outer"):
            with operation(self.log, "inner"):
                event(self.log, "count", rows=3)
        records = self.records()
        outer, inner = records[:2]
        self.assertEqual(len({r["trace_id"] for r in records}), 1)
        self.assertIsNotNone(outer["trace_id"])
        self.assertNotEqual(outer["span_id"], inner["span_id"])
        self.assertEqual(inner["fields"]["parent_span_id"], outer["span_id"])
        self.assertEqual(
            [r["event"] for r in records],
            [
                "outer.started",
                "inner.started",
                "count",
                "inner.completed",
                "outer.completed",
            ],
        )
        self.assertGreaterEqual(records[-1]["fields"]["duration_ms"], 0)
        self.assertIsNone(trace_id.get())
        self.assertIsNone(span_id.get())

    def test_failure_preserves_exception_and_never_formats_arguments_or_results(self):
        class Private:
            def __repr__(self):
                raise AssertionError("Must not inspect arguments/results")

        @traced
        def success(value):
            return value

        @traced
        def fail(value):
            raise error

        # Decorated test functions live outside backend; attach its logger explicitly.
        with patch(
            "backend.application.telemetry.function_logger", return_value=self.log
        ):
            success, fail = traced(success.__wrapped__), traced(fail.__wrapped__)
        value = Private()
        self.assertIs(success(value), value)
        error = ValueError("token=private-secret https://private.example/?key=secret")
        with self.assertRaises(ValueError) as caught:
            fail(value)
        self.assertIs(caught.exception, error)
        self.assertNotIn("private-secret", self.output.getvalue())
        self.assertNotIn("private.example", self.output.getvalue())
        failed = self.records()[-1]
        self.assertTrue(failed["event"].endswith(".failed"))
        self.assertEqual(failed["fields"]["error_type"], "ValueError")
        self.assertIsNone(trace_id.get())

    def test_cancellation_restores_existing_context(self):
        token = trace_id.set("parent-trace")
        parent = span_id.set("parent-span")
        try:
            with self.assertRaises(asyncio.CancelledError):
                with operation(self.log, "cancelled"):
                    raise asyncio.CancelledError("private-secret")
            self.assertEqual(trace_id.get(), "parent-trace")
            self.assertEqual(span_id.get(), "parent-span")
            self.assertEqual(
                self.records()[-1]["fields"]["error_type"], "CancelledError"
            )
            self.assertNotIn("private-secret", self.output.getvalue())
        finally:
            trace_id.reset(token)
            span_id.reset(parent)

    def test_disabled_trace_emits_nothing_and_preserves_behavior(self):
        configure_logging(level="WARNING")
        with operation(self.log, "quiet"):
            event(self.log, "hidden")
        self.assertEqual(self.output.getvalue(), "")

    def test_configuration_is_idempotent_and_preserves_host_handlers(self):
        root = logging.getLogger()
        before = root.handlers[:], root.level
        host = logging.NullHandler()
        self.logger.addHandler(host)
        configure_logging()
        configure_logging()
        self.assertEqual(
            sum(
                bool(getattr(h, "_backend_owned", False)) for h in self.logger.handlers
            ),
            1,
        )
        self.assertIn(host, self.logger.handlers)
        self.assertEqual((root.handlers, root.level), before)
        event(self.log, "once")
        self.assertEqual(len(self.records()), 1)

    def test_invalid_configuration_keeps_existing_handler(self):
        for options in ({"level": "secret-level"}, {"output_format": "xml"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                configure_logging(**options)
        event(self.log, "still_works")
        self.assertEqual(self.records()[0]["event"], "still_works")

    def test_text_format_escapes_newlines_and_exception_text(self):
        configure_logging(output_format="text")
        try:
            raise ValueError("private-secret")
        except ValueError:
            self.log.exception("failure\nforged entry")
        text = self.output.getvalue()
        self.assertEqual(len(text.splitlines()), 1)
        self.assertIn("ValueError", text)
        self.assertNotIn("private-secret", text)
        self.assertNotIn("Traceback", text)

    def test_cli_reports_return_and_system_exit_codes_without_stdout_logs(self):
        def finish():
            print('{"ok":true}')
            return 2

        with patch(
            "backend.infrastructure.logging.function_logger", return_value=self.log
        ):
            finish = cli_entrypoint(finish)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(finish(), 2)
        self.assertEqual(json.loads(output.getvalue()), {"ok": True})
        self.assertEqual(
            next(r for r in self.records() if r["event"] == "cli.exit")["fields"][
                "exit_code"
            ],
            2,
        )
        self.output.seek(0)
        self.output.truncate()

        def exit_now():
            raise SystemExit(7)

        with patch(
            "backend.infrastructure.logging.function_logger", return_value=self.log
        ):
            exit_now = cli_entrypoint(exit_now)
        with self.assertRaises(SystemExit) as caught:
            exit_now()
        self.assertEqual(caught.exception.code, 7)
        self.assertEqual(
            next(r for r in self.records() if r["event"] == "cli.exit")["fields"][
                "exit_code"
            ],
            7,
        )

    def test_module_cli_trace_and_quiet_modes_preserve_stdout(self):
        command = [
            sys.executable,
            "-m",
            "backend.presentation.cli.mock_ignav",
            "health",
        ]
        traced_run = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "LOG_LEVEL": "TRACE", "LOG_FORMAT": "json"},
        )
        quiet_run = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "LOG_LEVEL": "WARNING"},
        )
        self.assertEqual(traced_run.stdout, quiet_run.stdout)
        self.assertEqual(quiet_run.stderr, "")
        records = [json.loads(line) for line in traced_run.stderr.splitlines()]
        self.assertEqual(
            [r["event"] for r in records], ["cli.started", "cli.exit", "cli.completed"]
        )
        self.assertTrue(
            all(r["logger"] == "backend.presentation.cli.mock_ignav" for r in records)
        )

    def test_successful_help_reports_completion_and_preserves_exit_status(self):
        result = subprocess.run(
            [sys.executable, "-m", "backend.presentation.cli.mock_ignav", "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("usage:", result.stdout)
        records = [json.loads(line) for line in result.stderr.splitlines()]
        self.assertEqual(records[-1]["event"], "cli.completed")
        self.assertEqual(records[-2]["fields"]["exit_code"], 0)

    def test_gtfs_worker_operations_share_the_callers_trace(self):
        tables = {
            "routes.txt": "route_id,route_type\nr,2\n",
            "trips.txt": "trip_id,route_id,service_id\nt,r,s\n",
            "stops.txt": "stop_id,stop_name\ns,Station\n",
            "stop_times.txt": "trip_id,stop_id,stop_sequence,arrival_time,departure_time\nt,s,1,09:00:00,09:00:00\n",
            "calendar_dates.txt": "service_id,date,exception_type\ns,20260101,1\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw"
            raw.mkdir()
            for number in range(2):
                with ZipFile(raw / f"feed-{number}.zip", "w") as archive:
                    for name, contents in tables.items():
                        archive.writestr(name, contents)
            with operation(self.log, "compile"):
                result = combine(raw, Path(directory) / "schedules.duckdb", workers=2)
            self.assertEqual(result["feeds"], 2)
        records = self.records()
        workers = [r for r in records if r["event"] == "prepare_archive.started"]
        self.assertEqual(len(workers), 2)
        self.assertEqual({r["trace_id"] for r in records}, {records[0]["trace_id"]})
        self.assertNotEqual(workers[0]["span_id"], workers[1]["span_id"])
        parent = next(r["span_id"] for r in records if r["event"] == "combine.started")
        self.assertEqual({r["fields"]["parent_span_id"] for r in workers}, {parent})

    def test_scrappa_cache_and_transport_failures_are_private_and_do_not_retry(self):
        transport = Mock(
            return_value=(
                200,
                json.dumps({"success": True, "data": {"private": "private-payload"}}),
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            with ScrappaClient(
                Path(directory) / "cache.duckdb",
                api_key="private-key",
                transport=transport,
                clock=lambda: datetime(2026, 11, 14, tzinfo=timezone.utc),
            ) as client:
                first = client.request("places", {"query": "private-city"})
                second = client.request("places", {"query": "private-city"})
                self.assertEqual(first.response_id, second.response_id)
                transport.assert_called_once()
                transport.side_effect = OSError(
                    "https://private.example/?key=private-key"
                )
                for _ in range(2):
                    with self.assertRaises(ScrappaError):
                        client.request("places", {"query": "other-private-city"})
                self.assertEqual(transport.call_count, 2)
        names = [r["event"] for r in self.records()]
        for name in (
            "scrappa.cache_miss",
            "scrappa.cache_hit",
            "scrappa.http_request",
            "scrappa.response_archived",
            "scrappa.transport_failed",
        ):
            self.assertIn(name, names)
        for secret in (
            "private-key",
            "private-city",
            "private-payload",
            "private.example",
        ):
            self.assertNotIn(secret, self.output.getvalue())

    def test_api_correlates_worker_logs_and_rejected_requests_without_payloads(self):
        def search(settings):
            event(self.log, "worker.search")
            return []

        query = "query($input:RoundTripSearchInput!){round_trip_options(input:$input){stay_fit}}"
        settings = dict(
            departure_city="private-city",
            departure_date="2027-01-01T00:00:00Z",
            desired_arrival_date="2027-01-02T00:00:00Z",
            time_tolerance=0,
            transport_types=["TRAINS"],
            expenses_tolerance={"amount": "200", "currency": "EUR"},
        )
        with patch.dict(os.environ, {"APP_ACCESS_TOKEN": "private-token"}):
            client = TestClient(create_app(search))
            response = client.post(
                "/graphql",
                headers={
                    "Authorization": "Bearer private-token",
                    "X-Request-ID": "private-client-id",
                },
                json={"query": query, "variables": {"input": settings}},
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("errors", response.json())
            records = self.records()
            self.assertTrue(any(r["event"] == "worker.search" for r in records))
            self.assertEqual(
                {r["trace_id"] for r in records}, {response.headers["x-request-id"]}
            )
            self.assertEqual(len(response.headers["x-request-id"]), 32)
            rejected = client.post(
                "/graphql?secret-query",
                headers={"Authorization": "Bearer bad-token"},
                json={"query": "private-query"},
            )
            self.assertEqual(rejected.status_code, 401)
            self.assertNotEqual(
                rejected.headers["x-request-id"], response.headers["x-request-id"]
            )
        for secret in (
            "private-city",
            "private-token",
            "private-client-id",
            "private-query",
            "secret-query",
            "bad-token",
        ):
            self.assertNotIn(secret, self.output.getvalue())

    def test_api_failure_is_logged_without_exception_message(self):
        from test_graphql_api import INPUT, QUERY

        with patch.dict(os.environ, {"APP_ACCESS_TOKEN": "private-token"}):
            client = TestClient(create_app(Mock(side_effect=OSError("private-secret"))))
            response = client.post(
                "/graphql",
                headers={"Authorization": "Bearer private-token"},
                json={"query": QUERY, "variables": {"input": INPUT}},
            )
        self.assertEqual(response.status_code, 503)
        failures = [r for r in self.records() if r["event"] == "search.unavailable"]
        self.assertEqual(failures[0]["fields"]["error_type"], "OSError")
        self.assertNotIn("private-secret", self.output.getvalue())

    def test_concurrent_asgi_requests_and_cancellation_keep_context_isolated(self):
        async def run():
            both_started = asyncio.Event()
            seen = []

            async def app(scope, receive, send):
                seen.append(trace_id.get())
                if len(seen) == 2:
                    both_started.set()
                await both_started.wait()
                self.assertEqual(trace_id.get(), seen[scope["index"]])
                event(self.log, "concurrent.worker")
                await send(
                    {"type": "http.response.start", "status": 204, "headers": []}
                )
                await send({"type": "http.response.body", "body": b""})

            middleware = RequestTracingMiddleware(app)
            responses = [[], []]

            async def request(index):
                async def receive():
                    return {"type": "http.request", "body": b""}

                async def send(message):
                    responses[index].append(message)

                await middleware(
                    {
                        "type": "http",
                        "path": "/graphql",
                        "method": "POST",
                        "index": index,
                    },
                    receive,
                    send,
                )
                self.assertIsNone(trace_id.get())

            await asyncio.gather(request(0), request(1))
            self.assertEqual(len(set(seen)), 2)
            for index, messages in enumerate(responses):
                self.assertIn(
                    (b"x-request-id", seen[index].encode()), messages[0]["headers"]
                )

            async def cancelled(scope, receive, send):
                raise asyncio.CancelledError("private-secret")

            with self.assertRaises(asyncio.CancelledError):
                await RequestTracingMiddleware(cancelled)(
                    {"type": "http", "path": "/private-path", "method": "GET"},
                    None,
                    None,
                )
            self.assertIsNone(trace_id.get())

        asyncio.run(run())
        self.assertNotIn("private-secret", self.output.getvalue())
        self.assertNotIn("private-path", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
