"""Run with python -m spy_volatility --config configs/phase1.toml."""

import argparse
import json
import sys

from spy_volatility.application import ExperimentRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a configured SPY validation experiment; test remains reserved")
    parser.add_argument("--config", default="configs/phase1.toml", help="Path to an experiment or prospective protocol TOML configuration")
    parser.add_argument("--offline", action="store_true", help="Require the saved snapshot; never download data")
    arguments = parser.parse_args()
    try:
        result = ExperimentRunner(arguments.config, offline=arguments.offline).run()
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
