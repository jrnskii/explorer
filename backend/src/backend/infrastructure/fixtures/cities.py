"""Small offline city-marker catalog, independent of synthetic service coverage.

Coordinates transcribed from cities/Cities.csv (Work With Data, CC BY 4.0;
see fixtures/data/cities/README.md). Cracow is displayed as Krakow. Application
fixture IDs are deliberately preserved; they are not OSM or production graph IDs.
"""

from types import MappingProxyType

from backend.domain.cities import City

CITY_LOCATIONS = MappingProxyType(
    {
        city.id: city
        for city in (
            City("lt-vilnius", "Vilnius", 54.6833333, 25.3166667),
            City("pl-warsaw", "Warsaw", 52.25, 21.0),
            City("pl-krakow", "Krakow", 50.083333, 19.916667),
            City("fr-paris", "Paris", 48.866667, 2.333333),
            City("gb-london", "London", 51.514125, -0.093689),
            City("nl-amsterdam", "Amsterdam", 52.35, 4.916667),
        )
    }
)
