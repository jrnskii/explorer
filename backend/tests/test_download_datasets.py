"""Offline download and CLI contracts; provider clients are mocked at the boundary."""

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import Mock, patch

from backend.infrastructure.fixtures import download_datasets as downloads


class DownloadDatasetTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.api = Mock()
        self.kaggle_module = ModuleType("kaggle.api.kaggle_api_extended")
        self.kaggle_module.KaggleApi = Mock(return_value=self.api)
        self.hub_module = ModuleType("huggingface_hub")
        self.hub_module.snapshot_download = Mock()
        self.modules = {
            "kaggle": ModuleType("kaggle"),
            "kaggle.api": ModuleType("kaggle.api"),
            "kaggle.api.kaggle_api_extended": self.kaggle_module,
            "huggingface_hub": self.hub_module,
        }
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def run_main(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = downloads.main(["--output-dir", str(self.root), *arguments])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_all_datasets_use_requested_providers_and_separate_directories(self):
        self.api.dataset_download_files.side_effect = lambda *a, **kw: print(
            "Kaggle metadata"
        )
        status, stdout, stderr = self.run_main()
        self.assertEqual(status, 0, stderr)
        result = json.loads(stdout)
        self.assertEqual(set(result), {"train-stations", "airlines", "cities"})
        for name, repo in (
            ("train-stations", "headsortails/train-stations-in-europe"),
            ("airlines", "rohitgrewal/airlines-flights-data"),
        ):
            destination = self.root / name
            self.assertTrue(destination.is_dir())
            self.assertEqual(result[name], str(destination))
            self.api.dataset_download_files.assert_any_call(
                repo, path=str(destination), unzip=True, quiet=True
            )
        self.assertEqual(self.api.authenticate.call_count, 2)
        self.hub_module.snapshot_download.assert_called_once_with(
            repo_id="WorkWithData/cities",
            repo_type="dataset",
            local_dir=str(self.root / "cities"),
        )
        self.assertTrue((self.root / "cities").is_dir())
        self.assertEqual(result["cities"], str(self.root / "cities"))
        self.assertIn("Kaggle metadata", stderr)
        self.assertNotIn("Kaggle metadata", stdout)

    def test_cities_only_does_not_authenticate_kaggle_and_can_be_rerun(self):
        for _ in range(2):
            status, stdout, stderr = self.run_main("--dataset", "cities", "cities")
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout), {"cities": str(self.root / "cities")})
        self.kaggle_module.KaggleApi.assert_not_called()
        self.assertEqual(self.hub_module.snapshot_download.call_count, 2)
        self.assertFalse((self.root / "airlines").exists())

    def test_provider_and_filesystem_failures_return_clean_errors_and_allow_retry(self):
        for operation in (
            self.api.authenticate,
            self.api.dataset_download_files,
            self.hub_module.snapshot_download,
        ):
            with self.subTest(operation=operation):
                operation.side_effect = RuntimeError("secret-token")
                name = (
                    "cities"
                    if operation is self.hub_module.snapshot_download
                    else "airlines"
                )
                status, stdout, stderr = self.run_main("--dataset", name)
                self.assertEqual(status, 1)
                self.assertEqual(stdout, "")
                self.assertIn(downloads.DATASETS[name], stderr)
                self.assertIn("authentication", stderr)
                self.assertNotIn("secret-token", stderr)
                self.assertNotIn("Traceback", stderr)
                operation.side_effect = None
                self.assertEqual(self.run_main("--dataset", name)[0], 0)
        (self.root / "train-stations").write_text("not a directory")
        self.assertEqual(self.run_main("--dataset", "train-stations")[0], 1)

    def test_download_all_method_downloads_each_dataset(self):
        result = downloads.download_all_datasets(self.root)
        self.assertEqual(
            result, {name: self.root / name for name in downloads.DATASETS}
        )
        self.assertTrue(all(path.is_dir() for path in result.values()))
        self.assertEqual(self.api.dataset_download_files.call_count, 2)
        self.hub_module.snapshot_download.assert_called_once()

    def test_download_all_method_stops_on_failure(self):
        self.api.dataset_download_files.side_effect = RuntimeError("upstream failure")
        with self.assertRaisesRegex(RuntimeError, "upstream failure"):
            downloads.download_all_datasets(self.root)
        self.assertEqual(self.api.dataset_download_files.call_count, 1)
        self.hub_module.snapshot_download.assert_not_called()

    def test_missing_dependency_is_reported_with_install_command(self):
        self.kaggle_module.KaggleApi.side_effect = ModuleNotFoundError(
            "sensitive provider details", name="six"
        )
        status, stdout, stderr = self.run_main("--dataset", "train-stations")
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("missing Python module 'six'", stderr)
        self.assertIn("uv sync --project backend --locked", stderr)
        self.assertNotIn("sensitive provider details", stderr)

    def test_real_provider_imports_have_all_required_dependencies(self):
        # A subprocess avoids the mocked clients and catches undeclared imports
        # such as Kaggle 2.2.5's dependency on six. No downloads are performed.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "\n".join(
                    [
                        "import contextlib, io",
                        "capture = io.StringIO()",
                        "with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):",
                        "    from kaggle.api.kaggle_api_extended import KaggleApi",
                        "    from huggingface_hub import snapshot_download",
                        "print('provider imports OK')",
                    ]
                ),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "provider imports OK")

    def test_unknown_dataset_is_rejected_before_creating_files(self):
        with self.assertRaisesRegex(ValueError, "Unknown dataset"):
            downloads.download_dataset("unknown", self.root / "unused")
        self.assertFalse((self.root / "unused").exists())

    def test_module_help_and_invalid_options_require_no_credentials(self):
        for arguments, expected_status in (
            (["--help"], 0),
            (["--dataset", "unknown"], 2),
            (["--dataset"], 2),
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, "-m", downloads.__name__, *arguments],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, expected_status, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                if expected_status:
                    self.assertEqual(result.stdout, "")
                    self.assertIn("error:", result.stderr)
                else:
                    self.assertIn("--output-dir", result.stdout)


if __name__ == "__main__":
    unittest.main()
