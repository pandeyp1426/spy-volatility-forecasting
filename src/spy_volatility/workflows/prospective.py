"""Freeze a later-period protocol and a transparent model, without live scoring.

Only verified historical development rows and reserved identity metadata are
read. There is no data download, future-label loader, daily scheduler or scorer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import traceback
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from spy_volatility.core.models import FEATURE_COLUMNS, TARGET_COLUMN, model_frame
from spy_volatility.infrastructure.provenance import copy_source, source_hashes


INPUTS = ("development.csv", "reserved_identities.csv", "source_split_assignments.csv")
IDENTITIES = ["forecast_date", "row_id", "session_number", "target_start", "target_end"]
RESEARCH = {"windows": [5, 10, 20], "horizon": 5, "momentum_window": 5, "baseline_window": 20}
TRAINING = {"start": "2015-01-01", "label_cutoff": "2025-12-31", "model": "ridge", "alpha": 1.0,
            "features": list(FEATURE_COLUMNS), "prediction_floor": 0.0, "tail_quantile": 0.95, "refit": False}
EVALUATION = {"start": "2027-01-01", "end_exclusive": "2028-01-01", "calendar": "NYSE", "horizon": 5,
              "ddof": 1, "price_field": "Adj Close", "return": "log", "issue_deadline_minutes_after_close": 120,
              "label_deadline_hours_after_target_close": 24, "score_not_before": "2028-01-10",
              "containment": "target_start_and_end_in_forecast_calendar_year", "benchmarks": ["baseline", "baseline_5"],
              "primary_metric": "rmse_pp", "missing_policy": "common_valid_on_time_forecasts_and_archived_labels"}
UNCERTAINTY = {"method": "paired_stationary_bootstrap_original_session_grid", "replicates": 5000, "seed": 42,
               "primary_expected_block_length": 20, "expected_block_lengths": [5, 10, 20, 40, 60],
               "nominal_coverage": 0.95, "primary_family_individual_coverage": 0.975,
               "primary_comparisons": ["ridge_minus_baseline", "ridge_minus_baseline_5"],
               "evidence_rule": "lower_point_rmse_and_both_adjusted_upper_bounds_below_zero_at_primary_block_length"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def validate_protocol(config: dict, now: datetime) -> None:
    """Reject silent changes to the declared model, period or inferential rule."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Freeze time must be timezone-aware")
    if config.get("experiment", {}).get("strategy") != "prospective_protocol":
        raise ValueError("Expected prospective_protocol configuration")
    for key, expected in (("training", TRAINING), ("evaluation", EVALUATION), ("uncertainty", UNCERTAINTY)):
        if config.get(key) != expected:
            raise ValueError(f"The frozen prospective {key} specification must not be changed silently")
    local_date = now.astimezone(ZoneInfo("America/Chicago")).date()
    start = pd.Timestamp(config["evaluation"]["start"]).date()
    if local_date >= start:
        raise ValueError("Freeze must precede the evaluation start in America/Chicago; no retrospective freeze")
    if local_date <= pd.Timestamp(config["training"]["label_cutoff"]).date():
        raise ValueError("All frozen historical training labels must be available before preparation")


