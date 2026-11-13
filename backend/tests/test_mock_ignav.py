"""Behavioral tests for the offline Ignav generator; no network calls required."""

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.infrastructure.fixtures.ignav import MockIgnavGenerator

from backend.infrastructure.ignav import models as api

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
OUTBOUND = {
    "origin": "JFK",
    "destination": "LHR",
    "departure_date": "2026-06-10",
}
RETURN_DATE = "2026-06-20"
CALENDAR = {
    "origin": "JFK",
    "destination": "LHR",
    "departure_date_range": {"start": "2026-06-10", "end": "2026-06-12"},
}


def search_request(two_legs=False, **options):
    legs = [dict(OUTBOUND)]
    if two_legs:
        legs.append(
            {
                "origin": OUTBOUND["destination"],
                "destination": OUTBOUND["origin"],
                "departure_date": RETURN_DATE,
            }
        )
    return dict(options, legs=legs)


def utc(value):
    return datetime.fromisoformat(value)


def codes(item):
    return {
        segment.marketing_carrier_code for leg in item.legs for segment in leg.segments
    }


class MockIgnavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.openapi = json.loads(
            (ROOT / "docs/api_references/ignav/openapi.json").read_text()
        )

    def setUp(self):
        self.generator = MockIgnavGenerator(seed=17, count=24)

    def assert_contract(self, value, model):
        self.assertIsInstance(value, model)
        payload = value.model_dump(mode="json")
        self.assertEqual(model.model_validate_json(json.dumps(payload)), value)
        schema = self.openapi["components"]["schemas"][model.__name__]
        self.assertLessEqual(set(schema.get("required", [])), set(payload))
        if schema.get("additionalProperties") is False:
            self.assertLessEqual(set(payload), set(schema["properties"]))
        return payload

    def assert_leg(self, leg, origin, destination, departure_date):
        self.assertTrue(leg.segments)
        self.assertEqual(leg.segments[0].departure_airport, origin)
        self.assertEqual(leg.segments[-1].arrival_airport, destination)
        self.assertEqual(
            datetime.fromisoformat(leg.segments[0].departure_time_local).date(),
            date.fromisoformat(departure_date),
        )
        for segment in leg.segments:
            with self.subTest(segment=segment.flight_number):
                departure = utc(segment.departure_time_utc)
                arrival = utc(segment.arrival_time_utc)
                self.assertEqual(departure.utcoffset(), timedelta(0))
                self.assertEqual(arrival.utcoffset(), timedelta(0))
                self.assertGreater(arrival, departure)
                self.assertEqual(
                    (arrival - departure).total_seconds(),
                    segment.duration_minutes * 60,
                )
                for event in ("departure", "arrival"):
                    instant = utc(getattr(segment, event + "_time_utc"))
                    local = datetime.fromisoformat(
                        getattr(segment, event + "_time_local")
                    )
                    zone = ZoneInfo(getattr(segment, event + "_timezone"))
                    self.assertEqual(
                        local, instant.astimezone(zone).replace(tzinfo=None)
                    )
        for previous, following in zip(leg.segments, leg.segments[1:]):
            self.assertEqual(previous.arrival_airport, following.departure_airport)
            self.assertGreater(
                utc(following.departure_time_utc), utc(previous.arrival_time_utc)
            )
        elapsed = (
            utc(leg.segments[-1].arrival_time_utc)
            - utc(leg.segments[0].departure_time_utc)
        ).total_seconds() / 60
        self.assertEqual(leg.duration_minutes, elapsed)

    def assert_sorted_prices(self, itineraries):
        prices = [item.price.amount for item in itineraries]
        self.assertEqual(prices, sorted(prices))
        for item in itineraries:
            self.assertGreater(item.price.amount, 0)
            self.assertEqual(item.price.currency, "USD")
            self.assertEqual(item.price.status, "unverified")
            self.assertTrue(item.ignav_id)

    def assert_filtered(self, request, predicate):
        baseline = self.generator.search(search_request(two_legs=True))
        expected = [item for item in baseline.itineraries if predicate(item)]
        self.assertTrue(expected, "Fixture must exercise retained candidates")
        self.assertLess(len(expected), len(baseline.itineraries))
        actual = self.generator.search(request)
        self.assertEqual(actual.itineraries, expected)

    def test_health_shape(self):
        result = self.generator.health()
        self.assert_contract(result, api.HealthResponseModel)
        self.assertIs(result.ok, True)
        self.assertTrue(result.release)

    def test_airports_search_fields_case_whitespace_and_limit(self):
        for query, expected in (
            (" jFk ", "JFK"),
            ("kennedy", "JFK"),
            ("New York", "JFK"),
            ("gb", "LHR"),
        ):
            with self.subTest(query=query):
                results = self.generator.airports(query)
                self.assertIn(expected, [airport.code for airport in results])
                for airport in results:
                    self.assert_contract(airport, api.AirportModel)
        self.assertEqual(self.generator.airports("not-an-airport"), [])
        self.assertEqual(len(self.generator.airports("", limit=1)), 1)
        all_airports = self.generator.airports("", limit=20)
        self.assertGreater(len(all_airports), 1)
        self.assertLessEqual(len(all_airports), 20)
        self.assertEqual(len({a.code for a in all_airports}), len(all_airports))
        self.assertEqual(
            self.generator.airports("Warsaw", limit=1),
            self.generator.airports("Warsaw")[:1],
        )

    def test_search_one_and_two_leg_shapes(self):
        for two_legs in (False, True):
            with self.subTest(two_legs=two_legs):
                request = search_request(two_legs)
                result = self.generator.search(request)
                self.assert_contract(result, api.FareSearchModel)
                self.assertEqual(
                    [leg.model_dump() for leg in result.legs], request["legs"]
                )
                self.assertTrue(result.itineraries)
                self.assertLessEqual(len(result.itineraries), self.generator.count)
                self.assert_sorted_prices(result.itineraries)
                self.assertEqual(
                    len({i.ignav_id for i in result.itineraries}),
                    len(result.itineraries),
                )
                for item in result.itineraries:
                    self.assertEqual(len(item.legs), len(request["legs"]))
                    for leg, requested in zip(item.legs, request["legs"]):
                        self.assert_leg(leg, **requested)
                    mixed = any(
                        len({s.marketing_carrier_code for s in leg.segments}) > 1
                        for leg in item.legs
                    )
                    self.assertEqual(item.has_mixed_carriers, mixed)

    def test_directional_shapes_match_general_search(self):
        for two_legs in (False, True):
            with self.subTest(two_legs=two_legs):
                general = self.generator.search(search_request(two_legs))
                request = dict(OUTBOUND)
                if two_legs:
                    request["return_date"] = RETURN_DATE
                method = (
                    self.generator.round_trip if two_legs else self.generator.one_way
                )
                directional = method(request)
                self.assert_contract(directional, api.FareSearchResponseModel)
                self.assertEqual(directional.origin, OUTBOUND["origin"])
                self.assertEqual(directional.destination, OUTBOUND["destination"])
                self.assertEqual(directional.departure_date, OUTBOUND["departure_date"])
                self.assertEqual(
                    directional.return_date, RETURN_DATE if two_legs else None
                )
                self.assertEqual(len(directional.itineraries), len(general.itineraries))
                self.assertTrue(directional.itineraries)
                self.assert_sorted_prices(directional.itineraries)
                for actual, expected in zip(
                    directional.itineraries, general.itineraries
                ):
                    raw = actual.model_dump(exclude={"ignav_id", "outbound", "inbound"})
                    raw["legs"] = [actual.outbound.model_dump()]
                    if two_legs:
                        self.assertIsNotNone(actual.inbound)
                        raw["legs"].append(actual.inbound.model_dump())
                    else:
                        self.assertIsNone(actual.inbound)
                    self.assertEqual(raw, expected.model_dump(exclude={"ignav_id"}))

    def test_repeatability_model_inputs_and_seed_variation(self):
        cases = (
            ("search", search_request(True), api.FareSearchRequest),
            ("one_way", OUTBOUND, api.OneWayRequest),
            (
                "round_trip",
                dict(OUTBOUND, return_date=RETURN_DATE),
                api.RoundTripRequest,
            ),
            ("cheapest_dates", CALENDAR, api.CheapestDatesRequest),
        )
        for operation, request, model in cases:
            with self.subTest(operation=operation):
                original = deepcopy(request)
                method = getattr(self.generator, operation)
                first = method(request)
                self.assertEqual(first, method(request))
                self.assertEqual(first, method(model.model_validate(request)))
                self.assertEqual(request, original)
                other = MockIgnavGenerator(seed=17, count=24)
                self.assertEqual(first, getattr(other, operation)(request))
                different = MockIgnavGenerator(seed=18, count=24)
                self.assertNotEqual(first, getattr(different, operation)(request))

    def test_call_order_does_not_change_results(self):
        cases = {
            "search": search_request(True),
            "one_way": OUTBOUND,
            "round_trip": dict(OUTBOUND, return_date=RETURN_DATE),
            "cheapest_dates": CALENDAR,
        }
        expected = {
            name: getattr(self.generator, name)(request)
            for name, request in cases.items()
        }
        other = MockIgnavGenerator(seed=17, count=24)
        for name, request in reversed(list(cases.items())):
            other.health()
            other.airports("London")
            actual = getattr(other, name)(request)
            self.assertEqual(actual, expected[name])
            if hasattr(actual, "itineraries"):
                other.booking_links({"ignav_id": actual.itineraries[0].ignav_id})
        for name, request in cases.items():
            self.assertEqual(getattr(other, name)(request), expected[name])

    def test_observed_at_is_normalized_to_utc(self):
        observed = datetime(2026, 7, 1, 12, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
        generator = MockIgnavGenerator(observed_at=observed)
        for result in (
            generator.search(search_request()),
            generator.one_way(OUTBOUND),
            generator.round_trip(dict(OUTBOUND, return_date=RETURN_DATE)),
            generator.cheapest_dates(CALENDAR),
        ):
            with self.subTest(model=type(result).__name__):
                self.assertEqual(result.observed_at, observed.astimezone(UTC))
                self.assertEqual(result.observed_at.utcoffset(), timedelta(0))
        default = self.generator.one_way(OUTBOUND).observed_at
        self.assertIsNotNone(default)
        self.assertEqual(default.utcoffset(), timedelta(0))

    def test_timezone_and_dst_transition_dates(self):
        # Exercise US and European spring gaps and autumn folds, plus stable seasons.
        for origin, destination, zone, dates in (
            (
                "JFK",
                "LHR",
                "America/New_York",
                ("2026-01-15", "2026-03-08", "2026-07-15", "2026-11-01"),
            ),
            (
                "LHR",
                "JFK",
                "Europe/London",
                ("2026-01-15", "2026-03-29", "2026-07-15", "2026-10-25"),
            ),
        ):
            offsets = {}
            for day in dates:
                with self.subTest(origin=origin, day=day):
                    result = self.generator.one_way(
                        {
                            "origin": origin,
                            "destination": destination,
                            "departure_date": day,
                        }
                    )
                    self.assertTrue(result.itineraries)
                    for item in result.itineraries:
                        self.assert_leg(item.outbound, origin, destination, day)
                        first = item.outbound.segments[0]
                        self.assertEqual(first.departure_timezone, zone)
                    offsets[day] = (
                        utc(
                            result.itineraries[0]
                            .outbound.segments[0]
                            .departure_time_utc
                        )
                        .astimezone(ZoneInfo(zone))
                        .utcoffset()
                    )
            self.assertNotEqual(offsets[dates[0]], offsets[dates[2]])

    def test_round_trip_dates_and_connection_chronology(self):
        for return_date in (OUTBOUND["departure_date"], RETURN_DATE):
            with self.subTest(return_date=return_date):
                result = self.generator.round_trip(
                    dict(OUTBOUND, return_date=return_date)
                )
                if return_date == RETURN_DATE:
                    self.assertTrue(result.itineraries)
                for item in result.itineraries:
                    self.assert_leg(
                        item.outbound, "JFK", "LHR", OUTBOUND["departure_date"]
                    )
                    self.assert_leg(item.inbound, "LHR", "JFK", return_date)
                    self.assertGreater(
                        utc(item.inbound.segments[0].departure_time_utc),
                        utc(item.outbound.segments[-1].arrival_time_utc),
                    )

    def test_short_same_day_round_trip_is_feasible(self):
        request = dict(
            OUTBOUND,
            origin="WAW",
            destination="KRK",
            return_date=OUTBOUND["departure_date"],
            max_stops=0,
        )
        result = self.generator.round_trip(request)
        self.assertTrue(result.itineraries)
        for item in result.itineraries:
            self.assert_leg(item.outbound, "WAW", "KRK", request["departure_date"])
            self.assert_leg(item.inbound, "KRK", "WAW", request["return_date"])
            self.assertGreater(
                utc(item.inbound.segments[0].departure_time_utc),
                utc(item.outbound.segments[-1].arrival_time_utc),
            )

    def test_max_stops_filters_each_leg_without_regeneration(self):
        for maximum in (0, 1, 2):
            with self.subTest(maximum=maximum):
                request = search_request(True)
                for leg in request["legs"]:
                    leg["max_stops"] = maximum
                baseline = self.generator.search(search_request(True))
                actual = self.generator.search(request)
                expected = [
                    i
                    for i in baseline.itineraries
                    if all(len(leg.segments) - 1 <= maximum for leg in i.legs)
                ]
                self.assertTrue(expected)
                self.assertEqual(actual.itineraries, expected)

    def test_max_price_is_inclusive_and_zero_returns_no_fares(self):
        baseline = self.generator.search(search_request(True))
        threshold = int(
            baseline.itineraries[len(baseline.itineraries) // 2].price.amount
        )
        self.assert_filtered(
            search_request(True, max_price=threshold),
            lambda i: i.price.amount <= threshold,
        )
        self.assertEqual(
            self.generator.search(search_request(True, max_price=0)).itineraries, []
        )
        # Use a whole-dollar candidate to exercise equality at the integer cap,
        # without hardcoding a fare or depending on the pricing formula.
        generator = MockIgnavGenerator(seed=4, count=100)
        candidates = generator.search(search_request(True)).itineraries
        whole_dollar = [i for i in candidates if i.price.amount.is_integer()]
        self.assertTrue(whole_dollar, "Fixture must contain an exact price boundary")
        item = whole_dollar[0]
        cap = int(item.price.amount)
        self.assertIn(
            item, generator.search(search_request(True, max_price=cap)).itineraries
        )
        self.assertNotIn(
            item, generator.search(search_request(True, max_price=cap - 1)).itineraries
        )

    def test_airline_include_and_exclude_apply_to_every_segment(self):
        baseline = self.generator.search(search_request(True))
        single = next(i for i in baseline.itineraries if len(codes(i)) == 1)
        carrier = next(iter(codes(single)))
        self.assert_filtered(
            search_request(True, airlines_include=[carrier.lower()]),
            lambda i: codes(i) <= {carrier},
        )
        self.assert_filtered(
            search_request(True, airlines_exclude=[carrier.lower()]),
            lambda i: carrier not in codes(i),
        )
        self.assertEqual(
            self.generator.search(
                search_request(
                    True, airlines_include=[carrier], airlines_exclude=[carrier]
                )
            ).itineraries,
            [],
        )
        self.assertEqual(
            self.generator.search(
                search_request(True, airlines_include=["NOT-A-CARRIER"])
            ).itineraries,
            [],
        )
        self.assertEqual(
            self.generator.search(
                search_request(True, airlines_include=[], airlines_exclude=[])
            ),
            baseline,
        )

    def test_mixed_carrier_filter_and_flag(self):
        self.assert_filtered(
            search_request(True, allow_mixed_carriers=False),
            lambda i: all(
                len({s.marketing_carrier_code for s in leg.segments}) == 1
                for leg in i.legs
            ),
        )

    def test_local_time_range_bounds_are_inclusive(self):
        baseline = self.generator.search(search_request(True))
        target = baseline.itineraries[0]
        for leg_index in (0, 1):
            for prefix, event, segment_index in (
                ("", "departure", 0),
                ("arrival_", "arrival", -1),
            ):
                hour = datetime.fromisoformat(
                    getattr(
                        target.legs[leg_index].segments[segment_index],
                        event + "_time_local",
                    )
                ).hour
                for bounds in (
                    {prefix + "earliest_hour": hour},
                    {prefix + "latest_hour": hour},
                    {prefix + "earliest_hour": hour, prefix + "latest_hour": hour},
                ):
                    with self.subTest(leg=leg_index, bounds=bounds):
                        request = search_request(True)
                        request["legs"][leg_index]["departure_time_range"] = bounds

                        def matches(item):
                            value = datetime.fromisoformat(
                                getattr(
                                    item.legs[leg_index].segments[segment_index],
                                    event + "_time_local",
                                )
                            ).hour
                            return value >= bounds.get(
                                prefix + "earliest_hour", 0
                            ) and value <= bounds.get(prefix + "latest_hour", 23)

                        actual = self.generator.search(request)
                        self.assertEqual(
                            actual.itineraries,
                            [i for i in baseline.itineraries if matches(i)],
                        )
                        self.assertIn(target, actual.itineraries)

    def test_combined_filters_and_directional_return_time_range(self):
        request = dict(OUTBOUND, return_date=RETURN_DATE)
        baseline = self.generator.round_trip(request)
        target = next(i for i in baseline.itineraries if not i.has_mixed_carriers)
        hour = datetime.fromisoformat(
            target.inbound.segments[-1].arrival_time_local
        ).hour
        actual = self.generator.round_trip(
            dict(
                request,
                allow_mixed_carriers=False,
                max_price=int(target.price.amount) + 1,
                return_time_range={
                    "arrival_earliest_hour": hour,
                    "arrival_latest_hour": hour,
                },
            )
        )
        expected = [
            i
            for i in baseline.itineraries
            if (
                not i.has_mixed_carriers
                and i.price.amount <= int(target.price.amount) + 1
                and datetime.fromisoformat(
                    i.inbound.segments[-1].arrival_time_local
                ).hour
                == hour
            )
        ]
        self.assertTrue(expected)
        self.assertEqual(actual.itineraries, expected)

    def test_cheapest_dates_inclusive_and_matches_directional_search(self):
        options = {
            "adults": 2,
            "children": 1,
            "infants_in_seat": 1,
            "infants_on_lap": 1,
            "cabin_class": "business",
            "carry_on_bags": 2,
            "checked_bags": 1,
            "max_stops": 1,
            "max_price": 100000,
            "market": "GB",
            "departure_time_range": {"earliest_hour": 6},
            "return_time_range": {"latest_hour": 22},
        }
        for stay in (None, 0, 5):
            with self.subTest(stay=stay):
                result = self.generator.cheapest_dates(
                    dict(CALENDAR, stay_days=stay, **options)
                )
                self.assert_contract(result, api.CheapestDatesResponseModel)
                self.assertEqual((result.origin, result.destination), ("JFK", "LHR"))
                self.assertEqual(
                    [d.departure_date for d in result.dates],
                    ["2026-06-10", "2026-06-11", "2026-06-12"],
                )
                for entry in result.dates:
                    query = dict(
                        options,
                        origin="JFK",
                        destination="LHR",
                        departure_date=entry.departure_date,
                    )
                    if stay is None:
                        query.pop("return_time_range")
                        expected = self.generator.one_way(query)
                        self.assertIsNone(entry.return_date)
                    else:
                        return_date = (
                            date.fromisoformat(entry.departure_date)
                            + timedelta(days=stay)
                        ).isoformat()
                        self.assertEqual(entry.return_date, return_date)
                        expected = self.generator.round_trip(
                            dict(query, return_date=return_date)
                        )
                    prices = [i.price for i in expected.itineraries]
                    self.assertEqual(
                        entry.price,
                        min(prices, key=lambda p: p.amount) if prices else None,
                    )
                if stay != 0:
                    self.assertTrue(any(d.price is not None for d in result.dates))

    def test_cheapest_dates_single_day_and_null_fares(self):
        for stay in (None, 0, 3):
            with self.subTest(stay=stay):
                result = self.generator.cheapest_dates(
                    dict(
                        CALENDAR,
                        stay_days=stay,
                        max_price=0,
                        departure_date_range={
                            "start": "2026-12-31",
                            "end": "2026-12-31",
                        },
                    )
                )
                self.assertEqual(len(result.dates), 1)
                entry = result.dates[0]
                self.assertEqual(entry.departure_date, "2026-12-31")
                self.assertIsNone(entry.price)
                expected = (
                    None
                    if stay is None
                    else (date(2026, 12, 31) + timedelta(days=stay)).isoformat()
                )
                self.assertEqual(entry.return_date, expected)

    def test_cheapest_dates_maximum_inclusive_window(self):
        result = MockIgnavGenerator(count=1).cheapest_dates(
            dict(
                CALENDAR,
                max_price=0,
                departure_date_range={"start": "2026-01-01", "end": "2027-01-01"},
            )
        )
        self.assertEqual(len(result.dates), 366)
        self.assertEqual(result.dates[0].departure_date, "2026-01-01")
        self.assertEqual(result.dates[-1].departure_date, "2027-01-01")

    def test_booking_by_id_both_response_shapes_and_leg_coverage(self):
        for two_legs in (False, True):
            directional_request = dict(OUTBOUND)
            if two_legs:
                directional_request["return_date"] = RETURN_DATE
            directional_method = (
                self.generator.round_trip if two_legs else self.generator.one_way
            )
            for result, response_model in (
                (
                    self.generator.search(search_request(two_legs)),
                    api.SearchBookingOptionsResponseModel,
                ),
                (
                    directional_method(directional_request),
                    api.BookingOptionsResponseModel,
                ),
            ):
                with self.subTest(two_legs=two_legs, model=response_model.__name__):
                    original = result.itineraries[0]
                    request = api.BookingLinksRequest(ignav_id=original.ignav_id)
                    booking = self.generator.booking_links(request)
                    self.assert_contract(booking, response_model)
                    self.assertEqual(
                        booking.itinerary.model_dump(),
                        original.model_dump(exclude={"ignav_id"}),
                    )
                    self.assertTrue(booking.booking_options)
                    for option in booking.booking_options:
                        if response_model is api.SearchBookingOptionsResponseModel:
                            self.assertEqual(
                                option.leg_indexes, list(range(2 if two_legs else 1))
                            )
                        else:
                            self.assertEqual(
                                option.legs,
                                ["outbound", "inbound"] if two_legs else ["outbound"],
                            )
                        self.assertTrue(option.links)
                        for link in option.links:
                            self.assertTrue(link.url.startswith("https://"))
                            self.assertTrue(link.provider_name)
                            self.assertEqual(link.price, original.price)
                    self.assertEqual(booking, self.generator.booking_links(request))

    def test_booking_cache_is_isolated_from_mutations(self):
        for operation, request in (
            ("search", search_request(True)),
            ("round_trip", dict(OUTBOUND, return_date=RETURN_DATE)),
        ):
            with self.subTest(operation=operation):
                result = getattr(self.generator, operation)(request)
                item = result.itineraries[0]
                booking_request = {"ignav_id": item.ignav_id}
                original = self.generator.booking_links(booking_request).model_dump(
                    mode="json"
                )
                item.price.amount = -1
                legs = (
                    item.legs
                    if operation == "search"
                    else [item.outbound, item.inbound]
                )
                legs[0].segments[0].flight_number = "mutated-search"
                booking = self.generator.booking_links(booking_request)
                self.assertEqual(booking.model_dump(mode="json"), original)
                booking.itinerary.price.amount = -2
                booking_legs = (
                    booking.itinerary.legs
                    if operation == "search"
                    else [booking.itinerary.outbound]
                )
                booking_legs[0].segments.clear()
                booking.booking_options[0].links.clear()
                self.assertEqual(
                    self.generator.booking_links(booking_request).model_dump(
                        mode="json"
                    ),
                    original,
                )

    def test_booking_by_route_with_explicit_flights(self):
        for two_legs in (False, True):
            with self.subTest(two_legs=two_legs):
                request = dict(
                    OUTBOUND, outbound_carrier_code="lo", outbound_flight_number="123"
                )
                if two_legs:
                    request.update(
                        return_date=RETURN_DATE,
                        inbound_carrier_code="ba",
                        inbound_flight_number="456",
                    )
                original = deepcopy(request)
                result = self.generator.booking_links(request)
                self.assert_contract(result, api.BookingOptionsResponseModel)
                segment = result.itinerary.outbound.segments[0]
                self.assertEqual(
                    (segment.marketing_carrier_code, segment.flight_number),
                    ("LO", "123"),
                )
                if two_legs:
                    segment = result.itinerary.inbound.segments[0]
                    self.assertEqual(
                        (segment.marketing_carrier_code, segment.flight_number),
                        ("BA", "456"),
                    )
                else:
                    self.assertIsNone(result.itinerary.inbound)
                self.assertEqual(request, original)
                self.assertEqual(result, self.generator.booking_links(request))

    def test_booking_unknown_id_and_missing_or_inconsistent_flight_inputs(self):
        for request in (
            {"ignav_id": "unknown-id"},
            {},
            {"origin": "JFK"},
            dict(OUTBOUND, outbound_carrier_code="LO"),
            dict(OUTBOUND, outbound_flight_number="123"),
            dict(OUTBOUND, inbound_carrier_code="BA", inbound_flight_number="456"),
            dict(OUTBOUND, outbound_carrier_code="ZZ", outbound_flight_number="123"),
        ):
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    self.generator.booking_links(request)
        item = self.generator.one_way(OUTBOUND).itineraries[0]
        with self.assertRaises(ValueError):
            MockIgnavGenerator(seed=17, count=24).booking_links(
                {"ignav_id": item.ignav_id}
            )

    def test_constructor_and_airport_limit_validation(self):
        for count in (0, 101, -1, True, 1.5, "8", None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                MockIgnavGenerator(count=count)
        for count in (1, 100):
            self.assertTrue(
                MockIgnavGenerator(count=count).one_way(OUTBOUND).itineraries
            )
        with self.assertRaises(ValueError):
            MockIgnavGenerator(observed_at=datetime(2026, 1, 1))
        for limit in (0, 21, -1, True, 1.5, "10", None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.generator.airports("JFK", limit=limit)

    def test_directional_input_validation(self):
        invalid = (
            {"origin": "XXX"},
            {"destination": "XXX"},
            {"destination": "JFK"},
            {"departure_date": "not-a-date"},
            {"departure_date": "2026-02-30"},
            {"adults": 0},
            {"children": -1},
            {"infants_in_seat": -1},
            {"infants_on_lap": -1},
            {"cabin_class": "cargo"},
            {"max_stops": -1},
            {"max_stops": 3},
            {"max_price": -1},
            {"checked_bags": -1},
            {"carry_on_bags": 10},
            {"checked_bags": 2},
            {"carry_on_bags": 2},
            {"departure_time_range": {"earliest_hour": -1}},
            {"departure_time_range": {"latest_hour": 24}},
            {"departure_time_range": {"earliest_hour": 18, "latest_hour": 6}},
            {
                "departure_time_range": {
                    "arrival_earliest_hour": 18,
                    "arrival_latest_hour": 6,
                }
            },
            {"unexpected": True},
        )
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.generator.one_way(dict(OUTBOUND, **overrides))
        with self.assertRaises(ValueError):
            self.generator.one_way({})
        for request in (
            OUTBOUND,
            dict(OUTBOUND, return_date="2026-06-09"),
            dict(
                OUTBOUND,
                return_date=RETURN_DATE,
                return_time_range={"earliest_hour": 20, "latest_hour": 5},
            ),
        ):
            with self.subTest(round_trip=request), self.assertRaises(ValueError):
                self.generator.round_trip(request)

    def test_general_search_leg_validation(self):
        for legs in (
            [],
            [dict(OUTBOUND)] * 3,
            [{}],
            [dict(OUTBOUND, max_stops=3)],
            [dict(OUTBOUND), dict(OUTBOUND, departure_date="2026-06-09")],
        ):
            with self.subTest(legs=legs), self.assertRaises(ValueError):
                self.generator.search({"legs": legs})
        with self.assertRaises(ValueError):
            self.generator.search(dict(search_request(), unexpected=True))

    def test_calendar_input_validation(self):
        for overrides in (
            {"departure_date_range": {"start": "2026-06-12", "end": "2026-06-10"}},
            {"departure_date_range": {"start": "2026-01-01", "end": "2027-01-02"}},
            {"departure_date_range": {"start": "bad", "end": "2026-06-10"}},
            {"stay_days": -1},
            {"stay_days": 366},
            {"unexpected": True},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.generator.cheapest_dates(dict(CALENDAR, **overrides))

    def test_bag_limits_count_only_travelers_with_seats(self):
        request = dict(
            OUTBOUND, adults=1, children=1, infants_in_seat=1, infants_on_lap=2
        )
        result = self.generator.one_way(dict(request, carry_on_bags=3, checked_bags=3))
        self.assertTrue(result.itineraries)
        for item in result.itineraries:
            self.assertEqual(item.baggage_pricing.carry_on_bags, 3)
            self.assertEqual(item.baggage_pricing.checked_bags, 3)
            self.assertEqual(item.baggage_pricing.status, "estimated")
        for field in ("carry_on_bags", "checked_bags"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.generator.one_way(dict(request, **{field: 4}))

    def test_zero_null_and_omitted_bags_mean_no_preference(self):
        for field in ("carry_on_bags", "checked_bags"):
            for operation, request in (
                ("search", search_request()),
                ("one_way", OUTBOUND),
                ("round_trip", dict(OUTBOUND, return_date=RETURN_DATE)),
                ("cheapest_dates", CALENDAR),
            ):
                method = getattr(self.generator, operation)
                baseline = method(request)
                for preference in (None, 0):
                    with self.subTest(
                        field=field, operation=operation, preference=preference
                    ):
                        self.assertEqual(
                            method(dict(request, **{field: preference})),
                            baseline,
                            "OpenAPI specifies zero, null and omitted bags as no preference",
                        )


class MockIgnavCLITests(unittest.TestCase):
    def run_cli(self, operation, request=None, *extra):
        with tempfile.TemporaryDirectory() as directory:
            command = [
                sys.executable,
                "-m",
                "backend.presentation.cli.mock_ignav",
                operation,
                "--seed",
                "17",
                "--count",
                "8",
            ]
            if request is not None:
                path = Path(directory) / "request.json"
                path.write_text(json.dumps(request))
                command.extend(["--request", str(path)])
            command.extend(extra)
            return subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )

    def test_all_cli_operations_emit_json(self):
        cases = (
            ("health", None, api.HealthResponseModel),
            ("airports", {"q": "JFK", "limit": 1}, None),
            ("search", search_request(), api.FareSearchModel),
            ("one-way", OUTBOUND, api.FareSearchResponseModel),
            (
                "round-trip",
                dict(OUTBOUND, return_date=RETURN_DATE),
                api.FareSearchResponseModel,
            ),
            ("cheapest-dates", CALENDAR, api.CheapestDatesResponseModel),
            ("booking-links", OUTBOUND, api.BookingOptionsResponseModel),
        )
        for operation, request, model in cases:
            with self.subTest(operation=operation):
                process = self.run_cli(operation, request)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stderr, "")
                payload = json.loads(process.stdout)
                if model is None:
                    self.assertEqual(len(payload), 1)
                    self.assertEqual(
                        api.AirportModel.model_validate(payload[0]).code, "JFK"
                    )
                else:
                    model.model_validate(payload)

    def test_cli_rejects_invalid_requests_cleanly(self):
        for operation, request, extra in (
            ("one-way", {}, ()),
            ("one-way", [], ()),
            ("health", None, ("--count", "0")),
            ("booking-links", {"ignav_id": "unknown-id"}, ()),
            ("health", None, ("--request", "/nonexistent/mock-ignav-request.json")),
        ):
            with self.subTest(operation=operation, request=request, extra=extra):
                process = self.run_cli(operation, request, *extra)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, "")
                self.assertIn("mock-ignav:", process.stderr)
                self.assertNotIn("Traceback", process.stderr)

    def test_cli_rejects_malformed_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed.json"
            path.write_text("{not-json")
            process = self.run_cli("one-way", None, "--request", str(path))
        self.assertEqual(process.returncode, 2)
        self.assertIn("mock-ignav:", process.stderr)
        self.assertNotIn("Traceback", process.stderr)


if __name__ == "__main__":
    unittest.main()
