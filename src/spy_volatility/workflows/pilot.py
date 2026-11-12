"""One manual pilot with a frozen model; no fitting, labels or 2027 evaluation.

Each invocation creates a separate directory, including on failure. Replay only
verifies an existing record; it cannot issue or backdate a forecast.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import sys
import tomllib
from uuid import uuid4

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf

from spy_volatility.core.data import audit_prices, get_snapshot
from spy_volatility.core.models import FEATURE_COLUMNS
from spy_volatility.core.research import build_predictors
from spy_volatility.infrastructure.provenance import copy_source, source_hashes
from spy_volatility.verification.pilot import verify_pilot
from spy_volatility.workflows.prospective import predict_frozen, validate_protocol


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def verify_files(directory: Path, hashes: dict) -> None:
    if not hashes:
        raise ValueError("Missing artifact hash manifest")
    for name, digest in hashes.items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError(f"Artifact path escapes bundle: {name}")
        if not path.is_file():
            raise FileNotFoundError(f"Required artifact unavailable: {path}")
        if sha(path) != digest:
            raise ValueError(f"Artifact SHA-256 mismatch: {path}")


def load_prepared(bundle: Path, expected: dict) -> tuple[dict, dict]:
    """Check the designated bundle without parsing any training/test responses."""
    verify_files(bundle, {"freeze_record.json": expected["freeze_record_sha256"],
                          "model.json": expected["model_sha256"]})
    record = json.loads((bundle / "freeze_record.json").read_text(encoding="utf-8"))
    if (record.get("bundle_id") != bundle.name or record.get("status") != "prepared_not_live"
            or record.get("model_sha256") != expected["model_sha256"]
            or record.get("reserved_rows_excluded") is not True
            or record.get("reserved_responses_read") is not False
            or record.get("final_test_evaluated") is not False):
        raise ValueError("Bundle is not the designated, unscored prepared model")
    hashes = record.get("artifact_sha256", {})
    required = {"model.json", "source/prospective.toml", "source/prospective_protocol.md",
                "source/uncertainty_protocol.md", "preparation_verification.json"}
    if not required.issubset(hashes):
        raise ValueError(f"Missing required bundle manifest entries: {sorted(required - hashes.keys())}")
    verify_files(bundle, hashes)
    config_path = bundle / "source/prospective.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if sha(config_path) != record["config_sha256"] or config != record["config"]:
        raise ValueError("Frozen configuration differs from its preparation record")
    validate_protocol(config, datetime.fromisoformat(record["prepared_at_utc"]))
    for name, digest in record["source_sha256"].items():
        relative = Path(name).relative_to("spy_volatility")
        verify_files(bundle / "source", {relative.as_posix(): digest})
    verify_files(bundle / "inputs", record["source_artifact_sha256"])
    verification = json.loads((bundle / "preparation_verification.json").read_text(encoding="utf-8"))
    if verification.get("status") != "passed":
        raise ValueError("Frozen preparation verification did not pass")
    model = json.loads((bundle / "model.json").read_text(encoding="utf-8"))
    if (model.get("model") != "ridge" or model.get("alpha") != 1.0 or model.get("refit") is not False
            or model.get("n_training_rows") != record["n_training_rows"]
            or model.get("training_label_cutoff") != config["training"]["label_cutoff"]
            or model.get("units") != "decimal daily-return volatility"):
        raise ValueError("Frozen model does not match its protocol")
    # Existing predictor validates format, order, arrays, intercept and floor.
    predict_frozen(model, pd.DataFrame([[0.] * 5], columns=FEATURE_COLUMNS))
    return model, {"bundle_id": record["bundle_id"], "bundle_path": str(bundle.resolve()),
                   "freeze_record_sha256": sha(bundle / "freeze_record.json"),
                   "model_sha256": sha(bundle / "model.json"),
                   "config_sha256": record["config_sha256"],
                   "artifact_hashes_checked": len(hashes), "all_hashes_passed": True,
                   "preparation_verification": verification}


def pilot_schedule(now: datetime) -> pd.DataFrame:
    """21 historical and five future NYSE sessions, strictly after origin close."""
    instant = pd.Timestamp(now)
    if instant.tz is None:
        raise ValueError("Selection time must be timezone-aware")
    day = instant.tz_convert("America/New_York").tz_localize(None).normalize()
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(day - pd.Timedelta(days=90), day + pd.Timedelta(days=30))
    closed = schedule.loc[schedule.market_close < instant]
    if len(closed) < 21:
        raise ValueError("Not enough completed exchange sessions")
    origin = closed.index[-1]
    future = schedule.loc[schedule.index > origin].iloc[:5]
    if len(future) != 5:
        raise ValueError("Five future exchange sessions unavailable")
    result = pd.concat([closed.iloc[-21:], future]).copy()
    result.index.name = "session"
    result["role"] = ["input"] * 20 + ["origin"] + ["target"] * 5
    return result


def calculate(prices: pd.Series, model: dict, schedule: pd.DataFrame) -> tuple[dict, dict, pd.Series]:
    """Use research predictors and the existing frozen-model evaluator."""
    expected = schedule.index[:21]
    if len(prices) != 21 or not prices.index.equals(expected):
        raise ValueError("Require exactly 21 consecutive session prices ending at the latest completed origin")
    audit_prices(prices, expected[0].date().isoformat(),
                 (expected[-1] + pd.Timedelta(days=1)).date().isoformat(), "NYSE")
    predictors = build_predictors(prices)
    features = predictors.loc[[expected[-1]], list(FEATURE_COLUMNS)]
    predictions = predict_frozen(model, features).iloc[0].to_dict()
    z = (features.to_numpy()[0] - np.array(model["scaler_mean"])) / np.array(model["scaler_scale"])
    predictions["ridge_raw"] = float(z @ np.array(model["ridge_coefficients"]) + model["ridge_intercept"])
    returns = predictors.log_return.iloc[1:]
    verification = verify_pilot(prices, features, model, predictions, z.tolist(), returns)
    values = {name: float(features.iloc[0][name]) for name in FEATURE_COLUMNS}
    result = {"feature_order": list(FEATURE_COLUMNS), "features": values,
              "feature_units": {name: ("decimal log return" if name == "log_return" else
                  "sum of five decimal log returns" if name == "momentum_5" else
                  "decimal daily log-return sample SD (ddof=1)") for name in FEATURE_COLUMNS},
              "scaled_features": z.tolist(), "predictions": predictions,
              "prediction_units": "decimal daily log-return standard deviation; not annualized",
              "prediction_floor": model["prediction_floor"],
              "floor_applied": bool(predictions["ridge_raw"] < model["prediction_floor"]),
              "latest_adjusted_close": float(prices.iloc[-1]),
              "forecast_session": expected[-1].date().isoformat(),
              "scheduled_close_utc": schedule.market_close.iloc[20].isoformat(),
              "actual_close_independently_confirmed": False,
              "target_sessions": [d.date().isoformat() for d in schedule.index[21:]],
              "target_definition": "Sample SD of daily log returns over the entire next five-session window; not five daily price predictions"}
    return result, verification, returns


def report_markdown(record: dict, output: Path, config_path: Path) -> str:
    lines = ["# Separate SPY pilot forecast", "", f"Status: **{record['status']}**.", "",
             "This is a manual pilot, not a 2027 evaluation or a claimed prospective/on-time observation.",
             "No model fitting, parameter search, reserved outcome scoring or scheduler is involved.", ""]
    if "error" in record:
        lines += [f"Failure: `{record['error']['type']}`: {record['error']['message']}", "",
                  "No forecast was issued. Retained evidence is in this directory.", ""]
    if "forecast" in record:
        f = record["forecast"]
        lines += [f"Forecast origin: {f['forecast_session']}; scheduled close: {f['scheduled_close_utc']}.",
                  f"Created: {record['created_at_utc']}; acquired: {record['data']['retrieved_at_utc']}.",
                  f"Latest adjusted close: {f['latest_adjusted_close']:.15g} USD.",
                  f"Target sessions: {', '.join(f['target_sessions'])}.", "", f["target_definition"] + ".", "",
                  "| Predictor (stored order) | Value | Unit |", "| --- | ---: | --- |"]
        lines += [f"| {n} | {f['features'][n]:.15g} | {f['feature_units'][n]} |" for n in f["feature_order"]]
        lines += ["", "| Prediction | Decimal daily SD | Daily SD (%) |", "| --- | ---: | ---: |"]
        lines += [f"| {n} | {f['predictions'][n]:.15g} | {100*f['predictions'][n]:.10f} |"
                  for n in ("ridge_raw", "ridge", "baseline", "baseline_5")]
        lines += ["", f"Floor: {f['prediction_floor']}; applied: {f['floor_applied']}.",
                  f"Input vintage SHA-256: `{record['data']['sha256']}`.",
                  f"Source: {record['data']['source']}; request and versions: `snapshot/metadata.json`.",
                  "Verification passed: all 20 returns, ordered features/windows/momentum, stored scaling,",
                  "raw Ridge, floor and both benchmarks; independent scalar arithmetic and restored sklearn state.",
                  "Tolerance: rtol=1e-9, atol=1e-12. Details: `verification.json` and `returns.csv`.", ""]
    if "prepared" in record:
        p = record["prepared"]
        lines += [f"Prepared bundle: `{p['bundle_id']}`; {p['artifact_hashes_checked']} artifact hashes passed.",
                  f"Model SHA-256: `{p['model_sha256']}`.",
                  f"Bundle record SHA-256: `{p['freeze_record_sha256']}`.", ""]
    lines += ["## Reproduce", "", "Run from the repository directory containing pyproject.toml.", "", "```powershell",
              f'.\\.venv\\Scripts\\python.exe -m spy_volatility.workflows.pilot --config "{config_path}"',
              f'.\\.venv\\Scripts\\python.exe -m spy_volatility.workflows.pilot --replay "{output}"', "```", "",
              "The first command obtains a new vintage for the then-latest completed session; it cannot reproduce",
              "an old vendor vintage. Replay checks all saved hashes and recalculates without network access or issuing a forecast.", "",
              "## Limitations", "", *[f"- {item}" for item in record["limitations"]], ""]
    return "\n".join(lines)


LIMITATIONS = [
    "Pilot only; no trusted external timestamp retention or append-only prospective issuance system. No on-time claim.",
    "Uses versioned NYSE scheduled closes, not independently observed exchange close-event timestamps; unscheduled changes need official review.",
    "Yahoo can revise adjusted history. The single acquisition vintage is archived; no cross-vendor price verification.",
    "The archive contains all fields returned by yfinance as CSV, not original Yahoo HTTP response bytes.",
    "Predicted daily-return SD describes the entire next five-session window, not prices, cumulative return or annualized volatility.",
]


def run_pilot(config_path: str | Path) -> dict:
    config_path = Path(config_path).resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%S") + "_pilot_" + uuid4().hex[:8]
    output = root / config["paths"]["output_dir"] / run_id
    output.mkdir(parents=True, exist_ok=False)
    record = {"run_id": run_id, "status": "failed", "kind": "separate_pilot_forecast",
              "started_at_utc": started.isoformat(), "output_dir": str(output),
              "config": config, "config_sha256": sha(config_path), "source_sha256": source_hashes(),
              "model_fitted": False, "reserved_responses_read": False, "future_outcomes_read": False,
              "is_2027_evaluation": False, "prospective_on_time_claim": False,
              "limitations": LIMITATIONS, "calendar_version": version("pandas_market_calendars")}
    try:
        copy_source(output / "source", record["source_sha256"])
        shutil.copy2(config_path, output / "source/pilot.toml")
        bundle = root / config["prepared"]["bundle"]
        model, identity = load_prepared(bundle, config["prepared"])
        record["prepared"] = identity
        shutil.copy2(bundle / "model.json", output / "model.json")
        selection = datetime.now(timezone.utc)
        record["selection_time_utc"] = selection.isoformat()
        schedule = pilot_schedule(selection)
        schedule.to_csv(output / "calendar.csv")
        origin = schedule.index[20]
        record["expected_origin"] = origin.date().isoformat()
        data_config = {"ticker": "SPY", "calendar": "NYSE", "start": schedule.index[0].date().isoformat(),
                       "end": (origin + pd.Timedelta(days=1)).date().isoformat()}
        record["data_config"] = data_config
        # The default user-profile SQLite cache may be inaccessible in a
        # restricted workspace. This changes storage, not provider settings.
        cache = root / "artifacts/cache/pilot_yfinance"
        cache.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache))
        record["acquisition_started_at_utc"] = datetime.now(timezone.utc).isoformat()
        prices, metadata, audit = get_snapshot(data_config, output / "snapshot")
        record["data"] = metadata
        write_json(output / "data_audit.json", audit)
        forecast, verification, returns = calculate(prices, model, schedule)
        returns.to_csv(output / "returns.csv", index_label="session", header=["log_return"])
        write_json(output / "verification.json", verification)
        created = datetime.now(timezone.utc)
        if not (pd.Timestamp(record["acquisition_started_at_utc"]) <= pd.Timestamp(metadata["retrieved_at_utc"])
                <= pd.Timestamp(created)):
            raise ValueError("Invalid acquisition/creation timestamp ordering")
        if pilot_schedule(created).index[20] != origin:
            raise ValueError("A newer exchange session closed during acquisition; start a new pilot")
        # Recheck immutable evidence after all calculations, before recording success.
        load_prepared(bundle, config["prepared"])
        if sha(output / "snapshot/raw.csv") != metadata["sha256"] or source_hashes() != record["source_sha256"]:
            raise ValueError("Input or execution source changed during forecast")
        if sha(config_path) != record["config_sha256"]:
            raise ValueError("Pilot configuration changed during forecast")
        record.update(status="success", created_at_utc=created.isoformat(), forecast=forecast,
                      calculation_verification_passed=True,
                      minutes_after_scheduled_close=(pd.Timestamp(created) - schedule.market_close.iloc[20]).total_seconds()/60)
    except Exception as error:
        record["error"] = {"type": type(error).__name__, "message": str(error)}
        if hasattr(error, "report"):
            write_json(output / "data_audit.json", error.report)
    record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    (output / "report.md").write_text(report_markdown(record, output, config_path), encoding="utf-8")
    record["artifact_sha256"] = {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob("*")) if p.is_file()}
    write_json(output / "pilot_record.json", record)
    return record


def replay(output: str | Path) -> dict:
    """Read-only recomputation, retaining the original acquisition and creation times."""
    output = Path(output).resolve()
    record = json.loads((output / "pilot_record.json").read_text(encoding="utf-8"))
    if record["status"] != "success" or record["kind"] != "separate_pilot_forecast":
        raise ValueError("Replay requires a successful separate pilot")
    verify_files(output, record["artifact_sha256"])
    if sha(output / "source/pilot.toml") != record["config_sha256"]:
        raise ValueError("Saved pilot configuration hash mismatch")
    config = tomllib.loads((output / "source/pilot.toml").read_text(encoding="utf-8"))
    if config != record["config"]:
        raise ValueError("Saved pilot configuration differs")
    model, identity = load_prepared(Path(record["prepared"]["bundle_path"]), config["prepared"])
    if identity != record["prepared"] or sha(output / "model.json") != identity["model_sha256"]:
        raise ValueError("Saved prepared model identity differs")
    schedule = pilot_schedule(datetime.fromisoformat(record["selection_time_utc"]))
    saved_schedule = pd.read_csv(output / "calendar.csv", index_col="session", parse_dates=["session", "market_open", "market_close"])
    pd.testing.assert_frame_equal(schedule, saved_schedule, check_freq=False)
    prices, metadata, _ = get_snapshot(record["data_config"], output / "snapshot", offline=True)
    if metadata != record["data"]:
        raise ValueError("Saved data provenance differs")
    result, verification, _ = calculate(prices, model, schedule)
    if result != record["forecast"]:
        raise ValueError("Recomputed forecast differs from original record")
    created = pd.Timestamp(record["created_at_utc"])
    if not (schedule.market_close.iloc[20] < pd.Timestamp(record["selection_time_utc"])
            <= pd.Timestamp(record["acquisition_started_at_utc"]) <= pd.Timestamp(metadata["retrieved_at_utc"]) <= created):
        raise ValueError("Saved timestamp ordering is invalid")
    if pilot_schedule(created.to_pydatetime()).index[20] != schedule.index[20]:
        raise ValueError("Saved forecast origin was stale at creation")
    return {"status": "passed", "mode": "read_only_replay", "output_dir": str(output),
            "forecast": result, "verification": verification, "new_forecast_issued": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--config", default="configs/pilot.toml")
    group.add_argument("--replay", metavar="PILOT_DIRECTORY")
    args = parser.parse_args()
    try:
        record = replay(args.replay) if args.replay else run_pilot(args.config)
        print(json.dumps({key: record[key] for key in ("status", "output_dir", "forecast", "error", "mode") if key in record}, indent=2))
        return 0 if record["status"] in ("success", "passed") else 1
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
