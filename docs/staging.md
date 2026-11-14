# Staging deployment

The search path is browser → Next.js `/api/round-trip` → authenticated GraphQL API
→ local schedule/forecast ranking → Scrappa/Omio for **the best opportunity, with one runner-up fallback**.
No staging search uses mock schedules, preview itineraries or a five-city catalog.
The shared SDL remains `shared/graphql/schema_v1.graphql`.

If local dated schedules produce no candidates, search ranks supported reference
routes using the existing forecast models. It assigns evenly spaced request dates
within the trip window, considers up to eight legs, and verifies the best
city/mode/date path, then the second-best if verification fails. Reference times never become returned schedules: only actual
provider times and fares are returned for this fallback. Verification failure triggers at most one runner-up check; an over-budget
verified quote remains in results with an `over_budget` flag and does not trigger another check. A provider-advertised fare is not a
guaranteed checkout total. Cities without model coverage produce an explicit error.

Local development uses the existing `base_graph.pickle` and pricing
`forecast_models.json` artifacts by default; `REFERENCE_GRAPH_PATH` and
`FORECAST_MODELS_PATH` override them. For staging, copy the artifacts alongside
`schedules.sqlite` in `STAGING_DATA_DIRECTORY` (readable by UID 10001):

```sh
cp backend/src/backend/infrastructure/fixtures/data/base_graph.pickle /path/to/staging-data/base_graph.pickle
cp backend/src/backend/infrastructure/fixtures/data/pricing/forecast_models.json /path/to/staging-data/forecast_models.json
chmod a+r /path/to/staging-data/base_graph.pickle /path/to/staging-data/forecast_models.json
```

The graph is a trusted local NetworkX snapshot, built with the same locked backend
dependencies as the server. Missing reference artifacts disable the fallback with
an actionable coverage error; dated schedule searches continue to work.

## Prepare data

Install locked dependencies with `just setup`. Download/import real GTFS data with
`just download-schedules` and `just combine-schedules`, and prepare the forecast
artifact with `just extract-pricing` and `just train-pricing`. Then compile a serving
snapshot, from the repository root:

```sh
just prepare-schedules \
  --source backend/src/backend/infrastructure/fixtures/data/mobilitydatabase/schedules.duckdb \
  --catalog frontend/lib/data/europe-cities.json \
  --models backend/src/backend/infrastructure/fixtures/data/pricing/forecast_models.json \
  --output backend/data/staging/schedules.sqlite \
  --days 31
```

`--start YYYY-MM-DD` defaults to today; the compiled window is in UTC. The source
must be a closed, committed GTFS database. A committed `schedules.staging.duckdb`
checkpoint can also be specified explicitly, but contains only the feeds imported
so far; its feed fingerprints and coverage counts remain in the serving metadata.
The filename does not certify complete geographic coverage. Do not publish a file
while a source importer is still writing it.

The compiler publishes a small static connectivity index alongside dated offers,
so each request can load only the necessary city timetables. For a snapshot built
before serving indexes were added, run `just optimize-schedules /path/to/schedules.sqlite`.
This upgrades a copy and publishes it atomically, preserving its data timestamp.

The compiler applies weekday service, calendar exceptions, agency timezones and
GTFS extended-hour offsets. It excludes frequency services (including exact-times
frequency templates), ambiguous calendars, malformed/approximate stop times,
restricted boarding/alighting, unmapped pairs and services without forecast
coverage. Stops map conservatively to a unique nearby GeoNames city within 10 km.
Only adjacent mapped calls in different cities become candidate purchases; no
schedule is inferred across unknown calls. Coverage diagnostics report omissions.
Forecast prices are planning estimates for one adult, not purchasable GTFS fares.
There is no mock fallback. A failed build preserves the previously published file.

A compiler lock prevents concurrent writers. Each completed feed commits to a
`.schedules.sqlite.building` checkpoint. Interrupted builds resume with identical
source/catalog/model/window inputs; failed publication preserves the current
serving file. If inputs change, use a new output path or remove only the incomplete
`.building` checkpoint before rebuilding. Refresh source downloads, model artifacts and
serving snapshots on your deployment's data schedule, at least daily with the
default 86,400-second maximum serving snapshot age. Publishing a rebuilt snapshot
atomically updates subsequent readers; no API restart is required. Mount the
containing directory, not an individual inode, to preserve atomic updates.

