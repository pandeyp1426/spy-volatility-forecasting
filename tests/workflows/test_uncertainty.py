"""Artificial paired forecasts test masked, calendar-aware block uncertainty."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import spy_volatility.workflows.uncertainty as uncertainty


SUBSETS = ("within_year", "original")
SCORE_METRICS = ("mae_pp", "mse_pp2", "rmse_pp", "bias_pp")


def fixture_evidence():
    # Synthetic trading calendar; omitted identities at both ends of both years
    # and internally must retain their original position in each session grid.
    calendar = pd.bdate_range("2020-12-21", periods=25)
    all_positions = np.arange(20)
    retained = np.array([1, 2, 4, 7, 10, 12, 14, 16, 18])
    assignments = pd.DataFrame({
        "forecast_date": calendar[all_positions],
        "row_id": all_positions + 17,
        "session_number": all_positions + 100,
        "target_start": calendar[all_positions + 1],
        "target_end": calendar[all_positions + 5],
        "partition": np.where(np.isin(all_positions, retained), "validation", "test"),
    })
    ridge_errors = np.array([3., -1., 2., 1., 0., 0., .5, -.5, 0.])
    frames = []
    for variant, model, errors in (
        ("fixed", "baseline", np.full(len(retained), 2.)),
        ("comparator", "baseline_5", np.full(len(retained), 1.5)),
        ("fixed", "ridge", ridge_errors),
    ):
        identity = assignments.loc[retained].copy().reset_index(drop=True)
        identity["fold"] = identity.forecast_date.dt.year
        identity["fit_cutoff"] = pd.to_datetime([
            f"{year - 1}-12-31" for year in identity.fold
        ])
        frames.append(identity.assign(
            variant=variant, model=model, prediction=.1 + errors / 100.,
            observed=.1, threshold=.2, partition="evaluation",
        ))
    return pd.concat(frames, ignore_index=True), assignments


def point_scores(frame, model_keys):
    output = np.empty((2, len(model_keys), 4))
    for s, subset in enumerate(SUBSETS):
        chosen = frame
        if subset == "within_year":
            chosen = chosen.loc[
                chosen.target_start.dt.year.eq(chosen.forecast_date.dt.year)
                & chosen.target_end.dt.year.eq(chosen.forecast_date.dt.year)
            ]
        for m, (variant, model) in enumerate(model_keys):
            data = chosen.loc[chosen.variant.eq(variant) & chosen.model.eq(model)]
            errors = 100. * (data.prediction.to_numpy() - data.observed.to_numpy())
            mse = np.mean(errors ** 2)
            output[s, m] = [np.mean(abs(errors)), mse, np.sqrt(mse), np.mean(errors)]
    return output


def test_full_original_session_grids_preserve_reserved_edges_and_interior_gaps():
    frame, assignments = fixture_evidence()
    grids = uncertainty.prepare_grids(frame, assignments)
    assert [g["fold"] for g in grids] == [2020, 2021]
    for grid in grids:
        year_map = assignments.loc[assignments.forecast_date.dt.year.eq(grid["fold"])]
        np.testing.assert_array_equal(grid["sessions"], year_map.session_number)
        assert len(grid["sessions"]) > frame.loc[frame.fold.eq(grid["fold"]), "row_id"].nunique()
        for subset, label in enumerate(SUBSETS):
            allowed = year_map.partition.ne("test")
            if label == "within_year":
                allowed &= year_map.target_start.dt.year.eq(grid["fold"]) & year_map.target_end.dt.year.eq(grid["fold"])
            np.testing.assert_array_equal(grid["eligible"][subset], allowed)
            assert grid["original_counts"][subset] == allowed.sum()
        # Reserved gaps are placeholders, not fake zero-error observations.
        absent = year_map.partition.eq("test").to_numpy()
        assert not grid["eligible"][:, absent].any()
        assert np.equal(grid["losses"][absent], 0).all()
        assert not grid["eligible"][:, 0].any()
        assert not grid["eligible"][:, -1].any()


def test_grid_preparation_is_invariant_to_long_row_and_assignment_order():
    frame, assignments = fixture_evidence()
    expected = uncertainty.prepare_grids(frame, assignments)
    actual = uncertainty.prepare_grids(
        frame.sample(frac=1., random_state=7),
        assignments.sample(frac=1., random_state=17),
    )
    for left, right in zip(actual, expected):
        assert left["fold"] == right["fold"]
        assert left["model_keys"] == right["model_keys"]
        for column in ("sessions", "eligible", "losses", "original_counts"):
            np.testing.assert_array_equal(left[column], right[column])


def test_identity_draws_reproduce_original_full_precision_scores():
    frame, assignments = fixture_evidence()
    grids = uncertainty.prepare_grids(frame, assignments)
    draws = {g["fold"]: np.arange(len(g["sessions"]))[None, :] for g in grids}
    scores, counts = uncertainty.bootstrap_scores(grids, draws)
    assert scores.shape == (2, 1, 3, 4)
    assert counts.shape == (2, 1, 2)
    np.testing.assert_allclose(scores[:, 0], point_scores(frame, grids[0]["model_keys"]), rtol=1e-12)
    np.testing.assert_array_equal(counts[:, 0], np.column_stack([g["original_counts"] for g in grids]))


def test_masked_resampling_preserves_original_annual_weights_not_draw_counts():
    frame, assignments = fixture_evidence()
    grids = uncertainty.prepare_grids(frame, assignments)
    # In 2020 draw a high-error valid session once and the reserved first session
    # eight times. In 2021 draw the first valid session eleven times. Original
    # year weights must remain 4/9 and 5/9, not random replicate counts 1/12,11/12.
    draws = {}
    for grid in grids:
        n = len(grid["sessions"])
        first_valid = int(np.flatnonzero(grid["eligible"][1])[0])
        indexes = np.full(n, first_valid)
        if grid["fold"] == 2020:
            indexes[1:] = 0
        draws[grid["fold"]] = indexes[None, :]
    scores, counts = uncertainty.bootstrap_scores(grids, draws)
    ridge = grids[0]["model_keys"].index(("fixed", "ridge"))
    np.testing.assert_array_equal(counts[:, 0], [[1, 11], [1, 11]])
    # Both retained 2020 contained rows count in the fixed weight, even though
    # one error is sampled here; all five retained 2021 rows stay in its weight.
    assert scores[0, 0, ridge, 1] == pytest.approx(9. * 2. / 7.)
    assert scores[1, 0, ridge, 1] == pytest.approx(9. * 4. / 9.)
    assert scores[1, 0, ridge, 0] == pytest.approx(3. * 4. / 9.)
    assert scores[1, 0, ridge, 2] == pytest.approx(2.)
    assert scores[1, 0, ridge, 2] != pytest.approx(3. * 4. / 9.)  # no mean yearly RMSE
    assert scores[1, 0, ridge, 2] != pytest.approx(np.sqrt(9. / 12.))


def test_empty_resampled_year_invalidates_whole_subset_draw_without_redrawing():
    frame, assignments = fixture_evidence()
    grids = uncertainty.prepare_grids(frame, assignments)
    draws = {g["fold"]: np.tile(np.arange(len(g["sessions"])), (2, 1)) for g in grids}
    first = grids[0]
    crossing = np.flatnonzero(first["eligible"][1] & ~first["eligible"][0])[0]
    draws[first["fold"]][0] = crossing
    draws[first["fold"]][1] = 0  # reserved-only draw: both subsets unavailable
    scores, counts = uncertainty.bootstrap_scores(grids, draws)
    assert np.isnan(scores[0]).all()
    assert np.isfinite(scores[1, 0]).all()
    assert np.isnan(scores[1, 1]).all()
    assert counts[0, 0, 0] == 0
    assert counts[1, 0, 0] == len(first["sessions"])
    assert counts[:, 1, 0].tolist() == [0, 0]
    assert scores.shape[1] == 2


def test_original_empty_stratum_has_zero_weight_without_invalidating_other_years():
    frame, assignments = fixture_evidence()
    assignments.loc[assignments.forecast_date.dt.year.eq(2020), "target_end"] = pd.Timestamp("2021-01-15")
    frame.loc[frame.fold.eq(2020), "target_end"] = pd.Timestamp("2021-01-15")
    grids = uncertainty.prepare_grids(frame, assignments)
    assert grids[0]["original_counts"][0] == 0
    draws = {g["fold"]: np.arange(len(g["sessions"]))[None, :] for g in grids}
    # The first year's containment weight is zero, so even a draw that never
    # sees a permitted observation cannot make its other year's score undefined.
    draws[2020][:] = 0
    scores, counts = uncertainty.bootstrap_scores(grids, draws)
    assert np.isfinite(scores[0]).all()
    assert np.isnan(scores[1]).all()
    assert counts[0, 0, 0] == 0
    np.testing.assert_allclose(scores[0, 0], point_scores(frame, grids[0]["model_keys"])[0])


@pytest.mark.parametrize("tamper", ["negative", "too_large", "fractional", "wrong_length", "different_replicates"])
def test_bootstrap_scores_reject_invalid_saved_draws(tamper):
    frame, assignments = fixture_evidence()
    grids = uncertainty.prepare_grids(frame, assignments)
    draws = {g["fold"]: np.tile(np.arange(len(g["sessions"])), (2, 1)) for g in grids}
    if tamper == "negative":
        draws[2020][0, 0] = -1
    elif tamper == "too_large":
        draws[2020][0, 0] = len(grids[0]["sessions"])
    elif tamper == "fractional":
        draws[2020] = draws[2020].astype(float)
        draws[2020][0, 0] += .5
    elif tamper == "wrong_length":
        draws[2020] = draws[2020][:, :-1]
    else:
        draws[2020] = draws[2020][:1]
    with pytest.raises((ValueError, TypeError)):
        uncertainty.bootstrap_scores(grids, draws)


def test_stationary_indices_are_seeded_bounded_and_keep_session_grid_size():
    first = uncertainty.stationary_indices(17, 100, 5, np.random.default_rng(42))
    second = uncertainty.stationary_indices(17, 100, 5, np.random.default_rng(42))
    other = uncertainty.stationary_indices(17, 100, 5, np.random.default_rng(43))
    assert first.shape == (100, 17)
    assert np.issubdtype(first.dtype, np.integer)
    assert first.min() >= 0 and first.max() < 17
    np.testing.assert_array_equal(first, second)
    assert not np.array_equal(first, other)
    # The method retains genuine successive/wrapped grid steps, not rows after
    # removing unavailable dates; there are also random restarts.
    adjacent = first[:, 1:] == (first[:, :-1] + 1) % 17
    assert adjacent.mean() > .6
    assert (~adjacent).any()


def test_stationary_single_session_and_length_one_are_valid():
    np.testing.assert_array_equal(
        uncertainty.stationary_indices(1, 5, 60, np.random.default_rng(42)),
        np.zeros((5, 1), dtype=int),
    )
    draws = uncertainty.stationary_indices(50, 100, 1, np.random.default_rng(7))
    assert draws.shape == (100, 50)
    assert np.mean(draws[:, 1:] == (draws[:, :-1] + 1) % 50) < .1


@pytest.mark.parametrize("n,b,length", [
    (0, 5, 5), (5, 0, 5), (5, 5, 0), (-1, 5, 5),
    (5, -1, 5), (5, 5, -1), (2.5, 5, 5), (5, 2.5, 5),
    (5, 5, 2.5), (True, 5, 5), (5, 5, np.nan),
])
def test_stationary_indices_reject_invalid_sizes_or_block_lengths(n, b, length):
    with pytest.raises((ValueError, TypeError)):
        uncertainty.stationary_indices(n, b, length, np.random.default_rng(42))


@pytest.mark.parametrize("tamper", ["reserved_prediction", "missing_assignment", "fractional_session", "metadata", "unpaired"])
def test_grid_preparation_rejects_corrupted_identity_evidence(tamper):
    frame, assignments = fixture_evidence()
    if tamper == "reserved_prediction":
        assignments.loc[assignments.row_id.eq(18), "partition"] = "test"
    elif tamper == "missing_assignment":
        assignments = assignments.loc[~assignments.row_id.eq(20)]
    elif tamper == "fractional_session":
        assignments["session_number"] = assignments.session_number.astype(float)
        assignments.loc[0, "session_number"] += .5
    elif tamper == "metadata":
        assignments.loc[assignments.row_id.eq(18), "target_end"] = pd.Timestamp("2021-01-15")
    else:
        frame = frame.drop(frame.loc[frame.model.eq("ridge")].index[0])
    with pytest.raises((ValueError, AssertionError)):
        uncertainty.prepare_grids(frame, assignments)


def interval_evidence():
    keys = [("comparator", "baseline_5"), ("fixed", "baseline"), ("fixed", "ridge")]
    means = np.linspace(.2, 2.0, 100)
    samples = np.empty((2, 100, len(keys), 4))
    for s in range(2):
        for m in range(len(keys)):
            mae = means + .1 * m + .2 * s
            mse = mae ** 2 + .4 * m
            samples[s, :, m, :] = np.column_stack([mae, mse, np.sqrt(mse), mae / 3.])
    points = samples.mean(axis=1)
    points[:, :, 2] = np.sqrt(points[:, :, 1])
    return keys, points, samples


def test_intervals_use_paired_rmse_differences_and_adjust_only_primary_family():
    keys, points, samples = interval_evidence()
    tables = uncertainty.interval_tables(points, samples, keys, 20)
    comparison = tables["comparisons"]
    selected = comparison.loc[
        comparison["subset"].eq("within_year")
        & comparison["variant"].eq("fixed")
        & comparison["model"].eq("ridge")
        & comparison["reference_model"].eq("baseline")
        & comparison["metric"].eq("rmse_pp")
    ]
    assert len(selected) == 1
    row = selected.iloc[0]
    paired = samples[0, :, 2, 2] - samples[0, :, 1, 2]
    assert row["estimate"] == pytest.approx(points[0, 2, 2] - points[0, 1, 2])
    np.testing.assert_allclose([row.ci_lower, row.ci_upper], np.quantile(paired, [.025, .975], method="linear"))
    np.testing.assert_allclose([row.familywise_lower, row.familywise_upper], np.quantile(paired, [.0125, .9875], method="linear"))
    assert row.primary_analysis
    assert row.n_valid == 100 and row.n_invalid == 0
    # The correction belongs to exactly two RMSE contrasts, not every variant,
    # metric or block-length sensitivity considered during the study.
    assert comparison.primary_analysis.sum() == 2
    assert comparison.familywise_lower.notna().sum() == 2
    assert comparison.familywise_upper.notna().sum() == 2
    alternative = uncertainty.interval_tables(points, samples, keys, 40)["comparisons"]
    assert not alternative.primary_analysis.any()
    assert alternative.familywise_lower.isna().all()
    assert alternative.familywise_upper.isna().all()
    assert not any("p_value" in c or "probability" in c for c in comparison.columns)


def test_paired_identical_models_have_zero_difference_interval_despite_score_variation():
    keys, points, samples = interval_evidence()
    samples[:, :, 2] = samples[:, :, 1]
    points[:, 2] = points[:, 1]
    tables = uncertainty.interval_tables(points, samples, keys, 20)
    rows = tables["comparisons"]
    rows = rows.loc[rows.model.eq("ridge") & rows.reference_model.eq("baseline")]
    np.testing.assert_array_equal(rows[["estimate", "ci_lower", "ci_upper"]], 0.)
    score = tables["scores"].loc[tables["scores"].model.eq("ridge")]
    assert (score.ci_upper > score.ci_lower).all()


def test_any_invalid_replicate_withholds_interval_without_silently_dropping_draw():
    keys, points, samples = interval_evidence()
    samples[0, 12, 2, :] = np.nan
    tables = uncertainty.interval_tables(points, samples, keys, 20)
    rows = tables["comparisons"]
    missing = rows.loc[rows.subset.eq("within_year") & rows.model.eq("ridge")]
    assert missing.n_valid.eq(99).all() and missing.n_invalid.eq(1).all()
    assert missing[["ci_lower", "ci_upper", "familywise_lower", "familywise_upper"]].isna().all().all()
    assert not missing.availability.eq("available").any()
    original = rows.loc[rows.subset.eq("original")]
    assert original.n_valid.eq(100).all() and original.n_invalid.eq(0).all()
    assert original[["ci_lower", "ci_upper"]].notna().all().all()


def test_comparison_spec_includes_all_learned_variants_and_preserves_primary_pair():
    keys = sorted({("fixed", "baseline"), ("comparator", "baseline_5"),
                   *((v, m) for v in ("fixed", "tuned", "volatility_only")
                     for m in ("ridge", "random_forest", "gradient_boosting"))})
    specification = uncertainty.comparison_spec(keys)
    assert len(specification) == 24
    assert len({entry["comparison"] for entry in specification}) == 24
    pairings = {(keys[entry["model_index"]], keys[entry["reference_index"]]) for entry in specification}
    assert (("tuned", "ridge"), ("fixed", "ridge")) in pairings
    assert (("volatility_only", "gradient_boosting"), ("fixed", "gradient_boosting")) in pairings
    primary = [entry for entry in specification if entry["primary_contrast"]]
    assert len(primary) == 2
    assert {keys[entry["model_index"]] for entry in primary} == {("fixed", "ridge")}
    assert {keys[entry["reference_index"]] for entry in primary} == {("fixed", "baseline"), ("comparator", "baseline_5")}


def fixture_source_run(root):
    """Complete artificial parent: gaps are identity-only reserved positions."""
    import spy_volatility.workflows.sensitivity as sensitivity

    source = root / "artifacts/runs/synthetic_temporal"
    source.mkdir(parents=True)
    base, assignments = fixture_evidence()
    ridge = base.loc[base.model.eq("ridge")]
    frames = [base, *(ridge.assign(variant=v, model=m)
                     for v in ("fixed", "tuned", "volatility_only")
                     for m in ("ridge", "random_forest", "gradient_boosting")
                     if (v, m) != ("fixed", "ridge"))]
    predictions = pd.concat(frames, ignore_index=True)
    predictions.to_csv(source / "temporal_predictions.csv", index=False)
    assignments.to_csv(source / "source_split_assignments.csv", index=False)
    assignments.loc[assignments.partition.eq("test")].to_csv(source / "reserved_identities.csv", index=False)
    outer = predictions.drop_duplicates("row_id")[sensitivity.IDENTITY].rename(columns={"fold": "outer_fold"})
    outer.assign(level="outer", partition="evaluation").to_csv(source / "temporal_membership.csv", index=False)
    record = {"run_id": "synthetic_temporal", "experiment": "retrospective_temporal",
              "status": "success", "final_test_evaluated": False,
              "reserved_rows_excluded": True, "calculation_verification_passed": True,
              "snapshot_sha256": "synthetic-no-price-snapshot", "config": {"research": {"horizon": 5}},
              "artifact_sha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                                  for name in sensitivity.INPUTS}}
    (source / "run_record.json").write_text(json.dumps(record), encoding="utf-8")
    (source / "test_reserved.csv").write_text("reserved_response\n999999\n", encoding="utf-8")
    config_dir = root / "configs"
    config_dir.mkdir()
    config = config_dir / "uncertainty.toml"
    canonical = Path(__file__).resolve().parents[2] / "configs/uncertainty.toml"
    text = canonical.read_text(encoding="utf-8").replace(
        "artifacts/runs/20261027T001114_temporal_4bf4a071", "artifacts/runs/synthetic_temporal")
    config.write_text(text, encoding="utf-8")
    return source, config


def test_runner_is_offline_paired_reproducible_and_preserves_all_source_evidence(tmp_path, monkeypatch):
    import spy_volatility.core.data as data
    import spy_volatility.workflows.baseline as pipeline
    import spy_volatility.analysis.temporal as temporal
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge

    source, config = fixture_source_run(tmp_path)
    original_bytes = {p.name: p.read_bytes() for p in source.iterdir()}

    def forbidden(*args, **kwargs):
        pytest.fail("Uncertainty execution cannot download data or refit models")

    monkeypatch.setattr(data, "get_snapshot", forbidden)
    monkeypatch.setattr(data.yf, "download", forbidden)
    monkeypatch.setattr(pipeline, "get_snapshot", forbidden)
    monkeypatch.setattr(temporal, "_make_estimator", forbidden)
    for estimator in (Ridge, RandomForestRegressor, GradientBoostingRegressor):
        monkeypatch.setattr(estimator, "fit", forbidden)
    original_open, original_csv = Path.open, pd.read_csv
    accessed = []

    def guarded_open(path, *args, **kwargs):
        assert path.name != "test_reserved.csv", "Reserved response file was opened"
        return original_open(path, *args, **kwargs)

    def guarded_csv(path, *args, **kwargs):
        accessed.append(Path(path).name)
        assert Path(path).name != "test_reserved.csv"
        return original_csv(path, *args, **kwargs)

    with monkeypatch.context() as access:
        access.setattr(Path, "open", guarded_open)
        access.setattr(pd, "read_csv", guarded_csv)
        first = pipeline.run_phase1(config, offline=False)
        second = pipeline.run_phase1(config, offline=True)
    first_path, second_path = Path(first["output_dir"]), Path(second["output_dir"])
    assert first_path != second_path
    assert first["calculation_verification_passed"] is True
    assert first["test_evaluated"] is False
    for name in ("tables/scores.csv", "tables/comparisons.csv"):
        assert (first_path / name).read_bytes() == (second_path / name).read_bytes()
    for length in (5, 10, 20, 40, 60):
        with np.load(first_path / f"bootstrap_L{length}.npz") as left, np.load(second_path / f"bootstrap_L{length}.npz") as right:
            assert set(left.files) == set(right.files)
            for key in left.files:
                np.testing.assert_array_equal(left[key], right[key])
    assert {p.name: p.read_bytes() for p in source.iterdir()} == original_bytes
    assert "test_reserved.csv" not in accessed
    record = json.loads((first_path / "run_record.json").read_text(encoding="utf-8"))
    assert record["status"] == "success"
    assert record["offline"] is True and record["models_refitted"] is False
    assert record["reserved_responses_read"] is False and record["final_test_evaluated"] is False
    for name, digest in record["artifact_sha256"].items():
        assert hashlib.sha256((first_path / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("file", ["temporal_predictions.csv", "source_split_assignments.csv"])
def test_runner_rejects_source_tampering_before_new_output(tmp_path, file):
    source, config = fixture_source_run(tmp_path)
    (source / file).write_bytes((source / file).read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        uncertainty.run_uncertainty(config)
    assert list(source.parent.iterdir()) == [source]


@pytest.mark.parametrize("field,value", [
    ("status", "failed"), ("final_test_evaluated", True),
    ("reserved_rows_excluded", False), ("calculation_verification_passed", False),
])
def test_runner_rejects_unverified_parent(tmp_path, field, value):
    source, config = fixture_source_run(tmp_path)
    path = source / "run_record.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record[field] = value
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="successful verified temporal run"):
        uncertainty.run_uncertainty(config)
