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

# Download all three external fixture datasets.
download-all-datasets: download-datasets

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
