"""Artificial-source checks for the frozen 2027 study; no future prices are read."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tomllib

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

import spy_volatility.workflows.prospective as prospective
from spy_volatility.core.models import FEATURE_COLUMNS, TARGET_COLUMN


NOW = datetime(2026, 11, 11, 18, tzinfo=timezone.utc)


def configuration():
    return {"experiment": {"strategy": "prospective_protocol", "name": "frozen_ridge_2027"},
            "paths": {"temporal_run": "artifacts/source", "output_dir": "artifacts/protocols"},
            "training": deepcopy(prospective.TRAINING), "evaluation": deepcopy(prospective.EVALUATION),
            "uncertainty": deepcopy(prospective.UNCERTAINTY)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artificial_source(root):
    source = root / "artifacts" / "source"
    source.mkdir(parents=True)
    # Include a gap from reserved IDs and the exact frozen target-end cutoff.
    dates = pd.bdate_range("2025-11-03", periods=40)
    identities = pd.DataFrame({"forecast_date": dates[:-5], "row_id": np.arange(35),
                               "session_number": np.arange(700, 735),
                               "target_start": dates[1:-4], "target_end": dates[5:]})
    identities["partition"] = "train"
    identities.loc[[2, 9, 23], "partition"] = "test"
    identities.loc[[7, 16, 30], "partition"] = "validation"
    allowed = identities.loc[identities.partition.ne("test")].drop(columns="partition").copy()
    position = allowed.row_id.to_numpy(float)
    allowed["log_return"] = np.sin(position) * .01
    allowed["volatility_5"] = .006 + position * .0002
    allowed["volatility_10"] = .007 + np.cos(position) * .001
    allowed["volatility_20"] = .01 + position * .0001
    allowed["momentum_5"] = np.cos(position / 3) * .02
    allowed["target"] = .005 + .5 * allowed.volatility_5 + .02 * allowed.momentum_5
    allowed.to_csv(source / "development.csv", index=False)
    identities.to_csv(source / "source_split_assignments.csv", index=False)
    identities.loc[identities.partition.eq("test")].to_csv(source / "reserved_identities.csv", index=False)
    # A trap file is present but never belongs to any permitted input list.
    (source / "test_reserved.csv").write_text("never open reserved outcomes", encoding="utf-8")
    record = {"run_id": "artificial_parent", "status": "success", "experiment": "retrospective_temporal",
              "final_test_evaluated": False, "reserved_rows_excluded": True,
              "calculation_verification_passed": True,
              "config": {"research": deepcopy(prospective.RESEARCH), "data": {"ticker": "SPY"}},
              "snapshot_sha256": "artificial_snapshot",
              "artifact_sha256": {name: digest(source / name) for name in prospective.INPUTS}}
    (source / "run_record.json").write_text(json.dumps(record), encoding="utf-8")
    config_dir = root / "configs"
    config_dir.mkdir()
    # Reuse the actual frozen specification, changing only the local source path.
    template = Path(__file__).resolve().parents[2] / "configs" / "prospective.toml"
    text = template.read_text(encoding="utf-8").replace(
        "artifacts/runs/20261027T001114_temporal_4bf4a071", "artifacts/source")
    config_path = config_dir / "prospective.toml"
    config_path.write_text(text, encoding="utf-8")
    return source, config_path


def refresh_record(source):
    path = source / "run_record.json"
    record = json.loads(path.read_text())
    record["artifact_sha256"] = {name: digest(source / name) for name in prospective.INPUTS}
    path.write_text(json.dumps(record), encoding="utf-8")


def test_exact_freeze_rule_and_local_calendar_boundary():
    config = configuration()
    prospective.validate_protocol(config, NOW)
    # UTC New Year's Day is still the preceding local date before 06:00 UTC.
    prospective.validate_protocol(config, datetime(2027, 1, 1, 5, 59, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="precede"):
        prospective.validate_protocol(config, datetime(2027, 1, 1, 6, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="timezone-aware"):
        prospective.validate_protocol(config, datetime(2026, 11, 11))
    with pytest.raises(ValueError, match="labels must be available"):
        prospective.validate_protocol(config, datetime(2025, 12, 31, 18, tzinfo=timezone.utc))


@pytest.mark.parametrize("section,key,value", [
    ("training", "alpha", 10.), ("training", "refit", True),
    ("evaluation", "start", "2026-01-01"), ("evaluation", "horizon", 10),
    ("uncertainty", "primary_expected_block_length", 5),
    ("uncertainty", "primary_family_individual_coverage", .95),
])
def test_protocol_rejects_unannounced_design_changes(section, key, value):
    config = configuration()
    config[section][key] = value
    with pytest.raises(ValueError, match="must not be changed"):
        prospective.validate_protocol(config, NOW)


def test_calendar_has_contained_targets_and_early_close_deadlines():
    schedule = prospective.build_schedule(configuration())
    eligible = schedule.loc[schedule.eligible_forecast_origin]
    assert len(schedule) == 251 and len(eligible) == 246
    assert eligible.forecast_date.iloc[0] == pd.Timestamp("2027-01-04")
    assert eligible.forecast_date.iloc[-1] == pd.Timestamp("2027-12-23")
    assert eligible.target_end.iloc[-1] == pd.Timestamp("2027-12-31")
    assert not schedule.eligible_forecast_origin.iloc[-5:].any()
    early = schedule.set_index("forecast_date").loc["2027-11-26"]
    assert early.market_close == pd.Timestamp("2027-11-26 18:00Z")
    assert early.issue_deadline_utc == pd.Timestamp("2027-11-26 20:00Z")
    assert schedule.issue_deadline_utc.sub(schedule.market_close).eq(pd.Timedelta(hours=2)).all()
    assert eligible.label_deadline_utc.sub(eligible.target_close_utc).eq(pd.Timedelta(hours=24)).all()
    assert eligible.target_end.dt.year.eq(2027).all()


@pytest.mark.parametrize("field,value", [
    ("status", "failed"), ("final_test_evaluated", True),
    ("reserved_rows_excluded", False), ("calculation_verification_passed", False),
    ("experiment", "pooled_random"),
])
def test_rejects_unverified_or_wrong_parent(tmp_path, field, value):
    source, _ = artificial_source(tmp_path)
    path = source / "run_record.json"
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="verified temporal parent"):
        prospective.load_training(source, configuration())


def test_rejects_parent_target_definition_and_ticker_changes(tmp_path):
    source, _ = artificial_source(tmp_path)
    path = source / "run_record.json"
    record = json.loads(path.read_text())
    record["config"]["research"]["momentum_window"] = 10
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="verified temporal parent"):
        prospective.load_training(source, configuration())
    record["config"]["research"] = deepcopy(prospective.RESEARCH)
    record["config"]["data"]["ticker"] = "QQQ"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="verified temporal parent"):
        prospective.load_training(source, configuration())


def test_hash_mismatch_fails_before_loading_training_outcomes(tmp_path, monkeypatch):
    source, _ = artificial_source(tmp_path)
    with (source / "development.csv").open("a") as stream:
        stream.write("\n")
    monkeypatch.setattr(pd, "read_csv", lambda *args, **kwargs: pytest.fail("Changed input was read"))
    with pytest.raises(ValueError, match="hash mismatch"):
        prospective.load_training(source, configuration())


@pytest.mark.parametrize("tamper", ["reserved_row", "missing_allowed", "future_label", "fractional_id", "metadata"])
def test_identity_and_label_guards_even_with_matching_hashes(tmp_path, tamper):
    source, _ = artificial_source(tmp_path)
    path = source / "development.csv"
    frame = pd.read_csv(path)
    if tamper == "reserved_row":
        frame.loc[0, "row_id"] = 2
    elif tamper == "missing_allowed":
        frame = frame.iloc[1:]
    elif tamper == "fractional_id":
        frame["row_id"] = frame.row_id.astype(float)
        frame.loc[0, "row_id"] = .5
    elif tamper == "metadata":
        frame.loc[0, "session_number"] = 699
    else:
        # Keep identity maps in agreement so the target-availability rule is exercised.
        frame.loc[frame.index[-1], "target_end"] = "2026-01-02"
        assignments = pd.read_csv(source / "source_split_assignments.csv")
        assignments.loc[assignments.row_id.eq(frame.row_id.iloc[-1]), "target_end"] = "2026-01-02"
        assignments.to_csv(source / "source_split_assignments.csv", index=False)
    frame.to_csv(path, index=False)
    refresh_record(source)
    with pytest.raises(ValueError):
        prospective.load_training(source, configuration())


def test_freeze_roundtrip_equivalence_provenance_and_no_future_or_reserved_access(tmp_path, monkeypatch):
    source, config_path = artificial_source(tmp_path)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    read_csv = pd.read_csv
    copy = prospective.shutil.copy2
    def guarded_read(path, *args, **kwargs):
        assert "test_reserved" not in str(path)
        return read_csv(path, *args, **kwargs)
    def guarded_copy(path, *args, **kwargs):
        assert "test_reserved" not in str(path)
        return copy(path, *args, **kwargs)
    monkeypatch.setattr(pd, "read_csv", guarded_read)
    monkeypatch.setattr(prospective.shutil, "copy2", guarded_copy)
    monkeypatch.setattr("spy_volatility.core.data.get_snapshot", lambda *args, **kwargs: pytest.fail("No price loading allowed"))
    monkeypatch.setattr("spy_volatility.core.data.yf.download", lambda *args, **kwargs: pytest.fail("No download allowed"))
    first = prospective.freeze_prospective(config_path, now=NOW)
    second = prospective.freeze_prospective(config_path, now=NOW)
    assert first["bundle_id"] != second["bundle_id"]
    a, b = Path(first["output_dir"]), Path(second["output_dir"])
    assert (a / "model.json").read_bytes() == (b / "model.json").read_bytes()
    assert (a / "evaluation_schedule.csv").read_bytes() == (b / "evaluation_schedule.csv").read_bytes()
    record = json.loads((a / "freeze_record.json").read_text())
    model = json.loads((a / "model.json").read_text())
    assert record["status"] == "prepared_not_live"
    assert record["historical_model_fitted"] is True
    assert record["n_training_rows"] == 32
    for field in ("future_data_downloaded", "future_period_evaluated", "final_test_evaluated", "live_forecasting_started", "reserved_responses_read"):
        assert record[field] is False
    for name, expected in record["artifact_sha256"].items():
        assert digest(a / name) == expected
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    training, _, _ = prospective.load_training(source, configuration())
    x, y = training[list(FEATURE_COLUMNS)], training[TARGET_COLUMN]
    scaler = StandardScaler().fit(x)
    ridge = Ridge(alpha=1.).fit(scaler.transform(x), y)
    actual = prospective.predict_frozen(model, x)
    np.testing.assert_allclose(actual.ridge, np.maximum(ridge.predict(scaler.transform(x)), 0), rtol=1e-12, atol=1e-14)
    np.testing.assert_array_equal(actual.baseline, x.volatility_20)
    np.testing.assert_array_equal(actual.baseline_5, x.volatility_5)
    np.testing.assert_allclose(model["scaler_mean"], x.mean().to_numpy())
    assert model["training_target_q95"] == pytest.approx(np.quantile(y, .95))
    assert not (a / "inputs" / "test_reserved.csv").exists()


@pytest.mark.parametrize("tamper", ["order", "scale", "coefficient", "floor", "nan_feature", "negative_volatility"])
def test_frozen_prediction_rejects_invalid_model_and_features(tamper):
    model = {"format_version": 1, "features": list(FEATURE_COLUMNS), "prediction_floor": 0.,
             "scaler_mean": [0.] * 5, "scaler_scale": [1.] * 5, "ridge_coefficients": [1.] * 5,
             "ridge_intercept": 0.}
    frame = pd.DataFrame([[.01] * 5], columns=FEATURE_COLUMNS)
    if tamper == "order":
        model["features"] = list(reversed(FEATURE_COLUMNS))
    elif tamper == "scale":
        model["scaler_scale"][0] = 0.
    elif tamper == "coefficient":
        model["ridge_coefficients"][0] = np.inf
    elif tamper == "floor":
        model["prediction_floor"] = -1.
    elif tamper == "nan_feature":
        frame.loc[0, "log_return"] = np.nan
    else:
        frame.loc[0, "volatility_5"] = -.01
    with pytest.raises(ValueError):
        prospective.predict_frozen(model, frame)


def test_frozen_prediction_floors_negative_ridge_without_changing_benchmarks():
    model = {"format_version": 1, "features": list(FEATURE_COLUMNS), "prediction_floor": 0.,
             "scaler_mean": [0.] * 5, "scaler_scale": [1.] * 5, "ridge_coefficients": [0.] * 5,
             "ridge_intercept": -.01}
    frame = pd.DataFrame([[.01, .02, .03, .04, .05]], columns=FEATURE_COLUMNS)
    result = prospective.predict_frozen(model, frame)
    assert result.iloc[0].to_dict() == {"ridge": 0., "baseline": .04, "baseline_5": .02}
