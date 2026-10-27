"""Synthetic timing/isolation tests; no empirical reserved responses are read."""

from copy import deepcopy
import json
from pathlib import Path
import tomllib

import numpy as np
import pandas as pd
import pytest

from spy_volatility import temporal
from spy_volatility.models import FEATURE_COLUMNS, TARGET_COLUMN, compare_validation
from spy_volatility.research import build_features


@pytest.fixture
def config():
    path = Path(__file__).resolve().parents[1] / "configs" / "temporal.toml"
    with path.open("rb") as source:
        return tomllib.load(source)


@pytest.fixture
def synthetic():
    # Weekdays are a calculation fixture, not a claim about the NYSE calendar.
    dates = pd.bdate_range("2014-11-03", "2025-12-31")
    positions = np.arange(len(dates), dtype=float)
    returns = 0.012 * np.sin(positions * 0.31) + 0.004 * np.cos(positions * 0.071)
    prices = pd.Series(100.0 * np.exp(np.cumsum(returns)), index=dates)
    eligible = build_features(prices).loc[lambda rows: rows.index >= "2015-01-01"].copy()
    eligible["row_id"] = np.arange(len(eligible))
    return eligible, dates


def test_actual_session_cutoff_available_labels_and_gaps(synthetic):
    examples, dates = synthetic
    cutoff = dates[dates < "2020-01-01"][-1]
    cutoff_position = dates.get_loc(cutoff)
    # Remove the last actual session and several intervening forecast rows.
    # The cutoff still comes from prices, and availability is not a five-row gap.
    development = examples.drop(dates[[cutoff_position, cutoff_position - 2, cutoff_position - 4]])
    fold = temporal.annual_fold(development, dates, 2020)
    assert fold["fit_cutoff"] == cutoff
    exact_boundary = development.loc[development.target_end == cutoff]
    assert len(exact_boundary) == 1
    assert exact_boundary.index[0] in fold["train"].index
    assert (fold["train"].target_end <= cutoff).all()
    assert (fold["evaluation"].index > cutoff).all()
    assert set(fold["evaluation"].index.year) == {2020}
    expected_excluded = development.loc[(development.index <= cutoff) & (development.target_end > cutoff)]
    assert fold["excluded"].index.equals(expected_excluded.index)
    assert len(fold["excluded"]) == 2
    assert set(fold["excluded"].reason) == {"training_label_unavailable_at_fit_cutoff"}


def test_inner_membership_is_within_permitted_outer_training(synthetic):
    examples, dates = synthetic
    development = examples.loc[examples.row_id % 7 != 0]
    outer = temporal.annual_fold(development, dates, 2020)
    for year in (2017, 2018, 2019):
        inner = temporal.annual_fold(development, dates, year, outcome_cutoff=outer["fit_cutoff"])
        assert set(inner["train"].row_id).isdisjoint(inner["evaluation"].row_id)
        assert set(inner["train"].row_id).issubset(outer["train"].row_id)
        assert set(inner["evaluation"].row_id).issubset(outer["train"].row_id)
        assert (inner["train"].target_end <= inner["fit_cutoff"]).all()
        assert (inner["evaluation"].target_end <= outer["fit_cutoff"]).all()
    last = temporal.annual_fold(development, dates, 2019, outcome_cutoff=outer["fit_cutoff"])
    exclusions = last["excluded"].loc[
        last["excluded"].reason == "inner_evaluation_label_unavailable_at_outer_cutoff"]
    assert not exclusions.empty
    assert (exclusions.index.year == 2019).all()
    assert (exclusions.target_end > outer["fit_cutoff"]).all()


