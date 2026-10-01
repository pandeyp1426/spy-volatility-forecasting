"""Identify the package code actually executing an experiment."""

from __future__ import annotations

import hashlib
from pathlib import Path


def source_hashes() -> dict[str, str]:
    """Hash this package, independently of the config and working directory.

    Stable package-relative names allow runs on different computers to compare
    code fingerprints without depending on their local installation paths.
    """
    package_dir = Path(__file__).resolve().parent
    return {
        f"spy_volatility/{path.name}": hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(package_dir.glob("*.py"))
    }
