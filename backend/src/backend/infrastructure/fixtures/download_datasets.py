"""Download external reference datasets; importing this module performs no I/O."""

import argparse
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

DATASETS = {
    "train-stations": "headsortails/train-stations-in-europe",
    "airlines": "rohitgrewal/airlines-flights-data",
    "cities": "WorkWithData/cities",
}
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "data"


def download_dataset(name: str, output_dir: Path) -> Path:
    """Download one dataset into its own folder, extracting Kaggle archives.

    Credentials are read by the provider libraries from their standard environment
    variables/configuration. Existing files follow the libraries' cache behavior.
    """
    if name not in DATASETS:
        raise ValueError(f"Unknown dataset: {name}")
    destination = output_dir.expanduser().resolve() / name
    destination.mkdir(parents=True, exist_ok=True)
    # Kaggle prints metadata to stdout even with quiet=True. Keep stdout JSON-only.
    with redirect_stdout(sys.stderr):
        if name == "cities":
            from huggingface_hub import snapshot_download

            snapshot_download(
                repo_id=DATASETS[name],
                repo_type="dataset",
                local_dir=str(destination),
            )
        else:
            # Kaggle attempts authentication on import, so load it only as needed.
            from kaggle.api.kaggle_api_extended import KaggleApi

            api = KaggleApi()
            api.authenticate()
            api.dataset_download_files(
                DATASETS[name], path=str(destination), unzip=True, quiet=True
            )
    return destination


def download_all_datasets(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Path]:
    """Download all three datasets, returning their local directories.

    Stops on the first failure; completed downloads remain on disk.
    """
    return {name: download_dataset(name, output_dir) for name in DATASETS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download external fixture datasets.")
    parser.add_argument(
        "--dataset",
        nargs="+",
        choices=DATASETS,
        default=list(DATASETS),
        help="Datasets to download (default: all three).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Destination root (default: data/ beside this script).",
    )
    args = parser.parse_args(argv)
    downloaded = {}
    for name in dict.fromkeys(args.dataset):
        print(f"Downloading {DATASETS[name]}…", file=sys.stderr)
        try:
            downloaded[name] = str(download_dataset(name, args.output_dir))
        except ModuleNotFoundError as error:
            print(
                f"Download failed for {DATASETS[name]}: missing Python module "
                f"{error.name!r}. Run `uv sync --project backend --locked` "
                "to install the downloader dependencies.",
                file=sys.stderr,
            )
            return 1
        except Exception as error:
            # Provider errors may contain credential-bearing URLs or headers.
            print(
                f"Download failed for {DATASETS[name]} ({type(error).__name__}). "
                "Check provider authentication, "
                "dataset access, network connectivity, and output-directory permissions. "
                "Completed downloads are retained; rerun to retry.",
                file=sys.stderr,
            )
            return 1
    print(json.dumps(downloaded, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
