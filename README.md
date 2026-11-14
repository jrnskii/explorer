# Explorer — In this economy, we've made travelling cheap again

Explorer is a multi-weight graph optimization engine developed specifically for finding optimal closed-path routes under given constraints on logistics data.

## Tools used

- `mise-en-place` — dev environment manager
- `codegraph` — context compaction and code search (for free and locally!!!)
- `codex-cli` — AI-assisted code generation and refactoring

- `zed` — code editor with AI assistance
- `vscode` — code editor with AI assistance (used for ipynb)

## Under the hood

Libs, frameworks, and runtimes used at the foundation of Explorer project.

**Shared:**

- `just` — task runner for common commands
- `docker` — containerization and orchestration (TBD)
- `graphql` — API query language and schema
- `npx:skills` — LLM skill management

**Backend:**

- `networkx` — graph analysis and routing
- `duckdb` — analytical database for storage and querying
- `fastapi` — backend API server
- `pytest` — Python testing framework

**Frontend:**

- `bun` — JavaScript runtime and package manager
- `nextjs` — frontend framework
- `shadcn` — frontend component library
- `tailwindcss` — frontend styling framework
- `playwright` — end-to-end testing framework
- `npx:skills` — LLM skill management

And that's all basically.

## Tasks

Don't forget to run `mise install` and `just setup` after cloning the repository. It will install all dependencies and set up the environment.

```make
Available recipes:
    api port="8000"              # Authenticated GraphQL API; loads APP_ACCESS_TOKEN from the repository .env.
    build-base-graph *args       # Rebuild the complete static EU city graph, including city and transport weights.
    codegen                      # Generate Python models and TypeScript types from the v1 GraphQL schema.
    codegen-ignav                # Generate Pydantic v2 models from the Ignav OpenAPI schema.
    codegen-python               # Generate Pydantic v2 models for the backend.
    codegen-typescript           # Generate schema types for the frontend.
    combine-schedules *args      # Extract relevant rail/bus/ferry GTFS scheduling data into local DuckDB.
    default
    demo-round-trip *args        # Run the Vilnius round-trip demo with detailed action logs; accepts --seed.
    download-all-datasets        # Download all three external fixture datasets.
    download-datasets *args      # Download external fixture datasets; accepts --dataset and --output-dir options.
    download-schedules *args     # Download latest GTFS schedules for all European Mobility Database feeds.
    extract-pricing *args        # Extract local Schengen fares and GTFS fare rules into a separate DuckDB file.
    install                      # Install frontend dependencies
    optimize-schedules *args     # Atomically index an existing serving snapshot without repricing or changing its age.
    prepare-schedules *args      # Compile actual GTFS calendars and forecast prices into the serving snapshot.
    preview port="3000"          # Open http://localhost:3000/preview
    serve-base-graph port="8866" # Serve the base graph notebook as a standalone Voilà website.
    setup                        # Install code-generation dependencies from the lockfiles (run mise install first).
    staging                      # Build and start production servers for staging; requires a prepared schedule snapshot.
    test-omio *args              # Manual live Omio probe: just test-omio --date YYYY-MM-DD (uses API credits).
    train-pricing *args          # Fit independent flight/train/bus/ferry price models from extracted local data.
    update-flight-data           # The upstream generated JSON is large; this task downloads it without displaying it.
```
