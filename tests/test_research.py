"""Artificial prices below are calculation fixtures, never empirical results."""

import numpy as np
import pandas as pd
import pytest

from spy_volatility.research import (
    build_features,
    evaluate_predictions,
    nonoverlapping_predictions,
    split_examples,
    validation_predictions,
)


def artificial_prices(count=80, start="2021-11-01"):
    dates = pd.bdate_range(start, periods=count)
    positions = np.arange(1, count, dtype=float)
    # Vary the magnitudes so shifting a window incorrectly changes its std.
    returns = 0.01 * np.sin(positions / 3.0) + positions / 100000.0
    prices = pd.Series(100.0 * np.exp(np.r_[0.0, np.cumsum(returns)]), index=dates)
    return prices, returns


def test_hand_calculated_sample_standard_deviation():
    # Three observations 0.01, 0.02, 0.03 have mean 0.02 and sample std 0.01.
    returns = np.array([0.01, 0.02, 0.03, -0.01, 0.01, 0.03])
    prices = pd.Series(100.0 * np.exp(np.r_[0.0, np.cumsum(returns)]),
                       index=pd.bdate_range("2020-01-02", periods=7))
    row = build_features(prices, windows=(3,), horizon=3,
                         momentum_window=3, baseline_window=3).iloc[0]
    assert row["baseline"] == pytest.approx(0.01)
    assert row["volatility_3"] == pytest.approx(0.01)
    assert row["target"] == pytest.approx(0.02)


def test_sample_standard_deviation_and_exact_alignment():
    prices, returns = artificial_prices()
    examples = build_features(prices)
    row = examples.loc[prices.index[20]]
    assert row["log_return"] == pytest.approx(returns[19])
    assert row["volatility_5"] == pytest.approx(np.std(returns[15:20], ddof=1))
    assert row["volatility_10"] == pytest.approx(np.std(returns[10:20], ddof=1))
    assert row["volatility_20"] == pytest.approx(np.std(returns[:20], ddof=1))
    assert row["baseline"] == pytest.approx(np.std(returns[:20], ddof=1))
    assert row["momentum_5"] == pytest.approx(np.sum(returns[15:20]))
    assert row["target"] == pytest.approx(np.std(returns[20:25], ddof=1))
    assert row["target_start"] == prices.index[21]
    assert row["target_end"] == prices.index[25]
    assert row["session_number"] == 20


def test_incomplete_history_and_final_five_observations_are_excluded():
    prices, _ = artificial_prices(count=40)
    examples = build_features(prices)
    assert examples.index.equals(prices.index[20:-5].rename("forecast_date"))
    assert len(examples) == 15
    assert not examples.isna().any().any()
    with pytest.raises(ValueError, match="No complete examples"):
        build_features(prices.iloc[:25])


def test_future_prices_cannot_change_historical_inputs():
    prices, _ = artificial_prices()
    original = build_features(prices)
    changed_prices = prices.copy()
    changed_prices.iloc[41:] *= np.linspace(1.1, 1.8, len(prices) - 41)
    changed = build_features(changed_prices)
    input_columns = ["log_return", "volatility_5", "volatility_10", "volatility_20", "momentum_5", "baseline"]
    pd.testing.assert_frame_equal(
        original.loc[:prices.index[40], input_columns],
        changed.loc[:prices.index[40], input_columns],
    )
    assert original.loc[prices.index[40], "target"] != changed.loc[prices.index[40], "target"]


