# Backend

## Architecture

Dependencies point inward: **presentation → infrastructure → application → domain**.
The application owns its output ports; adapters implement them without pulling
NetworkX, Pydantic, provider schemas, or CLI concerns into the core.

```text
src/backend/
├── domain/                  # Immutable fare values and transport modes (stdlib only)
├── application/             # Fare-graph use case and FareGraphWriter port
├── infrastructure/
│   ├── fixtures/            # Offline Ignav, random, and fixed EU dataset generators
│   ├── ignav/               # Generated provider models, validation, mapping, composition
│   ├── graphql/             # Generated shared GraphQL contract models
│   └── graphs/              # NetworkX fare graph writer and weighted graph adapter
└── presentation/cli/        # Argument parsing, JSON output, and exit handling
```

`infrastructure.ignav.graph.ignav_to_graph` validates and normalizes provider data,
then calls `application.fare_graph.populate_fare_graph` with a NetworkX writer.
The same use case can target a different graph library by implementing
`application.ports.FareGraphWriter`. Generated wire models stay outside the domain;
GraphQL and domain transport enums share wire values but are independent types.
Provider prices retain their existing float contract; weighted travel costs remain
`Decimal`. This reorganization does not change either serialization contract.

The fixture envelopes (including `MockFlightNetwork.to_graph`) remain infrastructure
DTOs: they intentionally use Ignav models and NetworkX, not domain entities.
There is no live provider adapter, repository, HTTP API, or persistence layer yet;
none is invented by this layout. Future entry points should compose adapters around
application use cases rather than putting business logic in transport handlers.

Use the canonical imports shown below. Legacy flat modules and the `mock`,
`graphutils`, `models`, and `generated` packages have been removed; old Python
imports and module CLI paths are no longer supported. Migrate callers as follows:

| Removed path                                                                         | Canonical path                                 |
| ------------------------------------------------------------------------------------ | ---------------------------------------------- |
| `backend.ignav`, `backend.graphutils.ignav`                                          | `backend.infrastructure.ignav.graph`           |
| `backend.weighted_graph`, `backend.graphutils.weighted_graph`                        | `backend.infrastructure.graphs.weighted_graph` |
| `backend.mock_ignav`, `backend.mock.mock_ignav` (fixtures)                           | `backend.infrastructure.fixtures.ignav`        |
| `backend.mock_network`, `backend.mock.mock_network`                                  | `backend.infrastructure.fixtures.network`      |
| `backend.mock_eu_flights_network`, `backend.mock.mock_eu_flights_network` (fixtures) | `backend.infrastructure.fixtures.eu_network`   |
| `backend.generated.ignav`, `backend.models.ignav`                                    | `backend.infrastructure.ignav.models`          |
| `backend.generated.schema_v1`, `backend.models.schema_v1`                            | `backend.infrastructure.graphql.models`        |
| `backend:main`                                                                       | `backend.presentation.cli.backend:main`        |

For module CLI invocations, use `python -m backend.presentation.cli.mock_ignav`
or `python -m backend.presentation.cli.eu_network`. The installed `backend` and
`mock-ignav` commands remain available. `just codegen-python` and
`just codegen-ignav` target the infrastructure model files. Architecture tests
prevent reintroducing retired modules, enforce dependency direction, and ensure
the core imports without third-party packages.

## Download external reference datasets

The downloader in `src/backend/infrastructure/fixtures/download_datasets.py` uses
`kaggle` for `headsortails/train-stations-in-europe` and
`rohitgrewal/airlines-flights-data`, and `huggingface_hub` for
`WorkWithData/cities`. Both libraries are already backend dependencies.

Run from the repository root:

```sh
# Download all three datasets.
just download-all-datasets
# Equivalent: just download-datasets

# Download selected datasets into another directory.
uv run --project backend --locked python -m backend.infrastructure.fixtures.download_datasets \
  --dataset train-stations cities --output-dir ./reference-data
```

By default, files go into the git-ignored `data/` folder beside the script, under
`train-stations/`, `airlines/`, and `cities/`. Kaggle archives are extracted;
Hugging Face repository files retain their directory structure, including local
cache metadata. Custom output directories are not automatically git-ignored.

For Python callers, `download_all_datasets(output_dir=...)` in the downloader
module returns a mapping of dataset names to `Path` objects. It stops on the first
failure and retains completed downloads. The explicit `six` dependency supports
Kaggle 2.2.5, which imports it without declaring it as a dependency.

Configure Kaggle authentication with `KAGGLE_API_TOKEN`,
`~/.kaggle/access_token`, or legacy `~/.kaggle/kaggle.json` credentials. Hugging
Face uses `HF_TOKEN` or a stored login when authentication is needed; public
ungated datasets can be downloaded anonymously. Never commit credentials.

Downloads make live requests to Kaggle/Hugging Face and consume network and disk
space; provider access restrictions and rate limits apply. They retrieve the
current upstream versions, not pinned reproducible snapshots. Reruns use the
libraries' existing-file/cache behavior (Kaggle may download again after archive
extraction). No files are deleted on failure. Exit status is 1 on download
failure, with diagnostics on stderr; a successful run prints a JSON mapping of
dataset names to local directories on stdout. These are external reference data,
not live travel availability. Check each dataset's license before use or redistribution.

## European public-transport schedules (Mobility Database)

Run `just download-schedules` to fetch the latest available GTFS Schedule ZIP for
every catalogued feed with a European location. Set
`MOBILITYDATABASE_REFRESH_TOKEN` from your Mobility Database account, or set
`MOBILITYDATABASE_ACCESS_TOKEN` for an existing bearer token. Refresh tokens are
exchanged at `/v1/tokens`; an expired access token is retried once after refresh
when a refresh token is available. Credentials are read only from the environment.

