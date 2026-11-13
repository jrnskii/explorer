"""Emit the fixed EU-27 flight fixture as JSON."""

from backend.infrastructure.fixtures.eu_network import generate_network


def main() -> None:
    print(generate_network().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
