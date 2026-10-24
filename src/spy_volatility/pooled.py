"""Requested pooled comparison, with explicit overlap and a reserved test subset.

This module reuses the original acquisition, features, provenance and CLI.
It never fits, predicts, summarizes outcomes, or scores the test partition.
"""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import distributions
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys
import traceback
from uuid import uuid4

import numpy as np
import pandas as pd

from .data import get_snapshot, audit_raw_fields
from .eda import write_training_eda
from .models import compare_validation, model_frame, FEATURE_COLUMNS, TARGET_COLUMN, MODEL_NAMES
from .provenance import source_hashes
from .research import build_features, _check_index
from .verification import _close, _require, CalculationVerificationError


def validate_split_settings(seed, train_fraction, validation_fraction):
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    fractions = (train_fraction, validation_fraction)
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or
           not np.isfinite(x) or not 0 < x < 1 for x in fractions):
        raise ValueError("Split fractions must be finite numbers between zero and one")
    if sum(fractions) >= 1:
        raise ValueError("Training and validation fractions must leave a reserved test remainder")


def audit_overlap(splits: dict, horizon: int = 5) -> dict:
    """Count shared original return sessions using metadata only, not outcomes."""
    if type(horizon) is not int or horizon < 2:
        raise ValueError("horizon must be an integer >= 2")
    sessions = {}
    for name in ("train", "validation", "test"):
        frame = splits[name]
        _check_index(frame)
        values = frame["session_number"].to_numpy(dtype=float)
        if (not len(values) or not np.isfinite(values).all() or (values < 20).any()
                or (values != np.floor(values)).any() or (np.diff(values) <= 0).any()):
            raise ValueError("Original session numbers must be ordered distinct integers with 20-session history")
        sessions[name] = values.astype(np.int64)
    if len(set(np.concatenate(list(sessions.values())))) != sum(map(len, sessions.values())):
        raise ValueError("Partitions must have disjoint original session identities")
    training_outcomes = {int(s + offset) for s in sessions["train"] for offset in range(1, horizon + 1)}
    training_features = {int(s - offset) for s in sessions["train"] for offset in range(20)}
    result = {}
    for name in ("validation", "test"):
        outcomes = [set(range(int(s) + 1, int(s) + horizon + 1)) for s in sessions[name]]
        result[name] = {
            "n_rows": len(outcomes),
            "rows_with_training_outcome_overlap": sum(bool(x & training_outcomes) for x in outcomes),
            "rows_with_training_feature_overlap": sum(bool(x & training_features) for x in outcomes),
        }
    return result


def split_pooled(examples: pd.DataFrame, seed=42, train_fraction=.70,
                 validation_fraction=.15) -> tuple[dict, dict]:
    """One NumPy permutation of chronologically ordered eligible rows; no stratification."""
    _check_index(examples)
    validate_split_settings(seed, train_fraction, validation_fraction)
    n = len(examples)
    n_train, n_validation = int(train_fraction * n), int(validation_fraction * n)
    if min(n_train, n_validation, n - n_train - n_validation) < 1:
        raise ValueError("Each partition must contain at least one eligible row")
    if "row_id" in examples:
        raise ValueError("row_id is assigned once from eligible chronological order")
    frame = examples.copy()
    frame["row_id"] = np.arange(n)
    order = np.random.default_rng(seed).permutation(n)
    ids = (order[:n_train], order[n_train:n_train+n_validation], order[n_train+n_validation:])
    splits = {name: frame.iloc[selection].sort_index().copy()
              for name, selection in zip(("train", "validation", "test"), ids)}
    summary = {
        "strategy": "pooled_random", "seed": seed, "stratification": None,
        "assignment": "default_rng(seed).permutation(N), floor train, floor validation, test remainder",
        "n_eligible": n, "train_fraction": train_fraction, "validation_fraction": validation_fraction,
        "row_ids_disjoint": True, "exhaustive": True,
        "partitions": {name: {"n_rows": len(part),
            "first_forecast_date": part.index.min().date().isoformat(),
            "last_forecast_date": part.index.max().date().isoformat()}
            for name, part in splits.items()},
        "outcome_overlap": audit_overlap(splits),
        "limitation": "Row disjointness does not separate outcome returns or future training information.",
        "prior_exposure": "Earlier work inspected some 2015-2023 history; reserved rows are not a never-seen research sample.",
    }
    return splits, summary


