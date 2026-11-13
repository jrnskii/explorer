"""Fare graph orchestration tested with domain values and a plain recording port."""

import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass

from backend.application.fare_graph import populate_fare_graph
from backend.application.ports import FareGraphWriter
from backend.domain.fares import FareOffer, FarePrice, FareSearch, FlightSegment

OBSERVED_AT = "2026-01-01T00:00:00Z"


def segment(origin="WAW", destination="LHR", **changes):
    values = dict(
        marketing_carrier_code="XX",
        flight_number="101",
        operating_carrier_name="Synthetic Test Carrier",
        departure_airport=origin,
        departure_time_local="2026-12-10T10:00:00+01:00",
        departure_timezone="Europe/Warsaw",
        departure_time_utc="2026-12-10T09:00:00Z",
        arrival_airport=destination,
        arrival_time_local="2026-12-10T11:00:00+00:00",
        arrival_timezone="Europe/London",
        arrival_time_utc="2026-12-10T11:00:00Z",
        duration_minutes=120,
        aircraft="Synthetic aircraft",
    )
    values.update(changes)
    return FlightSegment(**values)


def offer(legs, *, offer_id="synthetic-offer", price=None, cabin_class="ECONOMY"):
    return FareOffer(
        legs=legs,
        price=price if price is not None else FarePrice(149.95, "EUR", "verified"),
        offer_id=offer_id,
        cabin_class=cabin_class,
    )


def search(offers=(), requested_routes=()):
    return FareSearch(
        requested_routes=requested_routes,
        offers=offers,
        observed_at=OBSERVED_AT,
    )


class RecordingWriter:
    def __init__(self):
        self.airports = []
        self.segments = []
        self.calls = []

    def add_airport(self, code):
        self.airports.append(code)
        self.calls.append(("airport", code))

    def add_segment(self, segment, offer, *, itinerary_index, leg_index, segment_index):
        record = (itinerary_index, leg_index, segment_index, segment, offer)
        self.segments.append(record)
        self.calls.append(("segment", record))


