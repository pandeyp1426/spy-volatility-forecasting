"""Explicitly synthetic, offline end-to-end demonstration in a separate store."""
from pathlib import Path
import json
from uuid import uuid4

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

from spy_volatility.core.data import _request_settings, _versions, get_snapshot
from spy_volatility.workflows.pilot import sha, write_json


class SyntheticMarket:
    """Test market; every saved vintage is labelled synthetic, never Yahoo data."""
    def __init__(self, instant="2026-11-12T21:05:00Z"):
        self.instant = pd.Timestamp(instant)
        self.revision = 0.
        self.calls = 0
        self.schedule = mcal.get_calendar("NYSE").schedule("2026-09-01", "2028-01-31")
        i = np.arange(len(self.schedule))
        self.prices = pd.Series(500 * np.exp(np.cumsum(.0003 + .009*np.sin(i*.83))),
                                index=self.schedule.index, name="adjusted_close")

    def now(self):
        return self.instant.to_pydatetime()

    def acquire(self, settings, directory):
        self.calls += 1
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        p = self.prices.loc[(self.prices.index >= settings["start"]) & (self.prices.index < settings["end"])].copy()
        p.iloc[-1] *= 1 + self.revision
        raw = pd.DataFrame({"Adj Close": p, "Close": p * 1.002})
        raw.index.name = "Date"
        raw.to_csv(directory / "raw.csv")
        # Snapshot's fixed provider schema is retained for reuse of its audit;
        # the extra fields and journal mode explicitly negate provider origin.
        metadata = {"schema_version": 1, "source": "Yahoo Finance via yfinance",
                    "synthetic": True, "actual_source": "Deterministic artificial prices; NOT fetched from Yahoo",
                    "request_settings": _request_settings(settings), "calendar": "NYSE",
                    "retrieved_at_utc": self.instant.isoformat(), "raw_file": "raw.csv", "sha256": sha(directory / "raw.csv"),
                    "actual_date_range": {"start": p.index.min().isoformat(), "end": p.index.max().isoformat()},
                    "row_count": len(p), "columns": raw.columns.tolist(), "package_versions": _versions()}
        write_json(directory / "metadata.json", metadata)
        return get_snapshot(settings, directory, offline=True)


def demonstrate(config_path):
    from spy_volatility.workflows.operations import Operations
    config_path = Path(config_path).resolve()
    directory = config_path.parent.parent / "artifacts/automation_demos" / uuid4().hex
    market = SyntheticMarket()
    worker = Operations(config_path, clock=market.now, acquire=market.acquire,
                        store_path=directory, evidence_mode="synthetic_demo")
    forecast = worker.execute("forecast")[0]
    if forecast.get("kind") != "forecast":
        raise ValueError(f"Synthetic forecast failed: {forecast}")
    duplicate = worker.execute("forecast")[0]
    immature = worker.execute("outcomes")[0]
    if duplicate["status"] != "already_recorded" or immature["status"] != "not_mature":
        raise ValueError("Synthetic duplicate/maturity guard failed")
    market.instant = pd.Timestamp(forecast["context"]["target_close_utc"]) + pd.Timedelta(minutes=5)
    completed = worker.execute("outcomes")
    if not any(r.get("kind") == "comparison" for r in completed):
        raise ValueError(f"Synthetic outcome/comparison failed: {completed}")
    market.instant += pd.Timedelta(minutes=5)
    market.revision = .001
    revised = worker.execute("outcomes", origin=forecast["context"]["origin"], reason="Synthetic provider revision test")
    if not any(r.get("role") == "revised_sensitivity" for r in revised):
        raise ValueError("Synthetic revision preservation failed")
    verified = worker.execute("verify")[0]
    if verified["status"] != "passed":
        raise ValueError(f"Synthetic verification failed: {verified}")
    summary = {"evidence_mode": "synthetic_demo", "real_forecast_issued": False,
               "synthetic_clock": True, "directory": str(directory), "provider_calls": market.calls,
               "duplicate_guard": duplicate["status"], "premature_guard": immature["status"],
               "forecast": forecast["forecast"], "completed": [r for r in completed if r.get("kind") in ("outcome", "comparison")],
               "verification": verified}
    # This standalone summary is outside the journal's sealed attempt folders.
    write_json(directory / "demo_summary.json", summary)
    return {k: summary[k] for k in ("evidence_mode", "real_forecast_issued", "directory", "provider_calls", "duplicate_guard", "premature_guard", "verification")}
