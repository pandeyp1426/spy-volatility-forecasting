import math
import numpy as np
import pandas as pd
import pytest

from spy_volatility.core.outcomes import aggregate_errors, forecast_errors, realized_volatility


def forecast(origin, target_start):
    return {"forecast_session": origin, "target_sessions": pd.bdate_range(target_start, periods=5).strftime("%Y-%m-%d").tolist(),
            "predictions": {"ridge": .01, "baseline": .02, "baseline_5": .03}}


def test_sample_target_mean_and_error_units():
    dates = pd.bdate_range("2026-11-11", periods=6)
    r = np.array([.01, -.02, .03, -.01, .005])
    prices = pd.Series(500 * np.exp(np.r_[0, np.cumsum(r)]), index=dates)
    close = pd.Timestamp("2026-11-18T21:00Z")
    target = realized_volatility(prices, dates, close, close + pd.Timedelta(minutes=1))
    expected = math.sqrt(sum((x - sum(r)/5)**2 for x in r)/4)
    assert target["observed_volatility"] == pytest.approx(expected)
    assert target["future_mean_return"] == pytest.approx(sum(r)/5)
    f = forecast("2026-11-11", "2026-11-12")
    errors = forecast_errors(f, expected, close + pd.Timedelta(minutes=1))
    for name in f["predictions"]:
        error = 100 * (f["predictions"][name] - expected)
        assert errors["errors"][name] == pytest.approx({"signed_error_pp": error,
            "absolute_error_pp": abs(error), "squared_error_pp2": error**2})


def test_common_sample_metrics_use_all_errors_not_average_group_rmse():
    cases = [{"forecast": forecast("2026-11-11", "2026-11-12"), "observed": .01},
             {"forecast": forecast("2026-11-12", "2026-11-13"), "observed": .05}]
    result = aggregate_errors(cases, "pilot_2026", pd.Timestamp("2026-12-01T00:00Z"))
    ridge = result["metrics"]["ridge"]
    assert ridge == pytest.approx({"n": 2, "mae_pp": 2., "mse_pp2": 8., "rmse_pp": math.sqrt(8), "bias_pp": -2.})
    assert ridge["rmse_pp"] != 2.  # Averaging per-origin/group RMSE would be wrong.
    with pytest.raises(ValueError, match="Duplicate"):
        aggregate_errors([cases[0], cases[0]], "pilot_2026", pd.Timestamp("2026-12-01T00:00Z"))


def test_formal_aggregate_gate_precedes_reading_outcomes_and_blocks_mixed_samples():
    class Unreadable(list):
        def __iter__(self):
            pytest.fail("Premature comparison touched its cases")
    with pytest.raises(ValueError, match="embargoed"):
        aggregate_errors(Unreadable(), "formal_2027", pd.Timestamp("2028-01-10T05:59:59Z"))
    case = {"forecast": forecast("2027-01-04", "2027-01-05"), "observed": .01}
    with pytest.raises(ValueError, match="mixed"):
        aggregate_errors([case], "pilot_2026", pd.Timestamp("2027-02-01T00:00Z"))
    assert aggregate_errors([], "formal_2027", pd.Timestamp("2028-01-10T06:00Z"))["metrics"]["ridge"]["rmse_pp"] is None


@pytest.mark.parametrize("bad", ["premature", "missing", "wrong_window", "future_extra"])
def test_target_maturity_and_membership_are_required(bad):
    dates = pd.bdate_range("2026-11-11", periods=6)
    prices = pd.Series([500., 501., 499., 503., 502., 505.], index=dates)
    close = pd.Timestamp("2026-11-18T21:00Z")
    now = close + pd.Timedelta(minutes=1)
    if bad == "premature":
        now = close
    elif bad == "missing":
        prices = prices.iloc[:-1]
    elif bad == "wrong_window":
        prices.index = prices.index + pd.Timedelta(days=1)
    else:
        prices = pd.concat([prices, pd.Series([505.], index=[pd.Timestamp("2026-11-19")])])
    with pytest.raises(ValueError):
        realized_volatility(prices, dates, close, now)
