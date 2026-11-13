"""Travel modes owned by the domain rather than a generated wire schema."""

from enum import StrEnum


class TransportType(StrEnum):
    BUSSES = "BUSSES"
    PLANES = "PLANES"
    TRAINS = "TRAINS"
    FERRIES = "FERRIES"
