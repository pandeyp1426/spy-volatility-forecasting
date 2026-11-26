"""Offline release safeguards; fixtures contain only artificial development rows."""
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from spy_volatility.workflows import public_history as history


def stamp(raw):
    return hashlib.sha256(raw).hexdigest()


def test_allowlisted_record_and_table_hashes_fail_closed(tmp_path, monkeypatch):
    directory = tmp_path / "artifacts/runs" / history.TEMPORAL
    directory.mkdir(parents=True)
    manifest = {"run_id": history.TEMPORAL, "status": "success",
                "calculation_verification_passed": True, "final_test_evaluated": False,
                "reserved_rows_excluded": True, "finished_at_utc": "2026-10-27T00:00:00Z",
                "private": "never copy private metadata", "artifact_sha256": {}}
    for name in history.TABLES[history.TEMPORAL]:
        path = directory / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"a,b\n1,2\n")
        manifest["artifact_sha256"][name] = stamp(path.read_bytes())
    # A hash for an additional (absent) private table must never be dereferenced.
    manifest["artifact_sha256"]["test_reserved.csv"] = "0" * 64
    record = directory / "run_record.json"
    record.write_bytes(json.dumps(manifest).encode())
    monkeypatch.setitem(history.RECORD_HASH, history.TEMPORAL, stamp(record.read_bytes()))
    _, public_source, frames = history._run(tmp_path, history.TEMPORAL)
    assert len(frames) == 3 and len(public_source["files"]) == 3
    assert public_source["finished_at"] == manifest["finished_at_utc"]
    assert "private" not in json.dumps(public_source) and "test_reserved" not in json.dumps(public_source)
    table = directory / history.TABLES[history.TEMPORAL][0]
    table.write_bytes(b"a,b\n1,3\n")
    with pytest.raises(ValueError, match="digest mismatch"):
        history._run(tmp_path, history.TEMPORAL)
    record.write_bytes(record.read_bytes() + b" ")
    with pytest.raises(ValueError, match="digest mismatch for run_record.json"):
        history._run(tmp_path, history.TEMPORAL)


def test_retrospective_observation_projection_rejects_reserved_and_formal_data():
    common = {"forecast_date": "2020-01-02", "target_start": "2020-01-03",
              "target_end": "2020-01-09", "fit_cutoff": "2019-12-31",
              "fold": 2020, "row_id": 100, "session_number": 115, "threshold": .03,
              "observed": .013, "partition": "evaluation", "private_field": "PRIVATE"}
    rows = pd.DataFrame([{**common, "variant": v, "model": m, "prediction": p}
                         for (v, m), p in zip((history.METHODS[k] for k in ("ridge", "hv5", "hv20")),
                                               (.01, .015, .02), strict=True)])
    result, = history._observations(rows)
    assert result["observed"] == pytest.approx(1.3)
    assert result["ridge"] == pytest.approx(1.)
    assert result["ridge_signed"] == pytest.approx(-.3)
    assert result["ridge_absolute"] == pytest.approx(.3)
    assert not ({"threshold", "row_id", "session_number", "private_field"} & result.keys())
    with pytest.raises(ValueError, match="Reserved/test"):
        history._observations(rows.assign(partition="test_reserved"))
    with pytest.raises(ValueError, match="Unexpected forecast date"):
        history._observations(rows.assign(fold=2027, forecast_date="2027-01-04",
                                         target_start="2027-01-05", target_end="2027-01-11"))


def test_missing_historical_sources_have_no_silent_fallback(tmp_path):
    with pytest.raises(FileNotFoundError):
        history.load_history(tmp_path)


def test_adjusted_interval_is_distinct_from_nominal_interval():
    comparisons = pd.DataFrame([{"subset": "within_year", "block_length": 20,
        "metric": "rmse_pp", "variant": "fixed", "model": "ridge", "availability": "available",
        "primary_analysis": True, "reference_variant": v, "reference_model": m,
        "n_invalid": 0, "n_valid": 5000, "ci_lower": -.12, "ci_upper": -.02,
        "familywise_lower": -.15, "familywise_upper": .01, "estimate": -.07}
        for v, m in (history.METHODS["hv20"], history.METHODS["hv5"])])
    record = {"config": {"uncertainty": {"n_resamples": 5000, "primary_block_length": 20}},
              "n_contained_forecasts": 75}
    summary = history._uncertainty(record, comparisons)
    assert summary["intervals"] == [{"method": m, "lower": -.15, "upper": .01, "estimate": -.07}
                                    for m in ("hv20", "hv5")]
    with pytest.raises(ValueError, match="draws incomplete"):
        history._uncertainty(record, comparisons.assign(n_valid=4999, n_invalid=1))


def test_published_reference_values_when_evidence_is_available():
    root = Path(__file__).resolve().parents[2]
    if not (root / "artifacts" / "runs" / history.TEMPORAL / "run_record.json").exists():
        pytest.skip("The designated historical evidence is local to the trusted exporter")
    report = history.load_history(root)
    assert [r["n"] for r in report["sensitivity"]] == [1272, 1252, 254, 249]
    assert [round(r["rmse"], 6) for r in report["performance"]] == [
        .661175, .723675, .764881, .793810, .804137]
    assert [round(r["vs5"], 2) for r in report["offsets"]] == [4.42, 13.76, 8.64, 7.51, 9.29]
    rows = report["observations"]
    assert len(rows) == len({r["date"] for r in rows}) == 1272
    for method in ("ridge", "hv5", "hv20"):
        rmse = math.sqrt(math.fsum(row[method + "_signed"] ** 2 for row in rows) / len(rows))
        assert rmse == pytest.approx(next(r["rmse"] for r in report["performance"] if r["method"] == method))
    assert report["uncertainty"]["intervals"][1]["lower"] < 0 < report["uncertainty"]["intervals"][1]["upper"]
