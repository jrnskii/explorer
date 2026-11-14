"""Build or migrate a fast native binary city graph snapshot."""

import argparse
import json
import sys
from pathlib import Path

import duckdb

from backend.infrastructure.logging import cli_entrypoint
from backend.infrastructure.catalog.base_graph import DATA, build_base_graph
from backend.infrastructure.catalog.graph_snapshot import (
    DEFAULT_GRAPH_PATH,
    load_base_graph_json,
    save_base_graph,
)


@cli_entrypoint
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cities", type=Path, default=None)
    parser.add_argument("--routes", type=Path, default=None)
    parser.add_argument(
        "--stations",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--schedules",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--air-only", action="store_true", help="Import cities and air routes only"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_GRAPH_PATH,
        help="Output .pickle (fastest) or .pickle.zst (smaller) snapshot",
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        help="Migrate existing node-link JSON without rebuilding the source graph",
    )
    args = parser.parse_args()
    if not (
        args.output.name.endswith(".pickle") or args.output.name.endswith(".pickle.zst")
    ):
        parser.error("--output must end with .pickle or .pickle.zst")
    if args.from_json and (
        args.air_only or any((args.cities, args.routes, args.stations, args.schedules))
    ):
        parser.error("--from-json cannot be combined with source import options")
    if args.from_json and args.output.resolve() == args.from_json.resolve():
        parser.error("Output must not replace the migration input")
    try:
        if args.from_json:
            graph = load_base_graph_json(args.from_json)
        else:
            graph = build_base_graph(
                args.cities or DATA / "cities" / "Cities.csv",
                args.routes or DATA / "airline_routes.json",
                stations_path=(
                    None
                    if args.air_only
                    else args.stations
                    or DATA / "train-stations" / "train_stations_europe.csv"
                ),
                schedules_path=(
                    None
                    if args.air_only
                    else args.schedules
                    or DATA / "mobilitydatabase" / "schedules.staging.duckdb"
                ),
            )
        output = save_base_graph(graph, args.output)
    except (OSError, ValueError, TypeError, KeyError, duckdb.Error) as error:
        print(f"Cannot build base graph: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(
        json.dumps(
            dict(
                output=str(output),
                nodes=len(graph),
                edges=graph.number_of_edges(),
                snapshot_id=graph.graph.get("snapshot_id"),
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