```sh
just download-schedules
just download-schedules --output-dir ./reference-data/schedules --page-size 500 --timeout 120
# Extract relevant rail/bus/ferry scheduling data into DuckDB:
just combine-schedules
just combine-schedules --raw-dir ./reference-data/schedules/raw --output ./schedules.duckdb
# Equivalent entry point:
uv run --project backend --locked python -m backend.infrastructure.fixtures.download_mobilitydatabase
```

The default destination is the git-ignored
`backend/src/backend/infrastructure/fixtures/data/mobilitydatabase/`. It contains
`catalog.json` (selected feed metadata, including locations, source/license details,
and service ranges where supplied), `raw/<feed-id>.zip` (unextracted schedules), and
`manifest.json` (per-feed download outcomes and dataset metadata). Catalogue requests
are paginated until exhausted, and feeds are deduplicated by ID rather than provider.
Public hosted archives receive no API credentials. Downloads are streamed, checked
as ZIPs, and SHA-256 verified when a hash is supplied before replacing existing files.
Reruns reuse files matching the latest dataset hash; files without a hash download again.

`just combine-schedules` writes `schedules.duckdb`. It retains rail, bus and
ferry routes and referenced trips, stop times, stops (including station ancestors),
calendars, frequencies, agencies and transfers. Shapes, bike attributes,
unsupported modes, arbitrary files and binaries are skipped. Columns are an
explicit scheduling projection, stored as VARCHAR with SQL NULL for missing
values; IDs and times after 24:00:00 are preserved. Join source IDs using `feed_id`
as well as the ID. Fare evaluation and canonical city mapping are separate work.
See the [schema and recovery description](../docs/api_references/mobilitydatabase/README.md).

Completed feeds commit transactionally to `schedules.staging.duckdb`; rerun the
same command to resume unchanged feeds. Changed feeds are replaced, removed feeds
are dropped after a successful run, and malformed relevant data fails the feed.
The current feed rolls back on interruption; other completed feeds survive.
Only a successful complete run atomically replaces the published database.
Keep readers closed during publication and reopen afterward. Legacy JSON outputs
and checkpoints are left untouched and are not reused. Stdout remains a JSON
command summary; diagnostics and progress go to stderr. No provider calls occur
during extraction.

Feed extraction uses a bounded thread pool (default: up to four workers). Use
`just combine-schedules --workers 8` to change it, or `--workers 1` for serial
extraction. Each worker has an isolated temporary DuckDB file, one DuckDB query
thread, and a 256 MB query-memory limit (not a total process-memory limit).
Temporary files/spill space grow with active feeds. A single coordinator merges
results transactionally into the staging database in archive order; completed
feeds still checkpoint independently, and failed feeds do not prevent the other
results from being saved. In-flight work finishes before temporary cleanup on
interruption, so shutdown may wait for an active feed.


Europe uses the explicit `EUROPE_COUNTRY_CODES` set in the script: European states
and dependencies, including the UK, Switzerland, Kosovo, Cyprus, the Caucasus, and
transcontinental Russia, Turkey, and Kazakhstan. Any matching location includes the
whole feed, including cross-border services. Feeds without matching country metadata
are excluded. All feed statuses are included and retained in `catalog.json`; this
includes potentially obsolete schedules. This downloads one latest dataset per feed,
not historical versions, GTFS Realtime, or GBFS. Coverage is limited to feeds listed
and hosted by Mobility Database, not every provider operating in Europe.

A missing hosted dataset is marked `unavailable`. Individual failures are recorded
as `failed` and downloading continues; completed archives remain intact. The manifest
is updated after each feed. Exit status is 1 for catalogue failures or any unavailable
or failed feed, 2 for invalid CLI arguments, and 0 for complete success (including an
empty selection). A completed catalogue run prints JSON counts and the output path to
stdout; diagnostics go to stderr. Rerun to retry failures. Network requests use a
finite timeout; failures other than token expiry are not automatically retried.
These are current upstream snapshots, not pinned fixtures or live availability.
Respect the individual feeds' licenses when using or redistributing the data.

## Static EU flight network

`backend.infrastructure.fixtures.eu_network.generate_network()` returns a fixed EU-27
fixture: **81 cities, 324 directed routes, and 648 flights**. Each member state
has its capital and two major non-capital cities. Population rankings vary by
city/municipality boundaries and census year; the catalog is representative,
not an authoritative ranking. Non-EU European countries are outside this fixture.

```python
from backend.infrastructure.fixtures.eu_network import generate_network

network = generate_network()  # No seed or current-date dependency.
graph = network.to_graph()
```

Export JSON from the repository root:

```sh
uv run --project backend --locked python -m backend.presentation.cli.eu_network > eu-network.json
```

Every city connects to both domestic peers, the next capital in a fixed EU
backbone, and the closest remaining foreign city. The route graph is strongly
connected. Each route departs at 08:00 and 17:00 origin-local time on 2026-01-01;
static connectivity does not guarantee time-feasible journeys. Durations and
USD fares are fixed distance-based mock values. The result uses the same
`MockFlightNetwork` models, JSON format, and graph attributes described below.

Coordinates denote city centers rather than airports. Codes containing digits
are fictional stand-ins for cities without a distinct airport in this catalog.
All airport names, routes (including very short domestic hops), schedules,
carriers, and fares are explicitly synthetic, not claims of real availability.
Every call returns independent mutable models.

## Random airport and flight networks

Use `backend.infrastructure.fixtures.network.generate_network` for graph optimization datasets.
Unlike the small fixed catalog in the Ignav search fixtures below, this mode
randomly generates **100 synthetic airports by default**, including unique
three-letter codes, names, coordinates, countries, and IANA timezones.

```sh
# From the repository root: 100 airports, 400 routes, 5,600 flights.
uv run --project backend --locked mock-ignav network --seed 42 > network.json

# Larger network: 250 airports, 1,500 routes, 63,000 flights.
uv run --project backend --locked mock-ignav network \
  --seed 42 --airports 250 --routes-per-airport 6 \
  --flights-per-route 3 --days 14 --start-date 2026-12-01 > network.json
```