def test_exact_ordered_grid_includes_every_original_candidate(config):
    grid = temporal.candidate_grid(config)
    assert len(grid) == 26
    assert [row["candidate_id"] for row in grid] == list(range(26))
    assert [row["model"] for row in grid].count("ridge") == 5
    assert [row["model"] for row in grid].count("random_forest") == 9
    assert [row["model"] for row in grid].count("gradient_boosting") == 12
    assert [row["parameters"]["alpha"] for row in grid[:5]] == [0.01, 0.1, 1.0, 10.0, 100.0]
    assert [(row["parameters"]["max_depth"], row["parameters"]["min_samples_leaf"])
            for row in grid[5:14]] == [(depth, leaf) for depth in (3, 5, 8) for leaf in (5, 10, 20)]
    assert [(row["parameters"]["n_estimators"], row["parameters"]["learning_rate"], row["parameters"]["max_depth"])
            for row in grid[14:]] == [(trees, rate, depth) for trees in (100, 200)
                                     for rate in (0.03, 0.05) for depth in (1, 2, 3)]
    for model, parameters in temporal.FIXED_PARAMETERS.items():
        assert sum(row["model"] == model and row["parameters"] == parameters for row in grid) == 1
    grid[0]["parameters"]["alpha"] = 999
    assert config["fixed"]["ridge"]["alpha"] == 1.0


@pytest.mark.parametrize("change", ["grid", "seed", "metric", "folds", "floor"])
def test_protocol_rejects_unregistered_changes(config, change):
    changed = deepcopy(config)
    if change == "grid":
        changed["search"]["ridge"]["alpha"].append(1000.0)
    elif change == "seed":
        changed["fixed"]["random_forest"]["random_state"] = 1
    elif change == "metric":
        changed["temporal"]["selection_metric"] = "mae_pp"
    elif change == "folds":
        changed["temporal"]["outer_years"] = [2024, 2025]
    else:
        changed["temporal"]["prediction_floor"] = 0.001
    with pytest.raises(ValueError):
        temporal.validate_temporal_config(changed)


def test_deterministic_tie_break_and_failed_candidates_are_not_selected():
    scores = pd.DataFrame([
        {"model": "ridge", "candidate_id": 4, "status": "complete", "rmse_pp": 0.2},
        {"model": "ridge", "candidate_id": 2, "status": "complete", "rmse_pp": 0.2},
        {"model": "ridge", "candidate_id": 0, "status": "failed", "rmse_pp": 0.0},
        {"model": "ridge", "candidate_id": 1, "status": "complete", "rmse_pp": np.nan},
    ])
    assert temporal.choose_candidate(scores, "ridge")["candidate_id"] == 2
    with pytest.raises(ValueError, match="No complete inner candidate"):
        temporal.choose_candidate(scores, "random_forest")


def test_training_only_scaler_and_fixed_predictions_match_original(synthetic):
    examples, _ = synthetic
    train, validation = examples.iloc[:90].copy(), examples.iloc[90:120].copy()
    validation.loc[:, "momentum_5"] += 100.0
    reference, _, record = compare_validation(train, validation)
    for model in temporal.FAMILIES:
        train_prediction, prediction, fit = temporal.fit_predict(
            train, validation, model, temporal.FIXED_PARAMETERS[model])
        np.testing.assert_array_equal(prediction, reference[model].to_numpy())
        assert len(train_prediction) == len(train)
        assert fit["feature_columns"] == list(FEATURE_COLUMNS)
        if model == "ridge":
            assert fit["scaler"]["mean"] == pytest.approx(train[list(FEATURE_COLUMNS)].mean())
            assert fit["scaler"]["n_samples_seen"] == len(train)
            assert fit["scaler"]["mean"] == record["ridge_scaler"]["mean"]
    _, _, ablation = temporal.fit_predict(train, validation, "ridge", {"alpha": 1.0}, temporal.VOLATILITY_COLUMNS)
    assert ablation["feature_columns"] == list(temporal.VOLATILITY_COLUMNS)
    assert len(ablation["scaler"]["mean"]) == 3
    with pytest.raises(ValueError, match="allowlist"):
        temporal.fit_predict(train, validation, "ridge", {"alpha": 1.0}, (*FEATURE_COLUMNS, "row_id"))


def test_fit_predictions_do_not_depend_on_evaluation_targets(synthetic):
    examples, _ = synthetic
    train, evaluation = examples.iloc[:70], examples.iloc[70:95].copy()
    fitted, predicted, before = temporal.fit_predict(train, evaluation, "ridge", {"alpha": 1.0})
    evaluation.loc[:, "target"] = 100.0
    changed_fitted, changed_predicted, after = temporal.fit_predict(train, evaluation, "ridge", {"alpha": 1.0})
    np.testing.assert_array_equal(fitted, changed_fitted)
    np.testing.assert_array_equal(predicted, changed_predicted)
    assert before["scaler"] == after["scaler"]


