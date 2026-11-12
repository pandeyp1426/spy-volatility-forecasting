"""Compatibility entry point; implementation lives in workflows.prospective."""
from .workflows.prospective import main

if __name__ == "__main__":
    raise SystemExit(main())