Each airport has exactly `routes_per_airport` distinct outgoing routes. A random
cycle through every airport guarantees **strong connectivity**: all airports are
reachable from every other airport, including when there is only one outgoing
route per airport. Additional routes are sampled randomly without duplicates or
self-loops. Every route gets `flights_per_route` random departures per
origin-local day.

```python
from datetime import date
from pathlib import Path
import networkx as nx
from backend.infrastructure.fixtures.network import generate_network, MockFlightNetwork

network = generate_network(
    seed=42,
    airport_count=150,
    routes_per_airport=5,
    flights_per_route=2,
    start_date=date(2026, 12, 1),
    days=7,
)
graph = network.to_graph()  # Directed MultiDiGraph: one edge per flight.
assert nx.is_strongly_connected(graph)
source, target = network.airports[0].code, network.airports[-1].code
path = nx.shortest_path(graph, source, target, weight="price")

Path("network.json").write_text(network.model_dump_json(indent=2))
restored = MockFlightNetwork.model_validate_json(Path("network.json").read_text())
```

The JSON envelope contains `airports`, `locations` keyed by airport code,
`flights`, and generation parameters. Each flight contains a unique `id`, an
Ignav `SegmentModel`, and an Ignav `PriceModel`. The envelope and coordinate
metadata are local dataset extensions, not an Ignav endpoint response.

Graph node attributes include airport fields and location metadata. Each edge
is keyed by flight ID and includes numeric `price` (also the default `weight`),
`currency`, `duration_minutes`, UTC departure/arrival strings, and a complete
`segment` dictionary. Parallel flights are preserved rather than collapsed.

**Important for optimization:** connectivity is a property of the route graph,
not a guarantee that a time-feasible journey exists inside the finite schedule.
The static shortest-path example above ignores departure times and layovers.
For itinerary optimization, enforce UTC arrival/departure ordering and minimum
connection times using the individual flight edges.

Generation is reproducible for the same parameters and seed. Airport locations
and topology stay unchanged when schedule parameters change. Coordinates are
jittered regional approximations; names, schedules, carriers, and USD fares are
synthetic. Times are DST-aware, durations are distance-based, and fares are
positive and marked `unverified`.

Limits: 2–17,576 airports; 1–(`airport_count` − 1) outgoing routes per airport;
1–24 daily flights per route; 1–366 days; at most 1,000,000 total flights. The
flight count is `airport_count × routes_per_airport × flights_per_route × days`.
Defaults are 100 airports, 4 routes, 2 flights per route per day, 7 days, starting
2026-01-01. For fewer than five airports, reduce `routes_per_airport` explicitly.
Large datasets consume memory proportional to the flights generated.

## Convert Ignav API output to a graph

```python
from backend.infrastructure.ignav.graph import ignav_to_graph

# Accepts response.json(), raw JSON text/bytes, or a generated Ignav model.
graph = ignav_to_graph(payload)
```

Supports fare `search`, `one-way`, and `round-trip` responses. The result is a
fresh NetworkX `MultiDiGraph`: airport codes are nodes, and each flight segment
occurrence is an edge. Keys are `(itinerary_index, leg_index, segment_index)`,
so parallel flights and offers with missing/repeated Ignav IDs are preserved.
Requested airports remain as nodes even when there are no fares.

Edges expose all segment fields, a detached `segment` dictionary, `ignav_id`,
index references, `cabin_class`, and the complete `itinerary_price` dictionary.
The default `weight` is **flight duration in minutes**, excluding layovers.
Ignav reports bundled itinerary fares, not individual segment fares: do not sum
`itinerary_price` across edges or treat segments as independently bookable.
Static graph paths also do not enforce schedule feasibility or connection times.
The graph retains `observed_at`; invalid payloads raise validation errors.

## Mock Ignav data

`backend.infrastructure.fixtures.ignav.MockIgnavGenerator` generates offline fixtures matching
[`openapi.json`](../docs/api_references/ignav/openapi.json). It makes no network
requests, needs no API key, and returns generated Pydantic models. This is a data
generator, not an HTTP server or a replacement for live fare availability.

### Python usage

```python
from backend.infrastructure.fixtures.ignav import MockIgnavGenerator

ignav = MockIgnavGenerator(seed=42, count=12)
result = ignav.round_trip({
    "origin": "WAW",
    "destination": "LHR",
    "departure_date": "2026-12-10",
    "return_date": "2026-12-17",
    "max_stops": 0,
    "adults": 2,
    "checked_bags": 1,
})
payload = result.model_dump(mode="json")
booking = ignav.booking_links({"ignav_id": result.itineraries[0].ignav_id})
```

Methods accept request dictionaries or their corresponding generated models:

| Method                    | Ignav operation                                    |
| ------------------------- | -------------------------------------------------- |
| `health()`                | `GET /api/health`                                  |
| `airports(q, limit=10)`   | `GET /api/airports`                                |
| `search(request)`         | `POST /api/fares/search` (one or two ordered legs) |
| `one_way(request)`        | `POST /api/fares/one-way`                          |
| `round_trip(request)`     | `POST /api/fares/round-trip`                       |
| `cheapest_dates(request)` | `POST /api/fares/cheapest-dates`                   |
| `booking_links(request)`  | `POST /api/fares/booking-links`                    |

### JSON CLI

Run from the repository root. First create a JSON request file, for example
`request.json`:

```json
{
  "origin": "WAW",
  "destination": "LHR",
  "departure_date": "2026-12-10",
  "max_stops": 0
}
```

```sh
uv run --project backend --locked mock-ignav one-way --seed 42 --count 12 --request request.json
uv run --project backend --locked mock-ignav health
```

