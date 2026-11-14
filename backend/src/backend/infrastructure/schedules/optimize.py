"""Atomically add serving indexes to an existing compiled schedule snapshot."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from backend.application.telemetry import traced
from backend.infrastructure.logging import cli_entrypoint
from backend.infrastructure.schedules.build import prepare_query_indexes


@traced
def optimize_snapshot(path):
    path = Path(path).resolve()
    with path.with_suffix(path.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd, staged = tempfile.mkstemp(prefix=".schedule-index-", dir=path.parent)
        os.close(fd)
        try:
            with closing(
                sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            ) as source, closing(sqlite3.connect(staged)) as target:
                source.backup(target)
                metadata = json.loads(
                    target.execute(
                        "SELECT value FROM metadata WHERE key='snapshot'"
                    ).fetchone()[0]
                )
                if metadata.get("query_index_version") != 2:
                    prepare_query_indexes(target)
                    metadata["query_index_version"] = 2
                    # Keep built_at: index maintenance must never refresh data provenance.
                    target.execute(
                        "UPDATE metadata SET value=? WHERE key='snapshot'",
                        [json.dumps(metadata)],
                    )
                    target.commit()
            os.chmod(staged, path.stat().st_mode & 0o777)
            os.replace(staged, path)
        finally:
            Path(staged).unlink(missing_ok=True)


@cli_entrypoint
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    optimize_snapshot(args.snapshot)
    print(json.dumps({"indexed": True}))


if __name__ == "__main__":
    main()
