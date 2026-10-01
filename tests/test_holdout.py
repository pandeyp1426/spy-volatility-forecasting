"""Verify that reserved outcomes never reach the scoring or plotting calls."""

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

from spy_volatility import pipeline


def test_pipeline_scores_validation_and_plots_only_train_and_validation(tmp_path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "phase1.toml"
    config_path.write_text(
        """[data]
ticker = "SPY"
start = "2021-11-01"
end = "2022-07-01"
calendar = "NYSE"
[research]
windows = [5, 10, 20]
horizon = 5
momentum_window = 5
baseline_window = 20
[split]
train_start = "2022-01-01"
validation_start = "2022-03-01"
test_start = "2022-05-01"
test_end = "2022-07-01"
[paths]
snapshot_dir = "data/raw/artificial_fixture"
output_dir = "artifacts/runs"
""",
        encoding="utf-8",
    )
    # Artificial observations cover actual sessions; no provider is contacted.
    dates = mcal.get_calendar("NYSE").schedule("2021-11-01", "2022-06-30").index
    prices = pd.Series(100 * np.exp(np.cumsum(0.01 * np.sin(np.arange(len(dates))))), index=dates)
    monkeypatch.setattr("spy_volatility.data.yf.download", lambda **kwargs: prices.to_frame("Adj Close"))
    validation_start = pd.Timestamp("2022-03-01")
    first_test_session = dates[dates >= "2022-05-01"][0]
    evaluations = []
    plots = []
    evaluate = pipeline.evaluate_predictions
    plot = pipeline._plot_results

    def validation_only(predictions):
        assert len(predictions) > 0
        assert (predictions.index >= validation_start).all()
        assert (predictions.index < first_test_session).all()
        assert (predictions["target_end"] < first_test_session).all()
        evaluations.append(predictions.index.copy())
        return evaluate(predictions)

    def development_plots_only(train, predictions, output):
        assert len(train) > 0
        assert (train.index < validation_start).all()
        assert (train["target_end"] < validation_start).all()
        assert (predictions.index >= validation_start).all()
        assert (predictions.index < first_test_session).all()
        assert (predictions["target_end"] < first_test_session).all()
        plots.append((train.index.copy(), predictions.index.copy()))
        return plot(train, predictions, output)

    monkeypatch.setattr(pipeline, "evaluate_predictions", validation_only)
    monkeypatch.setattr(pipeline, "_plot_results", development_plots_only)
    result = pipeline.run_phase1(config_path)

    assert len(evaluations) >= 2  # Every-session and disjoint-window scores.
    assert len(plots) == 1
    assert result["metrics"]["final_test"] == "reserved; performance not computed"