Output is JSON on stdout, so it can be redirected to a fixture file. Invalid
requests exit with status 2 and an explanation on stderr. The module entry point
also works: `uv run --project backend --locked python -m backend.presentation.cli.mock_ignav health`.
For airports, the request file contains `{"q": "Warsaw", "limit": 10}`. Other
operations use the request body in the OpenAPI reference.

### Fixture behavior and limits

- A seed and request produce repeatable results, independent of call order.
  `count` (1–100, default 8) controls candidates **before filtering**. Narrow
  filters can legitimately return fewer results or no results.
- Fixtures include direct, one-stop, two-stop, and mixed-carrier options; airline,
  stop, price, and inclusive airport-local departure/arrival hour filters are
  applied. Narrowing filters does not regenerate the candidate pool.
- Segment UTC and local times use IANA zones, including DST. Durations are
  synthetic distance-based estimates; connections have 90-minute layovers.
  Flights, schedules, carrier routes, and aircraft are not real-world availability.
- Supported airports: JFK, LAX, ORD, LHR, CDG, AMS, FRA, WAW, WMI, KRK, BCN,
  FCO, DXB, HND, SIN. Use `airports("", limit=20)` to inspect the catalog.
  Unsupported airport codes raise `ValueError` rather than inventing locations.
- All prices are synthetic party totals in USD, regardless of `market`, and are
  marked `unverified`. Cabin, seated travelers, lap infants, and requested bags
  affect estimates. Zero, null, and omitted bag counts all mean no preference.
- `observed_at` defaults to `2026-01-01T00:00:00Z` for stable fixtures. Pass an
  aware `datetime` to the constructor to override it; timestamps do not imply
  live freshness.
- Cheapest-date windows are inclusive, ordered, and limited to 366 dates. Omit
  `stay_days` for one-way prices; a value of zero means a same-day return.
  Dates without matching candidates have a null price. Non-null prices are the
  minimum of the equivalent fare search using the same seed and count.
- Booking IDs live only in the generator instance that performed the search.
  Both directional and ordered-leg booking response shapes are supported.
  For a standalone booking CLI request, provide `origin`, `destination`, and
  `departure_date`, plus optional `return_date`. Optional carrier/flight-number
  pairs select synthetic direct flights from the supported carrier catalog.
  Booking URLs use the reserved `.example` domain and are deliberately nonfunctional.
- Schema errors raise Pydantic `ValidationError`; cross-field errors (such as
  reversed dates, invalid time bounds, or more bags than seated travelers) raise
  `ValueError`. Provider authentication, billing, rate limits, and upstream error
  scenarios are not simulated.

### Regenerate models and run tests

From the repository root:

```sh
just codegen-ignav
uv run --project backend --locked python -m unittest discover -s backend/tests -v
```

`backend/src/backend/infrastructure/ignav/models.py` is generated; do not edit it manually.
The existing GraphQL code-generation commands remain separate and unchanged.

## Reference city base graph

Build the offline, fare-free EU-27 city multigraph directly into a native binary
snapshot, optimized for loading the whole graph into Python/NetworkX:

```sh
just build-base-graph
# Equivalent command:
uv run --project backend --locked python -m backend.presentation.cli.base_graph
```

The default output is `base_graph.pickle` under the fixture data directory. It uses
pickle protocol 5 and directly preserves the NetworkX graph, including shared
adjacency/attribute references, without constructing or decoding a node-link JSON
tree. For smaller storage, use `--output PATH.pickle.zst` (Zstandard level 1).
The uncompressed `.pickle` format is the default because full-graph loading was
fastest in the local benchmark. These are Python caches, not a language-neutral
interchange format or a replacement for an indexed database for selective queries.

```python
from pathlib import Path
from backend.infrastructure.catalog.graph_snapshot import load_base_graph

graph = load_base_graph()  # Default base_graph.pickle; structurally frozen.
# graph = load_base_graph(Path("reference-data/base_graph.pickle.zst"))
```

Historical schema-3 full-snapshot benchmark (20,934 cities, 999,686 parallel connections):

| Format | File size (MB) | Full graph load (s) | Peak RSS (MiB) |
| --- | ---: | ---: | ---: |
| Node-link JSON | 790.1 | 7.859 | 2933.8 |
| Native pickle (default) | 463.8 | 0.820 | 1745.1 |
| Zstandard pickle | 58.7 | 1.465 | 1746.6 |

Measured once per format in separate Python 3.14 processes using the repository
loaders and a warm filesystem cache. Timing includes graph reconstruction; peak
RSS includes the interpreter and imports. These are local measurements, not
portable latency guarantees. Both binary files preserve the same snapshot ID,
weights, parallel edges, isolated cities, and unknown travel times.

Snapshot files are trusted local caches. The loader restricts reconstructed
pickle globals to the NetworkX types used here, validates the container/version,
and rejects incompatible NetworkX versions. Do not load externally supplied pickle
files; regenerate caches after changing NetworkX. Graph attributes remain mutable
and should be treated as read-only. No new dependencies are required; compression
uses Python 3.14's standard library.

Migrate an existing JSON snapshot once, without rebuilding source data:

```sh
uv run --project backend --locked python -m backend.presentation.cli.base_graph \
  --from-json backend/src/backend/infrastructure/fixtures/data/base_graph.json \
  --output backend/src/backend/infrastructure/fixtures/data/base_graph.legacy.pickle
# Optional smaller output:
uv run --project backend --locked python -m backend.presentation.cli.base_graph \
  --from-json backend/src/backend/infrastructure/fixtures/data/base_graph.json \
  --output backend/src/backend/infrastructure/fixtures/data/base_graph.legacy.pickle.zst
```

