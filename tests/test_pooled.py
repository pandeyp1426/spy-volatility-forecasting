"""Pooled protocol checks use synthetic prices; no real test responses are read."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from spy_volatility.pooled import split_pooled, audit_overlap, verify_pooled
from spy_volatility.research import build_features
from spy_volatility.models import compare_validation, model_frame, FEATURE_COLUMNS, TARGET_COLUMN
from spy_volatility.eda import session_lag_correlations
from spy_volatility.data import audit_raw_fields, DataAuditError
from spy_volatility.verification import CalculationVerificationError


@pytest.fixture
def examples():
    dates = pd.bdate_range("2014-11-01", periods=170)
    r = .01*np.sin(np.arange(len(dates))*.7) + .003*np.cos(np.arange(len(dates))*.13)
    return build_features(pd.Series(100*np.exp(np.cumsum(r)), index=dates))


def test_exact_membership_rounding_and_no_mutation(examples):
    before = examples.copy(deep=True)
    splits, summary = split_pooled(examples)
    order = np.random.default_rng(42).permutation(len(examples))
    a, b = int(.7*len(examples)), int(.15*len(examples))
    for name, ids in zip(("train", "validation", "test"), (order[:a], order[a:a+b], order[a+b:])):
        assert splits[name]["row_id"].tolist() == sorted(ids)
        assert splits[name].index.equals(examples.index[np.sort(ids)])
        pd.testing.assert_frame_equal(splits[name], split_pooled(examples)[0][name])
    assert sum(map(len, splits.values())) == len(examples)
    assert len(set().union(*(set(p["row_id"]) for p in splits.values()))) == len(examples)
    pd.testing.assert_frame_equal(examples, before)
    assert summary["stratification"] is None


def test_overlap_uses_original_sessions_not_row_ids():
    def frame(sessions):
        return pd.DataFrame({"session_number": sessions}, index=pd.DatetimeIndex([
            pd.Timestamp("2015-01-01")+pd.Timedelta(days=int(s)) for s in sessions]))
    result = audit_overlap({"train": frame([20, 40]), "validation": frame([21]), "test": frame([25, 46])})
    assert result["validation"]["rows_with_training_outcome_overlap"] == 1
    assert result["validation"]["rows_with_training_feature_overlap"] == 1
    assert result["test"]["rows_with_training_outcome_overlap"] == 0
    assert result["test"]["rows_with_training_feature_overlap"] == 1


@pytest.mark.parametrize("kwargs", [{"seed": True}, {"train_fraction": .9, "validation_fraction": .2},
                                    {"validation_fraction": float("nan")}, {"seed": -1}])
def test_invalid_splits(examples, kwargs):
    with pytest.raises(ValueError):
        split_pooled(examples, **kwargs)


def test_year_boundary_alignment_before_random_split():
    dates = pd.bdate_range("2014-11-01", "2015-02-01")
    known = np.sin(np.arange(len(dates)))*.01
    prices = pd.Series(100*np.exp(np.cumsum(known)), index=dates)
    examples = build_features(prices)
    first = examples.loc[examples.index >= "2015-01-01"].iloc[0]
    pos = int(first["session_number"])
    assert first["volatility_20"] == pytest.approx(np.std(known[pos-19:pos+1], ddof=1))
    assert first["target"] == pytest.approx(np.std(known[pos+1:pos+6], ddof=1))
    assert first["momentum_5"] == pytest.approx(np.log(prices.iloc[pos]/prices.iloc[pos-5]))
    assert examples.index[-1] == dates[-6]


def test_train_only_scaler_explicit_allowlist_and_common_metrics(examples):
    splits, _ = split_pooled(examples)
    train, validation = splits["train"], splits["validation"].copy()
    validation.loc[:, "momentum_5"] += 1
    predictions, metrics, record = compare_validation(train, validation)
    assert record["feature_columns"] == list(FEATURE_COLUMNS)
    assert record["ridge_scaler"]["mean"] == pytest.approx(train[list(FEATURE_COLUMNS)].mean().to_numpy())
    assert record["ridge_scaler"]["n_samples_seen"] == len(train)
    assert record["test_scored"] is False
    assert predictions.index.equals(validation.index)
    assert (metrics.n_forecasts == len(validation)).all()
    for row in metrics.itertuples():
        errors = 100*(predictions[row.model]-validation.target)
        assert row.mae_pp == pytest.approx(errors.abs().mean())
        assert row.rmse_pp == pytest.approx(np.sqrt((errors**2).mean()))
        assert row.bias_pp == pytest.approx(errors.mean())
        assert (predictions[row.model] >= 0).all()
    assert list(model_frame(train)) == [*FEATURE_COLUMNS, TARGET_COLUMN]
    with pytest.raises(ValueError, match="disjoint"):
        compare_validation(train, train)
    conflicting = train.copy()
    conflicting[TARGET_COLUMN] = conflicting.target + 1
    with pytest.raises(ValueError, match="disagree"):
        model_frame(conflicting)


def test_lag_pairs_do_not_compress_missing_sessions(examples):
    train = examples.iloc[[0, 1, 4, 5, 9]].copy()
    table = session_lag_correlations(train, lags=(1, 4))
    rows = table[table.variable == "log_return"].set_index("lag_sessions")
    assert rows.loc[1, "pair_count"] == 2
    assert rows.loc[4, "pair_count"] == 3
    assert rows.loc[1, "pearson"] == pytest.approx(np.corrcoef(
        train.log_return.iloc[[1, 3]], train.log_return.iloc[[0, 2]])[0, 1])


def test_raw_ohlc_does_not_mix_adjusted_and_unadjusted_prices():
    frame = pd.DataFrame({"Open": [100.], "Close": [101.], "High": [102.], "Low": [99.],
                          "Adj Close": [50.], "Volume": [100.], "Dividends": [1.], "Stock Splits": [0.]},
                         index=pd.DatetimeIndex(["2015-01-02"]))
    assert audit_raw_fields(frame)["passed"]
    frame.loc[:, "High"] = 100.
    with pytest.raises(DataAuditError, match="OHLC"):
        audit_raw_fields(frame)


def test_pooled_pipeline_never_evaluates_test(tmp_path, monkeypatch):
    from spy_volatility import pooled
    from spy_volatility.pipeline import run_phase1
    dates = pd.bdate_range("2014-11-01", periods=190)
    values = 100*np.exp(np.cumsum(.01*np.sin(np.arange(len(dates)))))
    prices = pd.Series(values, index=dates)
    source = Path(__file__).resolve().parents[1]/"configs"/"pooled.toml"
    config_path = tmp_path/"configs"/"pooled.toml"
    config_path.parent.mkdir()
    config_path.write_text(source.read_text(), encoding="utf-8")
    raw_dir = tmp_path/"data/raw/spy_2014-11-01_2026-01-01"
    raw_dir.mkdir(parents=True)
    pd.DataFrame({"Adj Close": prices}).to_csv(raw_dir/"raw.csv", index_label="Date")
    monkeypatch.setattr(pooled, "get_snapshot", lambda *a, **kw: (prices, {"sha256": "synthetic"}, {"passed": True}))
    monkeypatch.setattr(pooled, "audit_raw_fields", lambda raw: {"passed": True})
    eligible = build_features(prices).loc[lambda x: x.index >= "2015-01-01"]
    expected, _ = split_pooled(eligible)
    compare = pooled.compare_validation
    def guarded_compare(train, validation):
        assert train.index.equals(expected["train"].index)
        assert validation.index.equals(expected["validation"].index)
        return compare(train, validation)
    monkeypatch.setattr(pooled, "compare_validation", guarded_compare)
    eda = pooled.write_training_eda
    def guarded_eda(train, output):
        assert train.index.equals(expected["train"].index)
        return eda(train, output)
    monkeypatch.setattr(pooled, "write_training_eda", guarded_eda)
    result = run_phase1(config_path, offline=True)
    out = Path(result["output_dir"])
    record = json.loads((out/"run_record.json").read_text())
    assert record["final_test_evaluated"] is False
    assert record["status"] == "success"
    assert (out/"reserved/test_matrix.csv").exists()
    assert not list(out.rglob("*test*prediction*"))
    # Independent verification must not open test files, even if corrupt.
    (out/"reserved/test_matrix.csv").write_text("sealed test; do not read")
    config = json.loads((out/"run_record.json").read_text())["config"]
    assert verify_pooled(out, prices, config)["passed"]
    saved = pd.read_csv(out/"validation_predictions.csv")
    saved.loc[0, "ridge"] += 1
    saved.to_csv(out/"validation_predictions.csv", index=False)
    with pytest.raises(CalculationVerificationError):
        verify_pooled(out, prices, config)
