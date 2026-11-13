"""City markers for mapping; coordinates never imply a service or actual track."""

from dataclasses import dataclass
from math import isfinite

from backend.domain.planning import identifier


@dataclass(frozen=True)
class City:
    id: str
    name: str
    latitude: float
    longitude: float

    def __post_init__(self):
        identifier(self.id)
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("city name must be non-empty")
        for name, value, bound in (
            ("latitude", self.latitude, 90),
            ("longitude", self.longitude, 180),
        ):
            if (
                type(value) not in (int, float)
                or not isfinite(value)
                or not -bound <= value <= bound
            ):
                raise ValueError(f"{name} must be finite and in [-{bound}, {bound}]")
