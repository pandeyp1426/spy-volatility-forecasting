"""Inventory completeness, honest missing evidence and reserved-file protection."""
import hashlib
import json
from pathlib import Path

import pandas as pd

from spy_volatility.experiment_register import build_register


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_registry_preserves_all_statuses_missing_artifacts_and_omits_circular_hash(tmp_path):
    root = tmp_path
    output = root / "artifacts/runs/selected"
    record = {"run_id": "selected", "status": "success", "final_test_evaluated": False,
              "config": {"split": {"strategy": "pooled_random", "seed": 42}},
              "snapshot_sha256": "frozen-data-hash", "source_git": {"commit": "abc", "working_tree": ""},
              "metrics": {"validation": [{"model": "ridge", "rmse_pp": .5}], "final_test": "reserved"},
              "artifact_sha256": {"missing.csv": "historical-missing-hash"}}
    save_json(output / "run_record.json", record)
    save_json(root / "artifacts/runs/failed/run_record.json", {"run_id": "failed", "status": "failed", "error": {"message": "fixture failure"}})
    save_json(root / "artifacts/runs/old/run_record.json", {"run_id": "old", "status": "success", "superseded_by": "selected"})
    (root / "artifacts/runs/interrupted").mkdir()
    old_bytes = (root / "artifacts/runs/old/run_record.json").read_bytes()
    summary = build_register(root, output, "selected")
    register = json.loads(Path(summary["register"]).read_text())
    runs = {entry["run_id"]: entry for entry in register["runs"]}
    assert set(runs) == {"selected", "failed", "old", "interrupted"}
    assert runs["selected"]["role"] == "selected"
    assert runs["failed"]["role"] == "failed" and "fixture failure" in runs["failed"]["interpretation"]
    assert runs["old"]["role"] == "superseded"
    assert runs["interrupted"]["status"] == "record missing"
    assert runs["interrupted"]["evidence_missing"]
    assert "final_test" not in runs["selected"]["results"]
    index = pd.read_csv(summary["artifact_index"], keep_default_na=False).set_index("path")
    selected = index.loc["artifacts/runs/selected/run_record.json"]
    assert selected.sha256 == "" and "self-referential" in selected.hash_status
    missing = index.loc["artifacts/runs/selected/missing.csv"]
    assert missing.availability == "missing"
    assert missing.sha256 == "historical-missing-hash"
    assert not any(Path(path).name in {"experiment_register.json", "artifact_index.csv"} for path in index.index)
    assert (root / "artifacts/runs/old/run_record.json").read_bytes() == old_bytes


def test_reserved_contents_never_opened_even_for_hashing_and_no_recursive_index(tmp_path, monkeypatch):
    output = tmp_path / "artifacts/runs/one"
    reserved = output / "reserved/test_matrix.csv"
    reserved.parent.mkdir(parents=True)
    reserved.write_text("DO NOT OPEN", encoding="utf-8")
    old_reserved = output / "test_reserved.csv"
    old_reserved.write_text("DO NOT OPEN", encoding="utf-8")
    save_json(output / "run_record.json", {"run_id": "one", "status": "success",
        "artifact_sha256": {"reserved/test_matrix.csv": "recorded-hash"}})
    original = Path.read_bytes

    def protect(path):
        assert path not in (reserved, old_reserved), "Reserved data must not be opened for inventory"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", protect)
    first = build_register(tmp_path, output, "one")
    second = build_register(tmp_path, output, "one")
    assert first["artifact_count"] == second["artifact_count"]
    index = pd.read_csv(second["artifact_index"], keep_default_na=False).set_index("path")
    item = index.loc["artifacts/runs/one/reserved/test_matrix.csv"]
    assert item.sha256 == "recorded-hash"
    assert "not opened" in item.hash_status
    assert item.availability == "present; unscored and unread"


def test_snapshot_builds_and_missing_external_reference_have_honest_evidence(tmp_path):
    save_json(tmp_path / "report/historical/source_manifest.json", {"archive": "pilot.zip", "archive_sha256": "pilot-hash"})
    save_json(tmp_path / "report/historical/handoff_reference.json", {"archive_available": False,
        "raw_csv_sha256": "different-snapshot", "validation": {"ridge": {"rmse_pp": .63}}})
    raw = tmp_path / "data/raw/frozen/raw.csv"
    raw.parent.mkdir(parents=True)
    raw.write_text("Date,Adj Close\n2020-01-02,100\n", encoding="utf-8")
    build = tmp_path / "output/pdf/builds/edition"
    save_json(build / "build_record.json", {"run_id": "selected", "status": "compiled",
        "report_date": "2026-10-26", "visual_review": "passed", "compiler_command": ["tectonic", "main.tex"]})
    (build / "main.pdf").write_bytes(b"%PDF-fixture")
    summary = build_register(tmp_path, tmp_path / "register")
    register = json.loads(Path(summary["register"]).read_text())
    assert summary["build_count"] == 1
    assert register["builds"][0]["visual_review"] == "passed"
    reference = next(run for run in register["runs"] if run["role"] == "missing reference")
    assert reference["status"] == "unavailable exact reproduction"
    assert reference["results"] == {"rounded_reference_only": {"ridge": {"rmse_pp": .63}}}
    assert reference["evidence_missing"]
    index = pd.read_csv(summary["artifact_index"], keep_default_na=False).set_index("path")
    assert index.loc["data/raw/frozen/raw.csv", "sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert index.loc["artifacts/source_materials/SPY_EDA_Research_Package.zip", "availability"] == "missing"
    assert index.loc["output/pdf/builds/edition/main.pdf", "run_id"] == "selected"


def test_temporal_schema_preserves_actual_results_parameters_and_question(tmp_path):
    output = tmp_path / "artifacts/runs/temporal"
    scores = [{"variant": "fixed", "model": "ridge", "n_forecasts": 3, "rmse_pp": .123456789}]
    save_json(output / "run_record.json", {"run_id": "temporal", "status": "success",
        "question": "Do pooled improvements persist temporally?", "source_pooled_run_id": "original_pooled",
        "config": {"fixed": {"ridge": {"alpha": 1.}}, "search": {"ridge": {"alpha": [.1, 1.]}},
                   "temporal": {"outer_years": [2020, 2021]}},
        "temporal_summary": {"metrics": scores, "metric_units": "daily-volatility percentage points"}})
    save_json(output / "model_records.json", [{"model": "ridge", "parameters": {"alpha": 1.}}])
    save_json(output / "chosen_parameters.json", [{"outer_fold": 2020, "model": "ridge", "parameters": {"alpha": .1}}])
    report_source = tmp_path / "report/main.tex"
    report_source.parent.mkdir(parents=True)
    report_source.write_text("Report source", encoding="utf-8")
    result = build_register(tmp_path, output, "temporal")
    register = json.loads(Path(result["register"]).read_text())
    run = register["runs"][0]
    assert run["research_question"] == "Do pooled improvements persist temporally?"
    assert run["parent_run"] == "original_pooled"
    assert run["results"]["temporal_development"] == scores
    assert not any("Saved metrics" in missing for missing in run["evidence_missing"])
    assert run["model_settings"]["chosen_parameters"][0]["parameters"]["alpha"] == .1
    index = pd.read_csv(result["artifact_index"])
    assert "report/main.tex" in set(index.path)
