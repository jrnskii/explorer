"""Emit the fixed EU-27 flight fixture as JSON."""

from backend.infrastructure.logging import cli_entrypoint
from backend.infrastructure.fixtures.eu_network import generate_network


@cli_entrypoint
def main() -> None:
    print(generate_network().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
