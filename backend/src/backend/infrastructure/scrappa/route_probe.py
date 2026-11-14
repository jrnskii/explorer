"""Manual live-route probe; every response commits through the Scrappa client."""

import unicodedata
import sys

from backend.application.telemetry import traced
from backend.infrastructure.fixtures.eu_network import EU_CITIES
from backend.infrastructure.scrappa.client import ScrappaClient, ScrappaError, matches_one_way_search

# City names only: no synthetic fixture schedules, fares or airport IDs are used.
MAJOR_DESTINATIONS = tuple(
    (city.city, city.country) for city in EU_CITIES if city.city != "Vilnius"
) + (
    ("London", "GB"), ("Manchester", "GB"), ("Edinburgh", "GB"),
    ("Oslo", "NO"), ("Bergen", "NO"), ("Zurich", "CH"),
    ("Geneva", "CH"), ("Reykjavik", "IS"), ("Istanbul", "TR"),
)
MODES = {"train", "bus", "flight"}
# Resume this dated snapshot even after the normal six-hour cache TTL.
SNAPSHOT_MAX_AGE = 100 * 366 * 24 * 60 * 60


def _name(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(c)
    )


def _request(client: ScrappaClient, endpoint: str, params: dict, refresh: bool):
    if not refresh:
        try:
            return client.request(
                endpoint, params, cache_only=True, max_age_seconds=SNAPSHOT_MAX_AGE
            )
        except ScrappaError:
            pass  # Retry a previous failure once on this invocation; keep its history.
    return client.request(endpoint, params, refresh=True)


@traced
def _place(client: ScrappaClient, city: str, country: str, refresh: bool) -> int:
    data = _request(client, "places", {"query": city, "locale": "en"}, refresh).payload["data"]
    places = data.get("results")
    if not isinstance(places, list):
        raise ValueError("Places response has no results list")
    matches = {
        p["position_id"] for p in places
        if isinstance(p, dict)
        and p.get("type") == "location"
        and p.get("country_code") == country
        and any(isinstance(p.get(k), str) and _name(p[k]) == _name(city)
                for k in ("name", "city_name", "default_name"))
        and type(p.get("position_id")) is int and p["position_id"] > 0
    }
    if len(matches) != 1:
        raise ValueError(f"Cannot resolve exactly one Omio city for {city}, {country}")
    return matches.pop()


@traced
def fetch_routes(
    client: ScrappaClient, day: str, destinations=MAJOR_DESTINATIONS, *, refresh=False,
) -> dict:
    """Fetch every available page per destination, continuing after individual errors.

    Raw successes, HTTP errors, invalid JSON and transport failures are committed
    independently by ScrappaClient before this function inspects their contents.
    No automatic retries occur within an invocation.
    """
    report = {"origin": "Vilnius", "date": day, "destinations": []}
    origin_id = _place(client, "Vilnius", "LT", refresh)
    for city, country in dict.fromkeys(destinations):
        print(f"Vilnius -> {city}, {country}", file=sys.stderr)
        outcome = {"city": city, "country": country, "status": "failed",
                   "pages": [], "trips": 0}
        report["destinations"].append(outcome)
        try:
            destination_id = _place(client, city, country, refresh)
            if destination_id == origin_id:
                raise ValueError("Destination resolves to the origin")
            seen = set()
            for page in range(1, 51):
                response = _request(client, "search", {
                    "origin_id": origin_id, "destination_id": destination_id,
                    "date": day, "currency": "EUR", "adults": 1,
                    "travel_mode": "train,bus,flight", "limit": 100,
                    "page": page, "sort": "departure",
                }, refresh)
                outcome["pages"].append(response.response_id)
                data = response.payload["data"]
                if not matches_one_way_search(data, {
                    "origin_id": origin_id, "destination_id": destination_id,
                    "date": day, "currency": "EUR", "adults": 1, "children": 0, "infants": 0,
                }):
                    raise ValueError("Search response does not match the requested route/date/passengers/currency")
                results, pagination = data.get("results"), data.get("pagination")
                if (not isinstance(results, list) or not isinstance(pagination, dict)
                    or type(pagination.get("has_more")) is not bool
                    or type(pagination.get("page")) is not int
                    or type(pagination.get("total")) is not int
                    or pagination["total"] < 0
                    or pagination["page"] != page):
                    raise ValueError("Invalid search results/pagination; raw response retained")
                meta = data.get("search_meta")
                if (not isinstance(meta, dict) or not isinstance(meta.get("modes_done"), list)
                    or not all(isinstance(mode, str) for mode in meta["modes_done"])
                    or not MODES.issubset(meta["modes_done"])):
                    raise ValueError("Search did not complete all requested modes")
                ids = [r.get("trip_id") if isinstance(r, dict) else None for r in results]
                if (any(not isinstance(i, str) or not i for i in ids)
                    or len(set(ids)) != len(ids) or seen.intersection(ids)):
                    raise ValueError("Invalid or repeated trips; pagination may have changed")
                seen.update(ids)
                outcome["trips"] += len(results)
                if not pagination["has_more"]:
                    if len(seen) != pagination["total"]:
                        raise ValueError("Trip count differs from provider total; results are incomplete")
                    outcome["status"] = "complete" if seen else "empty"
                    break
                if not results:
                    raise ValueError("Empty page claims more results")
            else:
                raise ValueError("Provider page limit reached; results are incomplete")
        except (ScrappaError, ValueError) as exc:
            outcome["error"] = str(exc)
    return report
