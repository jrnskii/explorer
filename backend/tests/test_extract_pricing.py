"""Offline contracts for pricing extraction, geography, and publication."""

import contextlib
import csv
from decimal import Decimal
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import duckdb
import pandas as pd

from backend.infrastructure.fixtures import extract_pricing as e


class PricingExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "result.duckdb"
        self.csv(
            "cities/Cities.csv",
            [
                dict(city="Paris", country="France"),
                dict(city="Berlin", country="Germany"),
                dict(city="London", country="United Kingdom"),
                dict(city="Madrid", country="Spain"),
                dict(city="Springfield", country="France"),
                dict(city="Springfield", country="Germany"),
                dict(city="Zürich", country="Switzerland"),
                dict(city="Munich", country="Germany"),
                dict(city="Nuremberg", country="Germany"),
                dict(city="New York", country="United States"),
            ],
        )
        self.csv(
            "train-stations/train_stations_europe.csv",
            [
                dict(
                    name="PARIS GARE",
                    name_norm="Paris Gare",
                    country="FR",
                    uic="8712345",
                ),
                dict(
                    name="BERLIN HBF",
                    name_norm="Berlin Hbf",
                    country="DE",
                    uic="8012345",
                ),
            ],
        )

    def csv(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
        return path

    def json(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data))
        return p

    def flight(self, origin="Paris", destination="Berlin", price="12.30", **extra):
        return dict(
            origin_city=origin,
            destination_city=destination,
            median_eur=price,
            min_eur="0",
            p10_eur="10",
            observations="5",
            departure_month="2026-11",
            **extra
        )

    def extract(self):
        with contextlib.redirect_stderr(io.StringIO()):
            return e.extract(self.root, self.output)

    def query(self, sql):
        with duckdb.connect(str(self.output), read_only=True) as db:
            return db.execute(sql).fetchall()

    def test_both_endpoints_required_and_ambiguity_is_reviewed(self):
        self.csv(
            "pricing/flights/fares-by-month.csv",
            [
                self.flight(),
                self.flight(destination="London"),
                self.flight(origin="Unknown"),
                self.flight(origin="Springfield"),
                self.flight(origin="ZURICH"),
            ],
        )
        result = self.extract()
        self.assertEqual(result["pricing_rows"], 2)
        self.assertEqual(result["review_rows"], 2)
        self.assertEqual(
            self.query(
                "SELECT outside_rows FROM sources WHERE source_id NOT LIKE 'reference:%'"
            ),
            [(1,)],
        )
        self.assertEqual(
            self.query("SELECT DISTINCT destination_country FROM pricing"), [("DE",)]
        )

    def test_decimal_zero_provenance_and_parallel_rows_preserved(self):
        self.csv(
            "pricing/flights/fares-by-month.csv",
            [self.flight(price="0"), self.flight(price="12.12345678")],
        )
        self.extract()
        self.assertEqual(
            self.query("SELECT price FROM pricing ORDER BY row_number"),
            [(Decimal("0"),), (Decimal("12.12345678"),)],
        )
        self.assertEqual(
            self.query(
                "SELECT count(DISTINCT row_number), min(currency), min(kind) FROM pricing"
            ),
            [(2, "EUR", "route_month_aggregate")],
        )
        self.assertEqual(len(self.query("SELECT sha256 FROM sources")[0][0]), 64)
        raw = json.loads(
            self.query("SELECT raw_json FROM pricing ORDER BY row_number LIMIT 1")[0][0]
        )
        self.assertEqual(raw["median_eur"], "0")

    def test_invalid_missing_and_overprecision_prices_quarantined(self):
        self.csv(
            "pricing/flights/fares-by-month.csv",
            [
                self.flight(price=v)
                for v in ["-1", "Infinity", "NaN", "abc", "1.1234567890123456789"]
            ],
        )
        # A missing median still has a valid minimum: preserve it, don't invent a median.
        self.extract()
        self.assertEqual(self.query("SELECT count(*) FROM pricing"), [(1,)])
        self.assertEqual(
            self.query("SELECT price, price_min FROM pricing"), [(None, Decimal("0"))]
        )
        self.assertEqual(self.query("SELECT count(*) FROM review"), [(4,)])

    def test_missing_all_prices_and_invalid_observation_counts(self):
        row = self.flight(price="")
        row.update(min_eur="", p10_eur="")
        invalid = self.flight()
        invalid["observations"] = "0"
        self.csv("pricing/flights/fares-by-month.csv", [row, invalid])
        self.extract()
        self.assertEqual(
            set(r[0] for r in self.query("SELECT reason FROM review")),
            {"missing_price", "invalid_observation_count"},
        )

    def test_sncf_uses_exact_uic_and_preserves_tariff_class(self):
        self.json(
            "pricing/sncf/tariffs.json",
            [
                dict(
                    gare_origine="Unknown label",
                    gare_destination="Another label",
                    gare_origine_code_uic="87123450",
                    gare_destination_code_uic="80123459",
                    prix_minimum=0,
                    prix_maximum=100.5,
                    classe="2",
                    profil_tarifaire="Tarif Normal",
                )
            ],
        )
        self.extract()
        self.assertEqual(
            self.query(
                "SELECT origin_country,destination_country,price,price_min,price_max,kind FROM pricing"
            ),
            [
                (
                    "FR",
                    "DE",
                    None,
                    Decimal("0"),
                    Decimal("100.5"),
                    "published_tariff_bounds",
                )
            ],
        )
        self.assertEqual(
            json.loads(self.query("SELECT raw_json FROM pricing")[0][0])["classe"], "2"
        )

    def test_inverted_bounds_are_reviewed(self):
        self.json(
            "pricing/sncf/tariffs.json",
            [
                dict(
                    gare_origine="Paris",
                    gare_destination="Berlin",
                    gare_origine_code_uic="",
                    gare_destination_code_uic="",
                    prix_minimum=100,
                    prix_maximum=1,
                )
            ],
        )
        self.extract()
        self.assertEqual(
            self.query("SELECT reason FROM review"), [("inverted_price_bounds",)]
        )

    def test_bus_uses_single_seat_fare_not_total_or_regression_float(self):
        p = self.root / "pricing/flixbus/data_flixbus.dta"
        p.parent.mkdir(parents=True)
        pd.DataFrame(
            [
                dict(
                    o="Munich",
                    d="Nuremberg",
                    fare=13.9,
                    totalfare=27.8,
                    fare1=13.899999618,
                    seat=2,
                    qdate=pd.Timestamp("2017-08-07"),
                    ddate=pd.Timestamp("2017-09-04"),
                )
            ]
        ).to_stata(p, write_index=False)
        self.extract()
        self.assertEqual(
            self.query("SELECT mode,price,observed_date,departure_date FROM pricing"),
            [("bus", Decimal("13.9"), "2017-08-07 00:00:00", "2017-09-04 00:00:00")],
        )
        self.assertEqual(
            json.loads(self.query("SELECT raw_json FROM pricing")[0][0])["seat"], 2
        )

    def test_renfe_archive_is_streamed_without_extracting_paths(self):
        p = self.root / "pricing/renfe/tickets.zip"
        p.parent.mkdir(parents=True)
        with zipfile.ZipFile(p, "w") as archive:
            archive.writestr(
                "../../tickets.csv",
                "origin,destination,price,insert_date,start_date\nMadrid,Paris,12.34,2019-01-01,2019-02-01\n",
            )
        self.extract()
        self.assertEqual(
            self.query("SELECT mode,price,origin_country FROM pricing"),
            [("rail", Decimal("12.34"), "ES")],
        )
        self.assertFalse((self.root / "tickets.csv").exists())

    def test_gtfs_keeps_zero_missing_distinctions_and_feed_namespaces(self):
        feeds = []
        for identifier, code in [("a", "FR"), ("b", "DE"), ("outside", "GB")]:
            feeds.append(dict(id=identifier, locations=[dict(country_code=code)]))
            p = self.root / ("mobilitydatabase/raw/" + identifier + ".zip")
            p.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(p, "w") as archive:
                archive.writestr(
                    "fare_attributes.txt",
                    "fare_id,price,currency_type,transfers\n001,0.00,EUR,\n",
                )
                archive.writestr("fare_rules.txt", "fare_id,route_id\n001,r1\n")
                archive.writestr(
                    "fare_products.txt",
                    "fare_product_id,amount,currency\np1,1.23,EUR\n",
                )
        self.json("mobilitydatabase/catalog.json", feeds)
        result = self.extract()
        self.assertEqual(result["pricing_rows"], 0)
        self.assertEqual(result["gtfs_fare_rows"], 6)
        self.assertEqual(
            self.query("SELECT count(DISTINCT source_id) FROM gtfs_fare_records"),
            [(2,)],
        )
        raw = json.loads(
            self.query(
                "SELECT raw_json FROM gtfs_fare_records WHERE table_name='fare_attributes' LIMIT 1"
            )[0][0]
        )
        self.assertEqual(
            raw, dict(fare_id="001", price="0.00", currency_type="EUR", transfers="")
        )

    def test_failed_rebuild_preserves_database_and_cleans_lock(self):
        p = self.csv("pricing/flights/fares-by-month.csv", [self.flight()])
        self.extract()
        previous = self.output.read_bytes()
        p.write_text("unexpected,columns\na,b\n")
        with self.assertRaises(KeyError):
            self.extract()
        self.assertEqual(self.output.read_bytes(), previous)
        self.assertFalse(self.output.with_suffix(".lock").exists())

    def test_existing_lock_prevents_publication(self):
        self.csv("pricing/flights/fares-by-month.csv", [self.flight()])
        self.output.with_suffix(".lock").write_text("existing")
        with self.assertRaises(FileExistsError):
            self.extract()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.output.with_suffix(".lock").read_text(), "existing")

    def test_rebuild_replaces_instead_of_duplicating(self):
        self.csv("pricing/flights/fares-by-month.csv", [self.flight()])
        self.extract()
        self.extract()
        self.assertEqual(self.query("SELECT count(*) FROM pricing"), [(1,)])

    def test_empty_supported_input_creates_valid_empty_database(self):
        self.json("pricing/sncf/tariffs.json", [])
        self.assertEqual(self.extract()["pricing_rows"], 0)

    def test_no_inputs_and_cli_failure(self):
        with self.assertRaisesRegex(ValueError, "No supported"):
            self.extract()
        with contextlib.redirect_stderr(
            io.StringIO()
        ) as err, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(
                e.main(
                    ["--fixtures-dir", str(self.root), "--output", str(self.output)]
                ),
                1,
            )
        self.assertEqual(out.getvalue(), "")
        self.assertIn("No supported", err.getvalue())

    def test_overseas_airport_and_ambiguous_code_are_not_accepted(self):
        self.json(
            "airline_routes.json",
            {
                "RUN": dict(city_name="Reunion", country_code="FR", continent="AF"),
                "CDG": dict(city_name="Paris", country_code="FR", continent="EU"),
            },
        )
        locations = e.Locations(self.root)
        self.assertEqual(
            locations.resolve("RUN", air=True), "outside_schengen_territory"
        )
        self.assertEqual(locations.resolve("CDG", air=True), "FR")

    def test_airport_city_lookup_avoids_unrelated_global_city_collision(self):
        self.json(
            "airline_routes.json",
            {
                "BER": dict(city_name="Berlin", country_code="DE", continent="EU"),
                "CDG": dict(city_name="Paris", country_code="FR", continent="EU"),
            },
        )
        self.csv(
            "cities/Cities.csv",
            [
                dict(city="Berlin", country="Germany"),
                dict(city="Berlin", country="United States"),
            ],
        )
        self.csv("pricing/flights/fares-by-month.csv", [self.flight()])
        self.assertEqual(self.extract()["pricing_rows"], 1)

    def test_country_summary_is_not_a_route_fare(self):
        self.json("pricing/sncf/tariffs.json", [])
        self.csv(
            "pricing/flights/research__europe-countries.csv",
            [
                dict(country="France", routes="5", median_eur="12.34"),
                dict(country="United Kingdom", routes="10", median_eur="2"),
            ],
        )
        result = self.extract()
        self.assertEqual(result["pricing_rows"], 0)
        self.assertEqual(result["country_summary_rows"], 1)
        self.assertEqual(
            self.query("SELECT country_code,median_eur FROM country_summaries"),
            [("FR", Decimal("12.34"))],
        )

    def test_source_float_precision_is_preserved_without_cent_rounding(self):
        self.csv(
            "pricing/flights/fares-by-month.csv",
            [self.flight(price="19.900000000000002")],
        )
        self.extract()
        self.assertEqual(
            self.query("SELECT price FROM pricing"), [(Decimal("19.900000000000002"),)]
        )

    def test_known_outside_endpoint_excludes_even_if_other_endpoint_unknown(self):
        self.csv(
            "pricing/flights/fares-by-month.csv",
            [self.flight(origin="London", destination="Unknown")],
        )
        self.assertEqual(self.extract()["review_rows"], 0)
        self.assertEqual(
            self.query("SELECT outside_rows FROM sources WHERE status='extracted'"),
            [(1,)],
        )

    def test_gtfs_context_retains_zone_and_route_mode_without_schedule_payload(self):
        self.json(
            "mobilitydatabase/catalog.json",
            [
                dict(id="a", locations=[dict(country_code="FR")]),
                dict(id="missing", locations=[dict(country_code="DE")]),
            ],
        )
        p = self.root / "mobilitydatabase/raw/a.zip"
        p.parent.mkdir(parents=True)
        with zipfile.ZipFile(p, "w") as archive:
            archive.writestr(
                "fare_products.txt", "fare_product_id,amount,currency\np1,1.23,EUR\n"
            )
            archive.writestr(
                "stops.txt",
                "stop_id,zone_id,stop_name,unrelated\n001,A,Station,ignored\n",
            )
            archive.writestr("routes.txt", "route_id,route_type\nr1,4\n")
        result = self.extract()
        self.assertEqual(result["gtfs_context_rows"], 2)
        row = json.loads(
            self.query("SELECT raw_json FROM gtfs_context WHERE table_name='stops'")[0][
                0
            ]
        )
        self.assertEqual(row["zone_id"], "A")
        self.assertEqual(row["stop_id"], "001")
        self.assertIsNone(row["stop_timezone"])
        self.assertNotIn("unrelated", row)
        self.assertEqual(
            self.query(
                "SELECT status,sha256 FROM sources WHERE source_id='gtfs:missing'"
            ),
            [("missing_archive", None)],
        )

    def test_cli_success_writes_json_summary(self):
        self.json("pricing/sncf/tariffs.json", [])
        with contextlib.redirect_stdout(
            io.StringIO()
        ) as out, contextlib.redirect_stderr(io.StringIO()):
            code = e.main(
                ["--fixtures-dir", str(self.root), "--output", str(self.output)]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["pricing_rows"], 0)

    def test_unrelated_database_cannot_be_overwritten(self):
        self.json("pricing/sncf/tariffs.json", [])
        with duckdb.connect(str(self.output)) as db:
            db.execute("CREATE TABLE schedules (id INTEGER)")
            db.execute("INSERT INTO schedules VALUES (123)")
        with self.assertRaisesRegex(ValueError, "not a pricing extraction"):
            self.extract()
        self.assertEqual(self.query("SELECT * FROM schedules"), [(123,)])

    def test_duplicate_headers_fail_without_publishing(self):
        path = self.root / "pricing/flights/fares-by-month.csv"
        path.parent.mkdir(parents=True)
        path.write_text("origin_city,origin_city\nParis,Berlin\n")
        with self.assertRaisesRegex(ValueError, "unique named columns"):
            self.extract()
        self.assertFalse(self.output.exists())

    def test_european_coach_station_disambiguates_same_named_overseas_city(self):
        self.csv(
            "cities/Cities.csv",
            [
                dict(city="Stuttgart", country="Germany"),
                dict(city="Stuttgart", country="United States"),
            ],
        )
        self.csv(
            "train-stations/train_stations_europe.csv",
            [
                dict(
                    name="Stuttgart", name_norm="Stuttgart", country="DE", uic="8012345"
                ),
                dict(name="Milano", name_norm="Milano", country="IT", uic="8312345"),
            ],
        )
        p = self.root / "pricing/flixbus/data_flixbus.dta"
        p.parent.mkdir(parents=True)
        pd.DataFrame(
            [
                dict(
                    o="stuttgart",
                    d="milan",
                    fare=19.900000000000002,
                    qdate=pd.Timestamp("2017-08-07"),
                    ddate=pd.Timestamp("2017-09-04"),
                )
            ]
        ).to_stata(p, write_index=False)
        self.assertEqual(self.extract()["pricing_rows"], 1)
        self.assertEqual(
            self.query("SELECT origin_country,destination_country,price FROM pricing"),
            [("DE", "IT", Decimal("19.900000000000002"))],
        )

    def test_batch_flush_preserves_large_duplicate_input(self):
        self.csv("pricing/flights/fares-by-month.csv", [self.flight()] * 10001)
        result = self.extract()
        self.assertEqual(result["pricing_rows"], 10001)
        self.assertEqual(self.query("SELECT max(row_number) FROM pricing"), [(10001,)])
