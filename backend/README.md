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
