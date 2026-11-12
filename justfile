# List available commands.
default:
    @just --list

# Install code-generation dependencies from the lockfiles (run mise install first).
setup:
    uv sync --project backend --locked
    bun install --cwd frontend --frozen-lockfile

# Generate Python models and TypeScript types from the v1 GraphQL schema.
codegen: codegen-python codegen-typescript

# Generate Pydantic v2 models for the backend.
codegen-python:
    uv run --project backend --locked datamodel-codegen \
        --input shared/graphql/schema_v1.graphql \
        --input-file-type graphql \
        --output backend/src/backend/generated/schema_v1.py \
        --output-model-type pydantic_v2.BaseModel \
        --target-python-version 3.14 \
        --extra-template-data shared/graphql/python-scalars.json \
        --additional-imports datetime,decimal \
        --graphql-no-typename \
        --formatters black isort \
        --disable-timestamp

# Generate schema types for the frontend.
codegen-typescript:
    bun run --cwd frontend codegen