def verify_pooled(output: Path, prices: pd.Series, config: dict) -> dict:
    """Independently verify saved train/validation windows, membership and scores.

    Test files are never opened. Split assignments contain only identities and
    dates and may be checked without reading test response values.
    """
    report = {"passed": False, "checked_rows": {}, "checks": [], "test_outcomes_read": False}
    try:
        returns = np.r_[np.nan, np.log(prices.to_numpy()[1:] / prices.to_numpy()[:-1])]
        positions = np.arange(20, len(prices) - 5)
        settings = config["split"]
        positions = positions[(prices.index[positions] >= settings["start"])
                              & (prices.index[positions] < settings["end"])]
        n = len(positions)
        order = np.random.default_rng(settings["seed"]).permutation(n)
        a, b = int(settings["train_fraction"] * n), int(settings["validation_fraction"] * n)
        labels = np.full(n, "test", dtype=object)
        labels[order[:a]], labels[order[a:a+b]] = "train", "validation"
        assignments = pd.read_csv(output / "split_assignments.csv", parse_dates=["forecast_date"])
        _require(np.array_equal(assignments["row_id"], np.arange(n)), "Split row IDs differ")
        _require(np.array_equal(assignments["partition"], labels), "Exact split membership differs")
        _require(np.array_equal(assignments["session_number"], positions), "Split session identities differ")
        _require(pd.DatetimeIndex(assignments["forecast_date"]).equals(prices.index[positions]), "Split dates differ")
        checked = {}
        for name in ("train", "validation"):
            frame = pd.read_csv(output / f"{name}.csv", index_col="forecast_date",
                                parse_dates=["forecast_date", "target_start", "target_end"],
                                float_precision="round_trip")
            ids = np.flatnonzero(labels == name)
            pos = positions[ids]
            _require(frame.index.equals(prices.index[pos]), f"{name}: forecast dates differ")
            _require(np.array_equal(frame["row_id"], ids), f"{name}: row IDs differ")
            _require(np.array_equal(frame["session_number"], pos), f"{name}: session IDs differ")
            for col, offset in (("target_start", 1), ("target_end", 5)):
                _require(pd.DatetimeIndex(frame[col]).equals(prices.index[pos+offset]), f"{name}: {col} differs")
            expected = {"log_return": returns[pos],
                        "momentum_5": [sum(returns[p-4:p+1]) for p in pos],
                        "target": [np.std(returns[p+1:p+6], ddof=1) for p in pos]}
            for w in (5, 10, 20):
                expected[f"volatility_{w}"] = [np.std(returns[p-w+1:p+1], ddof=1) for p in pos]
            expected["baseline"] = expected["volatility_20"]
            for col, values in expected.items():
                _close(frame[col].to_numpy(), values, f"{name}: {col}")
            matrix = pd.read_csv(output / "data" / f"{name}_matrix.csv", index_col="forecast_date",
                                 parse_dates=["forecast_date"], float_precision="round_trip")
            _require(matrix.index.equals(frame.index), f"{name}: matrix dates differ")
            _require(list(matrix.columns) == [*FEATURE_COLUMNS, TARGET_COLUMN], "Predictor allowlist violated")
            _close(matrix.to_numpy(), model_frame(frame).to_numpy(), f"{name}: matrix")
            report["checked_rows"][name] = len(frame)
            checked[name] = frame
        pred = pd.read_csv(output / "validation_predictions.csv", index_col="forecast_date",
                           parse_dates=["forecast_date"], float_precision="round_trip")
        metrics = pd.read_csv(output / "validation_metrics.csv", float_precision="round_trip").set_index("model")
        _require(pred.index.equals(checked["validation"].index), "Predictions use different validation dates")
        _require(list(metrics.index) == list(MODEL_NAMES), "Comparison has missing or extra models")
        _close(pred[TARGET_COLUMN], checked["validation"]["target"], "Validation response")
        _close(pred["baseline"], checked["validation"]["volatility_20"], "Baseline")
        for name in MODEL_NAMES:
            values = pred[name].to_numpy()
            _require(np.isfinite(values).all() and (values >= 0).all(), "Invalid model predictions")
            errors = 100 * (values - pred[TARGET_COLUMN].to_numpy())
            for column, value in (("mae_pp", np.mean(np.abs(errors))),
                                  ("rmse_pp", np.sqrt(np.mean(errors**2))), ("bias_pp", np.mean(errors))):
                _close(metrics.loc[name, column], value, f"{name}: {column}")
            _require(metrics.loc[name, "n_forecasts"] == len(pred), "Unequal evaluation sample")
        report["checks"] = ["exact single-permutation membership, row identity and dates",
                            "all saved training and validation windows by independent NumPy slices",
                            "explicit predictor matrices and validation dates",
                            "all validation metrics by independent arithmetic; decimal-to-pp conversion"]
        report["passed"] = True
        return report
    except (ValueError, KeyError, TypeError, OSError) as error:
        report["error"] = str(error)
        raise CalculationVerificationError(report) from error


