"""Acquire free pricing sources relevant to Schengen; preserve original semantics."""

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.request import Request, urlopen
import zipfile

SCHENGEN = tuple('AT BE BG HR CZ DK EE FI FR DE GR HU IS IT LV LI LT LU MT NL NO PL PT RO SK SI ES SE CH'.split())
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / 'fixtures' / 'data' / 'pricing'
HF = 'https://huggingface.co/datasets/DeusHorizon/flight-fare-history'
SNCF = 'https://ressources.data.sncf.com/explore/dataset/tarifs-tgv-inoui-ouigo/'
SOURCES = {
    'flights': dict(mode='air', kind='observed_route_month_aggregates', page=HF,
                    license='Custom HF terms; GitHub CC-BY claim conflicts; review before reuse',
                    scope='Global; requires endpoint resolution and Schengen filtering'),
    'sncf': dict(mode='rail', kind='published_tariff_bounds', page=SNCF,
                 license='ODbL', scope='French TGV/OUIGO; verify cross-border endpoints'),
    'renfe': dict(mode='rail', kind='historical_advertised_quotes',
                  page='https://www.kaggle.com/datasets/thegurusteam/spanish-high-speed-rail-system-ticket-pricing',
                  license='Consult downloaded Kaggle metadata and dataset page',
                  scope='Historical Spanish Renfe; not representative of all European rail'),
    'flixbus': dict(mode='bus', kind='historical_research_observations',
                    page='https://data.mendeley.com/datasets/j89kvrsdkn/1',
                    license='CC-BY-4.0', scope='European sample; inspect country fields before Schengen filtering'),
    'greenpeace': dict(mode='air,rail', kind='report_only',
                      page='https://es.greenpeace.org/es/wp-content/uploads/sites/3/2025/08/greenpeace-analysis-flight-vs-trains-2025.pdf',
                      license='Report copyright; no raw-data reuse rights inferred',
                      scope='142 European routes, 2025; raw dataset not verified public'),
    'checkmybus': dict(mode='bus', kind='report_only',
                      page='https://www.traspol.polimi.it/wp-content/uploads/2025/05/TRASPOL-Checkmybus-EU-Coach-market-report-2025.pdf',
                      license='Report copyright; underlying data requires author access',
                      scope='Europe 2019–2024; report only, not underlying millions of records'),
}
EXCLUDED = {
    'uk_fares': 'Great Britain is outside Schengen',
    'oag': 'Commercial data, not a free dataset',
    'european_airlines_routes': 'Estimated prices, not observed fare ground truth',
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, path: Path, timeout: float, max_bytes: int, expected=None) -> dict:
    """Bounded streaming download; failure never replaces an existing artifact."""
    request = Request(url, headers={'User-Agent': 'explorer-pricing-datasets/1.0'})
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            with urlopen(request, timeout=timeout) as response:
                size = 0
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError('Download exceeds byte limit')
                    output.write(chunk)
            output.close()
            sha = digest(temporary)
            if not size or (expected and sha != expected):
                raise ValueError('Empty download or checksum mismatch')
            if path.suffix == '.json':
                json.loads(temporary.read_text())
            if path.suffix == '.pdf' and not temporary.read_bytes()[:5] == b'%PDF-':
                raise ValueError('Expected PDF')
            if path.suffix == '.csv':
                with temporary.open() as check:
                    header = check.readline()
                if ',' not in header or '<html' in header.lower():
                    raise ValueError('Expected CSV')
            temporary.replace(path)
            return dict(file=path.name, url=url, sha256=sha, bytes=size)
        finally:
            temporary.unlink(missing_ok=True)


