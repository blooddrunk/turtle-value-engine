"""Allow ``python -m turtle_value_engine`` to invoke the CLI."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
