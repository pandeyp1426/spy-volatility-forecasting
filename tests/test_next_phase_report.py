"""Report inputs must match their named evidence and scientific narrative."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tomllib

import pytest

from spy_volatility.next_phase_report import (
    sha, validate_development, validate_pooled_narrative,
)
from spy_volatility.temporal import FIXED_PARAMETERS


@pytest.fixture
def report_evidence(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "configs/temporal.toml").read_text())
    pooled = tmp_path / "pooled"
    development = tmp_path / "development"
    pooled.mkdir()
    development.mkdir()
    parent = {"run_id": "saved-parent", "snapshot_sha256": "frozen-snapshot"}
    (pooled / "run_record.json").write_text(json.dumps(parent))
    protocol = deepcopy(config)
    protocol["reserved_row_ids"] = [2, 7]
    (development / "temporal_protocol.json").write_text(json.dumps(protocol))
    summary = {key: config["temporal"][key] for key in
               ("outer_years", "selection_metric", "tie_break", "high_volatility_quantile")}
    summary.update(status="complete", test_scored=False,
                   protocol_sha256=hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    (development / "temporal_summary.json").write_text(json.dumps(summary))
    (development / "evidence.csv").write_text("row_id,prediction\n1,0.01\n")
    record = {
        "status": "success", "experiment": "retrospective_temporal",
        "final_test_evaluated": False, "reserved_rows_excluded": True,
        "calculation_verification_passed": True, "config": config,
        "source_pooled_run_id": parent["run_id"],
        "source_pooled_run_record_sha256": sha(pooled / "run_record.json"),
        "snapshot_sha256": parent["snapshot_sha256"],
        "artifact_sha256": {
            name: sha(development / name)
            for name in ("evidence.csv", "temporal_protocol.json", "temporal_summary.json")
        },
    }
    (development / "run_record.json").write_text(json.dumps(record))
    return development, pooled, parent, record


def test_development_report_accepts_matched_provenance_without_reserved_file(report_evidence):
    development, pooled, parent, record = report_evidence
    # No reserved feature/response matrix exists in this fixture.
    assert validate_development(development, pooled, parent) == record


@pytest.mark.parametrize("key,value", [
    ("source_pooled_run_id", "another-parent"),
    ("source_pooled_run_record_sha256", "changed-source"),
    ("snapshot_sha256", "new-download"),
    ("status", "failed"),
    ("final_test_evaluated", True),
    ("reserved_rows_excluded", False),
    ("calculation_verification_passed", False),
])
def test_development_report_rejects_mismatched_or_unverified_run(report_evidence, key, value):
    development, pooled, parent, record = report_evidence
    record[key] = value
    (development / "run_record.json").write_text(json.dumps(record))
    with pytest.raises(ValueError):
        validate_development(development, pooled, parent)


def test_development_report_rejects_tampered_prediction_evidence(report_evidence):
    development, pooled, parent, _ = report_evidence
    (development / "evidence.csv").write_text("row_id,prediction\n1,0.02\n")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        validate_development(development, pooled, parent)


def test_development_report_rejects_protocol_drift_even_with_updated_hash(report_evidence):
    development, pooled, parent, record = report_evidence
    path = development / "temporal_protocol.json"
    protocol = json.loads(path.read_text())
    protocol["temporal"]["selection_metric"] = "mae_pp"
    path.write_text(json.dumps(protocol))
    record["artifact_sha256"][path.name] = sha(path)
    (development / "run_record.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="protocol differs"):
        validate_development(development, pooled, parent)


def test_development_report_rejects_artifact_outside_run(report_evidence):
    development, pooled, parent, record = report_evidence
    record["artifact_sha256"]["../outside.csv"] = "not-read"
    (development / "run_record.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="path leaves run"):
        validate_development(development, pooled, parent)


@pytest.fixture
def pooled_narrative():
    config = tomllib.loads((Path(__file__).resolve().parents[1] / "configs/pooled.toml").read_text())
    model = {
        "model_parameters": deepcopy(FIXED_PARAMETERS), "prediction_floor": 0,
        "feature_columns": ["log_return", "volatility_5", "volatility_10", "volatility_20", "momentum_5"],
        "response_column": "future_volatility_5d", "test_scored": False,
        "ridge_scaler": {"fit_partition": "train"},
    }
    return {"config": config}, model, {"row_ids_disjoint": True, "exhaustive": True}, {"passed": True, "raw_fields": {"passed": True}}


def test_pooled_report_accepts_original_protocol(pooled_narrative):
    validate_pooled_narrative(*pooled_narrative)


@pytest.mark.parametrize("change", ["seed", "fraction", "window", "model", "scaler", "feature"])
def test_pooled_report_rejects_stale_fixed_scientific_prose(pooled_narrative, change):
    record, model, summary, audit = pooled_narrative
    if change == "seed":
        record["config"]["split"]["seed"] = 43
    elif change == "fraction":
        record["config"]["split"]["train_fraction"] = .8
    elif change == "window":
        record["config"]["research"]["horizon"] = 10
    elif change == "model":
        model["model_parameters"]["ridge"]["alpha"] = 100
    elif change == "scaler":
        model["ridge_scaler"]["fit_partition"] = "validation"
    else:
        model["feature_columns"].append("session_number")
    with pytest.raises(ValueError):
        validate_pooled_narrative(record, model, summary, audit)
