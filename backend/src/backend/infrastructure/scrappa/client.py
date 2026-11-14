"""Scrappa Omio GET adapters and a persistent, append-only response cache.

No automatic retries: a retry can consume another credit. Estimates never use HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

import duckdb

DEFAULT_DATABASE = Path(__file__).resolve().parents[4] / "data" / "scrappa.duckdb"
MODES = {"train", "bus", "flight"}
CURRENCIES = {
    "EUR",
    "USD",
    "GBP",
    "CHF",
    "PLN",
    "CZK",
    "SEK",
    "NOK",
    "DKK",
    "HUF",
    "RON",
}
PATHS = {
    "places": "places",
    "search": "search",
    "summary": "search/summary",
    "trip": "trip",
    "providers": "providers",
    "route-page": "route-page",
}
FIELDS = {
    "places": {"query", "id", "departure_id", "locale"},
    "search": {
        "origin_id",
        "destination_id",
        "date",
        "return_date",
        "adults",
        "children",
        "infants",
        "travel_mode",
        "currency",
        "sort",
        "limit",
        "page",
    },
    "summary": {
        "origin_id",
        "destination_id",
        "date_start",
        "date_end",
        "adults",
        "children",
        "infants",
        "travel_mode",
        "currency",
        "calendar",
    },
    "trip": {"search_id", "trip_id"},
    "providers": {"search_id", "lang"},
    "route-page": {"origin", "destination", "mode"},
}
TTL = {
    "places": 604800,
    "search": 21600,
    "summary": 21600,
    "trip": 3600,
    "providers": 3600,
    "route-page": 86400,
}


class ScrappaError(RuntimeError):
    """Actionable provider/cache error without credentials or upstream body."""


@dataclass(frozen=True)
class CachedResponse:
    payload: dict
    source: str
    fetched_at: datetime
    response_id: str


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the API key to a redirect target.


def http_get(url: str, key: str, timeout: float) -> tuple[int, str]:
    request = Request(url, headers={"x-api-key": key, "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect).open(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        with exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError):
        raise ScrappaError(
            "Scrappa connection failed; check connectivity or try again explicitly."
        ) from None


def normalize(endpoint: str, params: dict) -> dict:
    if endpoint not in PATHS:
        raise ValueError(f"Unknown endpoint; choose from {', '.join(PATHS)}")
    if not isinstance(params, dict) or set(params) - FIELDS[endpoint]:
        raise ValueError(
            "Parameters must be an object containing only documented endpoint fields"
        )
    p = dict(params)
    for key, value in p.items():
        if value is None or not isinstance(value, (str, int, bool)):
            raise ValueError(f"Invalid value for {key}")
        if key in {
            "query",
            "search_id",
            "trip_id",
            "origin",
            "destination",
            "locale",
            "lang",
            "currency",
            "sort",
            "mode",
            "travel_mode",
        } and not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        if isinstance(value, str):
            p[key] = value.strip()
            if not p[key]:
                raise ValueError(f"{key} must not be empty")
    for key in {
        "origin_id",
        "destination_id",
        "id",
        "departure_id",
        "adults",
        "children",
        "infants",
        "limit",
        "page",
    } & p.keys():
        if type(p[key]) is not int:
            raise ValueError(f"{key} must be an integer")
        low, high = {
            "adults": (1, 9),
            "children": (0, 9),
            "infants": (0, 9),
            "limit": (1, 100),
            "page": (1, 50),
        }.get(key, (1, 2**63 - 1))
        if not low <= p[key] <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
    if endpoint in {"search", "summary"}:
        for key in (
            "origin_id",
            "destination_id",
            "date" if endpoint == "search" else "date_start",
        ):
            if key not in p:
                raise ValueError(f"{key} is required")
        p = {
            "adults": 1,
            "children": 0,
            "infants": 0,
            "currency": "EUR",
            "travel_mode": "bus,flight,train",
            **p,
        }
        if p["infants"] > p["adults"]:
            raise ValueError("infants must not exceed adults")
        if p["currency"] not in CURRENCIES:
            raise ValueError("Unsupported currency")
        modes = p["travel_mode"].split(",") if isinstance(p["travel_mode"], str) else []
        if not modes or not set(modes) <= MODES:
            raise ValueError("travel_mode must contain train, bus or flight")
        p["travel_mode"] = ",".join(sorted(set(modes)))
        dates = {}
        for key in ("date", "return_date", "date_start", "date_end"):
            if key in p:
                if not isinstance(p[key], str):
                    raise ValueError(f"{key} must be YYYY-MM-DD")
                dates[key] = date.fromisoformat(p[key])
                p[key] = dates[key].isoformat()
        if endpoint == "search":
            p = {"sort": "smart", "limit": 25, "page": 1, **p}
            if p["sort"] not in {"smart", "price", "duration", "departure", "arrival"}:
                raise ValueError("Unsupported sort")
            if dates.get("return_date", dates["date"]) < dates["date"]:
                raise ValueError("return_date precedes date")
        else:
            p = {"calendar": False, **p}
            if type(p["calendar"]) is not bool:
                raise ValueError("calendar must be boolean")
            p.setdefault(
                "date_end", (dates["date_start"] + timedelta(days=6)).isoformat()
            )
            if (
                not 0
                <= (date.fromisoformat(p["date_end"]) - dates["date_start"]).days
                <= 62
            ):
                raise ValueError("summary date range must be 0 to 62 days")
        # Past dates remain valid for cache reads; live requests enforce horizons below.
    elif endpoint == "places":
        p.setdefault("locale", "en")
        if "id" not in p and not (
            isinstance(p.get("query"), str) and 2 <= len(p["query"]) <= 100
        ):
            raise ValueError("places requires id or query of 2 to 100 characters")
        if p["locale"] not in {"en", "de", "fr", "es", "it", "nl", "pt", "pl"}:
            raise ValueError("Unsupported locale")
    elif endpoint == "trip":
        if not all(
            isinstance(p.get(k), str) and p[k] for k in ("search_id", "trip_id")
        ):
            raise ValueError("trip requires search_id and trip_id strings")
    elif endpoint == "providers":
        p.setdefault("lang", "en")
        if p["lang"] not in {"en", "de", "fr", "es", "it", "nl", "pt", "pl"}:
            raise ValueError("Unsupported lang")
    else:
        p.setdefault("mode", "trains")
        if not all(
            isinstance(p.get(k), str) and p[k] for k in ("origin", "destination")
        ):
            raise ValueError("route-page requires origin and destination slugs")
        if p["mode"] not in {"trains", "buses", "flights"}:
            raise ValueError("Unsupported route-page mode")
    return p


class ScrappaClient:
    def __init__(
        self,
        database: Path = DEFAULT_DATABASE,
        *,
        api_key: str | None = None,
        timeout: float = 60,
        transport: Callable = http_get,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        database = Path(database)
        database.parent.mkdir(parents=True, exist_ok=True)
        self.db = duckdb.connect(str(database))
        self.api_key, self.timeout, self.transport, self.clock = (
            api_key,
            timeout,
            transport,
            clock,
        )
        self.db.execute("""CREATE TABLE IF NOT EXISTS responses (
            response_id VARCHAR PRIMARY KEY, cache_key VARCHAR, endpoint VARCHAR,
            parameters VARCHAR, fetched_at TIMESTAMPTZ, status INTEGER,
            body VARCHAR, reusable BOOLEAN)""")
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS response_lookup ON responses(cache_key, fetched_at)"
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.db.close()

    def request(
        self,
        endpoint: str,
        params: dict,
        *,
        refresh: bool = False,
        cache_only: bool = False,
        max_age_seconds: int | None = None,
    ) -> CachedResponse:
        now = self.clock()
        if now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        if refresh and cache_only:
            raise ValueError("refresh and cache_only are mutually exclusive")
        age = TTL.get(endpoint, 0) if max_age_seconds is None else max_age_seconds
        if not math.isfinite(age) or age < 0:
            raise ValueError("max_age_seconds must be finite and nonnegative")
        p = normalize(endpoint, params)
        serialized = json.dumps(p, sort_keys=True, separators=(",", ":"))
        key = hashlib.sha256((endpoint + ":" + serialized).encode()).hexdigest()
        if not refresh:
            row = self.db.execute(
                """SELECT body, CAST(fetched_at AS VARCHAR), response_id, status, reusable FROM responses
                WHERE cache_key=? AND fetched_at > ? AND fetched_at <= ?
                ORDER BY fetched_at DESC, rowid DESC LIMIT 1""",
                [key, now - timedelta(seconds=age), now],
            ).fetchone()
            if row:
                if not row[4]:
                    raise ScrappaError(
                        f"Cached Scrappa failure (status {row[3]}); response {row[2]}. "
                        "No API request made; use refresh to retry explicitly."
                    )
                return CachedResponse(
                    json.loads(row[0]), "cache", datetime.fromisoformat(row[1]), row[2]
                )
        if cache_only:
            raise ScrappaError("No fresh cached response; no API request was made.")
        if not self.api_key or not self.api_key.strip():
            raise ScrappaError("Set SCRAPPA_API_KEY to fetch an uncached response.")
        for field in ("date", "return_date", "date_start", "date_end"):
            if field in p:
                days = (date.fromisoformat(p[field]) - now.date()).days
                if days < 0 or (endpoint == "search" and days > 364):
                    raise ValueError(f"{field} is outside the live request horizon")
        query = urlencode(
            {k: str(v).lower() if type(v) is bool else v for k, v in p.items()}
        )
        try:
            status, body = self.transport(
                "https://scrappa.co/api/omio/" + PATHS[endpoint] + "?" + query,
                self.api_key,
                self.timeout,
            )
        except Exception:
            # No HTTP body exists. Persist a safe diagnostic, never exception text
            # (which may contain a URL, credentials or other sensitive details).
            status = 0
            body = json.dumps(
                {
                    "success": False,
                    "error": {
                        "code": "TRANSPORT_FAILURE",
                        "message": "No HTTP response received",
                    },
                }
            )
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            payload = None
        valid = (
            200 <= status < 300
            and isinstance(payload, dict)
            and payload.get("success") is True
            and isinstance(payload.get("data"), dict)
        )
        response_id = str(uuid4())
        self.db.execute(
            "INSERT INTO responses VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [response_id, key, endpoint, serialized, now, status, body, valid],
        )
        if not valid:
            raise ScrappaError(
                f"Scrappa returned HTTP {status} or an invalid response; archived as {response_id}. No retry attempted."
            )
        return CachedResponse(payload, "api", now, response_id)

    def places(self, **params):
        return self.request("places", params)

    def search(self, **params):
        return self.request("search", params)

    def summary(self, **params):
        return self.request("summary", params)

    def trip(self, **params):
        return self.request("trip", params)

    def providers(self, **params):
        return self.request("providers", params)

    def route_page(self, **params):
        return self.request("route-page", params)

    def estimate(
        self,
        origin_id: int,
        destination_id: int,
        departure_date: str,
        mode: str,
        *,
        currency: str = "EUR",
        adults: int = 1,
        children: int = 0,
        infants: int = 0,
        max_age_days: int = 30,
        date_window_days: int = 28,
    ) -> dict:
        """Median of latest daily minima; exact-date observations take priority.

        Prices are whole journey/group totals, never apportioned to physical legs.
        All results are historical estimates, not bookable offers.
        """
        now = self.clock()
        if now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        target = date.fromisoformat(departure_date)
        p = normalize(
            "search",
            {
                "origin_id": origin_id,
                "destination_id": destination_id,
                "date": target.isoformat(),
                "travel_mode": mode,
                "currency": currency,
                "adults": adults,
                "children": children,
                "infants": infants,
            },
        )
        if mode not in MODES:
            raise ValueError("estimate requires exactly one transport mode")
        if type(max_age_days) is not int or not 1 <= max_age_days <= 365:
            raise ValueError("max_age_days must be 1 to 365")
        if type(date_window_days) is not int or not 0 <= date_window_days <= 365:
            raise ValueError("date_window_days must be 0 to 365")
        rows = self.db.execute(
            """SELECT parameters, body, CAST(fetched_at AS VARCHAR), response_id, endpoint
            FROM responses WHERE reusable AND endpoint IN ('search', 'summary')
            AND fetched_at >= ? AND fetched_at <= ?
            AND json_extract_string(parameters, '$.origin_id') = ?
            AND json_extract_string(parameters, '$.destination_id') = ?
            ORDER BY fetched_at DESC, rowid DESC""",
            [
                now - timedelta(days=max_age_days),
                now,
                str(origin_id),
                str(destination_id),
            ],
        ).fetchall()
        daily = {}
        for parameters, body, fetched, response_id, endpoint in rows:
            fetched = datetime.fromisoformat(fetched)
            request = json.loads(parameters)
            if any(
                request.get(k) != p[k]
                for k in (
                    "origin_id",
                    "destination_id",
                    "currency",
                    "adults",
                    "children",
                    "infants",
                )
            ):
                continue
            if request.get("return_date") or mode not in request["travel_mode"].split(
                ","
            ):
                continue
            data = json.loads(body)["data"]
            candidates = []
            if endpoint == "search" and data.get("trip_type") == "one_way":
                # Floor reflects the whole result set, unlike paginated result samples.
                floors = data.get("price_floor_per_mode")
                if isinstance(floors, dict):
                    candidates.append((request["date"], floors.get(mode), fetched))
            elif endpoint == "summary":
                days = data.get("days")
                for day in days if isinstance(days, list) else []:
                    if not isinstance(day, dict) or not isinstance(
                        day.get("modes"), dict
                    ):
                        continue
                    item = day["modes"].get(mode)
                    if not isinstance(item, dict):
                        continue
                    observed = fetched
                    if item.get("updated_at"):
                        try:
                            observed = datetime.fromisoformat(item["updated_at"])
                            if observed.utcoffset() is None:
                                continue
                            observed = min(observed, fetched)
                        except (ValueError, TypeError):
                            continue
                    candidates.append((day.get("date"), item.get("price"), observed))
            for travel_date, price, observed in candidates:
                if not isinstance(price, dict) or price.get("currency") != currency:
                    continue
                amount = price.get("amount_minor")
                if type(amount) is not int or amount < 0:
                    continue
                try:
                    day = date.fromisoformat(travel_date)
                except (ValueError, TypeError):
                    continue
                if (
                    abs((day - target).days) > date_window_days
                    or not now - timedelta(days=max_age_days) <= observed <= now
                ):
                    continue
                if day not in daily or observed > daily[day][1]:
                    daily[day] = (amount, observed, response_id)
        samples = {target: daily[target]} if target in daily else daily
        base = {
            "source": "historical_estimate",
            "live_search_eligible": False,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "departure_date": target.isoformat(),
            "mode": mode,
            "currency": currency,
            "passengers": {"adults": adults, "children": children, "infants": infants},
            "sample_days": len(samples),
            "method": "median_of_latest_daily_minima",
            "date_match": "exact" if target in daily else "nearby",
        }
        if not samples:
            return {
                **base,
                "amount": None,
                "reason": "No comparable recent cached prices",
            }
        amounts = [Decimal(v[0]) / 100 for v in samples.values()]
        return {
            **base,
            "amount": str(statistics.median(amounts)),
            "min_amount": str(min(amounts)),
            "max_amount": str(max(amounts)),
            "oldest_observed_at": min(v[1] for v in samples.values()).isoformat(),
            "newest_observed_at": max(v[1] for v in samples.values()).isoformat(),
            "response_ids": sorted({v[2] for v in samples.values()}),
        }
