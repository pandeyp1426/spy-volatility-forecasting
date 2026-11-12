"""Gapped, paired artificial forecasts exercise temporal sensitivity safeguards."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import spy_volatility.workflows.sensitivity as sensitivity
from spy_volatility.verification.sensitivity import verify_sensitivity


def fixture_predictions():
    # These are synthetic sessions. Session numbers are never renumbered after
    # omitted identities, and the modulo phase continues through New Year.
    calendar = pd.bdate_range("2020-12-14", periods=30)
    positions = np.array([0, 1, 3, 4, 5, 7, 8, 9, 10, 11, 13, 15, 16, 19, 20])
    observed = np.full(len(positions), .01)
    observed[[1, 4, 7, 11]] = .02  # Equality belongs in the high group.
    ridge_error = np.zeros(len(positions))
    ridge_error[0] = 1.
    frames = []
    for variant, model, errors in (
        ("fixed", "baseline", np.full(len(positions), 2.)),
        ("comparator", "baseline_5", np.ones(len(positions))),
        ("fixed", "ridge", ridge_error),
    ):
        dates = calendar[positions]
        frames.append(pd.DataFrame({
            "forecast_date": dates,
            "row_id": positions + 17,
            "session_number": positions + 100,
            "target_start": calendar[positions + 1],
            "target_end": calendar[positions + 5],
            "fold": dates.year,
            "variant": variant,
            "model": model,
            "prediction": observed + errors / 100.,
            "observed": observed,
            "threshold": .02,
            "partition": "evaluation",
            "fit_cutoff": pd.to_datetime([
                f"{year - 1}-12-31" for year in dates.year
            ]),
        }))
    return pd.concat(frames, ignore_index=True)


def checked_evidence():
    frame = sensitivity.validate_predictions_for_sensitivity(fixture_predictions())
    membership = sensitivity.build_membership(frame)
    return frame, membership


def selected(membership, subset):
    return membership.loc[
        membership["subset"].eq(subset) & membership["included"]
    ].sort_values("session_number")


def metric_rows(metrics, subset="original", aggregation="aggregate", tail_group="all"):
    return metrics.loc[
        metrics["subset"].eq(subset)
        & metrics["aggregation"].eq(aggregation)
        & metrics["tail_group"].eq(tail_group)
    ]


def test_membership_has_every_identity_and_filters_original_session_positions():
    frame, membership = checked_evidence()
    expected_subsets = {"original", "within_year"}
    expected_subsets.update(f"modulo_{residue}" for residue in range(5))
    expected_subsets.update(f"within_year_modulo_{residue}" for residue in range(5))
    assert set(membership["subset"]) == expected_subsets
    identities = frame.drop_duplicates("row_id")
    assert len(membership) == len(identities) * len(expected_subsets)
    assert not membership.duplicated(["subset", "row_id"]).any()
    assert membership.groupby("subset").size().eq(len(identities)).all()
    assert selected(membership, "original")["row_id"].tolist() == identities.sort_values(
        "session_number"
    )["row_id"].tolist()

    for residue in range(5):
        expected = identities.loc[identities["session_number"] % 5 == residue]
        actual = selected(membership, f"modulo_{residue}")
        assert set(actual["row_id"]) == set(expected["row_id"])
        assert actual["primary"].eq(residue == 0).all()
    # Compressed every-fifth retained row would select different forecast dates.
    assert set(selected(membership, "modulo_0")["row_id"]) != set(
        identities.sort_values("session_number").iloc[::5]["row_id"]
    )


def test_all_five_residues_are_disjoint_exhaustive_and_windows_do_not_overlap():
    _, membership = checked_evidence()
    all_ids = []
    for residue in range(5):
        rows = selected(membership, f"modulo_{residue}")
        all_ids.extend(rows["row_id"].tolist())
        assert (np.diff(rows["session_number"]) >= 5).all()
        # Check global order, including adjacent forecasts from different years.
        assert (
            rows["target_end"].iloc[:-1].to_numpy()
            < rows["target_start"].iloc[1:].to_numpy()
        ).all()
    assert len(all_ids) == len(set(all_ids))
    assert set(all_ids) == set(selected(membership, "original")["row_id"])
    primary = selected(membership, "modulo_0")
    assert {2020, 2021} == set(primary["fold"])


def test_membership_ignores_input_order_predictions_and_outcome_magnitudes():
    frame, expected = checked_evidence()
    changed = frame.sample(frac=1, random_state=23).copy()
    changed["prediction"] = .5
    changed["observed"] = .4
    actual = sensitivity.build_membership(
        sensitivity.validate_predictions_for_sensitivity(changed)
    )
    columns = ["subset", "row_id", "included", "exclusion_reason", "primary"]
    pd.testing.assert_frame_equal(
        actual[columns].sort_values(["subset", "row_id"]).reset_index(drop=True),
        expected[columns].sort_values(["subset", "row_id"]).reset_index(drop=True),
    )


def test_calendar_containment_uses_complete_outcome_and_combines_with_modulo():
    frame, membership = checked_evidence()
    identities = frame.drop_duplicates("row_id")
    contained = (
        identities["target_start"].dt.year.eq(identities["forecast_date"].dt.year)
        & identities["target_end"].dt.year.eq(identities["forecast_date"].dt.year)
    )
    expected_ids = set(identities.loc[contained, "row_id"])
    assert set(selected(membership, "within_year")["row_id"]) == expected_ids
    jan_first = identities["target_end"].eq(pd.Timestamp("2021-01-01"))
    assert jan_first.any()
    assert not set(identities.loc[jan_first, "row_id"]) & expected_ids
    for residue in range(5):
        residue_ids = set(selected(membership, f"modulo_{residue}")["row_id"])
        actual_ids = set(selected(membership, f"within_year_modulo_{residue}")["row_id"])
        assert actual_ids == expected_ids & residue_ids
    excluded = membership.loc[~membership["included"]]
    assert excluded["exclusion_reason"].notna().all()
    assert excluded["exclusion_reason"].str.len().gt(0).all()


def test_metrics_are_paired_full_precision_and_weighted_over_actual_rows():
    frame, membership = checked_evidence()
    tables = sensitivity.summarize_sensitivity(frame, membership)
    metrics, comparisons = tables["metrics"], tables["comparisons"]
    all_metrics = metric_rows(metrics).set_index("model")
    n = frame["row_id"].nunique()
    assert all_metrics["n_forecasts"].eq(n).all()
    assert all_metrics.loc["ridge", "mae_pp"] == pytest.approx(1 / n)
    assert all_metrics.loc["ridge", "rmse_pp"] == pytest.approx(np.sqrt(1 / n))
    assert all_metrics.loc["ridge", "mse_pp2"] == pytest.approx(1 / n)
    assert all_metrics.loc["ridge", "bias_pp"] == pytest.approx(1 / n)
    annual = metric_rows(metrics, aggregation="fold").query("model == 'ridge'")
    assert annual["n_forecasts"].sum() == n
    assert annual["rmse_pp"].mean() != pytest.approx(all_metrics.loc["ridge", "rmse_pp"])

    for subset, rows in membership.groupby("subset"):
        included = set(rows.loc[rows["included"], "row_id"])
        scores = metric_rows(metrics, subset).set_index("model")
        assert scores["n_forecasts"].eq(len(included)).all()
        for model in scores.index:
            data = frame.loc[frame["model"].eq(model) & frame["row_id"].isin(included)]
            errors = 100 * (data["prediction"].to_numpy() - data["observed"].to_numpy())
            assert scores.loc[model, "mae_pp"] == pytest.approx(np.abs(errors).mean())
            assert scores.loc[model, "rmse_pp"] == pytest.approx(np.sqrt(np.mean(errors ** 2)))

    comparison = comparisons.loc[
        comparisons["subset"].eq("original")
        & comparisons["aggregation"].eq("aggregate")
        & comparisons["tail_group"].eq("all")
        & comparisons["model"].eq("ridge")
    ].set_index("benchmark")
    assert set(comparison.index) == {"baseline", "baseline_5"}
    for model, error in (("baseline", 2.), ("baseline_5", 1.)):
        assert comparison.loc[model, "delta_rmse_pp"] == pytest.approx(np.sqrt(1 / n) - error)
        assert comparison.loc[model, "relative_rmse_improvement_pct"] == pytest.approx(
            100 * (1 - np.sqrt(1 / n) / error)
        )


def test_tail_threshold_equality_and_empty_annual_cells_remain_explicit():
    frame, membership = checked_evidence()
    metrics = sensitivity.summarize_sensitivity(frame, membership)["metrics"]
    high = metric_rows(metrics, tail_group="at_or_above_training_q95")
    assert high["n_forecasts"].eq(4).all()
    low = metric_rows(metrics, tail_group="below_training_q95")
    assert low["n_forecasts"].eq(11).all()
    empty = metric_rows(metrics, "modulo_2", "fold").query("fold == 2021")
    assert len(empty) == 3
    assert empty["n_forecasts"].eq(0).all()
    assert empty[["mae_pp", "rmse_pp", "mse_pp2", "bias_pp"]].isna().all().all()
    assert empty["availability"].str.contains("unavailable").all()


@pytest.mark.parametrize("change", [
    "fractional_session", "fractional_row", "contradictory_session",
    "contradictory_target_start", "contradictory_target_end", "contradictory_cutoff",
    "reserved_partition", "training_partition", "missing_benchmark", "duplicate",
    "missing_model_row", "invalid_target_order", "forecast_before_fit", "wrong_fold",
])
def test_invalid_prediction_evidence_is_rejected(change):
    frame = fixture_predictions()
    if change in ("fractional_session", "fractional_row"):
        column = "session_number" if change == "fractional_session" else "row_id"
        frame[column] = frame[column].astype(float)
        frame.loc[0, column] += .5
    elif change == "contradictory_session":
        frame.loc[0, "session_number"] += 1
    elif change == "contradictory_target_start":
        frame.loc[0, "target_start"] += pd.Timedelta(days=1)
    elif change == "contradictory_target_end":
        frame.loc[0, "target_end"] += pd.Timedelta(days=1)
    elif change == "contradictory_cutoff":
        frame.loc[0, "fit_cutoff"] -= pd.Timedelta(days=1)
    elif change == "reserved_partition":
        frame.loc[0, "partition"] = "test"
    elif change == "training_partition":
        frame.loc[0, "partition"] = "train"
    elif change == "missing_benchmark":
        frame = frame.loc[frame["model"].ne("baseline_5")]
    elif change == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    elif change == "missing_model_row":
        frame = frame.iloc[1:]
    elif change == "invalid_target_order":
        frame.loc[frame["row_id"].eq(17), "target_start"] = pd.Timestamp("2020-12-14")
    elif change == "forecast_before_fit":
        frame.loc[frame["fold"].eq(2020), "fit_cutoff"] = pd.Timestamp("2020-12-31")
    else:
        frame.loc[frame["row_id"].eq(17), "fold"] = 2021
    with pytest.raises(ValueError):
        sensitivity.validate_predictions_for_sensitivity(frame)


def test_reserved_identity_is_rejected_even_when_partition_claims_evaluation():
    with pytest.raises(ValueError):
        sensitivity.validate_predictions_for_sensitivity(fixture_predictions(), reserved_row_ids={17})


def test_perfect_benchmark_retains_absolute_difference_with_undefined_relative_gain():
    frame = fixture_predictions()
    frame.loc[frame["model"].eq("baseline"), "prediction"] = frame.loc[
        frame["model"].eq("baseline"), "observed"
    ]
    frame = sensitivity.validate_predictions_for_sensitivity(frame)
    membership = sensitivity.build_membership(frame)
    comparisons = sensitivity.summarize_sensitivity(frame, membership)["comparisons"]
    rows = comparisons.loc[
        comparisons["subset"].eq("original")
        & comparisons["aggregation"].eq("aggregate")
        & comparisons["tail_group"].eq("all")
        & comparisons["model"].eq("ridge")
        & comparisons["benchmark"].eq("baseline")
    ]
    assert len(rows) == 1
    assert rows["relative_rmse_improvement_pct"].isna().all()
    assert rows["relative_mae_improvement_pct"].isna().all()
    assert rows.iloc[0]["delta_rmse_pp"] == pytest.approx(np.sqrt(1 / 15))


def write_saved_sensitivity(folder):
    frame, membership = checked_evidence()
    tables = sensitivity.summarize_sensitivity(frame, membership)
    (folder / "tables").mkdir()
    frame.to_csv(folder / "source_predictions.csv", index=False)
    pd.DataFrame({"row_id": [999]}).to_csv(folder / "source_reserved_identities.csv", index=False)
    membership.to_csv(folder / "membership.csv", index=False)
    for name, table in tables.items():
        table.to_csv(folder / "tables" / f"{name}.csv", index=False)


def test_independent_verifier_recomputes_every_saved_subset_and_score(tmp_path):
    write_saved_sensitivity(tmp_path)
    result = verify_sensitivity(tmp_path)
    assert result["passed"] is True
    assert result["subsets_checked"] == 12
    assert result["source_n_forecasts"] == 15
    assert result["model_variants"] == 3
    assert result["metric_rows_checked"] == 12 * 3 * 3 * 3
    assert result["comparison_rows_checked"] == 12 * 3 * 3 * 3 * 2
    assert result["final_test_evaluated"] is False
    assert result["reserved_responses_read"] is False


@pytest.mark.parametrize("tamper", ["membership", "reason", "audit", "metric", "comparison", "reserved"])
def test_independent_verifier_rejects_tampered_saved_evidence(tmp_path, tamper):
    write_saved_sensitivity(tmp_path)
    if tamper == "membership":
        path = tmp_path / "membership.csv"
        table = pd.read_csv(path)
        table.loc[0, "included"] = not table.loc[0, "included"]
    elif tamper == "reason":
        path = tmp_path / "membership.csv"
        table = pd.read_csv(path)
        table.loc[0, "exclusion_reason"] = "incorrect reason"
    elif tamper == "audit":
        path = tmp_path / "tables" / "audit.csv"
        table = pd.read_csv(path)
        table.loc[0, "n_overlapping_predecessors"] += 1
    elif tamper == "metric":
        path = tmp_path / "tables" / "metrics.csv"
        table = pd.read_csv(path)
        table.loc[0, "rmse_pp"] += 1.
    elif tamper == "comparison":
        path = tmp_path / "tables" / "comparisons.csv"
        table = pd.read_csv(path).iloc[1:]
    else:
        path = tmp_path / "source_reserved_identities.csv"
        table = pd.DataFrame({"row_id": [17]})
    table.to_csv(path, index=False)
    with pytest.raises(ValueError, match="Sensitivity verification"):
        verify_sensitivity(tmp_path)


def fixture_source_run(root):
    """A complete artificial eleven-variant parent and its immutable manifest."""
    source = root / "artifacts" / "runs" / "synthetic_temporal"
    source.mkdir(parents=True)
    base = fixture_predictions()
    ridge = base.loc[base["model"].eq("ridge")]
    extra = [ridge.assign(variant=variant, model=model)
             for variant in ("fixed", "tuned", "volatility_only")
             for model in ("ridge", "random_forest", "gradient_boosting")
             if (variant, model) != ("fixed", "ridge")]
    frame = pd.concat([base, *extra], ignore_index=True)
    frame.to_csv(source / "temporal_predictions.csv", index=False)
    identity_columns = ["row_id", "forecast_date", "session_number", "target_start", "target_end"]
    development = frame.drop_duplicates("row_id")[identity_columns].assign(partition="validation")
    reserved = pd.DataFrame({
        "row_id": [999], "forecast_date": ["2021-02-01"], "session_number": [135],
        "target_start": ["2021-02-02"], "target_end": ["2021-02-08"], "partition": ["test"],
    })
    reserved.to_csv(source / "reserved_identities.csv", index=False)
    pd.concat([development, reserved], ignore_index=True).to_csv(
        source / "source_split_assignments.csv", index=False
    )
    outer = frame.drop_duplicates("row_id")[sensitivity.IDENTITY].rename(columns={"fold": "outer_fold"})
    outer.assign(level="outer", partition="evaluation").to_csv(
        source / "temporal_membership.csv", index=False
    )
    record = {
        "run_id": "synthetic_temporal", "experiment": "retrospective_temporal",
        "status": "success", "final_test_evaluated": False,
        "reserved_rows_excluded": True, "calculation_verification_passed": True,
        "snapshot_sha256": "synthetic-no-price-snapshot",
        "config": {"research": {"horizon": 5}},
        "artifact_sha256": {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in sensitivity.INPUTS
        },
    }
    (source / "run_record.json").write_text(json.dumps(record), encoding="utf-8")
    # This artificial trap must not be opened, copied or scored by the runner.
    (source / "test_reserved.csv").write_text("reserved_response\n999999\n", encoding="utf-8")
    config_dir = root / "configs"
    config_dir.mkdir()
    config = config_dir / "sensitivity.toml"
    config.write_text('''[experiment]
strategy = "temporal_sensitivity"
[paths]
temporal_run = "artifacts/runs/synthetic_temporal"
output_dir = "artifacts/runs"
[sensitivity]
horizon = 5
primary_residue = 0
residues = [0, 1, 2, 3, 4]
containment = "target_start_and_end_in_forecast_calendar_year"
sampling = "original_session_number_modulo_horizon"
''', encoding="utf-8")
    return source, config


def test_runner_dispatch_is_offline_preserves_source_and_reproduces_scores(tmp_path, monkeypatch):
    import spy_volatility.core.data as data
    import spy_volatility.workflows.baseline as pipeline
    import spy_volatility.analysis.temporal as temporal
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge

    source, config = fixture_source_run(tmp_path)
    before = {file.name: file.read_bytes() for file in source.iterdir()}

    def forbidden(*args, **kwargs):
        pytest.fail("Sensitivity execution must not download prices or refit models")

    monkeypatch.setattr(data, "get_snapshot", forbidden)
    monkeypatch.setattr(data.yf, "download", forbidden)
    monkeypatch.setattr(pipeline, "get_snapshot", forbidden)
    monkeypatch.setattr(temporal, "_make_estimator", forbidden)
    for estimator in (Ridge, RandomForestRegressor, GradientBoostingRegressor):
        monkeypatch.setattr(estimator, "fit", forbidden)
    csv_reads = []
    original_read_csv, original_open = pd.read_csv, Path.open

    def protected_csv(path, *args, **kwargs):
        csv_reads.append(Path(path).name)
        assert Path(path).name != "test_reserved.csv"
        return original_read_csv(path, *args, **kwargs)

    def protected_open(path, *args, **kwargs):
        assert path.name != "test_reserved.csv"
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as access:
        access.setattr(pd, "read_csv", protected_csv)
        access.setattr(Path, "open", protected_open)
        # Omitting --offline still cannot trigger the price-loader path.
        first = pipeline.run_phase1(config, offline=False)
        second = pipeline.run_phase1(config, offline=True)
    first_path, second_path = Path(first["output_dir"]), Path(second["output_dir"])
    assert first_path != second_path
    assert first["calculation_verification_passed"] is True
    assert first["test_evaluated"] is False
    assert first["sample_counts"] == second["sample_counts"]
    for name in ("membership.csv", "tables/metrics.csv", "tables/comparisons.csv", "tables/audit.csv"):
        assert (first_path / name).read_bytes() == (second_path / name).read_bytes()
    assert {file.name: file.read_bytes() for file in source.iterdir()} == before
    assert "reserved_identities.csv" in csv_reads
    assert "test_reserved.csv" not in csv_reads
    assert not (first_path / "test_reserved.csv").exists()
    record = json.loads((first_path / "run_record.json").read_text(encoding="utf-8"))
    assert record["status"] == "success"
    assert record["offline"] is True
    assert record["models_refitted"] is False
    assert record["reserved_responses_read"] is False
    assert record["final_test_evaluated"] is False
    assert record["parent_run_id"] == "synthetic_temporal"
    for relative, expected_hash in record["artifact_sha256"].items():
        assert hashlib.sha256((first_path / relative).read_bytes()).hexdigest() == expected_hash


def test_runner_rejects_corrupted_source_hash_before_creating_output(tmp_path):
    source, config = fixture_source_run(tmp_path)
    prediction_path = source / "temporal_predictions.csv"
    prediction_path.write_bytes(prediction_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Source artifact hash mismatch"):
        sensitivity.run_sensitivity(config)
    assert list(source.parent.iterdir()) == [source]


@pytest.mark.parametrize("key,value", [
    ("status", "failed"), ("final_test_evaluated", True),
    ("reserved_rows_excluded", False), ("calculation_verification_passed", False),
])
def test_runner_rejects_unverified_or_unprotected_parent(tmp_path, key, value):
    source, config = fixture_source_run(tmp_path)
    record_path = source / "run_record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record[key] = value
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="successful verified temporal run"):
        sensitivity.run_sensitivity(config)
