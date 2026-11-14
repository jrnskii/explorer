"""Forecast -> one provider route -> transparent ranking calibration, offline."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

from test_round_trip import settings, offer, START
from backend.application.round_trip_search import find_round_trips, SearchLimits
from backend.domain.planning import Money
from backend.domain.pricing import (
    PriceForecast,
    QuotedPurchase,
    RoundTripQuote,
    ExactPricingUnavailable,
)
from backend.domain.travel import TransportType
from backend.infrastructure.scrappa.client import ScrappaClient
from backend.infrastructure.scrappa.exact_pricing import ScrappaRoundTripPricer

NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def routes():
    return (
        offer("ab", "A", "B", 0, 1, "10"),
        offer("ba", "B", "A", 9, 10, "10"),
        offer("ac", "A", "C", 0, 1, "15"),
        offer("ca", "C", "A", 9, 10, "15"),
    )


def quote(option, amount="25"):
    return RoundTripQuote(
        tuple(
            QuotedPurchase(
                o.id,
                replace(
                    o, synthetic=False, price=Money(Decimal(amount), o.price.currency)
                ),
                ("response-" + o.id,),
                NOW,
                o.id,
            )
            for o in option.offers
        )
    )


class StagedTests(unittest.TestCase):
    def test_second_ranked_route_is_used_when_first_quote_fails(self):
        pricer = Mock()
        def verify(option, request):
            if option.offers[0].id == "ab":
                raise ExactPricingUnavailable("no service")
            return quote(option, "12")
        pricer.quote.side_effect = verify
        result = find_round_trips(settings(), routes(), exact_pricer=pricer)
        self.assertEqual([c.args[0].offers[0].id for c in pricer.quote.call_args_list], ["ab", "ac"])
        self.assertEqual(result.pricing.provider_pricing_attempts, 2)
        self.assertEqual(len(result.options), 1)
        self.assertEqual(result.options[0].offers[0].id, "ac")
        self.assertEqual(result.options[0].price_status, "provider_advertised")

    def test_only_cheapest_is_checked_and_uplift_is_separate(self):
        pricer = Mock()
        pricer.quote.side_effect = lambda o, s: quote(o)
        result = find_round_trips(settings(), routes(), exact_pricer=pricer)
        pricer.quote.assert_called_once()
        self.assertEqual(
            tuple(o.id for o in pricer.quote.call_args.args[0].offers), ("ab", "ba")
        )
        self.assertEqual(
            [o.total_price.amount for o in result.options], [Decimal(50), Decimal(60)]
        )
        self.assertEqual(result.options[1].approximate_price.amount, Decimal(30))
        self.assertEqual(result.options[1].ranking_adjustment.amount, Decimal(30))
        self.assertEqual(
            sum(o.price.amount for o in result.options[1].offers), Decimal(30)
        )
        self.assertFalse(result.pricing.fees_complete)
        self.assertEqual(result.options[0].price_status, "provider_advertised")

    def test_provider_detail_recheck_preserves_minimum_connection_buffer(self):
        pricer = Mock()
        def too_tight(option, request):
            quoted = quote(option)
            purchases = list(quoted.purchases)
            second = purchases[1]
            earlier = replace(second.offer.path[0], departure_at=START.replace(hour=1, minute=10))
            purchases[1] = replace(second, offer=replace(second.offer, path=(earlier,)))
            return replace(quoted, purchases=tuple(purchases))
        pricer.quote.side_effect = too_tight
        result = find_round_trips(settings(), routes(), exact_pricer=pricer, min_connection_seconds=1800)
        self.assertEqual(result.pricing.status, "unavailable")
        self.assertEqual(pricer.quote.call_count, 2)

    def test_lower_actual_needs_no_uplift_and_tie_keeps_checked_first(self):
        for amount in ("5", "15"):
            with self.subTest(amount=amount):
                pricer = Mock()
                pricer.quote.side_effect = lambda o, s: quote(o, amount)
                result = find_round_trips(settings(), routes(), exact_pricer=pricer)
                self.assertEqual(result.pricing.common_uplift.amount, 0)
                self.assertEqual(result.options[0].price_status, "provider_advertised")

    def test_forecast_port_overrides_placeholder_once_after_filtering(self):
        forecaster = Mock()

        def predict(o):
            price = Money(Decimal(2), "USD")
            return (
                PriceForecast(price, price, price, "model", "test", 1, None, None, ())
                if o.id != "ac"
                else None
            )

        forecaster.estimate_offer.side_effect = predict
        supplied = routes()
        result = find_round_trips(
            settings(),
            (*supplied, supplied[0], offer("past", "A", "B", -3, -2)),
            price_forecaster=forecaster,
        )
        self.assertEqual(forecaster.estimate_offer.call_count, 4)
        self.assertEqual(result.options[0].total_price.amount, 4)
        self.assertEqual(result.pricing.unpriced_offer_ids, ("ac",))

    def test_failure_tries_second_route_and_stops(self):
        pricer = Mock()
        pricer.quote.side_effect = ExactPricingUnavailable("unavailable")
        result = find_round_trips(settings(), (*routes(), offer("ad", "A", "D", 0, 1, "20"), offer("da", "D", "A", 9, 10, "20")), exact_pricer=pricer)
        self.assertEqual(pricer.quote.call_count, 2)
        self.assertEqual(result.pricing.status, "unavailable")
        self.assertEqual([o.total_price.amount for o in result.options], [20, 30, 40])
        pricer.reset_mock()
        find_round_trips(settings(), (), exact_pricer=pricer)
        pricer.quote.assert_not_called()

    def test_over_budget_options_remain_after_provider_check(self):
        pricer = Mock()
        pricer.quote.side_effect = lambda o, s: quote(o, "5")
        result = find_round_trips(
            settings(expenses_tolerance=Money(Decimal(15), "USD")),
            routes(),
            exact_pricer=pricer,
        )
        self.assertEqual([o.total_price.amount for o in result.options], [10, 30])
        pricer.quote.side_effect = lambda o, s: quote(o)
        result = find_round_trips(
            settings(expenses_tolerance=Money(Decimal(40), "USD")),
            routes(),
            exact_pricer=pricer,
        )
        self.assertEqual([o.total_price.amount for o in result.options], [50, 60])
        self.assertEqual(result.pricing.status, "over_budget")

    def test_invalid_quotes_rejected_for_both_candidates(self):
        for transform in (
            lambda q: replace(q, purchases=q.purchases[:1]),
            lambda q: replace(q, purchases=(q.purchases[0], q.purchases[0])),
            lambda q: replace(
                q,
                purchases=(
                    replace(
                        q.purchases[0],
                        offer=replace(
                            q.purchases[0].offer, price=Money(Decimal(1), "EUR")
                        ),
                    ),
                    q.purchases[1],
                ),
            ),
            lambda q: replace(
                q,
                purchases=tuple(
                    replace(
                        p,
                        offer=replace(
                            p.offer,
                            path=tuple(replace(l, origin="X") for l in p.offer.path),
                        ),
                    )
                    for p in q.purchases
                ),
            ),
        ):
            with self.subTest(transform=transform):
                pricer = Mock()
                pricer.quote.side_effect = lambda o, s: transform(quote(o))
                result = find_round_trips(settings(), routes(), exact_pricer=pricer)
                self.assertEqual(result.pricing.status, "unavailable")
                self.assertEqual(pricer.quote.call_count, 2)

    def test_price_ranking_precedes_fuzzy_retention(self):
        pricer = Mock()
        pricer.quote.side_effect = lambda o, s: quote(o, "5")
        result = find_round_trips(
            settings(fuzzy_search=True),
            routes(),
            SearchLimits(max_results=1),
            exact_pricer=pricer,
        )
        self.assertEqual(result.pricing.checked_offer_ids, ("ab", "ba"))
        self.assertTrue(result.results_limited)

    def test_changed_timetable_must_remain_feasible(self):
        from datetime import timedelta

        def changed(o, s):
            q = quote(o)
            first = q.purchases[0]
            late = replace(
                first.offer,
                path=tuple(
                    replace(l, arrival_at=l.arrival_at + timedelta(hours=9))
                    for l in first.offer.path
                ),
            )
            return replace(q, purchases=(replace(first, offer=late), q.purchases[1]))

        pricer = Mock()
        pricer.quote.side_effect = changed
        result = find_round_trips(settings(), routes(), exact_pricer=pricer)
        self.assertEqual(result.pricing.status, "unavailable")
        self.assertEqual(pricer.quote.call_count, 2)

    def test_calibration_preserves_decimal_precision(self):
        pricer = Mock()
        pricer.quote.side_effect = lambda o, s: quote(o, "25.123456789")
        with localcontext() as context:
            context.prec = 3
            result = find_round_trips(settings(), routes(), exact_pricer=pricer)
        self.assertEqual(result.options[0].total_price.amount, Decimal("50.246913578"))
        self.assertEqual(result.options[1].total_price.amount, Decimal("60.246913578"))

    def test_bundled_purchase_is_quoted_and_counted_once(self):
        from test_round_trip import leg

        bundle = replace(
            routes()[0], path=(leg("A", "X", 0, 0.5), leg("X", "B", 0.5, 1))
        )
        pricer = Mock()
        pricer.quote.side_effect = lambda o, s: quote(o, "7")
        result = find_round_trips(
            settings(), (bundle, routes()[1]), exact_pricer=pricer
        )
        self.assertEqual(result.options[0].total_price.amount, 14)
        self.assertEqual(len(result.options[0].path), 3)
        self.assertEqual(len(result.options[0].offers), 2)
        pricer.quote.assert_called_once()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []
        self.client = ScrappaClient(
            Path(self.tmp.name) / "cache.duckdb",
            api_key="test",
            transport=self.transport,
            clock=lambda: NOW,
        )
        self.addCleanup(self.client.close)
        self.pricer = ScrappaRoundTripPricer(self.client, {"A": 1, "B": 2, "C": 3})

    def service(self, tid):
        out = tid == "1"
        start = START.replace(hour=0 if out else 9)
        end = START.replace(hour=1 if out else 10)
        return dict(
            trip_id=tid,
            mode="train",
            is_bookable=True,
            is_split_ticket=False,
            is_routed_connection=False,
            departure_time=start.isoformat(),
            arrival_time=end.isoformat(),
            legs=[
                dict(
                    mode="train",
                    departure_time=start.isoformat(),
                    arrival_time=end.isoformat(),
                )
            ],
            offers=[
                dict(
                    type="ONE_WAY",
                    is_available=True,
                    discount_cards=[],
                    unavailability_reasons=[],
                    price=dict(amount_minor=2500, currency="USD"),
                )
            ],
        )

    def transport(self, url, key, timeout):
        self.calls.append(url)
        params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        if urlparse(url).path.endswith("/search"):
            tid = params["origin_id"]
            data = dict(
                trip_type="one_way",
                origin_id=int(params["origin_id"]),
                destination_id=int(params["destination_id"]),
                date=params["date"],
                currency="USD",
                passengers=dict(adults=1, children=0, infants=0),
                search_meta=dict(search_id=tid),
                results=[self.service(tid)],
            )
        else:
            data = dict(
                search_id=params["search_id"], trip=self.service(params["trip_id"]), currency="USD"
            )
        return 200, json.dumps(dict(success=True, data=data))

    def test_cache_and_observations_reuse_original_provenance(self):
        first = find_round_trips(settings(), routes(), exact_pricer=self.pricer)
        self.assertEqual(first.pricing.status, "provider_priced")
        self.assertEqual(len(self.calls), 4)
        rows = self.client.db.execute(
            "SELECT response_id,CAST(observed_at AS VARCHAR),amount FROM fare_observations ORDER BY response_id"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual([r[2] for r in rows], [25, 25])
        self.pricer.cache_only = True
        second = find_round_trips(settings(), routes(), exact_pricer=self.pricer)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(second.pricing.response_ids, first.pricing.response_ids)
        self.assertEqual(
            self.client.db.execute(
                "SELECT response_id,CAST(observed_at AS VARCHAR),amount FROM fare_observations ORDER BY response_id"
            ).fetchall(),
            rows,
        )
        self.assertEqual(
            self.client.db.execute("SELECT count(*) FROM responses").fetchone()[0], 4
        )

    def test_unsupported_or_unmapped_route_does_not_call_api(self):
        for mode, places in (
            (TransportType.FERRIES, {"A": 1, "B": 2}),
            (TransportType.TRAINS, {"A": 1}),
        ):
            pricer = ScrappaRoundTripPricer(self.client, places)
            result = find_round_trips(
                settings(),
                tuple(
                    replace(
                        o, path=tuple(replace(l, transport_type=mode) for l in o.path)
                    )
                    for o in routes()[:2]
                ),
                exact_pricer=pricer,
            )
            self.assertEqual(result.pricing.status, "unavailable")
        self.assertFalse(self.calls)

    def test_provider_error_is_cached_and_never_retried(self):
        self.client.transport = Mock(return_value=(503, '{"success":false}'))
        for _ in range(2):
            result = find_round_trips(settings(), routes(), exact_pricer=self.pricer)
            self.assertEqual(result.pricing.status, "unavailable")
        self.assertEqual(self.client.transport.call_count, 2)
        self.assertEqual(
            self.client.db.execute("SELECT count(*) FROM fare_observations").fetchone()[
                0
            ],
            0,
        )

    def test_wrong_search_cohort_cannot_create_fare_observations(self):
        for field, value in (
            ("passengers", dict(adults=2, children=0, infants=0)),
            ("passengers", dict(adults=True, children=0, infants=0)),
            ("origin_id", True),
            ("currency", "EUR"),
        ):
            with self.subTest(field=field):
                def wrong_cohort(url, key, timeout):
                    status, raw = self.transport(url, key, timeout)
                    payload = json.loads(raw)
                    payload["data"][field] = value
                    return status, json.dumps(payload)
                with tempfile.TemporaryDirectory() as directory:
                    with ScrappaClient(Path(directory) / "cache.duckdb", api_key="test",
                                       transport=wrong_cohort, clock=lambda: NOW) as client:
                        pricer = ScrappaRoundTripPricer(client, {"A": 1, "B": 2, "C": 3})
                        result = find_round_trips(settings(), routes(), exact_pricer=pricer)
                        self.assertEqual(result.pricing.status, "unavailable")
                        self.assertEqual(client.db.execute("SELECT count(*) FROM fare_observations").fetchone()[0], 0)
                        self.assertEqual(client.db.execute("SELECT count(*) FROM responses").fetchone()[0], 2)

    def test_wrong_detail_currency_is_not_recorded_as_an_observation(self):
        def wrong_currency(url, key, timeout):
            status, raw = self.transport(url, key, timeout)
            payload = json.loads(raw)
            if urlparse(url).path.endswith("trip"):
                payload["data"]["currency"] = "EUR"
            return status, json.dumps(payload)
        self.client.transport = wrong_currency
        result = find_round_trips(settings(), routes(), exact_pricer=self.pricer)
        self.assertEqual(result.pricing.status, "unavailable")
        self.assertEqual(self.client.db.execute("SELECT count(*) FROM fare_observations").fetchone()[0], 0)
        self.assertEqual(self.client.db.execute("SELECT count(*) FROM responses").fetchone()[0], 5)

    def test_probe_and_exact_verification_coexist_and_resume_in_same_database(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from backend.infrastructure.scrappa.route_probe import fetch_routes

        def combined_transport(url, key, timeout):
            query = parse_qs(urlparse(url).query)
            path = urlparse(url).path
            if path.endswith("places"):
                city = query["query"][0]
                return 200, json.dumps(dict(success=True, data=dict(results=[dict(
                    name=city, type="location", country_code="LT" if city == "Vilnius" else "PL",
                    position_id=1 if city == "Vilnius" else 2,
                )])))
            status, raw = self.transport(url, key, timeout)
            payload = json.loads(raw)
            if len(query.get("travel_mode[]", [])) == 3:
                payload["data"].update(
                    currency="EUR", pagination=dict(page=1, has_more=False, total=1),
                    search_meta=dict(search_id="probe", modes_done=["train", "bus", "flight"]),
                )
                payload["data"]["results"][0]["offers"][0]["price"]["currency"] = "EUR"
            return status, json.dumps(payload)

        self.client.transport = combined_transport
        with redirect_stderr(StringIO()):
            probe = fetch_routes(self.client, "2026-12-01", (("Warsaw", "PL"),))
        self.assertEqual(probe["destinations"][0]["status"], "complete")
        self.assertEqual(self.client.db.execute("SELECT count(*) FROM fare_observations").fetchone()[0], 0)
        first = find_round_trips(settings(), routes(), exact_pricer=self.pricer)
        self.assertEqual(first.pricing.status, "provider_priced")
        self.assertEqual(self.client.db.execute("SELECT count(*) FROM responses").fetchone()[0], 7)
        rows = self.client.db.execute("SELECT response_id, search_response_id, CAST(observed_at AS VARCHAR), amount FROM fare_observations ORDER BY response_id").fetchall()
        self.assertEqual(len(rows), 2)
        self.client.transport = Mock(side_effect=AssertionError("No HTTP during resume"))
        self.pricer.cache_only = True
        with redirect_stderr(StringIO()):
            self.assertEqual(fetch_routes(self.client, "2026-12-01", (("Warsaw", "PL"),)), probe)
        second = find_round_trips(settings(), routes(), exact_pricer=self.pricer)
        self.assertEqual(second.pricing.response_ids, first.pricing.response_ids)
        self.client.transport.assert_not_called()
        self.assertEqual(self.client.db.execute("SELECT response_id, search_response_id, CAST(observed_at AS VARCHAR), amount FROM fare_observations ORDER BY response_id").fetchall(), rows)

    def test_floor_only_response_is_not_a_quote(self):
        self.client.transport = Mock(
            return_value=(
                200,
                json.dumps(
                    dict(
                        success=True,
                        data=dict(
                            trip_type="one_way",
                            origin_id=1,
                            destination_id=2,
                            date="2026-12-01",
                            currency="USD",
                            passengers=dict(adults=1, children=0, infants=0),
                            search_meta=dict(search_id="1"),
                            price_floor_per_mode=dict(
                                train=dict(amount_minor=1, currency="USD")
                            ),
                        ),
                    )
                ),
            )
        )
        result = find_round_trips(settings(), routes(), exact_pricer=self.pricer)
        self.assertEqual(result.pricing.status, "unavailable")
        self.assertEqual(self.client.transport.call_count, 2)
        self.assertEqual(
            self.client.db.execute("SELECT count(*) FROM fare_observations").fetchone()[
                0
            ],
            0,
        )

    def test_invalid_provider_fares_are_never_observations(self):
        from backend.infrastructure.scrappa.exact_pricing import _parse

        original = routes()[0]
        for amount in (True, -1, "2500", None):
            raw = self.service("1")
            raw["offers"][0]["price"]["amount_minor"] = amount
            self.assertIsNone(_parse(raw, original, "train", "USD", "2026-12-01"))
        raw = self.service("1")
        raw["offers"][0]["discount_cards"] = ["card"]
        self.assertIsNone(_parse(raw, original, "train", "USD", "2026-12-01"))

    def test_actual_services_are_selected_for_connection_feasibility(self):
        from backend.infrastructure.scrappa.exact_pricing import _Service
        from datetime import timedelta

        out, back = routes()[:2]
        late = replace(
            out,
            path=tuple(
                replace(l, arrival_at=l.arrival_at + timedelta(hours=9))
                for l in out.path
            ),
            price=Money(Decimal(1), "USD"),
        )
        services = [
            (None, None, [_Service(late, "late", {}), _Service(out, "feasible", {})]),
            (None, None, [_Service(back, "home", {})]),
        ]
        selected = self.pricer._choose_services(services, settings())
        self.assertEqual([s.trip_id for s in selected], ["feasible", "home"])
