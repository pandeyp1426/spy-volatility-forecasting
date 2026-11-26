"""Collect 2026 pilot forecasts and replay them for the loopback dashboard."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

import pandas as pd
import pandas_market_calendars as mcal

from spy_volatility.workflows import pilot
from spy_volatility.workflows.operations import Operations
from spy_volatility.workflows.public_forecasts import _release


def trigger_times(now):
    """First attempt five minutes after each remaining eligible 2026 NYSE close."""
    calendar = mcal.get_calendar("NYSE").schedule("2026-01-01", "2026-12-31")
    starts = calendar.market_close.iloc[:-5] + pd.Timedelta(minutes=5)
    return [value.isoformat() for value in starts if value > now]


def eligible_origin(now, *, latest=False):
    if now.tz_convert("America/New_York").year != 2026:
        return None
    schedule = pilot.pilot_schedule(now.to_pydatetime())
    close = schedule.market_close.iloc[20]
    if schedule.index[-1].year != 2026 or schedule.index[20].year != 2026:
        return None
    if not latest and now > close + pd.Timedelta(hours=2):
        return None
    return schedule.index[20].date().isoformat()


def collect(config_path, *, latest=False):
    ops = Operations(config_path)
    origin = eligible_origin(ops.now(), latest=latest)
    if not origin or origin < ops.config["collection"]["pilot_start"]:
        return {"status": "outside_pilot_window"}
    directory = ops.root / "artifacts/dashboard_pilot"
    destination = directory / (origin + ".json")
    if destination.is_file():
        return {"status": "already_displayed", "origin": origin}
    result, = ops.execute("forecast")
    if result.get("status") not in {"valid", "already_recorded"}:
        raise ValueError(f"Collector returned {result.get('status')} for {origin}: {result.get('error', result.get('reason'))}")
    if result["context"]["origin"] != origin or result["context"]["study"] != "pilot_2026":
        raise ValueError("Session changed during collection")
    database = ops.store_path / "journal.sqlite3"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        event, = db.execute("""SELECT event_hash FROM events
            WHERE json_extract(payload, '$.kind') = 'forecast'
            AND json_extract(payload, '$.attempt_id') = ?""", (result["attempt_id"],)).fetchall()
        row = _release(db, ops.root, ops.store_path, ops.config, ops.model, ops.identity,
                       {"origin": origin, "forecast_sha256": event[0]})
    directory.mkdir(parents=True, exist_ok=True)
    stage = directory / (uuid4().hex + ".tmp")
    try:
        stage.write_text(json.dumps(row, allow_nan=False) + "\n", encoding="utf-8")
        stage.replace(destination)
    finally:
        stage.unlink(missing_ok=True)
    return {"status": "verified", "origin": origin, "timing": row["timing"], "id": row["id"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["schedule", "tick", "latest"])
    parser.add_argument("--config", default="configs/operations.toml")
    args = parser.parse_args()
    if args.action == "schedule":
        print(json.dumps(trigger_times(datetime.now(timezone.utc))))
        return 0
    try:
        print(json.dumps(collect(Path(args.config), latest=args.action == "latest")))
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
