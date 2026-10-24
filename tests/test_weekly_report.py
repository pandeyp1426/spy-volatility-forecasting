"""Fail closed before rendering unverified or test-scored report inputs."""
import json
from pathlib import Path

import pytest

from spy_volatility.weekly_report import prepare_report


@pytest.mark.parametrize("change", [{"status": "failed"}, {"final_test_evaluated": True},
                                   {"calculation_verification_passed": False}])
def test_report_rejects_unverified_or_scored_run(tmp_path, change):
    record = {"status": "success", "final_test_evaluated": False,
              "calculation_verification_passed": True,
              "config": {"split": {"strategy": "pooled_random"}}}
    record.update(change)
    (tmp_path/"run_record.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="test unscored"):
        prepare_report(tmp_path, tmp_path, "2026-10-24")
    assert not (tmp_path/"output").exists()


def test_report_rejects_modified_metrics_before_creating_output(tmp_path):
    record = {"status": "success", "final_test_evaluated": False,
              "calculation_verification_passed": True,
              "config": {"split": {"strategy": "pooled_random", "start": "2015-01-01", "end": "2026-01-01"},
                         "data": {"start": "2014-11-01", "end": "2026-01-01"}},
              "artifact_sha256": {"validation_metrics.csv": "not-the-file-hash"}}
    (tmp_path/"run_record.json").write_text(json.dumps(record))
    (tmp_path/"validation_metrics.csv").write_text("altered metrics")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        prepare_report(tmp_path, tmp_path, "2026-10-24")
    assert not (tmp_path/"output").exists()