def _identity_table(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if not set(IDENTITIES).issubset(frame.columns) or frame.empty:
        raise ValueError(f"{name} requires complete identity metadata")
    checked = frame[IDENTITIES].copy()
    if checked.isna().any().any():
        raise ValueError(f"{name} has missing identities")
    for column in ("row_id", "session_number"):
        values = pd.to_numeric(checked[column], errors="raise").to_numpy(float)
        if not np.isfinite(values).all() or (values < 0).any() or (values != np.floor(values)).any():
            raise ValueError(f"{name} {column} must contain nonnegative integers")
        checked[column] = values.astype(np.int64)
    for column in ("forecast_date", "target_start", "target_end"):
        checked[column] = pd.to_datetime(checked[column], errors="raise")
        if checked[column].dt.tz is not None or not checked[column].eq(checked[column].dt.normalize()).all():
            raise ValueError(f"{name} requires timezone-free session dates")
    if not checked.row_id.is_unique or not checked.forecast_date.is_unique or not checked.session_number.is_unique:
        raise ValueError(f"{name} identities must be unique")
    checked = checked.sort_values("forecast_date").reset_index(drop=True)
    if (np.diff(checked.session_number) <= 0).any():
        raise ValueError(f"{name} session order differs from dates")
    if not ((checked.forecast_date < checked.target_start) & (checked.target_start <= checked.target_end)).all():
        raise ValueError(f"{name} target intervals must be strictly after forecast dates")
    return checked


def load_training(source: Path, config: dict) -> tuple[pd.DataFrame, dict, dict[str, str]]:
    """Read allowed historical outcomes; reserve metadata is never a model input."""
    record_path = source / "run_record.json"
    parent = json.loads(record_path.read_text(encoding="utf-8"))
    if (parent.get("status") != "success" or parent.get("experiment") != "retrospective_temporal"
            or parent.get("final_test_evaluated") is not False or parent.get("reserved_rows_excluded") is not True
            or parent.get("calculation_verification_passed") is not True
            or parent.get("config", {}).get("research") != RESEARCH
            or parent.get("config", {}).get("data", {}).get("ticker") != "SPY"):
        raise ValueError("Use a successful verified temporal parent with reserved test excluded")
    hashes = {"run_record.json": _sha(record_path)}
    for name in INPUTS:
        hashes[name] = _sha(source / name)
        if hashes[name] != parent.get("artifact_sha256", {}).get(name):
            raise ValueError(f"Historical input hash mismatch: {name}")
    development = pd.read_csv(source / "development.csv", float_precision="round_trip")
    assignments = pd.read_csv(source / "source_split_assignments.csv", usecols=[*IDENTITIES, "partition"])
    reserved = pd.read_csv(source / "reserved_identities.csv", usecols=[*IDENTITIES, "partition"])
    if set(assignments.partition) != {"train", "validation", "test"} or not reserved.partition.eq("test").all():
        raise ValueError("Saved identity roles must be train, validation and excluded test")
    _identity_table(assignments, "pooled assignments")
    reserved_ids = _identity_table(reserved, "reserved identities")
    assigned_reserved = _identity_table(assignments.loc[assignments.partition.eq("test")], "assigned reserved")
    if not reserved_ids.equals(assigned_reserved):
        raise ValueError("Reserved metadata differs from the original pooled map")
    identities = _identity_table(development, "development")
    if identities.row_id.isin(reserved_ids.row_id).any():
        raise ValueError("Reserved identity entered prospective training")
    allowed = _identity_table(assignments.loc[assignments.partition.isin(["train", "validation"])], "allowed identities")
    if not identities.equals(allowed):
        raise ValueError("Training must preserve every permitted development identity and its metadata")
    cutoff = pd.Timestamp(config["training"]["label_cutoff"])
    if not (identities.forecast_date.ge(config["training"]["start"]).all()
            and identities.forecast_date.le(cutoff).all() and identities.target_end.le(cutoff).all()):
        raise ValueError("Training contains observations outside 2015–2025 or labels unavailable at the cutoff")
    development["forecast_date"] = pd.to_datetime(development.forecast_date)
    development = development.set_index("forecast_date").sort_index()
    frame = model_frame(development)
    # Prevent accepting an input that changed after its recorded hash was checked.
    if any(_sha(source / name) != digest for name, digest in hashes.items()):
        raise ValueError("Historical evidence changed while loading training data")
    return frame, parent, hashes


def predict_frozen(model: dict, features: pd.DataFrame) -> pd.DataFrame:
    """Evaluate transparent JSON coefficients; this does not issue a live forecast."""
    if model.get("format_version") != 1 or model.get("features") != list(FEATURE_COLUMNS):
        raise ValueError("Unexpected frozen model format or feature order")
    if not features.columns.is_unique or not set(FEATURE_COLUMNS).issubset(features.columns):
        raise ValueError("Prediction inputs must provide the five unique allowed features")
    values = features.loc[:, list(FEATURE_COLUMNS)].to_numpy(float)
    if not np.isfinite(values).all() or (features[["volatility_5", "volatility_10", "volatility_20"]].to_numpy(float) < 0).any():
        raise ValueError("Frozen-model inputs must be finite with nonnegative volatility")
    mean, scale, coefficient = (np.asarray(model[key], dtype=float) for key in ("scaler_mean", "scaler_scale", "ridge_coefficients"))
    if any(a.shape != (len(FEATURE_COLUMNS),) or not np.isfinite(a).all() for a in (mean, scale, coefficient)) or (scale <= 0).any():
        raise ValueError("Frozen scaler/coefficient arrays are invalid")
    intercept = float(model["ridge_intercept"])
    if not np.isfinite(intercept) or model.get("prediction_floor") != 0.0:
        raise ValueError("Frozen intercept or nonnegative floor is invalid")
    prediction = np.maximum(((values - mean) / scale) @ coefficient + intercept, 0.0)
    if not np.isfinite(prediction).all():
        raise ValueError("Frozen model produced a nonfinite value")
    return pd.DataFrame({"ridge": prediction, "baseline": features.volatility_20.to_numpy(float),
                         "baseline_5": features.volatility_5.to_numpy(float)}, index=features.index)


def build_schedule(config: dict) -> pd.DataFrame:
    """Freeze planned exchange sessions, issue deadlines and contained targets."""
    evaluation = config["evaluation"]
    schedule = mcal.get_calendar(evaluation["calendar"]).schedule(
        evaluation["start"], pd.Timestamp(evaluation["end_exclusive"]) - pd.Timedelta(days=1))
    schedule.index.name = "forecast_date"
    schedule = schedule.reset_index()
    schedule["session_position"] = np.arange(len(schedule), dtype=int)
    schedule["issue_deadline_utc"] = schedule.market_close + pd.Timedelta(minutes=evaluation["issue_deadline_minutes_after_close"])
    schedule["target_start"] = schedule.forecast_date.shift(-1)
    schedule["target_end"] = schedule.forecast_date.shift(-evaluation["horizon"])
    schedule["target_close_utc"] = schedule.market_close.shift(-evaluation["horizon"])
    schedule["label_deadline_utc"] = schedule.target_close_utc + pd.Timedelta(hours=evaluation["label_deadline_hours_after_target_close"])
    schedule["eligible_forecast_origin"] = (schedule.target_start.dt.year.eq(schedule.forecast_date.dt.year)
                                             & schedule.target_end.dt.year.eq(schedule.forecast_date.dt.year))
    return schedule


def freeze_prospective(config_path: str | Path, *, now: datetime | None = None) -> dict:
    """Prepare a new immutable-by-convention bundle; never publish or score it."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc) if now is None or now.tzinfo is not None else now
    config_path = Path(config_path).resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    validate_protocol(config, now)
    root = config_path.parent.parent
    source = (root / config["paths"]["temporal_run"]).resolve()
    frame, parent, input_hashes = load_training(source, config)
    bundle_id = now.strftime("%Y%m%dT%H%M%S") + "_prospective_" + uuid4().hex[:8]
    output = root / config["paths"]["output_dir"] / bundle_id
    output.mkdir(parents=True, exist_ok=False)
    record = {"bundle_id": bundle_id, "status": "preparing", "prepared_at_utc": now.isoformat(),
              "prepared_local_date": now.astimezone(ZoneInfo("America/Chicago")).date().isoformat(),
              "parent_run_id": parent["run_id"], "source_artifact_sha256": input_hashes,
              "snapshot_sha256": parent.get("snapshot_sha256"), "config": config, "config_sha256": _sha(config_path),
              "source_sha256": source_hashes(), "python": sys.version,
              "package_versions": {d.metadata["Name"]: d.version for d in distributions() if d.metadata["Name"]},
              "offline": True, "historical_model_fitted": False, "live_forecasting_started": False,
              "future_data_downloaded": False, "future_period_evaluated": False, "reserved_responses_read": False,
              "reserved_rows_excluded": True, "final_test_evaluated": False,
              "model_choice": "Fixed Ridge selected from previously reviewed historical evidence, before current uncertainty outputs",
              "limitations": ["Prepared protocol/model only; operational forecast collection is not installed",
                              "Provider adjustment vintages and timestamp integrity require prospective archiving",
                              "Historical development data informed model choice; only later outcomes can test extension"]}
    _write_json(output / "freeze_record.json", record)
    try:
        (output / "source").mkdir()
        (output / "inputs").mkdir()
        for name, digest in input_hashes.items():
            shutil.copy2(source / name, output / "inputs" / name)
            if _sha(output / "inputs" / name) != digest:
                raise ValueError(f"Source changed while copying {name}")
        copy_source(output / "source", record["source_sha256"])
        shutil.copy2(config_path, output / "source" / "prospective.toml")
        if _sha(output / "source" / "prospective.toml") != record["config_sha256"]:
            raise ValueError("Configuration changed during freezing")
        for name in ("prospective_protocol.md", "uncertainty_protocol.md"):
            document = root / "docs" / "protocols" / name
            if document.is_file():
                shutil.copy2(document, output / "source" / name)
        record["source_git"] = {}
        for name, args in (("commit", ["rev-parse", "HEAD"]), ("working_tree", ["status", "--short"])):
            try:
                result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
                record["source_git"][name] = result.stdout.strip() if result.returncode == 0 else "unavailable"
            except OSError:
                record["source_git"][name] = "unavailable"
        x, y = frame[list(FEATURE_COLUMNS)], frame[TARGET_COLUMN]
        scaler = StandardScaler().fit(x)
        regressor = Ridge(alpha=1.0).fit(scaler.transform(x), y)
        model = {"format_version": 1, "model": "ridge", "features": list(FEATURE_COLUMNS), "alpha": 1.0,
                 "units": "decimal daily-return volatility", "prediction_floor": 0.0,
                 "scaler_mean": scaler.mean_.tolist(), "scaler_scale": scaler.scale_.tolist(),
                 "ridge_coefficients": regressor.coef_.tolist(), "ridge_intercept": float(regressor.intercept_),
                 "training_target_q95": float(np.quantile(y.to_numpy(), .95, method="linear")),
                 "n_training_rows": len(frame), "first_training_forecast": frame.index.min().date().isoformat(),
                 "last_training_forecast": frame.index.max().date().isoformat(),
                 "training_label_cutoff": TRAINING["label_cutoff"], "refit": False}
        _write_json(output / "model.json", model)
        reloaded = json.loads((output / "model.json").read_text(encoding="utf-8"))
        expected = np.maximum(regressor.predict(scaler.transform(x)), 0.0)
        reconstructed = predict_frozen(reloaded, x)
        np.testing.assert_allclose(reconstructed.ridge.to_numpy(), expected, rtol=1e-12, atol=1e-14)
        np.testing.assert_array_equal(reconstructed.baseline.to_numpy(), x.volatility_20.to_numpy())
        np.testing.assert_array_equal(reconstructed.baseline_5.to_numpy(), x.volatility_5.to_numpy())
        schedule = build_schedule(config)
        schedule.to_csv(output / "evaluation_schedule.csv", index=False)
        training_rows = pd.read_csv(output / "inputs" / "development.csv", usecols=IDENTITIES)
        training_rows.to_csv(output / "training_identities.csv", index=False)
        verification = {"status": "passed", "n_training_rows": len(frame),
                        "serialized_prediction_max_absolute_difference": float(np.max(np.abs(reconstructed.ridge.to_numpy() - expected))),
                        "scaler_fitted_only_on_permitted_training": True, "all_training_labels_available_by_cutoff": True,
                        "reserved_rows_excluded": True, "reserved_responses_read": False,
                        "future_period_evaluated": False, "scheduled_sessions": len(schedule),
                        "eligible_forecast_origins": int(schedule.eligible_forecast_origin.sum())}
        _write_json(output / "preparation_verification.json", verification)
        (output / "dependencies.txt").write_text("\n".join(f"{k}=={v}" for k, v in sorted(record["package_versions"].items())) + "\n", encoding="utf-8")
        record.update(status="prepared_not_live", historical_model_fitted=True, model_sha256=_sha(output / "model.json"),
                      n_training_rows=len(frame), eligible_forecast_origins=int(schedule.eligible_forecast_origin.sum()))
        (output / "readiness.md").write_text(
            f"# Prepared prospective study\n\nBundle: `{bundle_id}`. Status: **prepared, not live**.\n\n"
            f"Frozen Ridge plus both historical benchmarks; {len(frame)} permitted 2015–2025 training rows. "
            f"The saved calendar contains {len(schedule)} 2027 sessions and {record['eligible_forecast_origins']} contained five-session forecast origins.\n\n"
            "The JSON model's predictions match the fitted estimator. All source identities and hashes were checked. "
            "No future data was acquired, no future period was scored, and reserved responses were not opened.\n\n"
            "Before live collection: designate this bundle; implement and test issue-time acquisition, immutable input vintages, "
            "trusted timestamped append-only forecast records, missing-attempt records and separately matured labels. "
            "No scheduler or live logger was started. Do not backfill missed forecasts. Comparative scoring begins no earlier than 10 January 2028.\n",
            encoding="utf-8")
        if any(_sha(source / name) != digest for name, digest in input_hashes.items()):
            raise ValueError("Historical source changed during protocol preparation")
        return {"bundle_id": bundle_id, "output_dir": str(output), "status": "prepared_not_live",
                "n_training_rows": len(frame), "eligible_forecast_origins": record["eligible_forecast_origins"],
                "model_sha256": record["model_sha256"], "live_forecasting_started": False,
                "future_period_evaluated": False, "final_test_evaluated": False}
    except Exception as error:
        record.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
        (output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        record["artifact_sha256"] = {p.relative_to(output).as_posix(): _sha(p) for p in sorted(output.rglob("*"))
                                    if p.is_file() and p != output / "freeze_record.json"}
        _write_json(output / "freeze_record.json", record)


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze the 2027 protocol/model offline; no live forecasts or future scoring")
    parser.add_argument("--config", default="configs/prospective.toml")
    args = parser.parse_args()
    try:
        print(json.dumps(freeze_prospective(args.config), indent=2))
        return 0
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
