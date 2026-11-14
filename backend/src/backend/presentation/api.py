"""Authenticated, bounded GraphQL transport using the shared v1 SDL verbatim."""

from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import secrets
import threading
from typing import Annotated, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from graphql import GraphQLError, build_schema, execute_sync, parse, validate
from graphql.language import Visitor, visit
from graphql.utilities import value_from_ast_untyped
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from backend.application.telemetry import event, operation, traced
from backend.domain.planning import SearchSettings
from backend.infrastructure.graphql.inputs import parse_settings
from backend.infrastructure.graphql.search import configured_search
from backend.infrastructure.logging import configure_logging
from backend.infrastructure.schedules.store import (
    SearchInputError,
    SearchResponse,
    SearchUnavailable,
)
from backend.presentation.tracing import RequestTracingMiddleware

logger = logging.getLogger(__name__)


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=16000)
    variables: dict | None = None
    operationName: str | None = None


class QueryBudget(Visitor):
    def __init__(self):
        super().__init__()
        self.depth = self.fields = self.searches = 0

    def enter_field(self, node, *_):
        self.depth += 1
        self.fields += 1
        if node.name.value == "round_trip_options":
            self.searches += 1
            if self.searches > 1:
                raise GraphQLError("Only one round-trip search is allowed per request.")
        if self.depth > 16 or self.fields > 200:
            raise GraphQLError("Query exceeds the supported complexity.")

    def leave_field(self, node, *_):
        self.depth -= 1


