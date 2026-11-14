import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.infrastructure.pricing import download as d


class PricingDownloadTests(unittest.TestCase):
    def test_default_output_is_ignored_fixture_data(self):
        self.assertEqual(d.DEFAULT_OUTPUT, Path(__file__).resolve().parents[1] / "src/backend/infrastructure/fixtures/data/pricing")

    def test_schengen_membership(self):
        self.assertEqual(len(d.SCHENGEN), 29)
        self.assertTrue({'BG', 'RO', 'CH', 'NO'} <= set(d.SCHENGEN))
        self.assertFalse({'GB', 'IE', 'CY'} & set(d.SCHENGEN))

    def test_catalogue_is_offline_and_distinguishes_semantics(self):
        with patch.object(d, 'acquire') as acquire, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(d.main(['--list']), 0)
        acquire.assert_not_called()
        sources = json.loads(out.getvalue())['sources']
        self.assertEqual(sources['sncf']['kind'], 'published_tariff_bounds')
        self.assertEqual(sources['greenpeace']['kind'], 'report_only')

    def test_stream_failure_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.csv'
            path.write_text('old')
            with patch.object(d, 'urlopen', return_value=io.BytesIO(b'a,b\n1,2\n')):
                with self.assertRaises(ValueError):
                    d.fetch('https://example.org/data', path, 1, 2)
            self.assertEqual(path.read_text(), 'old')
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_checksum_and_format_validation(self):
        for suffix, body, expected in [('.dta', b'abc', 'wrong'), ('.json', b'<html>', None),
                                        ('.csv', b'<html>oops</html>', None), ('.pdf', b'no', None)]:
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as tmp:
                with patch.object(d, 'urlopen', return_value=io.BytesIO(body)):
                    with self.assertRaises(ValueError):
                        d.fetch('https://example.org/data', Path(tmp) / ('data' + suffix), 1, 100, expected)

    def test_download_and_cache_corruption_recovery(self):
        def acquire(name, directory, timeout, limit):
            path = directory / 'data.csv'
            path.write_text('price\n12.30\n')
            return [dict(file=path.name, sha256=d.digest(path), bytes=path.stat().st_size)]
        with tempfile.TemporaryDirectory() as tmp:
            argv = ['--source', 'sncf', '--output-dir', tmp]
            with patch.object(d, 'acquire', side_effect=acquire) as mock, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(d.main(argv), 0)
                self.assertEqual(d.main(argv), 0)
                self.assertEqual(mock.call_count, 1)
                (Path(tmp) / 'sncf/data.csv').write_text('corrupt')
                self.assertEqual(d.main(argv), 0)
                self.assertEqual(mock.call_count, 2)
                self.assertEqual(d.main(argv + ['--refresh']), 0)
                self.assertEqual(mock.call_count, 3)

    def test_partial_failure_continues_and_sanitizes_errors(self):
        def acquire(name, directory, timeout, limit):
            if name == 'flights':
                raise RuntimeError('secret-token')
            path = directory / 'data.json'
            path.write_text('[]')
            return [dict(file=path.name, sha256=d.digest(path))]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(d, 'acquire', side_effect=acquire), contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(d.main(['--source', 'flights', 'sncf', '--output-dir', tmp]), 1)
            manifest = (Path(tmp) / 'manifest.json').read_text()
            self.assertNotIn('secret-token', manifest + out.getvalue() + err.getvalue())
            self.assertEqual(json.loads(manifest)['sources']['sncf']['status'], 'downloaded')

    def test_invalid_limits(self):
        for value in ['0', '-1', 'nan', 'inf']:
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    d.main(['--timeout', value, '--list'])
                self.assertEqual(error.exception.code, 2)

    def test_mendeley_requires_expected_artifacts(self):
        def fetch(url, path, *args):
            path.write_text(json.dumps(dict(version=1, files=[])))
            return {}
        with tempfile.TemporaryDirectory() as tmp, patch.object(d, 'fetch', side_effect=fetch):
            with self.assertRaisesRegex(ValueError, 'missing'):
                d.acquire('flixbus', Path(tmp), 1, 100)
