"""Identify the package code actually executing an experiment."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def source_hashes() -> dict[str, str]:
    """Hash this package, independently of the config and working directory.

    Stable package-relative names allow runs on different computers to compare
    code fingerprints without depending on their local installation paths.
    """
    return {
        f"spy_volatility/{path.relative_to(PACKAGE_ROOT).as_posix()}": hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
    }


def copy_source(destination: Path, expected_hashes: dict[str, str]) -> None:
    """Snapshot the entire package hierarchy and verify every copied module."""
    destination = Path(destination)
    if source_hashes() != expected_hashes:
        raise ValueError("Execution source changed before copying")
    for name, digest in expected_hashes.items():
        relative = Path(name).relative_to("spy_volatility")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PACKAGE_ROOT / relative, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Execution source changed while copying {name}")