def run_pooled(config_path: Path, config: dict, *, offline=False) -> dict:
    from .pipeline import write_json
    root = config_path.parent.parent
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S") + "_pooled_" + uuid4().hex[:8]
    output = root / config["paths"]["output_dir"] / run_id
    output.mkdir(parents=True, exist_ok=False)
    packages = {dist.metadata["Name"]: dist.version for dist in distributions() if dist.metadata["Name"]}
    git_info = {}
    for label, args in (("commit", ["rev-parse", "HEAD"]), ("working_tree", ["status", "--short"])):
        try:
            result = subprocess.run(["git", "-c", f"safe.directory={root.as_posix()}", *args],
                                    cwd=root, capture_output=True, text=True, check=True)
            git_info[label] = result.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            git_info[label] = "unavailable"
    record = {"run_id": run_id, "started_at_utc": now.isoformat(), "status": "running",
              "config": config, "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
              "source_sha256": source_hashes(), "source_git": git_info, "package_versions": packages,
              "python": sys.version, "offline": offline, "final_test_evaluated": False,
              "reproduction_status": "Separate pooled run on original yfinance snapshot; newer research archive unavailable."}
    write_json(output / "run_record.json", record)
    source_dir = output / "source"
    source_dir.mkdir()
    for path in Path(__file__).parent.glob("*.py"):
        shutil.copy2(path, source_dir / path.name)
    shutil.copy2(config_path, source_dir / "experiment.toml")
    (output / "dependencies.txt").write_text("\n".join(f"{k}=={v}" for k, v in sorted(packages.items()))+"\n", encoding="utf-8")
    try:
        snapshot_dir = root / config["paths"]["snapshot_dir"]
        prices, metadata, audit = get_snapshot(config["data"], snapshot_dir, offline=offline)
        raw = pd.read_csv(snapshot_dir / "raw.csv", index_col="Date", parse_dates=["Date"], float_precision="round_trip")
        audit["raw_fields"] = audit_raw_fields(raw)
        write_json(output / "data_audit.json", audit)
        record["snapshot_sha256"], record["snapshot_metadata"] = metadata["sha256"], metadata
        examples = build_features(prices, **config["research"])
        settings = config["split"]
        examples = examples.loc[(examples.index >= settings["start"]) & (examples.index < settings["end"])]
        splits, summary = split_pooled(examples, **{k: settings[k] for k in ("seed", "train_fraction", "validation_fraction")})
        summary["construction"] = {
            "raw_price_rows": len(prices), "history_returns_required": 20,
            "initial_rows_without_complete_history": 20,
            "final_rows_without_complete_target": 5,
            "complete_rows_outside_forecast_period": len(build_features(prices, **config["research"]))-len(examples),
            "eligible_first_forecast": examples.index.min().date().isoformat(),
            "eligible_last_forecast": examples.index.max().date().isoformat(),
            "missing_session_prices_filled": 0, "extreme_returns_removed": 0,
        }
        write_json(output / "split_summary.json", summary)
        assignments = []
        for name, part in splits.items():
            identity = part[["row_id", "session_number", "target_start", "target_end"]].copy()
            identity["partition"] = name
            assignments.append(identity)
            destination = output / ("reserved" if name == "test" else "data")
            destination.mkdir(exist_ok=True)
            model_frame(part).to_csv(destination / f"{name}_matrix.csv", index_label="forecast_date")
            identity.to_csv(destination / f"{name}_metadata.csv", index_label="forecast_date")
            if name != "test":
                part.to_csv(output / f"{name}.csv", index_label="forecast_date")
        pd.concat(assignments).sort_values("row_id").to_csv(output / "split_assignments.csv", index_label="forecast_date")
        predictions, metric_table, model_record = compare_validation(splits["train"], splits["validation"])
        predictions.to_csv(output / "validation_predictions.csv", index_label="forecast_date")
        metric_table.to_csv(output / "validation_metrics.csv", index=False)
        write_json(output / "model_record.json", model_record)
        metrics = {"units": "daily-volatility percentage points", "validation": metric_table.to_dict("records"),
                   "final_test": "reserved; performance not computed"}
        write_json(output / "metrics.json", metrics)
        verification = verify_pooled(output, prices, config)
        write_json(output / "calculation_verification.json", verification)
        eda = write_training_eda(splits["train"], output)
        write_json(output / "eda_summary.json", eda)
        # The high-volatility threshold is learned from training only.
        threshold = splits["train"]["target"].quantile(.95)
        group = predictions.loc[predictions[TARGET_COLUMN] >= threshold]
        group_rows = [{"model": name, "threshold_decimal": threshold, "n_forecasts": len(group),
                       "bias_pp": float(100*(group[name]-group[TARGET_COLUMN]).mean()) if len(group) else None}
                      for name in MODEL_NAMES]
        pd.DataFrame(group_rows).to_csv(output / "tables" / "validation_high_volatility.csv", index=False)
        lines = ["# Pooled validation comparison", "", record["reproduction_status"], "",
                 "All errors are daily-volatility percentage points. Test is reserved and unscored.", "",
                 "| Model | N | MAE | RMSE | Bias |", "| --- | ---: | ---: | ---: | ---: |"]
        for row in metric_table.to_dict("records"):
            lines.append(f"| {row['model']} | {row['n_forecasts']} | {row['mae_pp']:.6f} | {row['rmse_pp']:.6f} | {row['bias_pp']:+.6f} |")
        lines += ["", "Random row separation does not prevent shared outcomes or future training information.",
                  "See split_summary.json for both overlap audits. Earlier history has been inspected.",
                  "The chronological pilot remains separate; its validation sample is not comparable directly."]
        (output / "results.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
        record.update(status="success", metrics=metrics, calculation_verification_passed=True)
        record["artifact_sha256"] = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(output.rglob("*")) if p.is_file() and p.name != "run_record.json"}
        return {"output_dir": str(output), "metrics": metrics, "snapshot_sha256": metadata["sha256"],
                "calculation_verification_passed": True, "report": str(output / "results.md")}
    except Exception as error:
        record.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
        if hasattr(error, "verification_report"):
            write_json(output / "calculation_verification.json", error.verification_report)
        if hasattr(error, "report"):
            write_json(output / "data_audit.json", error.report)
        (output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(output / "run_record.json", record)