JSON migration preserves the original file and its existing semantic schema; it
does not enrich older graphs with new fields. Rebuild from sources with
`just build-base-graph` to get all current fields, even when the old snapshot is
lost. The current graph semantic schema is version 4; the binary storage container
has its own version 1. Writes use a same-directory staging file and atomic
replacement so interrupted/failed writes
do not truncate an existing snapshot. Stdout is a small JSON summary containing
`output`, `nodes`, `edges`, and `snapshot_id`; progress and errors go to stderr.
Missing/invalid inputs exit with status 1; invalid CLI options exit with status 2.

The default source inputs remain `cities/Cities.csv`, `airline_routes.json`,
`train-stations/train_stations_europe.csv`, and
`mobilitydatabase/schedules.staging.duckdb` under the fixture data directory.
Override them with `--cities`, `--routes`, `--stations`, and `--schedules`.
`--air-only` imports just the city CSV and airport routes. `--from-json` cannot
be combined with source import options. For Python source imports:

```python
from backend.infrastructure.catalog.base_graph import build_base_graph
from backend.infrastructure.catalog.graph_snapshot import save_base_graph

graph = build_base_graph()
save_base_graph(graph)
```

All city rows in the 27 EU member countries are included, even without connections.
Station catalog rows explicitly marked `is_city` supplement missing city names.
This is coverage of the available snapshots, not a claim that every real EU
settlement is catalogued. The scope uses source country labels, including any
outlying locations assigned those countries; it is not a territorial boundary
polygon. Python callers can select a custom `countries` frozenset. Station ISO
code translation currently covers EU-27 only.

Cities are **nodes**; transport connections are edges. Every city node has two
filterable weight attributes, listed in graph metadata as `node_weight_attributes`:

| Attribute | Type | Meaning |
| --- | --- | --- |
| `population` | nonnegative integer or `None` | Source population from `Cities.csv`; unknown for station-only cities without a matched population record. |
| `attractiveness` | number | Defaults to `1` for every city, including isolated and station-only cities. This is a neutral default, not a measured tourism score. |

Zero population is preserved and differs from an unknown population. Graph
metadata includes `default_attractiveness=1` and `cities_without_population`.
City weights are separate from the edge `weight_attributes` (`distance_km` and
`travel_time_minutes`), and survive both binary snapshot formats.

```python
selected = [
    city_id
    for city_id, city in graph.nodes(data=True)
    if city["population"] is not None
    and city["population"] >= 100_000
    and city["attractiveness"] >= 1
]
filtered_graph = graph.subgraph(selected)  # Retains parallel routes between selected cities.
```

The source builder applies the attractiveness default after all city sources have
been imported. A fresh `just build-base-graph` reconstructs the complete EU graph
with city identities, source populations, default attractiveness, terminal
associations, both transport weights and their provenance, diagnostics, and source
checksums. It does not read or depend on any pre-existing graph snapshot. Use
`just build-base-graph --output PATH.pickle.zst` for a compressed full rebuild.

City IDs hash country, name and coordinates and survive row reordering. Airports
map only to unique normalized city/country names, or explicit reviewed
`airport_city_overrides={iata: city_id}`. Station terminals use explicit catalog
parent-city associations when available, otherwise the nearest city in their
country within 10 km. GTFS stops use the nearest in-scope city within 10 km;
GTFS does not supply a stop country, so this geographic association can cross
country borders. Tied nearest matches and invalid coordinates remain unmapped.
These heuristic associations are labeled and are not verified terminal catchments.

The directed `MultiDiGraph` preserves separate airport/carrier connections and
separate GTFS feed/route connections for each city pair. GTFS base and extended
rail, coach/bus and water transport types produce `TRAINS`, `BUSSES`, and `FERRIES`
edges alongside `PLANES`. Each trip is ordered by numeric stop sequence; only
adjacent mapped stops in different cities establish a connection. Unmapped stops
and ambiguous duplicate sequences do not create shortcuts. Trips with invalid
sequence numbers are excluded. Duplicate services collapse into static route
connectivity, and no reverse service is invented. The station list alone does
not establish rail connections.

Edges now have two independent numeric weight attributes:

| Attribute | Unit | Meaning |
| --- | --- | --- |
| `distance_km` | kilometres | Great-circle distance between city centres. |
| `travel_time_minutes` | minutes | Minimum valid reference/scheduled ride duration for that connection; null when unknown. |

