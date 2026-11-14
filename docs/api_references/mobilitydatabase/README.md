# Mobility Database files

`openapi.yml` describes the Mobility Database API. The schedule downloader stores
archives in `backend/src/backend/infrastructure/fixtures/data/mobilitydatabase/raw/`.

The ZIP filename prefix identifies the feed's catalogue source, not its format:

| Prefix | Source and contents |
| --- | --- |
| `tld-` | Transitland feeds imported into Mobility Database. (`tlg` is a typo; the reference and downloaded files use `tld`.) |
| `tdg-` | Feeds imported from France's transport.data.gouv.fr catalogue; the suffix is the resource ID. |
| `mdb-` | Feeds identified by a Mobility Database ID. |

All three contain GTFS Schedule data: CSV tables stored as `.txt` files inside a
ZIP archive. Typical tables describe operators (`agency.txt`), stops (`stops.txt`),
routes (`routes.txt`), trips (`trips.txt`), arrival/departure times
(`stop_times.txt`), service dates (`calendar.txt`, `calendar_dates.txt`), and route
geometry (`shapes.txt`). The exact set of tables varies by feed.

Alongside `raw/`, `catalog.json` contains the selected feeds' metadata, and
`manifest.json` records dataset metadata, download status, and relative archive
paths. The downloader fetches each feed's latest available schedule snapshot.

## Filtered DuckDB extraction

Run `just combine-schedules`, optionally with `--raw-dir PATH --output PATH.duckdb`.
The default output is `schedules.duckdb` alongside `raw/`.

Tables: `agency`, `routes`, `trips`, `stops`, `stop_times`, `calendar`,
`calendar_dates`, `frequencies`, `transfers`, `feed_info`. Each table includes
`feed_id` (relative archive path without its extension); GTFS identifiers are
scoped to that feed. Source values remain VARCHAR, with empty/missing fields
represented as SQL NULL. No schedule times are coerced into same-day clocks.

Modes: base route types 2 (rail), 3 (bus), 4 (ferry), plus extended families
100–199 (rail), 200–299 (coach), 700–799 (bus), 1000–1099 (water), and 1200 (ferry).
Unsupported modes are removed along with unrelated trips, stop times, calendars,
frequencies and transfer references. Used stops and station ancestors are kept.
Shapes, bike attributes, arbitrary files, binaries and fare-rule tables are not
imported. The explicit column allowlist is in `combine_mobilitydatabase.py`.
This is scheduling staging data; fare rules, pathways and canonical city mapping
require separate normalization capabilities. Missing fare data never means free.

The archive must contain routes, trips, stops, stop_times and at least one calendar
table. Invalid required headers, malformed relevant CSV or invalid ZIPs fail a
feed instead of retaining opaque fallback data. Unrelated files are never parsed.
The `feeds` metadata table retains archive path, SHA-256 and retained row count.
`extraction` binds the staging database to its raw directory and format version.
Keep the downloader's catalog/manifest and raw ZIPs for rights and dataset lineage.

Checkpoint state lives in `schedules.staging.duckdb`. Each feed commits atomically;
interruption rolls back the current feed. Reruns skip unchanged completed feeds
and reload changed ones. After all feeds succeed, removed feeds are discarded and
a closed database copy atomically replaces `schedules.duckdb`. A failed run keeps
the previous published database intact. A lock file prevents simultaneous writers.
Keep the staging database for resume, and close published readers during replacement.
Legacy JSON exports/checkpoints are untouched and not reused. Stdout contains a
small JSON summary; INFO progress and errors go to stderr (`--log-level WARNING`
reduces output). Extraction uses local archives without network access.

Feed extraction uses a bounded thread pool (default: up to four workers). Use
`just combine-schedules --workers 8` to change it, or `--workers 1` for serial
extraction. Each worker has an isolated temporary DuckDB file, one DuckDB query
thread, and a 256 MB query-memory limit (not a total process-memory limit).
Temporary files/spill space grow with active feeds. A single coordinator merges
results transactionally into the staging database in archive order; completed
feeds still checkpoint independently, and failed feeds do not prevent the other
results from being saved. In-flight work finishes before temporary cleanup on
interruption, so shutdown may wait for an active feed.