def test_metric_conversion_and_concatenated_rmse():
    # Three errors: one +1pp and two +3pp. Overall RMSE must weight rows.
    score = temporal._scores(np.array([0.01, 0.01, 0.01]), np.array([0.02, 0.04, 0.04]))
    assert score["mae_pp"] == pytest.approx(7 / 3)
    assert score["bias_pp"] == pytest.approx(7 / 3)
    assert score["rmse_pp"] == pytest.approx(np.sqrt(19 / 3))
    assert score["rmse_pp"] != pytest.approx((1 + 3) / 2)


def test_reserved_identity_rejected_before_fitting(config, synthetic, tmp_path, monkeypatch):
    examples, dates = synthetic
    config["reserved_row_ids"] = [int(examples.row_id.iloc[0])]
    def forbidden_fit(*args, **kwargs):
        pytest.fail("Reserved identity must be rejected before any estimator fit.")
    monkeypatch.setattr(temporal, "fit_predict", forbidden_fit)
    with pytest.raises(ValueError, match="protected reserved"):
        temporal.run_temporal_experiments(examples, dates, config, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()


@pytest.mark.parametrize("corruption", ["forecast_session", "target_end", "duplicate_id"])
def test_invalid_original_metadata_is_rejected(config, synthetic, tmp_path, corruption):
    examples, dates = synthetic
    broken = examples.copy()
    if corruption == "forecast_session":
        broken.loc[:, "session_number"] += 1
    elif corruption == "target_end":
        broken.loc[broken.index[0], "target_end"] = broken.target_end.iloc[1]
    else:
        broken.loc[broken.index[1], "row_id"] = broken.row_id.iloc[0]
    with pytest.raises(ValueError):
        temporal.run_temporal_experiments(broken, dates, config, tmp_path / "blocked")


def _fast_fit(train, evaluation, model, parameters, features=FEATURE_COLUMNS):
    """A deterministic stand-in tests orchestration, not model accuracy."""
    if model in ("baseline", "baseline_5"):
        column = "volatility_20" if model == "baseline" else "volatility_5"
        train_values, values = train[column].to_numpy(), evaluation[column].to_numpy()
    else:
        parameter_offset = (parameters.get("alpha", 0) * 0.00001
                            + parameters.get("max_depth", 0) * 0.0001
                            + parameters.get("learning_rate", 0) * 0.001)
        fitted_mean = float(train.target.mean()) + parameter_offset
        train_values = np.full(len(train), fitted_mean)
        values = np.full(len(evaluation), fitted_mean)
    record = {"model": model, "parameters": deepcopy(parameters), "feature_columns": list(features),
              "n_train": len(train), "n_evaluation": len(evaluation), "elapsed_seconds": 0.0,
              "n_train_floored": 0, "n_evaluation_floored": 0}
    return train_values, values, record


def test_nested_artifacts_samples_and_outer_label_blindness(config, synthetic, tmp_path, monkeypatch):
    examples, dates = synthetic
    # Sparse development membership leaves real session positions intact.
    development = examples.iloc[::23].copy()
    reserved_ids = set(examples.row_id) - set(development.row_id)
    config["reserved_row_ids"] = sorted(reserved_ids)
    calls = []
    def guarded_fit(train, evaluation, model, parameters, features=FEATURE_COLUMNS):
        assert set(train.row_id).isdisjoint(reserved_ids)
        assert set(evaluation.row_id).isdisjoint(reserved_ids)
        assert train.target_end.max() < evaluation.index.min()
        calls.append((set(train.row_id), set(evaluation.row_id)))
        return _fast_fit(train, evaluation, model, parameters, features)
    monkeypatch.setattr(temporal, "fit_predict", guarded_fit)
    first = tmp_path / "original"
    summary = temporal.run_temporal_experiments(development, dates, config, first)
    assert summary["status"] == "complete"
    assert summary["test_scored"] is False
    assert summary["n_fit_failures"] == 0
    assert summary["n_search_candidates_scored"] == 26 * 6
    assert len(calls) == 26 * 3 * 6 + 11 * 6
    predictions = pd.read_csv(first / "temporal_predictions.csv")
    training = pd.read_csv(first / "temporal_training_predictions.csv")
    assert set(predictions.partition) == {"evaluation"}
    assert set(training.partition) == {"train"}
    assert list(predictions.columns) == temporal.PREDICTION_COLUMNS
    expected = set(development.loc[development.index.year >= 2020, "row_id"])
    for _, rows in predictions.groupby(["variant", "model"]):
        assert len(rows) == len(expected)
        assert set(rows.row_id) == expected
    assert set(predictions.groupby(["variant", "model"]).size().index) == {
        ("fixed", "baseline"), ("comparator", "baseline_5"),
        *((variant, model) for variant in ("fixed", "tuned", "volatility_only") for model in temporal.FAMILIES),
    }
    membership = pd.read_csv(first / "temporal_membership.csv")
    assert set(membership.row_id).isdisjoint(reserved_ids)
    assert set(membership.level) == {"outer", "inner"}
    for year in range(2020, 2026):
        outer_train = membership.loc[(membership.outer_fold == year) & (membership.level == "outer")
                                     & (membership.partition == "train")]
        inner_rows = membership.loc[(membership.outer_fold == year) & (membership.level == "inner")]
        assert set(inner_rows.row_id).issubset(outer_train.row_id)
        threshold = development.loc[development.row_id.isin(outer_train.row_id), "target"].quantile(0.95)
        assert predictions.loc[predictions.fold == year, "threshold"].to_numpy() == pytest.approx(threshold)
    search = pd.read_csv(first / "search_results.csv")
    inner = pd.read_csv(first / "inner_predictions.csv")
    for row in search.itertuples():
        values = inner.loc[(inner.outer_fold == row.outer_fold) & (inner.candidate_id == row.candidate_id)]
        assert len(values) == row.n_forecasts
        assert values.fold.nunique() == 3
        errors = 100 * (values.prediction - values.observed)
        assert row.rmse_pp == pytest.approx(np.sqrt(np.mean(errors**2)))

    # The final year's outcomes are outer evaluation only in every search.
    # Changing them must change scored errors without changing any selected settings.
    changed = development.copy()
    changed.loc[changed.index.year == 2025, "target"] += 0.5
    second = tmp_path / "changed_outer_outcomes"
    changed_summary = temporal.run_temporal_experiments(changed, dates, config, second)
    assert json.loads((first / "chosen_parameters.json").read_text()) == json.loads((second / "chosen_parameters.json").read_text())
    changed_predictions = pd.read_csv(second / "temporal_predictions.csv")
    np.testing.assert_array_equal(predictions.prediction, changed_predictions.prediction)
    assert summary["metrics"] != changed_summary["metrics"]
    with pytest.raises(FileExistsError, match="preserved"):
        temporal.run_temporal_experiments(development, dates, config, first)


def test_failed_inner_candidate_is_saved_and_excluded(config, synthetic, tmp_path, monkeypatch):
    examples, dates = synthetic
    development = examples.iloc[::40].copy()
    def fail_one_candidate(train, evaluation, model, parameters, features=FEATURE_COLUMNS):
        if model == "ridge" and parameters.get("alpha") == 0.01:
            raise RuntimeError("Deliberate synthetic candidate failure")
        return _fast_fit(train, evaluation, model, parameters, features)
    monkeypatch.setattr(temporal, "fit_predict", fail_one_candidate)
    summary = temporal.run_temporal_experiments(development, dates, config, tmp_path)
    assert summary["status"] == "complete"
    assert summary["n_fit_failures"] == 18
    failures = pd.read_csv(tmp_path / "fit_failures.csv")
    assert set(failures.candidate_id) == {0}
    search = pd.read_csv(tmp_path / "search_results.csv")
    assert search.loc[search.candidate_id == 0, "rmse_pp"].isna().all()
    assert (search.loc[search.candidate_id == 0, "status"] == "failed").all()
    chosen = json.loads((tmp_path / "chosen_parameters.json").read_text())
    assert all(row["candidate_id"] != 0 for row in chosen)
