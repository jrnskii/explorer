FROM ghcr.io/astral-sh/uv:python3.14-bookworm@sha256:73868e084ba4de5da1f7fb3c0cfa29edf93e1d965f9a1afe9a496fd6f97db574 AS build
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./backend/
RUN uv sync --project backend --locked --no-dev --no-install-project
COPY backend/src ./backend/src
RUN uv sync --project backend --locked --no-dev --no-editable

FROM python:3.14.8-slim-bookworm AS runtime
ENV PATH=/app/backend/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    GRAPHQL_SCHEMA_PATH=/app/shared/graphql/schema_v1.graphql APP_ENV=staging
WORKDIR /app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app && mkdir /cache && chown app:app /cache
COPY --from=build /app/backend/.venv /app/backend/.venv
COPY shared/graphql/schema_v1.graphql ./shared/graphql/schema_v1.graphql
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "backend.presentation.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header", "--limit-concurrency", "32", "--timeout-keep-alive", "5"]
