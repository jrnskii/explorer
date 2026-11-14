"""Offline DuckDB extraction and recovery contracts."""

import io
import json
import unittest
import threading
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

import duckdb
from backend.infrastructure.fixtures import combine_mobilitydatabase as export


class CombineSchedulesTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.output = self.root / "schedules.duckdb"

    def archive(self, name="mdb-1.zip", mode="2", extra=None):
        tables = {
            "agency.txt": "agency_id,agency_name,agency_timezone\na,Rail,Europe/Vilnius\n",
            "routes.txt": f"route_id,agency_id,route_type\n001,a,{mode}\nbike,a,1\n",
            "trips.txt": "trip_id,route_id,service_id,bikes_allowed,shape_id\nt,001,weekday,1,shape\nx,bike,other,1,shape\n",
            "stop_times.txt": "trip_id,stop_id,stop_sequence,arrival_time,departure_time\nt,s,1,25:00:00,25:00:00\nx,b,1,09:00:00,09:00:00\n",
            "stops.txt": "stop_id,stop_name,parent_station\ns,Platform,p\np,Station,\nb,Bike,\n",
            "calendar_dates.txt": "service_id,date,exception_type\nweekday,20260101,1\nother,20260101,1\n",
            "frequencies.txt": "trip_id,start_time,end_time,headway_secs,exact_times\nt,25:00:00,26:00:00,600,0\nx,09:00:00,10:00:00,300,0\n",
            "transfers.txt": "from_stop_id,to_stop_id,transfer_type,min_transfer_time\ns,p,2,120\ns,b,2,120\n",
            "shapes.txt": b"not even CSV\xff",
            "station_information.json": "{}",
        }
        tables.update(extra or {})
        path = self.raw / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(path, "w") as archive:
            for key, value in tables.items():
                archive.writestr(key, value)
        return path

    def query(self, sql):
        with duckdb.connect(str(self.output), read_only=True) as db:
            return db.execute(sql).fetchall()

    def test_modes_dependencies_projection_and_string_precision(self):
        for index, mode in enumerate(
            ("2", "3", "4", "106", "200", "700", "1000", "1200")
        ):
            self.archive(f"feed-{index}.zip", mode)
        result = export.combine(self.raw, self.output)
        self.assertEqual(result["feeds"], 8)
        self.assertEqual(self.query("SELECT DISTINCT route_id FROM routes"), [("001",)])
        self.assertEqual(
            self.query("SELECT DISTINCT arrival_time FROM stop_times"), [("25:00:00",)]
        )
        self.assertEqual(
            set(self.query("SELECT DISTINCT stop_id FROM stops")), {("s",), ("p",)}
        )
        self.assertEqual(
            self.query("SELECT DISTINCT service_id FROM calendar_dates"), [("weekday",)]
        )
        self.assertEqual(self.query("SELECT count(*) FROM transfers"), [(8,)])
        self.assertEqual(self.query("SELECT count(*) FROM frequencies"), [(8,)])
        columns = self.query(
            "SELECT column_name FROM information_schema.columns WHERE table_name='trips'"
        )
        self.assertNotIn(("shape_id",), columns)
        self.assertNotIn(("bikes_allowed",), columns)
        self.assertNotIn(("shapes",), self.query("SHOW TABLES"))

    def test_unsupported_mode_produces_no_scheduling_rows(self):
        self.archive(mode="1")
        export.combine(self.raw, self.output)
        for table in export.COLUMNS:
            self.assertEqual(
                self.query(f'SELECT count(*) FROM "{table}"'), [(0,)], table
            )

    def test_empty_and_nested_inputs_and_namespaces(self):
        self.assertEqual(export.combine(self.raw, self.output)["feeds"], 0)
        self.archive("a/feed.zip")
        self.archive("b/feed.ZIP")
        export.combine(self.raw, self.output)
        self.assertEqual(
            set(self.query("SELECT feed_id FROM routes")), {("a/feed",), ("b/feed",)}
        )

    def test_resume_changed_and_removed_archives(self):
        first = self.archive()
        self.archive("mdb-2.zip")
        export.combine(self.raw, self.output)
        self.assertEqual(export.combine(self.raw, self.output)["resumed"], 2)
        self.archive(mode="4")
        self.assertEqual(export.combine(self.raw, self.output)["resumed"], 1)
        self.assertEqual(
            self.query("SELECT route_type FROM routes WHERE feed_id='mdb-1'"), [("4",)]
        )
        first.unlink()
        export.combine(self.raw, self.output)
        self.assertEqual(self.query("SELECT feed_id FROM feeds"), [("mdb-2",)])

    def test_failure_preserves_published_db_and_checkpoints_other_feeds(self):
        self.archive()
        export.combine(self.raw, self.output)
        previous = self.output.read_bytes()
        self.archive("mdb-2.zip")
        (self.raw / "broken.zip").write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "Rerun to resume"):
            export.combine(self.raw, self.output)
        self.assertEqual(previous, self.output.read_bytes())
        (self.raw / "broken.zip").unlink()
        self.assertEqual(export.combine(self.raw, self.output)["resumed"], 2)

    def test_interruption_rolls_back_current_feed_and_resumes(self):
        self.archive()
        self.archive("mdb-2.zip")
        original = export.convert_archive

        def interrupted(path, feed_id, db):
            if feed_id == "mdb-2":
                original(path, feed_id, db)
                raise KeyboardInterrupt()
            return original(path, feed_id, db)

        with patch.object(export, "convert_archive", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                export.combine(self.raw, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(export.combine(self.raw, self.output)["resumed"], 1)
        self.assertEqual(self.query("SELECT count(*) FROM routes"), [(2,)])

    def test_malformed_relevant_data_fails_and_unrelated_files_are_not_read(self):
        self.archive(extra={"routes.txt": 'route_id,route_type\n"unterminated'})
        with self.assertRaisesRegex(ValueError, "archives failed"):
            export.combine(self.raw, self.output)
        self.assertFalse(self.output.exists())
        self.archive(extra={"stop_times.txt": "invalid\nvalue\n"})
        with self.assertRaises(ValueError):
            export.combine(self.raw, self.output)

    def test_cli_stdout_summary_and_errors(self):
        self.archive()
        args = ["--raw-dir", str(self.raw), "--output", str(self.output)]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(export.main(args), 0)
        self.assertEqual(json.loads(out.getvalue())["feeds"], 1)
        self.assertIn("Checkpoint committed", err.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(
                export.main([*args, "--output", str(self.root / "bad.json")]), 1
            )

    def test_source_binding_missing_input_and_output_collision(self):
        with self.assertRaises(ValueError):
            export.combine(self.root / "missing", self.output)
        archive = self.archive()
        with self.assertRaisesRegex(ValueError, "input archive"):
            export.combine(self.raw, archive)
        export.combine(self.raw, self.output)
        other = self.root / "other"
        other.mkdir()
        with self.assertRaisesRegex(ValueError, "source/version mismatch"):
            export.combine(other, self.output)

    def test_failed_publication_reuses_all_committed_feeds(self):
        self.archive()
        export.combine(self.raw, self.output)
        previous = self.output.read_bytes()
        self.archive("mdb-2.zip")
        with patch.object(export.shutil, "copyfile", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                export.combine(self.raw, self.output)
        self.assertEqual(previous, self.output.read_bytes())
        self.assertFalse(self.output.with_suffix(".duckdb.part").exists())
        self.assertEqual(export.combine(self.raw, self.output)["resumed"], 2)

    def test_large_stop_time_table_and_missing_optional_fields(self):
        rows = "trip_id,stop_id,stop_sequence,arrival_time,departure_time\n"
        rows += "".join(f"t,s,{i},25:00:00,25:00:00\n" for i in range(1, 10002))
        self.archive(extra={"stop_times.txt": rows})
        export.combine(self.raw, self.output)
        self.assertEqual(self.query("SELECT count(*) FROM stop_times"), [(10001,)])
        self.assertEqual(
            self.query("SELECT count(*) FROM stop_times WHERE pickup_type IS NULL"),
            [(10001,)],
        )

    def test_parallel_workers_overlap_and_match_serial_output(self):
        for index in range(4):
            self.archive(f"feed-{index}.zip", mode=str(2 + index % 3))
        original = export.convert_archive
        barrier = threading.Barrier(2)
        names = set()
        guard = threading.Lock()

        def concurrent(path, feed_id, db):
            with guard:
                names.add(threading.current_thread().name)
            barrier.wait(timeout=10)
            return original(path, feed_id, db)

        with patch.object(export, "convert_archive", side_effect=concurrent):
            export.combine(self.raw, self.output, workers=2)
        self.assertEqual(len(names), 2)
        serial = self.root / "serial.duckdb"
        export.combine(self.raw, serial, workers=1)
        with duckdb.connect(str(serial), read_only=True) as db:
            for table in (*export.COLUMNS, "feeds"):
                sql = f'SELECT * FROM "{table}" ORDER BY ALL'
                self.assertEqual(self.query(sql), db.execute(sql).fetchall(), table)

    def test_invalid_worker_count(self):
        for workers in (0, -1, True):
            with self.subTest(workers=workers), self.assertRaisesRegex(
                ValueError, "positive integer"
            ):
                export.combine(self.raw, self.output, workers=workers)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            export.main(["--workers", "0"])
        self.assertEqual(error.exception.code, 2)

    def test_merge_failure_rolls_back_and_can_resume(self):
        self.archive()
        original = export.merge_archive

        def fail(db, shard, feed_id, relative, fingerprint, rows):
            # Fail after the first table is deleted, inside the merge transaction.
            with patch.dict(export.COLUMNS, {"nonexistent": "id"}):
                return original(db, shard, feed_id, relative, fingerprint, rows)

        with patch.object(export, "merge_archive", side_effect=fail):
            with self.assertRaisesRegex(ValueError, "archives failed"):
                export.combine(self.raw, self.output, workers=2)
        self.assertFalse(self.output.exists())
        self.assertEqual(export.combine(self.raw, self.output, workers=2)["resumed"], 0)
        self.assertEqual(self.query("SELECT count(*) FROM routes"), [(1,)])

    def test_lock(self):
        with self.output.with_suffix(".lock").open("a") as lock:
            export.fcntl.flock(lock, export.fcntl.LOCK_EX | export.fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "Another conversion"):
                export.combine(self.raw, self.output)


if __name__ == "__main__":
    unittest.main()
