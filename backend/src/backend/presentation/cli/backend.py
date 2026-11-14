"""Default package command."""

from backend.infrastructure.logging import cli_entrypoint


@cli_entrypoint
def main() -> None:
    print("Hello from backend!")


if __name__ == "__main__":
    main()