Parallel edges retain separate transport modes, carriers, and GTFS routes. The
snapshot schema is version 4 and `weight_attributes` lists both attributes.
Air edges use the source route's `min` field, documented as flight minutes in the
[airline-route-data contract](https://github.com/Jonty/airline-route-data#readme).
The reference duration applies to the airport pair; it is not carrier-specific
schedule availability. Repeated listings use the minimum valid duration.

Rail, bus, and ferry times use the minimum nonnegative destination-arrival minus
origin-departure duration across consecutive stops mapped to different cities,
within each feed/route/direction. This is the ride between the last stop in the
origin city and the first stop in the next city, not city-centre access time.
`travel_time_basis` identifies `airline_route_reference_minutes`,
`gtfs_min_scheduled_stop_pair`, or `unknown`; `travel_time_samples` counts valid
source observations, not calendar-weighted service frequency. No speed-based
duration estimates are fabricated. Missing/invalid times remain null without
removing the connection; valid zero durations are preserved.

GTFS time parsing preserves hours beyond 24 and uses service-day offsets in the
agency time zone, rather than converting stops' wall-clock times or assuming
that midnight resets the trip. A missing arrival/departure may use the other
field at that same stop, as allowed by the
[GTFS stop-times contract](https://gtfs.org/documentation/schedule/reference/#stop_timestxt).
Malformed values, overflow, and negative leg durations are excluded from duration
aggregation. Source times may themselves be interpolated. Calendars and dates
are not evaluated, so these values do not assert availability on any date.

To route by time, select `travel_time_minutes` as the weight and exclude edges
where it is null. Do not substitute a default numeric weight for unknown times.
Independent minima across edges need not belong to compatible trips. Static path
sums exclude waiting, transfers, check-in, boarding, and terminal access; they are
not door-to-door or time-feasible itinerary durations. `distance_km` remains
straight-line geography rather than road/track length. Graph metadata reports
`connections_without_travel_time` and `travel_time_includes_waiting=false`.

There are no fares, currencies, departure/arrival timestamps, or service dates in
the export. Raw GTFS clock times are used only to derive static duration weights.
The available `airlines_flights_data.csv` contains Indian fare observations and is
not an EU route source. Edge provenance uses `data_source` so it survives node-link
serialization, which reserves `source` for the origin node ID.

GTFS extraction runs one feed at a time against a read-only DuckDB connection,
using SQL aggregation and batched result reads instead of loading all stop times
into Python. The staging database may be incomplete; only its committed feed
snapshots are imported. Do not run extraction concurrently with a writer. Metadata
includes feed count, source checksums (GTFS uses the ordered source archive hashes),
static weight attributes, mapping counters/issues, terminals, isolated cities,
and connections without reverse adjacency. Snapshot IDs include all selected
source fingerprints and the EU/custom scope.

These are unverified reference connections, not time-feasible itineraries or
current availability. `live_search_eligible` is false. Publication dates and rights
have not been verified. Graph structure is frozen; attribute dictionaries remain
mutable and should be treated as read-only. Binary reloads are structurally frozen; legacy node-link JSON reloads are mutable by default.

## Visualize the base graph

The `notebooks/01_eu_graph_visualization.ipynb` notebook loads the local
`base_graph.pickle` snapshot, collapses parallel connections into unique
directed city routes, and renders the result with the GPU-accelerated
Cosmograph widget. Open it with the backend environment after generating the
snapshot:

```sh
just setup
uv run --project backend jupyter notebook backend/notebooks/01_eu_graph_visualization.ipynb
```

To run it as a standalone website instead of opening Jupyter:

```sh
just serve-base-graph
```

Then open <http://127.0.0.1:8866>. Voilà executes the notebook on the server
and serves the Cosmograph widget without involving the frontend application.

## Cheapest scheduled round trips (offline core)

Run the first offline slice with v1 GraphQL-shaped JSON settings:

```sh
uv run --project backend --locked python -m backend.presentation.cli.round_trip \
  --request backend/examples/round_trip.json --seed 42 --max-results 10
```

The CLI emits a JSON envelope with `options` shaped as `RoundTripOption`, exact
string amounts, `from` aliases, synthetic provenance, explored-state count,
`truncation_reasons`, and `results_limited`. Invalid input/provider coverage exits
with status 2 and diagnostics on stderr. This is a CLI, not an executable GraphQL
server; output is validated against the shared schema and generated models.

The provider-independent `application.round_trip_search.find_round_trips` accepts
validated `domain.planning.SearchSettings` and a finite snapshot of independently
purchasable `JourneyOffer` values. Future adapters can implement
`application.ports.JourneyOfferProvider` without changing traversal. Each offer
can contain multiple physical legs, but its price is counted once. Internal
connections participate in excluded/mandatory city checks. Under v1, endpoint
presence constitutes a visit; no minimum stay is inferred. Branches end on their
first return home. Previously visited cities are skipped per itinerary by default,
including internal ticket connections; the final return home is allowed. Python
callers can opt into revisits with `find_round_trips(..., allow_city_revisits=True)`.
Waiting is checked for feasibility; default price-first searches break ties
by summed movement seconds, excluding waiting. Fuzzy city-stay ranking is
available as described below.

`expenses_tolerance` is the absolute inclusive budget. `time_tolerance` is the
allowed deviation in minutes around the target return instant, including an
exact match at zero. The earliest departure remains a hard lower bound. All
instants require explicit UTC offsets. Different currencies are rejected rather
than implicitly converted. The core preserves supplied Decimal amounts; the
Ignav fixture already uses float amounts, converted with `Decimal(str(amount))`
at this synthetic adapter boundary.

The demo has fixture-local canonical IDs `pl-warsaw`, `pl-krakow`, `fr-paris`,
`gb-london`, and `nl-amsterdam`. Flights reuse the same `MockIgnavGenerator` as
`mock_ignav.py`, requesting direct, one-adult, independent one-way offers. All
five-city directed airport pairs are hypothetical fixture coverage. Train
(Warsaw/Krakow), bus (Paris/Amsterdam), and ferry (London/Amsterdam) services are
explicit synthetic corridors in both directions, departing at 08:00/16:00 UTC.
`StaticTransportPrices.train/bus/ferry` supply deterministic USD amounts. These
prices, schedules, ferry city access assumptions, and flights are **not live
availability**. No terminal-access, check-in, or boarding-time guarantee is made.

The demo supports USD and horizons up to 31 days. It resolves the overlay once
before exploration; no network or paid requests occur. Core limits default to
8 physical legs, 100,000 explored states, and 20 retained results. Result limits
retain the best options encountered while continuing exploration; leg/state
limits explicitly report truncation. Cheapest is relative to the supplied
schedule snapshot and selected limits, not a global market-price guarantee.
Provider errors are distinct from a successful empty result.

This implements the offline solver/provider slice of `IMPLEMENTATION.md`.
Production catalog mapping, historical observations, calendar-aware GTFS
services, live providers, terminal transfers, and the evolved uncertainty/API/UI
contracts remain separate delivery stages. Synthetic observations are not
written to real price history or reference graph weights.

### Verbose Vilnius demo

Run a small, fixed-date example from the repository root:

```sh
just demo-round-trip
# Optional: change the mock flight seed.
just demo-round-trip --seed 7
# Explicitly include journeys that pass through Warsaw twice.
just demo-round-trip --allow-city-revisits
```

The equivalent module command is
`uv run --project backend --locked python -m backend.presentation.cli.round_trip_demo`.

It starts and ends in **Vilnius** (`lt-vilnius`), requires Krakow, and compares
synthetic buses/trains via Warsaw with seeded Ignav mock flights between Warsaw
and Krakow. The search runs December 1–3, 2026 with a USD 200 budget. With the
default policy, no trips qualify: returning through Warsaw revisits a city.
The solver skips previously visited cities per itinerary by default (including
internal ticket connections), except the final return home. Python callers can
explicitly pass `allow_city_revisits=True` to `find_round_trips`; with seed 42,
the cheapest qualifying trip under that policy costs USD 98.00. The table notebook
`notebooks/02_algo_demo_visualization.ipynb` exposes the same opt-in through
the **Allow city revisits** checkbox. All notebook search settings are widgets;
run all cells once, then committed widget edits automatically refresh the search
and itinerary tables. Dates use the browser timezone in the pickers and UTC in
the tables. Changing dates queries in-process mock flight, train, bus and ferry
APIs to generate synthetic schedules on existing base-graph connections only.
The snapshot path and home/constraint cities are widgets; graph city IDs, directed
modes, operators and parallel connection keys are preserved. The entire snapshot
is used as one graph, without city, regional or connected-component partitions.
City search filters only the home, required, excluded and preference selectors;
all graph cities remain available as interchanges. Configure the seed and services per day,
or click **Generate new sample**. Identical seeds and requests
reproduce the same tickets. Generation is bounded to 14 days. The notebook contains
its models, solver, restricted snapshot loader, mock APIs and reactive UI directly,
with no backend-package imports. Graph snapshots are cached until the selected file
changes. A missing connection or direction is never generated. Search limits may
truncate exploration and are reported explicitly. Vilnius surface services in
this demo are invented; this does not add Vilnius to the general provider catalog.

Every provider lookup, generated service, offer inspection/filter, explored
state, branch expansion/rejection, candidate ranking, and final summary is logged
to stderr. Machine-readable results remain JSON on stdout. Save both separately:

```sh
uv run --project backend --locked python -m backend.presentation.cli.round_trip_demo \
  > results.json 2> actions.log
```

Use `--seed INTEGER` to change the mock flights. Fixed dates and seeds make the
trace repeatable. The reusable solver emits the same detailed trace through the
standard Python `logging` API when its caller enables DEBUG logging.

### Map-ready route output

The existing `shared/graphql/schema_v1.graphql` now defines `City` and requires
`from_city` / `to_city` on each `TripLeg`. Both search CLIs serialize through the
same contract. Existing `from` / `to` identifiers and timing fields are preserved:

```json
{
  "from": "lt-vilnius",
  "to": "pl-warsaw",
  "from_city": {
    "id": "lt-vilnius",
    "name": "Vilnius",
    "latitude": 54.6833333,
    "longitude": 25.3166667
  },
  "to_city": {
    "id": "pl-warsaw",
    "name": "Warsaw",
    "latitude": 52.25,
    "longitude": 21.0
  },
  "departure_at": "2026-12-01T08:00:00Z",
  "arrival_at": "2026-12-01T16:00:00Z",
  "time_in_travel": 28800,
  "transport_type": "BUSSES"
}
```

Coordinates are finite WGS 84 decimal degrees: latitude in `[-90, 90]`, longitude
in `[-180, 180]`. Endpoint objects must have IDs equal to `from` / `to`. Missing
city mappings are errors; they are never replaced with `(0, 0)`. IDs are canonical
within this application/fixture catalog, not universal identifiers or OSM node IDs.
The fixed city-centre markers come from the local `Cities.csv` snapshot by
[Work With Data](https://www.workwithdata.com/datasets/cities), licensed CC BY 4.0;
see `src/backend/infrastructure/fixtures/data/cities/README.md`. The source's
Cracow label is displayed as Krakow. Timetables and fares remain synthetic.

For a Leaflet-style overlay, use `[city.latitude, city.longitude]`. For GeoJSON
or MapLibre, use `[city.longitude, city.latitude]`. Interpolate from `from_city`
to `to_city` between the leg's `departure_at` and `arrival_at`, and hold the marker
at the city during gaps between legs. These endpoints support a schematic
animation; actual road/rail/ferry tracks or aircraft positions require separate
geometry/position data. No map tiles, geocoder, or network requests are required
to resolve these endpoint markers. This change supplies data, not a map renderer.

## Scrappa Omio API and local fare history

The adapter in `infrastructure/scrappa/client.py` implements all six documented
Scrappa Omio GET endpoints: `places`, `search`, `summary` (`search/summary`),
`trip`, `providers`, and `route-page`. It uses `x-api-key` authentication and a
finite timeout. Contracts: [Scrappa Omio documentation](https://scrappa.co/docs/omio-api/omio_search),
[price summary](https://scrappa.co/docs/omio-api/omio_summary). The documented
search modes are **train, bus and flight**; ferry support is not assumed.

Export `SCRAPPA_API_KEY` in your shell (the CLI does not load `.env` automatically).
Each uncached request can spend credits. Examples from the repository root:

```sh
# Resolve provider-specific place IDs; the response is cached automatically.
uv run --project backend --locked python -m backend.presentation.cli.scrappa request places \
  --params '{"query":"Berlin"}'

# Search one-way fares. Identical requests reuse fresh local responses.
uv run --project backend --locked python -m backend.presentation.cli.scrappa request search \
  --params '{"origin_id":376217,"destination_id":379727,"date":"2026-12-01","travel_mode":"train,bus"}'

# Collect a week of daily minima with one summary request.
uv run --project backend --locked python -m backend.presentation.cli.scrappa request summary \
  --params '{"origin_id":376217,"destination_id":379727,"date_start":"2026-12-01","date_end":"2026-12-07","travel_mode":"train,bus"}'

# Estimate offline from observations already collected; no API key or HTTP needed.
uv run --project backend --locked python -m backend.presentation.cli.scrappa estimate \
  --origin-id 376217 --destination-id 379727 --date 2026-12-02 --mode train
```

Use future dates within the provider's horizon when running live examples.
For other endpoints, pass their documented parameters in `--params`: `trip`
requires `search_id` and `trip_id`; `providers` optionally accepts `search_id`;
`route-page` requires city slugs `origin` and `destination` with optional `mode`
(`trains`, `buses`, or `flights`). No pagination, trip-detail follow-up, or retry
is automatic, so a single CLI request makes at most one billable HTTP call.

The default database is **`backend/data/scrappa.duckdb`**, separate from GTFS and
base-graph databases and ignored by Git. Override it using `--database PATH`
**before** the `request` or `estimate` subcommand. The append-only `responses`
table stores the full HTTP response body, HTTP status, endpoint, normalized
parameters, response ID and UTC fetch time, including error/non-JSON bodies.
Transport failures are also cached, with status `0` and a safe diagnostic
instead of an HTTP body; exception text is not stored. API keys and
request authentication headers are never persisted. Keep this database private.
The Python adapter supports a context manager and must be closed after use.
DuckDB permits one writer process; do not run separate cache writers concurrently.

Cache keys include all request parameters, with explicit defaults and normalized
mode ordering. Defaults are seven days for places, one day for route pages, six
hours for searches/summaries, and one hour for trip/provider responses. These
are local reuse policies, not promises about fare validity. `--refresh` explicitly
spends a request to bypass cache; `--cache-only` forbids HTTP and fails on a cache
miss; `--max-age-seconds` overrides the freshness window (zero disables reuse).
All outcomes are reused within the freshness window, including HTTP errors,
malformed bodies, and transport failures. Cached failures raise a clear error
with their stored response ID without making another API call. Use `--refresh`
to retry explicitly; expired entries may trigger a new call. The newest outcome
takes precedence, even if it is a failure following an older success. Failed
outcomes never contribute to price estimates. Cached output
includes `source`, `fetched_at`, `response_id`, and the untouched provider payload.
An upstream search ID can expire even while its local response remains cached;
refresh the search explicitly if a subsequent detail request reports expiry.

The offline estimate selects comparable **one-way, whole-journey/group** daily
minima from search floors and summary responses. It matches route direction,
mode, currency and adult/child/infant counts exactly, without currency conversion
or treating a bundled journey's price as independent leg fares. Repeated
observations do not increase the sample count: only the newest observed minimum
per departure day contributes. Summary `updated_at` timestamps are respected,
so an old upstream price is not treated as newly observed when fetched again.
Exact-date observations take priority; otherwise the median of nearby departure
days is used. Defaults are a 28-day date window and 30-day observation age,
configurable with `--date-window-days` and `--max-age-days`. Output includes the
sample-day count, observed range, source response IDs and timestamps. Monetary
amounts use Decimal and serialize as strings; no intermediate float rounding.
Missing comparable history returns `amount: null`, never a fabricated zero.

These are historical estimates, not current availability or bookable offers.
They do not model seasonality, booking lead time or fare classes, and daily
minima may refer to different services. Route-page marketing prices and round-trip
bundles remain archived but are excluded from this estimator. This is an adapter
and CLI; it does not alter the synthetic solver or frontend search flow.
CLI stdout is JSON; validation/provider/cache-miss errors exit 2 with stderr
diagnostics, and database/file failures exit 1. Ordinary tests mock HTTP and never
consume API credits.

### Approximate city stays

The offline solver accepts `fuzzy_search: true` to rank by city-stay fit before
price and movement time. Existing requests retain price-first ranking. Add these
fields to a normal search request, or run the example:

```sh
uv run --project backend --locked python -m backend.presentation.cli.round_trip \
  --request backend/examples/round_trip_fuzzy.json --seed 42
```

```json
{
  "fuzzy_search": true,
  "max_trip_duration": 172800,
  "city_attractiveness": [
    {"city": "pl-krakow", "weight": 3},
    {"city": "fr-paris", "weight": 2}
  ]
}
```

`max_trip_duration` is an optional positive number of **seconds** measured from
`departure_date`, including initial waiting at home, movement, connections, and
stays. It intersects the existing return window; it does not expand that window.
An empty intersection yields no results. `city_attractiveness` contains distinct
canonical city IDs and finite, strictly positive relative weights. Home and
excluded cities cannot have weights. Missing weights default to 1; these are
planning preferences, not verified tourism ratings. A weight alone does not
make a city mandatory.

Each result includes `city_stays`, with `city`, actual `time_spent`, approximate
`target_time` (both seconds), and `attractiveness`. Actual times sum the gaps
between consecutive physical legs, including internal ticket connections and
repeated visits. They exclude waiting at home and the final return. Such gaps
are elapsed city time, not a guarantee of sightseeing time or terminal access.
The existing endpoint-based mandatory-city rule remains unchanged.

For each candidate, the stay budget is the target return (capped by the duration
deadline) minus its actual first departure and all movement time, floored at
zero. Divide that budget among distinct visited non-home cities in proportion
to their attractiveness. For example, seven available hours with weights 3:1
target 5.25 and 1.75 hours. A scheduled allocation of five and two hours remains
eligible and scores better than three and four hours.

The fuzzy `stay_fit` is `1 - sum(abs(actual - target)) / (total_actual +
total_target)`, clamped to [0, 1]; zero when both totals are zero. Higher is
better, with price and movement time breaking ties. It is null for price-first
searches, which still return stay data. Targets are soft preferences: the solver
ranks supplied schedules rather than inventing departures or rejecting slightly
different stays. Budget, modes, mandatory/excluded cities, chronology, maximum
duration, and return window stay strict. Search state/leg/result limits retain
their existing truncation reporting; a limited search need not find the best fit.
