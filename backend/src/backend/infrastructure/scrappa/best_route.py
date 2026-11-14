"""Price exactly one selected route; bounded calls, persistent cache, no retries."""

import os
from pathlib import Path
import threading
import time
import unicodedata

from backend.application.telemetry import traced
from backend.domain.pricing import ExactPricingUnavailable
from backend.infrastructure.scrappa.client import ScrappaClient, http_get
from backend.infrastructure.scrappa.exact_pricing import MODES, ScrappaRoundTripPricer

_CACHE_LOCK = threading.Lock()


def folded(value):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(c)
    )


class BestRoutePricer:
    def __init__(
        self,
        cities,
        *,
        database,
        api_key,
        client_factory=ScrappaClient,
        timeout=180
    ):
        self.cities, self.database, self.api_key = cities, Path(database), api_key
        self.client_factory, self.timeout = client_factory, timeout
        self._deadline = None
        self._network_calls = 0

    @traced
    def quote(self, option, settings):
        # This method is invoked only after local candidate ranking has completed.
        if any(
            len(offer.path) != 1 or offer.path[0].transport_type not in MODES
            for offer in option.offers
        ):
            raise ExactPricingUnavailable(
                "Scrappa/Omio cannot price the selected route's purchase or transport type."
            )
        if not _CACHE_LOCK.acquire(timeout=2):
            raise ExactPricingUnavailable(
                "Price verification is busy. Try again shortly."
            )
        if self._deadline is None:
            self._deadline = time.monotonic() + self.timeout
        deadline = self._deadline
        try:
            def transport(url, key, timeout):
                self._network_calls += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._network_calls > 25:
                    raise ExactPricingUnavailable(
                        "Price verification reached its request limit."
                    )
                return http_get(url, key, min(timeout, remaining))

            with self.client_factory(
                self.database, api_key=self.api_key, timeout=60, transport=transport
            ) as client:
                ids = {}
                selected = dict.fromkeys(
                    city
                    for offer in option.offers
                    for leg in offer.path
                    for city in (leg.origin, leg.destination)
                )
                for city in selected:
                    if time.monotonic() >= deadline:
                        raise ExactPricingUnavailable("Price verification timed out.")
                    record = self.cities[city]
                    payload = client.request(
                        "places",
                        {"query": record["name"], "locale": "en"},
                    ).payload
                    results = payload["data"].get("results")
                    if not isinstance(results, list):
                        raise ExactPricingUnavailable(
                            "Provider city lookup returned an invalid response."
                        )
                    matches = {
                        p["position_id"]
                        for p in results
                        if isinstance(p, dict)
                        and p.get("type") == "location"
                        and p.get("country_code") == record["country"]
                        and type(p.get("position_id")) is int
                        and p["position_id"] > 0
                        and any(
                            isinstance(p.get(field), str)
                            and folded(p[field]) == folded(record["name"])
                            for field in ("name", "city_name", "default_name")
                        )
                    }
                    if len(matches) != 1:
                        raise ExactPricingUnavailable(
                            "Provider could not uniquely identify a city on the selected route."
                        )
                    ids[city] = matches.pop()
                return ScrappaRoundTripPricer(
                    client,
                    ids,
                    cities=self.cities,
                    min_connection_seconds=1800,
                    # Reuse identical provider responses within the one-hour TTL.
                    refresh=False,
                ).quote(option, settings)
        except ExactPricingUnavailable:
            raise
        except Exception as exc:
            raise ExactPricingUnavailable(
                "The selected opportunity could not be priced by Scrappa/Omio."
            ) from exc
        finally:
            _CACHE_LOCK.release()


@traced
def configured_pricer(cities):
    return BestRoutePricer(
        cities,
        database=os.environ.get("SCRAPPA_CACHE_PATH", "backend/data/scrappa.duckdb"),
        api_key=os.environ.get("SCRAPPA_API_KEY"),
    )
