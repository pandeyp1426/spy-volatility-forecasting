"""Hand-calculated report checks using artificial validation observations."""

import math

import pandas as pd
import pytest

from spy_volatility.reporting import write_results_report


@pytest.fixture
def report_inputs(tmp_path):
    # Forecast errors in percentage points: 2022 [1, -2], 2023 [0.5, 0.5].
    pd.DataFrame({
        "forecast_date": ["2022-12-28", "2022-12-29", "2023-01-03", "2023-01-04"],
        "baseline": [0.02, 0.01, 0.01, 0.02],
        "target": [0.01, 0.03, 0.005, 0.015],
    }).to_csv(tmp_path / "validation_predictions.csv", index=False)
    return {
        "output": tmp_path,
        "run_id": "artificial-report-test",
        "config": {"research": {"horizon": 3, "baseline_window": 7},
                   "paths": {"snapshot_dir": "data/raw/artificial"}},
        "metadata": {"sha256": "artificial-snapshot-reference",
                     "actual_date_range": {"start": "2021-01-01T00:00:00", "end": "2024-12-31T00:00:00"}},
        "audit": {"passed": True, "row_count": 100},
        "summary": {"partitions": {
            name: {"first_forecast_date": first, "last_forecast_date": last,
                   "n_after_purge": count, "n_purged": purged}
            for name, first, last, count, purged in [
                ("train", "2021-01-20", "2021-12-20", 7, 3),
                ("validation", "2022-12-28", "2023-01-04", 4, 3),
                ("test", "2024-01-02", "2024-12-20", 9, 0),
            ]
        }},
        "metrics": {
            "validation_daily": {"n_forecasts": 4, "mae_pp": 1.0, "rmse_pp": math.sqrt(1.375)},
            "validation_nonoverlapping": {"n_forecasts": 2, "mae_pp": 0.75, "rmse_pp": math.sqrt(0.625)},
            "nonoverlapping_anchor": "2022-12-28",
        },
        "verification": {"passed": True, "checked_rows": {"train": 7, "validation": 4},
                         "checks": ["Artificial fixture checks"], "rtol": 1e-9, "atol": 1e-12},
    }


def test_report_annual_diagnostics_and_configured_windows(report_inputs, monkeypatch):
    original_read = pd.read_csv

    def validation_only(path, *args, **kwargs):
        assert path.name == "validation_predictions.csv", "Reports may only read validation predictions."
        return original_read(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(pd, "read_csv", validation_only)
        path = write_results_report(**report_inputs)
    annual = pd.read_csv(path.parent / "validation_by_year.csv").set_index("year")
    assert annual.index.tolist() == [2022, 2023]
    assert annual["n_forecasts"].tolist() == [2, 2]
    assert annual.loc[2022, "mae_pp"] == pytest.approx(1.5)
    assert annual.loc[2022, "rmse_pp"] == pytest.approx(math.sqrt(2.5))
    assert annual.loc[2022, "bias_pp"] == pytest.approx(-0.5)
    assert annual.loc[2023, ["mae_pp", "rmse_pp", "bias_pp"]].tolist() == pytest.approx([0.5, 0.5, 0.5])
    report = path.read_text(encoding="utf-8")
    for text in (
        "last 7 daily returns", "next 3 trading sessions", "Every 3 trading sessions",
        "daily-volatility percentage points", "7 training rows and 4 validation rows",
        "Reserved; performance not computed", "artificial-snapshot-reference",
        "training_history.png", "validation_baseline.png", "not a model-selection rule",
    ):
        assert text in report


@pytest.mark.parametrize("failed_check", ["audit", "verification"])
def test_report_requires_passing_checks(report_inputs, failed_check):
    report_inputs[failed_check]["passed"] = False
    with pytest.raises(ValueError, match="passing data audit"):
        write_results_report(**report_inputs)
    assert not (report_inputs["output"] / "results.md").exists()
    assert not (report_inputs["output"] / "validation_by_year.csv").exists()