## Configure and run

Create a git-ignored `.env.staging` with restricted permissions (`chmod 600`):

```dotenv
APP_ACCESS_TOKEN=<random shared secret of at least 32 characters>
SCRAPPA_API_KEY=<Scrappa API credential>
STAGING_DATA_DIRECTORY=/absolute/path/to/explorer/backend/data/staging
FRONTEND_PORT=3100
```

`APP_ACCESS_TOKEN` authenticates the Next.js server to the backend. It is injected
at runtime into both services, never a `NEXT_PUBLIC_` variable or build argument.
Keep the staging host behind the deployment's HTTPS/authenticated ingress. Only
the frontend's localhost port is published; backend traffic stays on the Compose
network. The compiler output must be named `schedules.sqlite` inside the mounted
data directory. Then run:

```sh
just staging
# Equivalent:
docker compose --project-name explorer-staging --env-file .env.staging \
  -f compose.staging.yml up --build -d --wait
```

Open `http://localhost:3100`. The images run production servers as non-root users.
The backend has a read-only root filesystem and schedule mount; its persistent
Scrappa cache is a separate writable volume. One Uvicorn worker and a process lock
serialize DuckDB cache writes; do not increase workers against the same cache.
The API bounds request bodies, query complexity, concurrent searches, snapshot
reads, graph traversal and provider calls. Timetables are loaded only for cities
actually explored. Price-first traversal uses a cost lower bound to stop after
retaining the best results; 100,000 states, 100,000 loaded services and 500,000
considered transitions remain explicit bounds. Any reached bound is returned in
GraphQL metadata and shown in the frontend. Startup/readiness fails on missing data,
invalid configuration or weak staging tokens. Never use the example placeholder.

`GET /healthz` is process liveness; `GET /readyz` validates token configuration and
snapshot readability/freshness. Neither endpoint returns credentials or paths.
The frontend waits for backend readiness. A stale snapshot makes readiness fail
and searches return a service error; it does not become an empty schedule.

## Price verification

Local ranking finishes before any provider access. Only cities and purchases on
the best retained opportunity are resolved and checked. The verifier may make a
places lookup per distinct selected city and a search/detail request per selected
purchase; it does **not** price every candidate itinerary. Cached responses are
reused within their TTL, retained across restarts, and failures are cached too.
Individual failed requests are not retried. Both candidates share a 180-second network budget
and at most 25 network calls. The Next.js upstream deadline is 240 seconds. Configure the staging ingress read timeout to at least 270 seconds.

Provider services must match city/mode/date/currency/passenger scope, be bookable,
and have available one-way fares. Actual departure/arrival times must still obey
ordering, connection buffers and the return window. The response labels the checked
opportunity `provider_advertised`; remaining options are `estimated` or
`adjusted_estimate`, with original forecasts retained separately in metadata.
If the best opportunity cannot be verified, the second-ranked candidate is checked.
If both fail, the frontend keeps dated schedule estimates explicitly labelled;
reference-only plans are never returned with invented times.

Scrappa/Omio advertises prices but does not certify every mandatory checkout fee;
`fees_verified` remains false. The adapter currently verifies direct bus, train and
flight purchases, not split tickets, bundled connections or ferries. Unsupported
verification fails explicitly. GTFS supplies ground/water schedules; the static
flight graph supplies connectivity only and is never converted into invented
flight departures. A flight schedule source must be integrated before flight-only
staging searches can produce genuine dated flight opportunities.

## Validate

```sh
bun run --cwd frontend test
bun run --cwd frontend lint
bun run --cwd frontend tsc --noEmit
bun run --cwd frontend build
uv run --project backend --locked python -m unittest discover -s backend/tests -v
```

Automated tests use deterministic local GTFS inputs and mocked provider boundaries;
they do not call billable services. An explicit staging search with real credentials
can consume credits, and checks its best opportunity and, on verification failure, the runner-up.
