"""Pure ASGI HTTP tracing with server-generated IDs and no request payload logging."""

import logging
from time import perf_counter
from uuid import uuid4

from backend.application.telemetry import event, operation, trace_id

logger = logging.getLogger(__name__)


class RequestTracingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = trace_id.set(uuid4().hex)
        status = 500
        # Unknown paths, query strings, client addresses and headers stay private.
        route = (
            scope["path"]
            if scope["path"] in ("/graphql", "/healthz", "/readyz")
            else "unmatched"
        )
        method = (
            scope["method"]
            if scope["method"] in ("GET", "POST", "HEAD", "OPTIONS")
            else "other"
        )
        level = logging.DEBUG if route in ("/healthz", "/readyz") else logging.INFO
        started = perf_counter()

        async def traced_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {
                    **message,
                    "headers": [
                        (k, v)
                        for k, v in message.get("headers", [])
                        if k.lower() != b"x-request-id"
                    ]
                    + [(b"x-request-id", trace_id.get().encode("ascii"))],
                }
            await send(message)

        try:
            with operation(logger, "http.request", level=level):
                try:
                    await self.app(scope, receive, traced_send)
                except BaseException as error:
                    event(
                        logger,
                        "http.error",
                        level=logging.ERROR,
                        error_type=type(error).__name__,
                    )
                    raise
                finally:
                    event(
                        logger,
                        "http.response",
                        level=logging.ERROR if status >= 500 else level,
                        method=method,
                        route=route,
                        status=status,
                        duration_ms=round((perf_counter() - started) * 1000, 3),
                    )
        finally:
            trace_id.reset(token)
