"""Build the reviewed static dashboard release offline. Run from the research root."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from contextlib import ExitStack
from uuid import uuid4
import tomllib

import pandas as pd

from spy_volatility.core.data import get_snapshot
from spy_volatility.core.research import build_predictors
from spy_volatility.workflows.public_forecasts import read_forecasts, read_coverage
from spy_volatility.workflows.public_history import load_history

PRICE_SHA = "2e65e0a45ec8e6bc81339f2fe3f07a3069c905f8e613e7eda723cb96121e16bf"
SNAPSHOT = "spy_2014-11-01_2026-01-01"
DATASETS = ("market", "market_preview", "history", "observations", "forecasts", "status")


def market_history(root: Path) -> dict:
    settings = {"ticker": "SPY", "start": "2014-11-01", "end": "2026-01-01", "calendar": "NYSE"}
    prices, metadata, _ = get_snapshot(settings, root / "data/raw" / SNAPSHOT, offline=True)
    if metadata["sha256"] != PRICE_SHA:
        raise ValueError("Historical market snapshot differs from the reviewed release")
    columns = ["log_return", "volatility_5", "volatility_10", "volatility_20"]
    frame = build_predictors(prices)[columns] * 100
    frame.insert(0, "price", prices)
    frame.insert(0, "date", frame.index.strftime("%Y-%m-%d"))
    rows = frame.astype(object).where(pd.notnull(frame), None).to_dict("records")
    return {"acquired_at": metadata["retrieved_at_utc"], "rows": rows}


def encode(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()


def export(root: Path, *, now=None) -> dict:
    """Publish only into dashboard/public/data. On bad inputs retain the previous release."""
    root = root.resolve()
    output = root / "dashboard/public/data"
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    market = market_history(root)
    history = load_history(root)
    observations = history.pop("observations")
    forecasts = read_forecasts(root)
    config = tomllib.loads((root / "configs/public_status.toml").read_text(encoding="utf-8"))
    status = {key: config[key] for key in ("reviewed_on", "collector", "formal", "milestones")}
    status["collection"] = read_coverage(root)
    datasets = {}

    def add(key, payload, source, units, start, end):
        datasets[key] = {"schema_version": 1, "dataset": key, "generated_at": stamp,
                         "source": source, "units": units, "coverage": {"start": start, "end": end},
                         "status": "empty" if payload.get("rows") == [] else "available", "data": payload}

    for key, rows in [("market", market["rows"]), ("market_preview", market["rows"][-252:])]:
        add(key, {"rows": rows, "acquired_at": market["acquired_at"]}, SNAPSHOT + " sha256:" + PRICE_SHA,
            "USD adjusted close; daily log return and sample volatility in percent",
            rows[0]["date"], rows[-1]["date"])
    coverage = history["coverage"]
    add("history", history, ", ".join(s["run_id"] for s in history["sources"]),
        "daily-volatility percentage points; relative RMSE reduction in percent", coverage["start"], coverage["end"])
    add("observations", {"rows": observations}, history["sources"][0]["run_id"],
        "volatility in percent; errors in percentage points", coverage["start"], coverage["end"])
    origins = [row["origin"] for row in forecasts]
    add("forecasts", {"rows": forecasts}, "Forecast release policy in configs/public_forecasts.toml",
        "volatility in percent; predictors decimal; errors in percentage points",
        min(origins, default=None), max(origins, default=None))
    add("status", status, "docs/results/automation_progress.md and configs/public_status.toml",
        "research milestones", config["reviewed_on"], config["reviewed_on"])
    output.mkdir(parents=True, exist_ok=True)
    allowed = {f"{key}.json" for key in (*DATASETS, "manifest")}
    if any(path.name not in allowed or not path.is_file() or path.is_symlink() for path in output.iterdir()):
        raise ValueError("Unexpected files in public data directory; review them before publishing")
    entries = {}
    # Stage and validate every projection before replacing public files. Readers
    # pin the manifest and check each digest, including during a concurrent refresh.
    # Use normal inherited workspace permissions for these public files.
    # TemporaryDirectory's owner-only Windows ACL travels with renamed files.
    with ExitStack() as cleanup:
        stage = output.parent.parent / ('.release-' + uuid4().hex)
        stage.mkdir()
        cleanup.callback(stage.rmdir)
        for filename in allowed:
            cleanup.callback((stage / filename).unlink, missing_ok=True)
        for key, payload in datasets.items():
            content = encode(payload)
            name = f"{key}.json"
            (stage / name).write_bytes(content)
            entries[key] = {"file": name, "sha256": hashlib.sha256(content).hexdigest(),
                            "status": payload["status"]}
        manifest = {"schema_version": 1, "generated_at": stamp, "datasets": entries}
        (stage / "manifest.json").write_bytes(encode(manifest))
        for key in (*DATASETS, "manifest"):
            name = f"{key}.json"
            (stage / name).replace(output / name)
    return manifest


if __name__ == "__main__":
    print(json.dumps(export(Path.cwd()), indent=2))
