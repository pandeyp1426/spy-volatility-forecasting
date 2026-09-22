"""Offline integration checks; generated observations are artificial test fixtures."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import pytest

from spy_volatility.data import DownloadError
from spy_volatility.pipeline import load_config, run_phase1


@pytest.fixture
def short_config(tmp_path):
    config_path = tmp_path / "configs" / "phase1.toml"
    config_path.parent.mkdir()
    original = Path(__file__).resolve().parents[1] / "configs" / "phase1.toml"
    text = original.read_text(encoding="utf-8")
    for old, new in [
        ('start = "2014-11-01"', 'start = "2021-11-01"'),
        ('end = "2026-01-01"', 'end = "2022-07-01"'),
        ('train_start = "2015-01-01"', 'train_start = "2022-01-01"'),
        ('validation_start = "2022-01-01"', 'validation_start = "2022-03-01"'),
        ('test_start = "2024-01-01"', 'test_start = "2022-05-01"'),
    ]:
        text = text.replace(old, new)
    config_path.write_text(text, encoding="utf-8")
    return config_path


def test_complete_pipeline_saves_only_validation_scores(short_config, monkeypatch):
    config = load_config(short_config)
    dates = mcal.get_calendar("NYSE").schedule(
        config["data"]["start"], pd.Timestamp(config["data"]["end"]) - pd.Timedelta(days=1)
    ).index
    prices = pd.Series(100 * np.exp(np.cumsum(0.01 * np.sin(np.arange(len(dates))))), index=dates)
    monkeypatch.setattr("spy_volatility.data.yf.download", lambda **kwargs: prices.to_frame("Adj Close"))
    first = run_phase1(short_config)
    output = Path(first["output_dir"])
    record = json.loads((output / "run_record.json").read_text(encoding="utf-8"))
    metrics = first["metrics"]
    assert record["status"] == "success"
    assert record["final_test_evaluated"] is False
    assert metrics["final_test"] == "reserved; performance not computed"
    summary = json.loads((output / "split_summary.json").read_text(encoding="utf-8"))
    assert metrics["validation_daily"]["n_forecasts"] == summary["partitions"]["validation"]["n_after_purge"]
    assert summary["partitions"]["train"]["n_purged"] == 5
    assert summary["partitions"]["validation"]["n_purged"] == 5
    assert (output / "test_reserved.csv").exists()
    assert (output / "training_history.png").stat().st_size > 1000
    assert (output / "validation_baseline.png").stat().st_size > 1000
    examples = pd.read_csv(output / "features.csv", parse_dates=["forecast_date"])
    assert examples["forecast_date"].min() >= pd.Timestamp(config["split"]["train_start"])

    def forbidden(**kwargs):
        pytest.fail("A repeat experiment must reuse its snapshot without network access")

    monkeypatch.setattr("spy_volatility.data.yf.download", forbidden)
    second = run_phase1(short_config)
    assert second["output_dir"] != first["output_dir"]
    assert second["snapshot_sha256"] == first["snapshot_sha256"]
    assert second["metrics"] == first["metrics"]


def test_failed_download_records_actual_error_without_results(short_config, monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError("Artificial test fixture: network unavailable")

    monkeypatch.setattr("spy_volatility.data.yf.download", unavailable)
    with pytest.raises(DownloadError, match="network unavailable"):
        run_phase1(short_config)
    output = next((short_config.parent.parent / "artifacts" / "runs").iterdir())
    record = json.loads((output / "run_record.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert "network unavailable" in record["error"]["message"]
    assert not (output / "metrics.json").exists()
    assert not (output / "features.csv").exists()