class FareGraphApplicationTests(unittest.TestCase):
    def test_completely_empty_search_performs_no_writes(self):
        writer = RecordingWriter()
        populate_fare_graph(search(), writer)
        self.assertEqual(writer.calls, [])

    def test_no_offers_still_writes_every_requested_airport(self):
        writer = RecordingWriter()
        populate_fare_graph(
            search(requested_routes=(("WAW", "LHR"), ("LHR", "CDG"))), writer
        )
        self.assertEqual(set(writer.airports), {"WAW", "LHR", "CDG"})
        self.assertEqual(writer.segments, [])
        self.assertLessEqual(len(writer.calls), 4)

    def test_parallel_identical_segments_are_indexed_not_deduplicated(self):
        flight = segment()
        for offer_id in (None, "repeated-id"):
            with self.subTest(offer_id=offer_id):
                first = offer(((flight, flight),), offer_id=offer_id)
                second = offer(((flight,),), offer_id=offer_id)
                writer = RecordingWriter()
                populate_fare_graph(search((first, second)), writer)
                self.assertEqual(
                    writer.segments,
                    [
                        (0, 0, 0, flight, first),
                        (0, 0, 1, flight, first),
                        (1, 0, 0, flight, second),
                    ],
                )
                for record in writer.segments:
                    self.assertIs(record[3], flight)
                    self.assertIs(record[4], (first, second)[record[0]])

    def test_legs_and_connections_preserve_input_order_and_restart_indices(self):
        outbound = (segment("WAW", "FRA"), segment("FRA", "LHR"))
        onward = (segment("LHR", "CDG"),)
        inbound = (segment("CDG", "WAW"),)
        itinerary = offer((outbound, onward, inbound))
        writer = RecordingWriter()
        populate_fare_graph(search((itinerary,)), writer)
        self.assertEqual(
            writer.segments,
            [
                (0, 0, 0, outbound[0], itinerary),
                (0, 0, 1, outbound[1], itinerary),
                (0, 1, 0, onward[0], itinerary),
                (0, 2, 0, inbound[0], itinerary),
            ],
        )

    def test_empty_offers_and_legs_do_not_renumber_later_occurrences(self):
        flight = segment()
        empty_offer = offer(())
        itinerary = offer(((), (flight,), ()))
        writer = RecordingWriter()
        populate_fare_graph(search((empty_offer, itinerary)), writer)
        self.assertEqual(writer.segments, [(1, 1, 0, flight, itinerary)])

    def test_bundled_price_is_forwarded_unchanged_on_every_segment(self):
        for amount, currency, status in (
            (149.95, "EUR", "verified"),
            (0.0, "USD", "unverified"),
        ):
            with self.subTest(amount=amount, currency=currency, status=status):
                price = FarePrice(amount=amount, currency=currency, status=status)
                itinerary = offer(
                    (
                        (segment("WAW", "FRA"), segment("FRA", "LHR")),
                        (segment("LHR", "WAW"),),
                    ),
                    price=price,
                    offer_id=None,
                    cabin_class=None,
                )
                writer = RecordingWriter()
                populate_fare_graph(search((itinerary,)), writer)
                self.assertEqual(len(writer.segments), 3)
                for *_, written_offer in writer.segments:
                    self.assertIs(written_offer, itinerary)
                    self.assertIs(written_offer.price, price)
                    self.assertEqual(written_offer.price.amount, amount)
                    self.assertEqual(written_offer.price.currency, currency)
                    self.assertEqual(written_offer.price.status, status)
                    self.assertIsNone(written_offer.offer_id)
                    self.assertIsNone(written_offer.cabin_class)

    def test_nullable_segment_fields_and_zero_duration_are_not_filled_in(self):
        flight = segment(
            marketing_carrier_code=None,
            flight_number=None,
            operating_carrier_name=None,
            departure_timezone=None,
            departure_time_utc=None,
            arrival_timezone=None,
            arrival_time_utc=None,
            duration_minutes=0,
            aircraft=None,
        )
        itinerary = offer(((flight,),))
        writer = RecordingWriter()
        populate_fare_graph(search((itinerary,)), writer)
        self.assertIs(writer.segments[0][3], flight)
        self.assertEqual(writer.segments[0][3].duration_minutes, 0)
        self.assertIsNone(writer.segments[0][3].departure_time_utc)
        self.assertIsNone(writer.segments[0][3].marketing_carrier_code)

    def test_writer_airport_failure_propagates_without_writing_segments(self):
        failure = RuntimeError("airport writer unavailable")

        class FailingWriter(RecordingWriter):
            def add_airport(self, code):
                super().add_airport(code)
                raise failure

        writer = FailingWriter()
        with self.assertRaises(RuntimeError) as caught:
            populate_fare_graph(
                search((offer(((segment(),),)),), (("WAW", "LHR"),)), writer
            )
        self.assertIs(caught.exception, failure)
        self.assertEqual(writer.airports, ["WAW"])
        self.assertEqual(writer.segments, [])

    def test_writer_segment_failure_propagates_and_stops_traversal(self):
        failure = RuntimeError("segment writer unavailable")

        class FailingWriter(RecordingWriter):
            def add_segment(self, segment, offer, **indices):
                super().add_segment(segment, offer, **indices)
                if len(self.segments) == 2:
                    raise failure

        itinerary = offer(((segment(), segment(), segment()), (segment(),)))
        writer = FailingWriter()
        with self.assertRaises(RuntimeError) as caught:
            populate_fare_graph(search((itinerary,)), writer)
        self.assertIs(caught.exception, failure)
        self.assertEqual(
            [record[:3] for record in writer.segments], [(0, 0, 0), (0, 0, 1)]
        )

    def test_port_calls_scale_with_segment_occurrences_not_offer_combinations(self):
        flight = segment()
        for count in (1, 8, 64):
            with self.subTest(offers=count):
                offers = tuple(
                    offer(((flight,) * 3, (flight,) * 2)) for _ in range(count)
                )
                writer: FareGraphWriter = RecordingWriter()
                populate_fare_graph(search(offers, (("WAW", "LHR"),)), writer)
                segment_count = 5 * count
                self.assertEqual(len(writer.segments), segment_count)
                self.assertEqual(
                    len({record[:3] for record in writer.segments}), segment_count
                )
                self.assertLessEqual(len(writer.airports), 2 + 2 * segment_count)
                self.assertLessEqual(len(writer.calls), 2 + 3 * segment_count)


class FareDomainValueTests(unittest.TestCase):
    def test_domain_values_are_frozen_dataclasses_with_tuple_collections(self):
        flight = segment()
        itinerary = offer(((flight,),))
        result = search((itinerary,), (("WAW", "LHR"),))
        for value in (flight, itinerary.price, itinerary, result):
            with self.subTest(type=type(value).__name__):
                self.assertTrue(is_dataclass(value))
                name = fields(value)[0].name
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, name, getattr(value, name))
        self.assertIsInstance(result.requested_routes, tuple)
        self.assertIsInstance(result.requested_routes[0], tuple)
        self.assertIsInstance(result.offers, tuple)
        self.assertIsInstance(itinerary.legs, tuple)
        self.assertIsInstance(itinerary.legs[0], tuple)
        self.assertEqual(result.observed_at, OBSERVED_AT)


if __name__ == "__main__":
    unittest.main()
