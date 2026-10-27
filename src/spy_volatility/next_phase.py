"""Offline orchestration for the preregistered retrospective development phase.

The saved pooled map is authoritative. Reserved responses are never loaded.
All new evidence has a new run directory; older experiments remain immutable.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import distributions
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import traceback
from uuid import uuid4

import numpy as np
import pandas as pd

from .data import get_snapshot, audit_raw_fields
from .diagnostics import write_diagnostics, error_metrics
from .models import FEATURE_COLUMNS, MODEL_NAMES, TARGET_COLUMN, model_frame
from .pooled import verify_pooled
from .provenance import source_hashes
from .research import build_features
from .temporal import (FIXED_PARAMETERS, _make_estimator, _prediction_rows,
                       validate_temporal_config, run_temporal_experiments)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def load_development(prices, pooled_dir: Path, pooled_record: dict, research: dict):
    """Recover saved membership, checking metadata without opening test matrices."""
    required = ("split_assignments.csv", "train.csv", "validation.csv",
                "validation_predictions.csv", "validation_metrics.csv", "model_record.json")
    hashes = {}
    for name in required:
        hashes[name] = sha(pooled_dir/name)
        if hashes[name] != pooled_record.get("artifact_sha256", {}).get(name):
            raise ValueError(f"Preserved pooled artifact hash mismatch: {name}")
    if (pooled_record.get("status") != "success" or pooled_record.get("final_test_evaluated") is not False
            or not pooled_record.get("calculation_verification_passed")):
        raise ValueError("Use a successful verified pooled source with test unscored")
    saved = pd.read_csv(pooled_dir/"split_assignments.csv", index_col="forecast_date",
                        parse_dates=["forecast_date", "target_start", "target_end"])
    full = build_features(prices, **research)
    full = full.loc[(full.index >= "2015-01-01") & (full.index < "2026-01-01")].copy()
    if not saved.index.equals(full.index) or not saved.index.is_unique:
        raise ValueError("Saved pooled identities differ from full-history eligible forecasts")
    if not np.array_equal(saved.row_id, np.arange(len(full))):
        raise ValueError("Saved row identities differ from the original eligible row positions")
    if set(saved.partition) != {"train", "validation", "test"}:
        raise ValueError("Pooled assignments must identify training, validation and reserved test")
    for column in ("session_number", "target_start", "target_end"):
        if not np.array_equal(saved[column].to_numpy(), full[column].to_numpy()):
            raise ValueError(f"Pooled membership metadata {column} differs from raw history")
    full["row_id"] = saved.row_id
    reserved = saved.loc[saved.partition == "test"].copy()
    development = full.loc[saved.partition != "test"].copy()
    if set(development.row_id) & set(reserved.row_id):
        raise AssertionError("Reserved row entered development data")
    verification = verify_pooled(pooled_dir, prices, pooled_record["config"])
    return development, saved, reserved, hashes, verification


def pooled_prediction_evidence(development, assignments, pooled_dir, output):
    """Retain original validation predictions; add clearly fitted training errors."""
    train = development.loc[assignments.partition == "train"]
    validation = development.loc[assignments.partition == "validation"]
    saved = pd.read_csv(pooled_dir/"validation_predictions.csv", index_col="forecast_date",
                        parse_dates=["forecast_date"], float_precision="round_trip")
    if not saved.index.equals(validation.index):
        raise ValueError("Saved pooled predictions have different validation identities")
    threshold = float(train.target.quantile(.95))
    observed = model_frame(train)
    fitted, evaluation, records = [], [], []
    for model in MODEL_NAMES:
        if model == "baseline":
            values = train.volatility_20.to_numpy()
        else:
            estimator = _make_estimator(model, deepcopy(FIXED_PARAMETERS[model]))
            estimator.fit(observed[list(FEATURE_COLUMNS)], observed[TARGET_COLUMN])
            values = np.maximum(estimator.predict(observed[list(FEATURE_COLUMNS)]), 0)
        for frame, prediction, partition, destination in (
            (train, values, "train", fitted),
            (validation, saved[model].to_numpy(), "evaluation", evaluation),
        ):
            rows = _prediction_rows(frame, prediction, fold="pooled", variant="fixed", model=model,
                                    threshold=threshold, partition=partition, fit_cutoff=pd.NaT)
            destination.append(rows)
        records.append({"model": model, "parameters": FIXED_PARAMETERS.get(model, {}),
                        "n_train": len(train), "threshold": threshold,
                        "training_status": "newly fitted training diagnostics on original training identities",
                        "validation_status": "original saved validation predictions, not regenerated"})
    fitted, evaluation = pd.concat(fitted, ignore_index=True), pd.concat(evaluation, ignore_index=True)
    fitted.to_csv(output/"pooled_training_predictions.csv", index=False)
    evaluation.to_csv(output/"pooled_validation_predictions.csv", index=False)
    write_json(output/"pooled_diagnostic_fit_record.json", records)
    return evaluation, fitted


def _git_record(root):
    result = {}
    for label, args in (("commit", ["rev-parse", "HEAD"]), ("working_tree", ["status", "--short"])):
        try:
            p = subprocess.run(["git", "-c", f"safe.directory={root.as_posix()}", *args], cwd=root,
                               capture_output=True, text=True, check=True)
            result[label] = p.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            result[label] = "unavailable"
    return result


def _hash_artifacts(output):
    return {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob("*"))
            if p.is_file() and p != output/"run_record.json"}


def run_next_phase(config_path: str | Path, *, offline=True):
    """Execute the declared sequence against existing immutable local evidence."""
    config_path = Path(config_path).resolve()
    with config_path.open("rb") as stream:
        config = tomllib.load(stream)
    validate_temporal_config(config)
    if config.get("experiment", {}).get("strategy") != "retrospective_temporal":
        raise ValueError("Expected retrospective_temporal experiment configuration")
    root = config_path.parent.parent
    pooled_dir = root/config["paths"]["pooled_run"]
    pooled_record = json.loads((pooled_dir/"run_record.json").read_text(encoding="utf-8"))
    for section in ("data", "research"):
        if config.get(section) != pooled_record["config"][section]:
            raise ValueError(f"Temporal {section} must preserve the designated pooled source")
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S")+"_temporal_"+uuid4().hex[:8]
    output = root/config["paths"]["output_dir"]/run_id
    output.mkdir(parents=True, exist_ok=False)
    record = {"run_id": run_id, "experiment": "retrospective_temporal", "status": "running",
              "started_at_utc": now.isoformat(), "config": config, "config_sha256": sha(config_path),
              "source_sha256": source_hashes(), "source_git": _git_record(root),
              "source_pooled_run_id": pooled_record["run_id"], "source_pooled_run_record_sha256": sha(pooled_dir/"run_record.json"),
              "final_test_evaluated": False, "reserved_rows_excluded": False,
              "package_versions": {d.metadata["Name"]: d.version for d in distributions() if d.metadata["Name"]},
              "python": sys.version, "offline": True,
              "question": "Do apparent pooled gains persist in retrospective annual development evaluation?",
              "intended_change": "Temporal evaluation, then preregistered comparator, tuning and group ablation",
              "limitations": ["Historical data reuse; not pristine final test", "Overlapping return windows remain dependent"]}
    write_json(output/"run_record.json", record)
    write_json(output/"preregistered_protocol.json", {"frozen_at_utc": now.isoformat(), "config": config,
                                                     "config_sha256": record["config_sha256"], "source_git": record["source_git"]})
    (output/"source").mkdir()
    for source in Path(__file__).parent.glob("*.py"):
        shutil.copy2(source, output/"source"/source.name)
    shutil.copy2(config_path, output/"source/experiment.toml")
    (output/"dependencies.txt").write_text("\n".join(f"{k}=={v}" for k,v in sorted(record["package_versions"].items()))+"\n")
    try:
        # This new experiment always requires the preserved snapshot, regardless
        # of CLI default; downloading a different dataset is outside its protocol.
        snapshot_dir = root/config["paths"]["snapshot_dir"]
        prices, metadata, audit = get_snapshot(config["data"], snapshot_dir, offline=True)
        if metadata["sha256"] != pooled_record["snapshot_sha256"]:
            raise ValueError("Snapshot differs from the source pooled experiment")
        raw = pd.read_csv(snapshot_dir/"raw.csv", index_col="Date", parse_dates=["Date"], float_precision="round_trip")
        audit["raw_fields"] = audit_raw_fields(raw)
        write_json(output/"data_audit.json", audit)
        record.update(snapshot_sha256=metadata["sha256"], snapshot_metadata=metadata)
        development, assignments, reserved, hashes, pooled_check = load_development(prices, pooled_dir, pooled_record, config["research"])
        record.update(source_pooled_artifact_sha256=hashes, reserved_rows_excluded=True,
                      n_development_rows=len(development), n_reserved_rows=len(reserved))
        write_json(output/"source_pooled_verification.json", pooled_check)
        development.to_csv(output/"development.csv", index_label="forecast_date")
        reserved.to_csv(output/"reserved_identities.csv", index_label="forecast_date")
        assignments.to_csv(output/"source_split_assignments.csv", index_label="forecast_date")
        write_json(output/"run_record.json", record)
        # Identity guard is copied to runtime config; it never contains outcomes.
        runtime_config = deepcopy(config)
        runtime_config["reserved_row_ids"] = reserved.row_id.astype(int).tolist()
        summary = run_temporal_experiments(development, prices.index, runtime_config, output)
        record["temporal_summary"] = summary
        predictions = pd.read_csv(output/"temporal_predictions.csv", parse_dates=["forecast_date"], float_precision="round_trip")
        training = pd.read_csv(output/"temporal_training_predictions.csv", parse_dates=["forecast_date"], float_precision="round_trip")
        pooled_predictions, pooled_training = pooled_prediction_evidence(development, assignments, pooled_dir, output)
        write_diagnostics(pooled_predictions, pooled_training, output, "pooled")
        write_diagnostics(predictions, training, output, "temporal")
        write_diagnostics(predictions.loc[predictions.variant == "fixed"],
                          training.loc[training.variant == "fixed"], output, "temporal_fixed")
        from .next_phase_verification import verify_next_phase
        verification = verify_next_phase(output, prices, config)
        write_json(output/"calculation_verification.json", verification)
        record.update(status="success", calculation_verification_passed=True)
        record["artifact_sha256"] = _hash_artifacts(output)
        write_json(output/"run_record.json", record)
        from .experiment_register import build_register
        register = build_register(root, output, selected_run_id=run_id)
        record["register"] = register
        record["artifact_sha256"] = _hash_artifacts(output)
        return {"run_id": run_id, "output_dir": str(output), "test_evaluated": False,
                "calculation_verification_passed": True, "metrics": summary["metrics"]}
    except Exception as error:
        record.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
        if hasattr(error, "verification_report"):
            write_json(output/"calculation_verification.json", error.verification_report)
        (output/"error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(output/"run_record.json", record)