def test_boundary_purge_uses_actual_next_forecast_date():
    prices, _ = artificial_prices(count=240, start="2021-09-01")
    # Explicitly remove the Monday after each Sunday boundary to exercise an
    # actual-session gap. This is a split fixture, not an exchange-calendar fixture.
    prices = prices.drop(pd.to_datetime(["2022-01-03", "2022-04-04"]))
    examples = build_features(prices)
    partitions, summary = split_examples(examples, "2021-10-01", "2022-01-02", "2022-04-03", "2022-08-01")
    assert partitions["validation"].index[0] == pd.Timestamp("2022-01-04")
    assert partitions["test"].index[0] == pd.Timestamp("2022-04-05")
    for current, following in (("train", "validation"), ("validation", "test")):
        cutoff = partitions[following].index[0]
        assert (partitions[current]["target_end"] < cutoff).all()
        unpurged = examples.loc[(examples.index < cutoff) & (examples["target_end"] >= cutoff)]
        assert len(unpurged) == 5
        assert not unpurged.index.isin(partitions[current].index).any()
        assert summary["partitions"][current]["n_purged"] == 5
        assert summary["partitions"][current]["next_partition_first_forecast"] == cutoff.date().isoformat()
    assert summary["partitions"]["test"]["n_purged"] == 0


def test_split_rejects_missing_period_and_reversed_boundaries():
    prices, _ = artificial_prices()
    examples = build_features(prices)
    with pytest.raises(ValueError, match="test partition has no complete examples"):
        split_examples(examples, "2021-11-01", "2022-01-01", "2024-01-01", "2026-01-01")
    with pytest.raises(ValueError, match="boundaries must increase"):
        split_examples(examples, "2022-01-01", "2021-01-01", "2024-01-01", "2026-01-01")


def test_metrics_are_percentage_points_not_percent_relative_error():
    predictions = pd.DataFrame({"baseline": [0.02, 0.01], "target": [0.01, 0.03]})
    result = evaluate_predictions(predictions)
    assert result["n_forecasts"] == 2
    assert result["mae_pp"] == pytest.approx(1.5)
    assert result["rmse_pp"] == pytest.approx(np.sqrt(2.5))
    with pytest.raises(ValueError, match="finite and nonnegative"):
        evaluate_predictions(pd.DataFrame({"baseline": [np.nan], "target": [0.01]}))


def test_five_session_spacing_produces_disjoint_target_windows():
    prices, _ = artificial_prices()
    predictions = validation_predictions(build_features(prices))
    selected = nonoverlapping_predictions(predictions)
    assert selected.index[0] == predictions.index[0]
    assert (np.diff(selected["session_number"]) == 5).all()
    assert (selected["target_start"].iloc[1:].to_numpy() > selected["target_end"].iloc[:-1].to_numpy()).all()
    assert len(selected) == 11


def test_nonoverlap_rejects_invalid_session_spacing_and_overlapping_windows():
    prices, _ = artificial_prices()
    predictions = validation_predictions(build_features(prices))
    missing_selected_session = predictions.drop(predictions.index[5])
    with pytest.raises(ValueError, match="not spaced exactly"):
        nonoverlapping_predictions(missing_selected_session)
    overlapping = predictions.copy()
    overlapping.loc[overlapping.index[0], "target_end"] = overlapping.loc[overlapping.index[5], "target_start"]
    with pytest.raises(ValueError, match="overlapping future outcome"):
        nonoverlapping_predictions(overlapping)


@pytest.mark.parametrize("bad_value", [0.0, -1.0, np.nan, np.inf])
def test_bad_prices_cannot_reach_feature_calculations(bad_value):
    prices, _ = artificial_prices()
    prices.iloc[30] = bad_value
    with pytest.raises(ValueError, match="finite and strictly positive"):
        build_features(prices)


def test_custom_windows_and_horizon_are_applied_consistently():
    prices, returns = artificial_prices()
    examples = build_features(prices, windows=(3, 7), horizon=3, momentum_window=2, baseline_window=7)
    row = examples.iloc[0]
    assert row["session_number"] == 7
    assert row["baseline"] == pytest.approx(np.std(returns[:7], ddof=1))
    assert row["target"] == pytest.approx(np.std(returns[7:10], ddof=1))
    assert row["momentum_2"] == pytest.approx(np.sum(returns[5:7]))
    assert examples.index[-1] == prices.index[-4]
