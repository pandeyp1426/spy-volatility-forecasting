"""Run with python -m spy_volatility --config configs/phase1.toml."""

import argparse
import json
import sys

from .pipeline import run_phase1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local SPY historical-volatility baseline")
    parser.add_argument("--config", default="configs/phase1.toml", help="Path to Phase 1 TOML configuration")
    arguments = parser.parse_args()
    try:
        result = run_phase1(arguments.config)
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
