"""Project approved forecasts into public rows, entirely offline.

Do not instantiate Operations or ForecastStore: their normal entry points
initialize the private journal. Only read records selected by an approved
event hash, matching date and kind. The optional automatic policy selects only
original live 2026 pilot forecast IDs. The clock never releases a formal outcome.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tomllib

import pandas as pd

from spy_volatility.core.data import get_snapshot
from spy_volatility.core.models import FEATURE_COLUMNS
from spy_volatility.core.outcomes import forecast_errors, realized_volatility, study_for
from spy_volatility.infrastructure.forecast_store import canonical
from spy_volatility.workflows import pilot


METHODS = {"ridge": "ridge", "hv5": "baseline_5", "hv20": "baseline"}


def _event(db, digest, origin, kinds, status="valid"):
    """Check the signed-off local event bytes without scanning other payloads."""
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("A release approval requires a full SHA-256 event hash")
    placeholders = ",".join("?" for _ in kinds)
    query = f"""
        SELECT sequence, previous_hash, payload FROM events
        WHERE event_hash = ?
          AND json_extract(payload, '$.kind') IN ({placeholders})
          AND json_extract(payload, '$.context.origin') = ?
          AND json_extract(payload, '$.context.study') = ?
          AND json_extract(payload, '$.status') = ?
          AND json_extract(payload, '$.evidence_mode') = 'live'
    """
    study = "formal_2027" if origin.startswith("2027-") else "pilot_2026"
    row = db.execute(query, (digest, *kinds, origin, study, status)).fetchone()
    if row is None:
        raise ValueError("Approved event is missing, invalid, or belongs to another origin or study")
    if hashlib.sha256(canonical(list(row)).encode()).hexdigest() != digest:
        raise ValueError("Approved event hash mismatch")
    return json.loads(row[2])


def _evidence(store, event):
    directory = (store / event["evidence_dir"]).resolve()
    if not directory.is_relative_to(store.resolve()) or directory == store.resolve():
        raise ValueError("Evidence must belong to this collection store")
    pilot.verify_files(directory, event["artifact_sha256"])
    return directory


def _snapshot(directory, record):
    prices, metadata, _ = get_snapshot(record["data_config"], directory / "snapshot", offline=True)
    if (metadata != record["data"] or metadata.get("synthetic")
            or metadata["request_settings"]["tickers"] != "SPY"
            or metadata["calendar"] != "NYSE"):
        raise ValueError("Forecast release requires a verified SPY market-data vintage")
    return prices, metadata["retrieved_at_utc"]


def _replay_forecast(root, store, config, model, identity, event):
    directory = _evidence(store, event)
    record = event
    if event["kind"] == "pilot_import":
        manual = config["manual_pilot"]
        directory = root / manual["path"]
        if (event["original_record_sha256"] != manual["record_sha256"]
                or pilot.sha(directory / "pilot_record.json") != manual["record_sha256"]):
            raise ValueError("Imported pilot differs from the approved original")
        record = json.loads((directory / "pilot_record.json").read_text(encoding="utf-8"))
        if (record["kind"] != "separate_pilot_forecast" or record["status"] != "success"
                or record["calculation_verification_passed"] is not True
                or record["created_at_utc"] != event["issued_at_utc"]):
            raise ValueError("Original pilot timing or validation differs")
        pilot.verify_files(directory, record["artifact_sha256"])
    elif record.get("numerical_verification_passed") is not True:
        raise ValueError("Forecast numerical verification did not pass")

    for key in ("model_sha256", "freeze_record_sha256", "bundle_id"):
        if record["prepared"][key] != identity[key] or event["prepared"][key] != identity[key]:
            raise ValueError("Forecast uses a different prepared model or protocol")
    if pilot.sha(directory / "model.json") != identity["model_sha256"]:
        raise ValueError("Forecast model copy has changed")
    issued = pd.Timestamp(event["issued_at_utc"])
    selected = pd.Timestamp(record["selection_time_utc"])
    schedule = pilot.pilot_schedule(selected.to_pydatetime())
    prices, acquired = _snapshot(directory, record)
    verified, _, _ = pilot.calculate(prices, model, schedule)
    if verified != record["forecast"] or verified != event["forecast"]:
        raise ValueError("Public replay differs from the approved forecast")
    close = schedule.market_close.iloc[20]
    if not close < selected <= pd.Timestamp(record["acquisition_started_at_utc"]) <= pd.Timestamp(acquired) <= issued:
        raise ValueError("Forecast timestamps do not follow acquisition order")
    if pilot.pilot_schedule(issued.to_pydatetime()).index[20] != schedule.index[20]:
        raise ValueError("A newer session had closed at issue time")
    context = event["context"]
    if (context["origin"] != verified["forecast_session"]
            or context["target_sessions"] != verified["target_sessions"]
            or pd.Timestamp(context["target_close_utc"]) != schedule.market_close.iloc[-1]
            or pd.Timestamp(context["scheduled_close_utc"]) != close
            or pd.Timestamp(context["issue_deadline_utc"]) != close + pd.Timedelta(hours=2)):
        raise ValueError("Forecast origin, targets or deadlines differ from the verified calendar")
    return verified, acquired


def _pilot_outcome(db, store, approval, event, forecast):
    # The release decision and the replayed dates must both identify a 2026 pilot,
    # before even selecting an outcome. A future date cannot unlock this branch.
    origin = forecast["forecast_session"]
    if approval["origin"] != origin or study_for(origin, forecast["target_sessions"]) != "pilot_2026":
        raise ValueError("Formal outcomes require a separately reviewed completed evaluation release")
    label = _event(db, approval["outcome_sha256"], origin, ("outcome",))
    if (label["forecast_attempt_id"] != event["attempt_id"] or label["context"] != event["context"]
            or label["numerical_verification_passed"] is not True):
        raise ValueError("Approved pilot outcome does not match the forecast")
    prices, acquired = _snapshot(_evidence(store, label), label)
    sessions = pd.DatetimeIndex([origin, *forecast["target_sessions"]])
    close = pd.Timestamp(event["context"]["target_close_utc"])
    observed_at = pd.Timestamp(label["observed_at_utc"])
    if not close < pd.Timestamp(label["acquisition_started_at_utc"]) <= pd.Timestamp(acquired) <= observed_at:
        raise ValueError("Pilot outcome snapshot was acquired outside its recorded maturity order")
    observed = realized_volatility(prices, sessions, close, observed_at)
    if observed != label["outcome"]:
        raise ValueError("Realized volatility replay differs from the approved outcome")
    value = observed["observed_volatility"]
    errors = forecast_errors(forecast, value, observed_at)["errors"]
    return {"observed_pct": 100 * value, "acquired_at_utc": acquired,
            "signed_error_pp": {name: errors[key]["signed_error_pp"] for name, key in METHODS.items()},
            "absolute_error_pp": {name: errors[key]["absolute_error_pp"] for name, key in METHODS.items()}}


def _formal_receipt(db, approval, event):
    receipt = _event(db, approval.get("receipt_sha256"), approval["origin"], ("retention_receipt",), "retained")
    if (event["timing_status"] != "local_on_time" or receipt["retained_by_deadline"] is not True
            or receipt["retained_event_hash"] != approval["forecast_sha256"]
            or receipt["receipt"]["server_timestamp_verified"] is not True
            or receipt["receipt"]["checksum_verified"] is not True):
        raise ValueError("Formal forecast lacks qualifying external retention")
    close = pd.Timestamp(event["context"]["scheduled_close_utc"])
    deadline = pd.Timestamp(event["context"]["issue_deadline_utc"])
    if not close < pd.Timestamp(receipt["receipt"]["server_last_modified_utc"]) <= deadline:
        raise ValueError("Formal forecast retention timestamp misses the issue window")


def _release(db, root, store, config, model, identity, approval):
    origin = approval["origin"]
    event = _event(db, approval["forecast_sha256"], origin, ("forecast", "pilot_import"))
    forecast, acquired = _replay_forecast(root, store, config, model, identity, event)
    study = study_for(forecast["forecast_session"], forecast["target_sessions"])
    if study != event["context"]["study"]:
        raise ValueError("Approved forecast has inconsistent study dates")
    if event["kind"] == "pilot_import":
        if study != "pilot_2026" or origin != "2026-11-11":
            raise ValueError("Invalid manual pilot classification")
        study, timing = "manual_pilot_2026", "historical_manual_pilot"
    else:
        timely = pd.Timestamp(event["issued_at_utc"]) <= pd.Timestamp(event["context"]["issue_deadline_utc"])
        timing = "local_on_time" if timely else "late"
        if timing != event["timing_status"]:
            raise ValueError("Forecast timing differs from the recorded issue deadline")
    if study == "formal_2027":
        _formal_receipt(db, approval, event)
    public = {"id": approval["forecast_sha256"], "origin": origin,
              "target_sessions": forecast["target_sessions"], "issued_at_utc": event["issued_at_utc"],
              "acquired_at_utc": acquired, "scheduled_close_utc": forecast["scheduled_close_utc"],
              "study": study, "timing": timing, "validation": "verified",
              "source": "Yahoo Finance via yfinance", "model_id": identity["bundle_id"],
              "predictions_pct": {name: 100 * forecast["predictions"][key] for name, key in METHODS.items()},
              "predictors": {name: forecast["features"][name] for name in FEATURE_COLUMNS},
              "outcome_status": "withheld" if study == "formal_2027" else "pending"}
    if "outcome_sha256" in approval:
        public["outcome"] = _pilot_outcome(db, store, approval, event, forecast)
        public["outcome_status"] = "observed"
    return public


def automatic_pilot_approvals(db, pinned_origins):
    """Select original forecasts only. Replay authenticates every selected event."""
    candidates = db.execute("""
        SELECT json_extract(payload, '$.context.origin'), event_hash FROM events
        WHERE json_extract(payload, '$.kind') = 'forecast'
          AND json_extract(payload, '$.evidence_mode') = 'live'
          AND json_extract(payload, '$.status') = 'valid'
          AND json_extract(payload, '$.numerical_verification_passed') = 1
          AND json_extract(payload, '$.context.study') = 'pilot_2026'
          AND json_extract(payload, '$.context.origin') BETWEEN '2026-01-01' AND '2026-12-31'
          AND json_extract(payload, '$.revision_of') IS NULL
        ORDER BY sequence
    """)
    approvals = {}
    for origin, digest in candidates:
        if origin in pinned_origins:
            continue
        if origin in approvals:
            raise ValueError(f"Multiple original pilot events for {origin}; explicit approval required")
        approvals[origin] = {"origin": origin, "forecast_sha256": digest}
    return approvals.values()


def read_forecasts(root: Path) -> list[dict]:
    """Return verified release-policy records, newest forecast first."""
    root = Path(root).resolve()
    release = tomllib.loads((root / "configs/public_forecasts.toml").read_text(encoding="utf-8"))
    auto = release.get("automatic_2026_pilots", False)
    if (release.get("schema_version") != 1 or not isinstance(auto, bool)
            or set(release) - {"schema_version", "forecasts", "automatic_2026_pilots"}):
        raise ValueError("Unknown forecast approval schema")
    approvals = release.get("forecasts", [])
    seen = set()
    for approval in approvals:
        origin = date.fromisoformat(approval["origin"])
        if (origin.isoformat() != approval["origin"] or origin.year not in (2026, 2027)
                or origin in seen or set(approval) - {"origin", "forecast_sha256", "outcome_sha256", "receipt_sha256"}):
            raise ValueError("Invalid or duplicate approved forecast origin")
        if origin.year == 2027 and "outcome_sha256" in approval:
            raise ValueError("Formal outcomes require a separately reviewed completed evaluation release")
        seen.add(origin)
    if not approvals and not auto:
        return []
    config = tomllib.loads((root / "configs/operations.toml").read_text(encoding="utf-8"))
    store = (root / config["collection"]["store"]).resolve()
    database = store / "journal.sqlite3"
    if not database.is_file():
        raise FileNotFoundError("Approved forecast journal unavailable")
    prepared = config["prepared"]
    model, identity = pilot.load_prepared(root / prepared["bundle"], prepared)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        if auto:
            approvals = [*approvals, *automatic_pilot_approvals(db, {day.isoformat() for day in seen})]
        rows = [_release(db, root, store, config, model, identity, approval) for approval in approvals]
    return sorted(rows, key=lambda r: (r["origin"], r["issued_at_utc"]), reverse=True)
