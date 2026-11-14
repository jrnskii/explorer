"""Download latest European GTFS Schedule archives; importing performs no I/O."""

import argparse
import hashlib
import json
import logging
import math
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile

from backend.application.telemetry import event, traced
from backend.infrastructure.logging import cli_entrypoint

API_URL = "https://api.mobilitydatabase.org/v1"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "mobilitydatabase"
logger = logging.getLogger("backend.infrastructure.fixtures.download_mobilitydatabase")
# Broad Europe scope: includes transcontinental states, Cyprus, the Caucasus,
# Kosovo (XK), and European dependencies. Selection uses feed locations, not HQs.
EUROPE_COUNTRY_CODES = frozenset(
    "AD AL AM AT AX AZ BA BE BG BY CH CY CZ DE DK EE ES FI FO FR GB GE GG GI "
    "GR HR HU IE IM IS IT JE KZ LI LT LU LV MC MD ME MK MT NL NO PL PT RO "
    "RS RU SE SI SJ SK SM TR UA VA XK".split()
)


class CatalogClient:
    def __init__(
        self, access_token: str | None, refresh_token: str | None, timeout: float
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.timeout = timeout

    @traced
    def refresh(self) -> None:
        if not self.refresh_token:
            raise ValueError("A refresh token is required")
        request = Request(
            f"{API_URL}/tokens",
            data=json.dumps({"refresh_token": self.refresh_token}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=self.timeout) as response:
            token = json.load(response).get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Token response has no access_token")
        self.access_token = token

    @traced
    def get(self, path: str, **parameters: object) -> object:
        if not self.access_token:
            self.refresh()
        url = f"{API_URL}/{path}?{urlencode(parameters)}"
        for attempt in range(2):
            request = Request(
                url, headers={"Authorization": f"Bearer {self.access_token}"}
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as error:
                event(logger, "mobility.http_error", level=logging.WARNING,
                      status=error.code, attempt=attempt + 1)
                if error.code != 401 or attempt or not self.refresh_token:
                    raise
                error.close()
                event(logger, "mobility.refresh_after_unauthorized", level=logging.DEBUG)
                self.refresh()
        raise RuntimeError("Authentication failed")


@traced
def european_feeds(client: CatalogClient, page_size: int) -> list[dict]:
    """Traverse the complete catalogue, deduplicating by feed ID, not provider."""
    feeds = {}
    offset = 0
    previous_ids: set[str] = set()
    while True:
        page = client.get("gtfs_feeds", limit=page_size, offset=offset)
        if not isinstance(page, list) or any(
            not isinstance(feed, dict) for feed in page
        ):
            raise ValueError("Expected a feed array")
        if not page:
            break
        ids = set()
        for feed in page:
            feed_id = feed.get("id")
            if not isinstance(feed_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]+", feed_id
            ):
                raise ValueError("Invalid feed ID")
            ids.add(feed_id)
            locations = feed.get("locations") or []
            if not isinstance(locations, list) or any(
                not isinstance(x, dict) for x in locations
            ):
                raise ValueError("Invalid feed locations")
            if any(
                location.get("country_code") in EUROPE_COUNTRY_CODES
                for location in locations
            ):
                feeds[feed_id] = feed
        if ids <= previous_ids:
            raise ValueError("Catalogue pagination made no progress")
        previous_ids.update(ids)
        # Continue until an empty page, even if the server caps our requested limit.
        offset += len(page)
        event(logger, "mobility.catalog_page", offset=offset,
              page_size=len(page), selected_feeds=len(feeds))
    return [feeds[key] for key in sorted(feeds)]


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@traced
def download_archive(
    url: str, destination: Path, expected_hash: str | None, timeout: float
) -> str:
    """Stream into a temporary file; publish only a valid, verified ZIP."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Expected a public HTTPS archive URL")
    if expected_hash is not None and not re.fullmatch(
        r"[a-fA-F0-9]{64}", expected_hash
    ):
        raise ValueError("Invalid SHA-256")
    expected_hash = expected_hash.lower() if expected_hash else None
    if (
        destination.is_file()
        and expected_hash
        and file_hash(destination) == expected_hash
    ):
        event(logger, "mobility.archive_cached", level=logging.DEBUG)
        return "cached"
    temporary = destination.with_suffix(".zip.part")
    try:
        # Hosted data is public: never forward the catalogue bearer token here.
        with urlopen(Request(url), timeout=timeout) as response, temporary.open(
            "wb"
        ) as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        if expected_hash and file_hash(temporary) != expected_hash:
            raise ValueError("SHA-256 mismatch")
        with ZipFile(temporary) as archive:
            if not archive.namelist() or archive.testzip() is not None:
                raise ValueError("Invalid ZIP contents")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return "downloaded"


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@traced
def download_schedules(
    client: CatalogClient, output_dir: Path, page_size: int = 500
) -> dict:
    destination = output_dir.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    raw_directory = destination / "raw"
    raw_directory.mkdir(exist_ok=True)
    manifest = {
        "source": API_URL,
        "scope": "latest GTFS Schedule dataset per feed; all statuses",
        "country_codes": sorted(EUROPE_COUNTRY_CODES),
        "feeds": [],
    }
    feeds = european_feeds(client, page_size)
    write_json(destination / "catalog.json", feeds)
    write_json(destination / "manifest.json", manifest)
    for feed in feeds:
        feed_id = feed["id"]
        record = {"feed_id": feed_id, "provider": feed.get("provider")}
        manifest["feeds"].append(record)
        latest = feed.get("latest_dataset")
        print(f"Fetching {feed_id}…", file=sys.stderr)
        try:
            if latest is None:
                record["status"] = "unavailable"
            else:
                if not isinstance(latest, dict):
                    raise ValueError("Invalid latest_dataset")
                dataset = latest
                if not latest.get("hosted_url") and latest.get("id"):
                    dataset_id = latest["id"]
                    if not isinstance(dataset_id, str) or not re.fullmatch(
                        r"[A-Za-z0-9_-]+", dataset_id
                    ):
                        raise ValueError("Invalid dataset ID")
                    dataset = client.get(f"datasets/gtfs/{dataset_id}")
                    if not isinstance(dataset, dict):
                        raise ValueError("Invalid dataset response")
                record["dataset"] = dataset
                url = dataset.get("hosted_url")
                if not url:
                    record["status"] = "unavailable"
                else:
                    archive = raw_directory / f"{feed_id}.zip"
                    record["status"] = download_archive(
                        url, archive, dataset.get("hash"), client.timeout
                    )
                    record["path"] = archive.relative_to(destination).as_posix()
        except Exception as error:
            # Upstream exception messages can contain credentials or signed URLs.
            record.update(status="failed", error=type(error).__name__)
            event(logger, "mobility.download_failed", level=logging.WARNING,
                  error_type=type(error).__name__)
            print(
                f"Download failed for {feed_id} ({type(error).__name__}); rerun to retry.",
                file=sys.stderr,
            )
        write_json(destination / "manifest.json", manifest)
        event(logger, "mobility.feed_processed", status=record["status"])
    return manifest


@cli_entrypoint
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--page-size", type=int, default=500, help="Catalogue page size (1–2500)."
    )
    parser.add_argument(
        "--timeout", type=float, default=120, help="Network timeout in seconds."
    )
    args = parser.parse_args(argv)
    if not 1 <= args.page_size <= 2500:
        parser.error("--page-size must be between 1 and 2500")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    access_token = os.environ.get("MOBILITYDATABASE_ACCESS_TOKEN")
    refresh_token = os.environ.get("MOBILITYDATABASE_REFRESH_TOKEN")
    if not access_token and not refresh_token:
        print(
            "Set MOBILITYDATABASE_REFRESH_TOKEN or MOBILITYDATABASE_ACCESS_TOKEN.",
            file=sys.stderr,
        )
        return 1
    try:
        manifest = download_schedules(
            CatalogClient(access_token, refresh_token, args.timeout),
            args.output_dir,
            args.page_size,
        )
    except Exception as error:
        print(
            f"Catalogue download failed ({type(error).__name__}). Check authentication, "
            "network connectivity, and output-directory permissions; rerun to retry.",
            file=sys.stderr,
        )
        return 1
    counts = {
        status: sum(feed["status"] == status for feed in manifest["feeds"])
        for status in ("downloaded", "cached", "unavailable", "failed")
    }
    print(
        json.dumps(
            {"output_dir": str(args.output_dir.expanduser().resolve()), **counts}
        )
    )
    return 1 if counts["failed"] or counts["unavailable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
