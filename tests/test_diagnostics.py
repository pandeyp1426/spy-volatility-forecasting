"""Artificial errors exercise units, tail groups and protected sample roles."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from spy_volatility import diagnostics


def fixture_predictions():
    # Annual sizes differ deliberately: aggregate RMSE cannot average fold RMSEs.
    observed = np.array([.010, .020, .020, .020])
    dates = pd.to_datetime(["2020-03-02", "2021-01-04", "2021-02-09", "2021-12-20"])
    frames = []
    for variant, model, error_pp in [
        ("fixed", "baseline", [2., 2., 2., 2.]),
        ("comparator", "baseline_5", [1., 1., 1., 1.]),
        ("fixed", "ridge", [1., 0., 0., 0.]),
    ]:
        frames.append(pd.DataFrame({"forecast_date": dates, "row_id": [10, 11, 12, 13],
            "fold": [2020, 2021, 2021, 2021], "variant": variant, "model": model,
            "prediction": observed + np.array(error_pp) / 100., "observed": observed,
            "threshold": .02, "partition": "development"}))
    return pd.concat(frames, ignore_index=True)


def write_without_plots(tmp_path, monkeypatch, frame, training=None):
    monkeypatch.setattr(diagnostics, "_plots", lambda *args: [])
    result = diagnostics.write_diagnostics(frame, training, tmp_path, "temporal")
    tables = {name: pd.read_csv(path) for name, path in result["tables"].items()}
    return result, tables


def test_full_precision_metrics_annual_weighting_and_exact_benchmark_rows(tmp_path, monkeypatch):
    result, tables = write_without_plots(tmp_path, monkeypatch, fixture_predictions())
    aggregate = tables["aggregate"].set_index("model")
    ridge = aggregate.loc["ridge"]
    assert ridge.n_forecasts == 4
    assert ridge.mae_pp == pytest.approx(.25)
    assert ridge.rmse_pp == pytest.approx(.5)  # sqrt((1 + 0 + 0 + 0) / 4)
    assert ridge.mse_pp2 == pytest.approx(.25)
    assert ridge.bias_pp == pytest.approx(.25)
    by_year = tables["year"].query("model == 'ridge'")
    assert list(by_year.n_forecasts) == [1, 3]
    assert list(by_year.rmse_pp) == pytest.approx([1., 0.])
    comparison = tables["comparisons"].query("model == 'ridge'").set_index("benchmark")
    assert comparison.loc["baseline", "relative_rmse_improvement_pct"] == pytest.approx(75.)
    assert comparison.loc["baseline_5", "relative_mae_improvement_pct"] == pytest.approx(75.)
    assert comparison.loc["baseline_5", "folds_rmse_improved"] == 1  # equality is not improvement
    assert comparison.loc["baseline", "folds_rmse_improved"] == 2
    assert result["unique_development_rows"] == 4
    assert result["units"]["mse_pp2"] == "squared percentage points"
    assert result["test_scored"] is False


def test_tail_uses_supplied_threshold_includes_equality_and_empty_is_unavailable(tmp_path, monkeypatch):
    _, tables = write_without_plots(tmp_path, monkeypatch, fixture_predictions())
    tail = tables["tail"].query("model == 'ridge'")
    overall = tail.query("aggregation == 'aggregate'").set_index("tail_group")
    assert overall.loc["at_or_above_training_q95", "n_forecasts"] == 3
    assert overall.loc["below_training_q95", "n_forecasts"] == 1
    empty = tail.query("aggregation == 'fold' and fold == 2020 and tail_group == 'at_or_above_training_q95'").iloc[0]
    assert empty.n_forecasts == 0
    assert empty.availability == "empty; unavailable"
    assert np.isnan(empty.mae_pp) and np.isnan(empty.rmse_pp) and np.isnan(empty.mse_pp2)


def test_overall_rmse_is_not_the_mean_of_annual_rmse(tmp_path, monkeypatch):
    predictions = fixture_predictions().query("model == 'ridge'").copy()
    predictions["prediction"] = predictions.observed + np.array([1., 3., 3., 3.]) / 100.
    _, tables = write_without_plots(tmp_path, monkeypatch, predictions)
    assert tables["aggregate"].iloc[0].rmse_pp == pytest.approx(np.sqrt(7.))
    assert tables["year"].rmse_pp.mean() == pytest.approx(2.)


def test_fitted_training_gap_keeps_fold_roles_and_unavailable_is_not_zero(tmp_path, monkeypatch):
    predictions = fixture_predictions()
    training = predictions.copy()
    training["row_id"] -= 10
    training["forecast_date"] -= pd.Timedelta(days=400)
    training["prediction"] = training.observed + .001
    training["partition"] = "train"
    result, tables = write_without_plots(tmp_path, monkeypatch, predictions, training)
    gap = tables["gap"].query("aggregation == 'aggregate' and model == 'ridge'").iloc[0]
    assert gap.training_rmse_pp == pytest.approx(.1)
    assert gap.development_rmse_pp == pytest.approx(.5)
    assert gap.gap_rmse_pp == pytest.approx(.4)
    assert result["training_predictions_available"] is True
    _, missing = write_without_plots(tmp_path, monkeypatch, predictions)
    row = missing["gap"].iloc[0]
    assert row.training_n_forecasts == 0
    assert np.isnan(row.training_rmse_pp) and np.isnan(row.gap_rmse_pp)
    assert "unavailable" in row.availability


@pytest.mark.parametrize("change,message", [
    ("reserved", "Reserved/test"),
    ("duplicate", "unique"),
    ("missing_model_row", "identical scoring"),
    ("contradictory_target", "disagree on observed"),
    ("contradictory_date", "disagree on forecast_date"),
    ("evaluation_threshold", "one training-derived threshold"),
    ("negative", "finite and nonnegative"),
    ("nonfinite", "nonmissing"),
])
def test_invalid_evidence_is_rejected(change, message):
    frame = fixture_predictions()
    if change == "reserved":
        frame.loc[0, "partition"] = "reserved test"
    elif change == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]])
    elif change == "missing_model_row":
        frame = frame.iloc[1:]
    elif change == "contradictory_target":
        frame.loc[0, "observed"] = .03
    elif change == "contradictory_date":
        frame.loc[0, "forecast_date"] += pd.Timedelta(days=1)
    elif change == "evaluation_threshold":
        frame.loc[0, "threshold"] = .03
    elif change == "negative":
        frame.loc[0, "prediction"] = -.01
    else:
        frame.loc[0, "prediction"] = np.nan
    with pytest.raises(ValueError, match=message):
        diagnostics.validate_predictions(frame)


def test_training_rows_cannot_be_reused_for_same_fold_evaluation(tmp_path, monkeypatch):
    frame = fixture_predictions()
    training = frame.assign(partition="train")
    with pytest.raises(ValueError, match="same row identity"):
        write_without_plots(tmp_path, monkeypatch, frame, training)


def test_missing_or_perfect_benchmark_produces_unavailable_relative_gain(tmp_path, monkeypatch):
    frame = fixture_predictions().query("model != 'baseline_5'").copy()
    frame.loc[frame.model == "baseline", "prediction"] = frame.loc[frame.model == "baseline", "observed"]
    _, tables = write_without_plots(tmp_path, monkeypatch, frame)
    comparisons = tables["comparisons"]
    assert comparisons.relative_rmse_improvement_pct.isna().all()
    assert comparisons.query("benchmark == 'baseline_5'").availability.eq("benchmark unavailable").all()


def test_history_uses_actual_dates_as_unconnected_points_and_figures_render(tmp_path, monkeypatch):
    import matplotlib.axes
    dates_seen = []
    original = matplotlib.axes.Axes.scatter

    def record_scatter(axis, x, y, *args, **kwargs):
        if isinstance(x, pd.Series) and pd.api.types.is_datetime64_any_dtype(x):
            dates_seen.append(pd.DatetimeIndex(x))
        return original(axis, x, y, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "scatter", record_scatter)
    frame = fixture_predictions().query("model == 'ridge'")
    result = diagnostics.write_diagnostics(frame, None, tmp_path, "pooled")
    assert len(result["figures"]) == 6
    assert all(Path(path).stat().st_size > 1000 for path in result["figures"])
    assert dates_seen and all(dates.equals(pd.DatetimeIndex(frame.forecast_date)) for dates in dates_seen)
