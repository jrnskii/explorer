set shell := ["sh", "-cu"]

default:
    @just --list

# Install frontend dependencies
install:
    cd frontend && bun install

# Live preview of all components that have a components/**/*.preview.tsx file.
# Watches for added/removed previews and hot-reloads on every change.
# Open http://localhost:3000/preview
preview port="3000": install
    cd frontend && bun scripts/gen-previews.ts --watch & \
    pid=$!; trap 'kill $pid 2>/dev/null' EXIT INT TERM; \
    cd frontend && bun run dev -- --port {{ port }}

# Install code-generation dependencies from the lockfiles (run mise install first).
setup:
    uv sync --project backend --locked
    bun install --cwd frontend --frozen-lockfile

# Download external fixture datasets; accepts --dataset and --output-dir options.
[positional-arguments]
download-datasets *args:
    uv run --project backend --locked python -m backend.infrastructure.fixtures.download_datasets "$@"

# Manual live Omio probe: just test-omio --date YYYY-MM-DD (uses API credits).
[positional-arguments]
test-omio *args:
    uv run --project backend --locked python -m backend.presentation.cli.test_omio "$@"

# Run the Vilnius round-trip demo with detailed action logs; accepts --seed.
[positional-arguments]
demo-round-trip *args:
    uv run --project backend --locked python -m backend.presentation.cli.round_trip_demo "$@"

# Download all three external fixture datasets.
download-all-datasets: download-datasets

# Download latest GTFS schedules for all European Mobility Database feeds.
[positional-arguments]
download-schedules *args:
    uv run --project backend --locked python -m backend.infrastructure.fixtures.download_mobilitydatabase "$@"

# Extract relevant rail/bus/ferry GTFS scheduling data into local DuckDB.
[positional-arguments]
combine-schedules *args:
    uv run --project backend --locked python -m backend.infrastructure.fixtures.combine_mobilitydatabase "$@"

# Extract local Schengen fares and GTFS fare rules into a separate DuckDB file.
[positional-arguments]
extract-pricing *args:
    uv run --project backend --locked python -m backend.infrastructure.fixtures.extract_pricing "$@"

# Fit independent flight/train/bus/ferry price models from extracted local data.
[positional-arguments]
train-pricing *args:
    uv run --project backend --locked python -m backend.infrastructure.pricing.train "$@"

# Rebuild the complete static EU city graph, including city and transport weights.
[positional-arguments]
build-base-graph *args:
    uv run --project backend --locked python -m backend.presentation.cli.base_graph "$@"

# Serve the base graph notebook as a standalone Voilà website.
serve-base-graph port="8866":
    uv run --project backend --locked voila \
        --no-browser \
        --Voila.ip=127.0.0.1 \
        --Voila.port={{ port }} \
        backend/notebooks/01_eu_graph_visualization.ipynb

# Update the local development flight-route fixture from airline-route-data.
# The upstream generated JSON is large; this task downloads it without displaying it.
update-flight-data:
    curl --fail --location --output backend/src/backend/infrastructure/fixtures/data/airlines/airline_routes.json https://raw.githubusercontent.com/Jonty/airline-route-data/master/airline_routes.json

# Generate Python models and TypeScript types from the v1 GraphQL schema.
codegen: codegen-python codegen-typescript

# Generate Pydantic v2 models for the backend.
codegen-python:
    uv run --project backend --locked datamodel-codegen \
        --input shared/graphql/schema_v1.graphql \
        --input-file-type graphql \
        --output backend/src/backend/infrastructure/graphql/models.py \
        --output-model-type pydantic_v2.BaseModel \
        --target-python-version 3.14 \
        --extra-template-data shared/graphql/python-scalars.json \
        --additional-imports datetime,decimal \
        --graphql-no-typename \
        --formatters black isort \
        --disable-timestamp

# Generate Pydantic v2 models from the Ignav OpenAPI schema.
codegen-ignav:
    uv run --project backend --locked datamodel-codegen \
        --input docs/api_references/ignav/openapi.json \
        --input-file-type openapi \
        --output backend/src/backend/infrastructure/ignav/models.py \
        --output-model-type pydantic_v2.BaseModel \
        --target-python-version 3.14 \
        --enum-field-as-literal all \
        --use-standard-collections \
        --use-union-operator \
        --field-constraints \
        --strict-nullable \
        --extra-fields forbid \
        --formatters black isort \
        --disable-timestamp

# Generate schema types for the frontend.
codegen-typescript:
    bun run --cwd frontend codegen

# Authenticated GraphQL API; loads APP_ACCESS_TOKEN from the repository .env.
api port="8000":
    uv run --project backend --locked --env-file .env uvicorn backend.presentation.api:app --host 127.0.0.1 --port {{ port }}

# Compile actual GTFS calendars and forecast prices into the serving snapshot.
[positional-arguments]
prepare-schedules *args:
    uv run --project backend --locked python -m backend.infrastructure.schedules.build "$@"

# Build and start production servers for staging; requires a prepared schedule snapshot.
staging:
    docker compose --project-name explorer-staging --env-file .env.staging -f compose.staging.yml up --build -d --wait

# Atomically index an existing serving snapshot without repricing or changing its age.
[positional-arguments]
optimize-schedules *args:
    uv run --project backend --locked python -m backend.infrastructure.schedules.optimize "$@"
