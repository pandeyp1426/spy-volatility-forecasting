"""Offline integration checks; generated observations are artificial test fixtures."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import pytest

from spy_volatility.data import DownloadError
from spy_volatility.pipeline import load_config, run_phase1
from spy_volatility.verification import CalculationVerificationError, verify_saved_calculations


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


@pytest.mark.parametrize("horizon", [5, 3])
def test_complete_pipeline_saves_only_validation_scores(short_config, monkeypatch, horizon):
    if horizon == 3:
        text = short_config.read_text(encoding="utf-8")
        for old, new in [("windows = [5, 10, 20]", "windows = [3, 7]"), ("horizon = 5", "horizon = 3"),
                         ("baseline_window = 20", "baseline_window = 7"), ("momentum_window = 5", "momentum_window = 2")]:
            text = text.replace(old, new)
        short_config.write_text(text, encoding="utf-8")
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
    assert summary["partitions"]["train"]["n_purged"] == horizon
    assert summary["partitions"]["validation"]["n_purged"] == horizon
    assert (output / "test_reserved.csv").exists()
    assert (output / "training_history.png").stat().st_size > 1000
    assert (output / "validation_baseline.png").stat().st_size > 1000
    examples = pd.read_csv(output / "features.csv", parse_dates=["forecast_date"])
    assert examples["forecast_date"].min() >= pd.Timestamp(config["split"]["train_start"])

    def forbidden(**kwargs):
        pytest.fail("A repeat experiment must reuse its snapshot without network access")

    monkeypatch.setattr("spy_volatility.data.yf.download", forbidden)
    second = run_phase1(short_config, offline=True)
    assert second["output_dir"] != first["output_dir"]
    assert second["snapshot_sha256"] == first["snapshot_sha256"]
    assert second["metrics"] == first["metrics"]
    assert second["calculation_verification_passed"] is True
    verification = json.loads((output / "calculation_verification.json").read_text(encoding="utf-8"))
    assert verification["checked_rows"] == {
        name: summary["partitions"][name]["n_after_purge"] for name in ("train", "validation")
    }
    assert Path(first["report"]).is_file()


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


@pytest.mark.parametrize("corruption", ["feature", "target_date", "missing_row", "sampling_offset", "metric"])
def test_corrupted_saved_results_fail_independent_verification(short_config, monkeypatch, corruption):
    """Catch realistic errors even if a faulty calculation would otherwise finish."""
    config = load_config(short_config)
    dates = mcal.get_calendar("NYSE").schedule(
        config["data"]["start"], pd.Timestamp(config["data"]["end"]) - pd.Timedelta(days=1)
    ).index
    prices = pd.Series(100 * np.exp(np.cumsum(0.01 * np.sin(np.arange(len(dates))))), index=dates)
    monkeypatch.setattr("spy_volatility.data.yf.download", lambda **kwargs: prices.to_frame("Adj Close"))

    def corrupt_then_verify(output, raw_prices, actual_config, metrics):
        if corruption == "metric":
            metrics["validation_daily"]["mae_pp"] *= 100  # accidental double percent conversion
            (output / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        else:
            filename = "train.csv" if corruption == "feature" else "validation.csv"
            if corruption == "sampling_offset":
                daily = pd.read_csv(output / "validation_predictions.csv")
                daily.iloc[1::config["research"]["horizon"]].to_csv(
                    output / "validation_nonoverlapping_predictions.csv", index=False
                )
            else:
                frame = pd.read_csv(output / filename)
                if corruption == "feature":
                    frame.loc[0, "volatility_5"] *= 1.1
                elif corruption == "target_date":
                    frame.loc[0, "target_start"] = frame.loc[0, "forecast_date"]
                else:
                    frame = frame.iloc[1:]
                frame.to_csv(output / filename, index=False)
        return verify_saved_calculations(output, raw_prices, actual_config, metrics)

    monkeypatch.setattr("spy_volatility.pipeline.verify_saved_calculations", corrupt_then_verify)
    with pytest.raises(CalculationVerificationError):
        run_phase1(short_config)
    output = next((short_config.parent.parent / "artifacts" / "runs").iterdir())
    record = json.loads((output / "run_record.json").read_text(encoding="utf-8"))
    verification = json.loads((output / "calculation_verification.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert verification["passed"] is False
    assert verification["error"]
    assert not (output / "results.md").exists()