def create_app(search: Callable | None = None) -> FastAPI:
    schema_path = Path(
        os.environ.get(
            "GRAPHQL_SCHEMA_PATH",
            Path(__file__).resolve().parents[4] / "shared/graphql/schema_v1.graphql",
        )
    )
    schema = build_schema(schema_path.read_text())
    active = threading.BoundedSemaphore(2)
    configured = search

    def token():
        value = os.environ.get("APP_ACCESS_TOKEN", "")
        if not value.strip() or value == "change_in_prod":
            raise SearchUnavailable("API authentication is not configured.")
        if os.environ.get("APP_ENV") in ("staging", "production") and len(value) < 32:
            raise SearchUnavailable(
                "APP_ACCESS_TOKEN must contain at least 32 characters."
            )
        return value

    @asynccontextmanager
    async def lifespan(_app):
        nonlocal configured
        configure_logging()
        with operation(logger, "api.startup", level=logging.INFO):
            token()
            if configured is None:
                configured = configured_search()
        try:
            yield
        finally:
            event(logger, "api.shutdown", level=logging.INFO)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RequestTracingMiddleware)
    security = HTTPBearer(auto_error=False)

    def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ):
        try:
            expected = token()
        except SearchUnavailable as exc:
            event(logger, "auth.unconfigured", level=logging.ERROR)
            raise HTTPException(503, "API authentication is not configured.") from exc
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), expected.encode()
        ):
            event(logger, "auth.rejected", level=logging.WARNING)
            raise HTTPException(
                401, "Invalid access token", headers={"WWW-Authenticate": "Bearer"}
            )

    def string_scalar(value):
        if not isinstance(value, str):
            raise GraphQLError("DateTime and Decimal values must be JSON strings.")
        return value

    for name in ("DateTime", "Decimal"):
        scalar = schema.get_type(name)
        scalar.parse_value = string_scalar
        scalar.parse_literal = lambda node, variables=None: string_scalar(
            value_from_ast_untyped(node, variables)
        )
        scalar.serialize = string_scalar

    @traced
    def resolve_options(_root, info, input):
        context = info.context
        context["searches"] += 1
        if context["searches"] > 1:
            raise GraphQLError(
                "Only one round-trip search is allowed per request.",
                extensions={"code": "BAD_USER_INPUT"},
            )
        try:
            settings: SearchSettings = parse_settings(json.dumps(input))
        except (ValueError, TypeError, OverflowError) as exc:
            event(logger, "graphql.invalid_constraints", level=logging.DEBUG,
                  error_type=type(exc).__name__)
            raise GraphQLError(
                "Invalid round-trip constraints. Check dates, cities and transport modes.",
                extensions={"code": "BAD_USER_INPUT"},
            ) from exc
        try:
            service = configured if configured is not None else configured_search()
            event(logger, "search.started", level=logging.INFO,
                  departure_date=settings.departure_date.isoformat(),
                  return_before=settings.return_window[1].isoformat(),
                  currency=settings.expenses_tolerance.currency,
                  transport_types=[mode.value for mode in settings.transport_types])
            result = service(settings)
            if isinstance(result, SearchResponse):
                event(logger, "search.completed", level=logging.INFO,
                      result_count=len(result.options) + len(result.metadata.get("estimated_routes", [])),
                      estimated_result_count=len(result.metadata.get("estimated_routes", [])),
                      price_status=result.metadata.get("price_status"),
                      provider_attempts=result.metadata.get("provider_pricing_attempts", 0),
                      truncation_reasons=result.metadata.get("truncation_reasons", []))
                context["metadata"] = result.metadata
                return result.options
            return result  # Explicitly injected service in transport tests.
        except SearchInputError as exc:
            event(logger, "search.invalid_input", level=logging.DEBUG)
            raise GraphQLError(str(exc), extensions={"code": "BAD_USER_INPUT"}) from exc
        except Exception as exc:
            event(logger, "search.unavailable", level=logging.ERROR,
                  error_type=type(exc).__name__)
            raise GraphQLError(
                "Search is temporarily unavailable. Please try again later.",
                extensions={"code": "SERVICE_UNAVAILABLE"},
            ) from exc

    schema.query_type.fields["round_trip_options"].resolve = resolve_options

    @traced
    def execute(operation):
        context = {"searches": 0, "metadata": {}}
        try:
            document = parse(operation.query, max_tokens=2000)
            visit(document, QueryBudget())
            errors = validate(schema, document, max_errors=10)
            if errors:
                event(logger, "graphql.validation_failed", level=logging.DEBUG,
                      error_count=len(errors))
                return {"errors": [error.formatted for error in errors]}
            result = execute_sync(
                schema,
                document,
                variable_values=operation.variables,
                operation_name=operation.operationName,
                context_value=context,
            )
            payload = result.formatted
            event(logger, "graphql.executed", error_count=len(result.errors or ()),
                  search_count=context["searches"])
            if context["metadata"]:
                payload["extensions"] = context["metadata"]
            return payload
        except GraphQLError as exc:
            event(logger, "graphql.rejected", level=logging.DEBUG)
            return {"errors": [exc.formatted]}

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        try:
            token()
            service = configured if configured is not None else configured_search()
            if hasattr(service, "ready"):
                service.ready()
        except Exception as error:
            event(logger, "readiness.unavailable", level=logging.WARNING,
                  error_type=type(error).__name__)
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready"}

    @app.post("/graphql", dependencies=[Depends(authenticate)])
    async def graphql(request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 65536:
                raise HTTPException(413, "GraphQL request exceeds 64 KiB.")
        try:
            operation = Operation.model_validate_json(data)
        except ValidationError as exc:
            raise HTTPException(400, "Invalid GraphQL request envelope.") from exc
        if not active.acquire(blocking=False):
            event(logger, "graphql.capacity_rejected", level=logging.WARNING)
            return JSONResponse(
                {
                    "errors": [
                        {"message": "Search capacity is busy. Try again shortly."}
                    ]
                },
                status_code=503,
                headers={"Retry-After": "2"},
            )
        try:
            payload = await run_in_threadpool(execute, operation)
            unavailable = any(
                error.get("extensions", {}).get("code") == "SERVICE_UNAVAILABLE"
                for error in payload.get("errors", [])
            )
            return JSONResponse(
                payload,
                status_code=503 if unavailable else 200,
                headers={"Cache-Control": "no-store"},
            )
        finally:
            active.release()

    return app


app = create_app()
