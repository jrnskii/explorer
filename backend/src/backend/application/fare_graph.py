"""Project fare searches onto static graphs without collapsing offer occurrences."""

from backend.application.ports import FareGraphWriter
from backend.domain.fares import FareSearch


def populate_fare_graph(search: FareSearch, writer: FareGraphWriter) -> None:
    """Keep empty-search airports and parallel flights, retaining bundled fares.

    This is a static projection, not a time-feasible itinerary search. An offer's
    price must not be allocated or summed across its individual segments.
    """
    for origin, destination in search.requested_routes:
        writer.add_airport(origin)
        writer.add_airport(destination)
    for itinerary_index, offer in enumerate(search.offers):
        for leg_index, leg in enumerate(offer.legs):
            for segment_index, segment in enumerate(leg):
                writer.add_airport(segment.departure_airport)
                writer.add_airport(segment.arrival_airport)
                writer.add_segment(
                    segment,
                    offer,
                    itinerary_index=itinerary_index,
                    leg_index=leg_index,
                    segment_index=segment_index,
                )