def acquire(name: str, directory: Path, timeout: float, max_bytes: int) -> list[dict]:
    def get(url, filename, expected=None):
        return fetch(url, directory / filename, timeout, max_bytes, expected)

    if name == 'flights':
        metadata = get('https://huggingface.co/api/datasets/DeusHorizon/flight-fare-history', 'metadata.json')
        revision = json.loads((directory / 'metadata.json').read_text())['sha']
        files = ['README.md', 'fares-by-month.csv', 'routes.csv', 'summary.json',
                 'research/booking-window.csv', 'research/europe-countries.csv']
        return [metadata] + [get(f'{HF}/resolve/{revision}/{f}', f.replace('/', '__')) for f in files]
    if name == 'sncf':
        root = 'https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/tarifs-tgv-inoui-ouigo'
        return [get(root, 'metadata.json'), get(root + '/exports/json', 'tariffs.json')]
    if name == 'flixbus':
        metadata = get('https://data.mendeley.com/public-api/datasets/j89kvrsdkn', 'metadata.json')
        data = json.loads((directory / 'metadata.json').read_text())
        if data['version'] != 1:
            raise ValueError('Mendeley version changed; review source before download')
        result = [metadata]
        for item in data['files']:
            if item['filename'] in ('data_flixbus.dta', 'regressions_flixbus.do'):
                details = item['content_details']
                result.append(get(details['download_url'], item['filename'], details['sha256_hash']))
        if len(result) != 3:
            raise ValueError('Expected FlixBus artifacts missing')
        return result
    if name == 'renfe':
        # Preserve the archive, rather than extracting untrusted paths.
        with redirect_stdout(sys.stderr):
            from kaggle.api.kaggle_api_extended import KaggleApi
            api = KaggleApi()
            api.authenticate()
            api.dataset_download_files('thegurusteam/spanish-high-speed-rail-system-ticket-pricing',
                                       path=str(directory), unzip=False, quiet=True, force=True)
        archives = list(directory.glob('*.zip'))
        if len(archives) != 1 or not zipfile.is_zipfile(archives[0]):
            raise ValueError('Expected one Kaggle ZIP')
        path = archives[0]
        return [dict(file=path.name, url=SOURCES[name]['page'], sha256=digest(path), bytes=path.stat().st_size)]
    return [get(SOURCES[name]['page'], 'report.pdf')]


def write_json(path: Path, data: dict):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', nargs='+', choices=SOURCES, default=list(SOURCES))
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--max-bytes', type=int, default=2 * 1024**3,
                        help='Per-file HTTP limit; Kaggle SDK downloads are not bounded by this option')
    parser.add_argument('--refresh', action='store_true', help='Fetch current upstream versions again')
    parser.add_argument('--list', action='store_true', help='Print catalogue without network requests')
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.max_bytes <= 0:
        parser.error('timeout and max-bytes must be positive and finite')
    manifest = dict(schengen_country_codes=SCHENGEN,
                    geography_reference='https://www.consilium.europa.eu/en/policies/schengen-area/',
                    geography='29 member countries; raw sources are NOT endpoint-filtered. Overseas territories require separate checks.',
                    excluded=EXCLUDED, sources={})
    if args.list:
        manifest['sources'] = SOURCES
        print(json.dumps(manifest, indent=2))
        return 0
    root = args.output_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    previous_path = root / 'manifest.json'
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    failures = 0
    for name in dict.fromkeys(args.source):
        old = previous.get('sources', {}).get(name, {})
        files = old.get('files', [])
        if (not args.refresh and old.get('status') == 'downloaded' and files
                and all((root / name / f['file']).is_file()
                        and digest(root / name / f['file']) == f['sha256'] for f in files)):
            manifest['sources'][name] = old
        else:
            print(f'Fetching {name}', file=sys.stderr)
            entry = dict(SOURCES[name], fetched_at=datetime.now(timezone.utc).isoformat())
            try:
                # Stage the whole source so failures preserve the previous source snapshot.
                with tempfile.TemporaryDirectory(dir=root) as staging:
                    paths = acquire(name, Path(staging), args.timeout, args.max_bytes)
                    target = root / name
                    target.mkdir(exist_ok=True)
                    for item in paths:
                        shutil.move(str(Path(staging) / item['file']), target / item['file'])
                entry.update(status='downloaded', files=paths)
            except Exception as error:
                failures += 1
                entry.update(status='failed', error_type=type(error).__name__,
                             action='Check network, source access and Kaggle credentials; rerun to retry')
                print(f'{name}: {entry["action"]} ({type(error).__name__})', file=sys.stderr)
            manifest['sources'][name] = entry
        write_json(previous_path, manifest)
    print(json.dumps(dict(output_dir=str(root), failed=failures,
                          sources={k: v['status'] for k, v in manifest['sources'].items()})))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
