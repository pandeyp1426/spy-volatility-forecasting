"""Pilot arithmetic, frozen research equivalence and no-fit/no-outcome guards."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import tomllib

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from spy_volatility.core import data, research
from spy_volatility.core.models import FEATURE_COLUMNS
from spy_volatility.workflows import pilot, prospective

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 11, 23, tzinfo=timezone.utc)


def model():
    return {"format_version": 1, "model": "ridge", "features": list(FEATURE_COLUMNS), "alpha": 1.,
            "units": "decimal daily-return volatility", "prediction_floor": 0.,
            "scaler_mean": [.001, .009, .01, .011, .005],
            "scaler_scale": [.01, .005, .006, .007, .02],
            "ridge_coefficients": [-.001, .002, .003, .004, -.002], "ridge_intercept": .01,
            "n_training_rows": 32, "training_label_cutoff": "2025-12-31", "refit": False}


def prices_for(schedule):
    returns = np.array([.008, -.015, .003, -.009, .017] * 4)
    return pd.Series(500 * np.exp(np.r_[0., returns.cumsum()]), index=schedule.index[:21], name="adjusted_close")


@pytest.mark.parametrize("instant,origin,close", [
    ("2026-11-15T23:00Z", "2026-11-13", "2026-11-13T21:00Z"),  # weekend
    ("2026-11-26T23:00Z", "2026-11-25", "2026-11-25T21:00Z"),  # holiday
    ("2026-11-27T18:00Z", "2026-11-25", "2026-11-25T21:00Z"),  # strictly after
    ("2026-11-27T18:01Z", "2026-11-27", "2026-11-27T18:00Z"),  # early close
    ("2026-03-09T20:01Z", "2026-03-09", "2026-03-09T20:00Z"),  # DST
    ("2026-11-11T20:59Z", "2026-11-10", "2026-11-10T21:00Z"),
])
def test_calendar_completed_sessions(instant, origin, close):
    schedule = pilot.pilot_schedule(pd.Timestamp(instant).to_pydatetime())
    assert len(schedule) == 26
    assert schedule.index[20] == pd.Timestamp(origin)
    assert schedule.market_close.iloc[20] == pd.Timestamp(close)
    assert (schedule.market_close.iloc[:21] < pd.Timestamp(instant)).all()
    assert (schedule.index[21:] > pd.Timestamp(origin)).all()


def test_current_origin_future_sessions_and_naive_time_rejection():
    s = pilot.pilot_schedule(NOW)
    assert s.index[21:].strftime("%Y-%m-%d").tolist() == ["2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18"]
    with pytest.raises(ValueError, match="timezone-aware"):
        pilot.pilot_schedule(datetime(2026, 11, 11))


def test_predictor_extraction_matches_unchanged_frozen_research():
    # Artificial prices only: the frozen implementation requires five future rows.
    bundle = ROOT / tomllib.loads((ROOT / "configs/pilot.toml").read_text())["prepared"]["bundle"]
    source = bundle / "source/research.py"
    if not source.exists():
        pytest.skip("Optional local frozen research bundle unavailable")
    freeze = json.loads((bundle / "freeze_record.json").read_text())
    assert pilot.sha(source) == freeze["source_sha256"]["spy_volatility/research.py"]
    spec = importlib.util.spec_from_file_location("frozen_pilot_research", source)
    frozen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen)
    rng = np.random.default_rng(17)
    p = pd.Series(500 * np.exp(np.r_[0., rng.normal(.0004, .012, 89).cumsum()]),
                  index=pd.bdate_range("2026-01-02", periods=90))
    pd.testing.assert_frame_equal(research.build_features(p), frozen.build_features(p))
    # Each origin is computed using only its 21 historical prices. The frozen
    # code's complete examples must agree regardless of the synthetic future.
    for pos in (20, 31, 70):
        actual = research.build_predictors(p.iloc[pos-20:pos+1]).iloc[-1]
        expected = frozen.build_features(p).loc[p.index[pos], [*FEATURE_COLUMNS, "baseline"]]
        np.testing.assert_allclose(actual.to_numpy(float), expected.to_numpy(float), rtol=1e-9, atol=1e-12)


@pytest.mark.parametrize("negative", [False, True])
def test_calculation_independent_arithmetic_and_floor(negative):
    s, m = pilot.pilot_schedule(NOW), model()
    if negative:
        m["ridge_coefficients"], m["ridge_intercept"] = [0.] * 5, -.01
    result, verification, returns = pilot.calculate(prices_for(s), m, s)
    assert verification["passed"] and len(returns) == 20
    assert result["feature_order"] == list(FEATURE_COLUMNS)
    assert result["predictions"]["baseline"] == result["features"]["volatility_20"]
    assert result["predictions"]["baseline_5"] == result["features"]["volatility_5"]
    if negative:
        assert result["predictions"]["ridge"] == 0.
        assert result["predictions"]["ridge_raw"] == -.01
        assert result["floor_applied"] is True


@pytest.mark.parametrize("bad", ["short", "missing", "extra", "duplicate", "unsorted", "zero", "nan", "inf"])
def test_invalid_or_nonconsecutive_prices_fail(bad):
    s = pilot.pilot_schedule(NOW)
    p = prices_for(s)
    if bad == "short":
        p = p.iloc[1:]
    elif bad == "missing":
        dates = list(p.index)
        dates[5] = dates[5] + pd.Timedelta(days=1)
        p.index = pd.DatetimeIndex(dates)
    elif bad == "extra":
        p = pd.concat([p, pd.Series([510.], index=s.index[21:22])])
    elif bad == "duplicate":
        p.index = pd.DatetimeIndex([p.index[1], *p.index[1:]])
    elif bad == "unsorted":
        p = p.iloc[::-1]
    else:
        p.iloc[3] = {"zero": 0., "nan": np.nan, "inf": np.inf}[bad]
    with pytest.raises(ValueError):
        pilot.calculate(p, model(), s)


def test_independent_verifier_detects_changed_research_formula(monkeypatch):
    original = pilot.build_predictors
    def wrong_ddof(prices):
        f = original(prices)
        f["volatility_5"] *= np.sqrt(4 / 5)
        return f
    monkeypatch.setattr(pilot, "build_predictors", wrong_ddof)
    s = pilot.pilot_schedule(NOW)
    with pytest.raises(AssertionError, match="volatility_5"):
        pilot.calculate(prices_for(s), model(), s)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """A transparent artificial bundle: no training or genuine response data."""
    bundle = tmp_path / "artifacts/protocols/artificial"
    (bundle / "source").mkdir(parents=True)
    (bundle / "inputs").mkdir()
    shutil.copy2(ROOT / "configs/prospective.toml", bundle / "source/prospective.toml")
    for name in ("prospective_protocol.md", "uncertainty_protocol.md"):
        (bundle / "source" / name).write_text("Artificial test protocol document")
    (bundle / "source/research.py").write_text("# artificial source")
    (bundle / "inputs/identities.csv").write_text("row_id\n1\n")
    pilot.write_json(bundle / "model.json", model())
    pilot.write_json(bundle / "preparation_verification.json", {"status": "passed"})
    record = {"bundle_id": bundle.name, "status": "prepared_not_live", "model_sha256": pilot.sha(bundle / "model.json"),
              "reserved_rows_excluded": True, "reserved_responses_read": False, "final_test_evaluated": False,
              "n_training_rows": 32, "prepared_at_utc": NOW.isoformat(),
              "config": tomllib.loads((ROOT / "configs/prospective.toml").read_text()),
              "config_sha256": pilot.sha(bundle / "source/prospective.toml"),
              "source_sha256": {"spy_volatility/research.py": pilot.sha(bundle / "source/research.py")},
              "source_artifact_sha256": {"identities.csv": pilot.sha(bundle / "inputs/identities.csv")},
              "artifact_sha256": {p.relative_to(bundle).as_posix(): pilot.sha(p) for p in bundle.rglob("*") if p.is_file()}}
    pilot.write_json(bundle / "freeze_record.json", record)
    (tmp_path / "configs").mkdir()
    config = tmp_path / "configs/pilot.toml"
    config.write_text(f'[prepared]\nbundle = "artifacts/protocols/artificial"\nfreeze_record_sha256 = "{pilot.sha(bundle / "freeze_record.json")}"\nmodel_sha256 = "{record["model_sha256"]}"\n[paths]\noutput_dir = "artifacts/pilots"\n')
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(pilot, "datetime", Clock)
    monkeypatch.setattr(data, "datetime", Clock)
    def forbidden(*args, **kwargs):
        pytest.fail("No fitting or historical response loading permitted")
    monkeypatch.setattr(Ridge, "fit", forbidden)
    monkeypatch.setattr(StandardScaler, "fit", forbidden)
    monkeypatch.setattr(prospective, "load_training", forbidden)
    read_csv = pd.read_csv
    def guarded(path, *args, **kwargs):
        assert not any(n in str(path) for n in ("development.csv", "test_reserved", "reserved_identities"))
        return read_csv(path, *args, **kwargs)
    monkeypatch.setattr(pd, "read_csv", guarded)
    return config, bundle


def provider_response():
    p = prices_for(pilot.pilot_schedule(NOW))
    return pd.DataFrame({"Adj Close": p, "Close": p * 1.01})


def test_run_replay_provenance_request_and_preservation(prepared, monkeypatch):
    config, bundle = prepared
    before = {p.relative_to(bundle): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    calls = []
    def download(**settings):
        calls.append(settings)
        return provider_response()
    monkeypatch.setattr(data.yf, "download", download)
    record = pilot.run_pilot(config)
    assert record["status"] == "success", record.get("error")
    assert calls == [data._request_settings(record["data_config"])]
    assert calls[0]["auto_adjust"] is False and calls[0]["repair"] is False
    assert record["forecast"]["latest_adjusted_close"] != provider_response().Close.iloc[-1]
    assert record["prospective_on_time_claim"] is False
    assert record["is_2027_evaluation"] is False
    monkeypatch.setattr(data.yf, "download", lambda **kw: pytest.fail("Replay must be offline"))
    replay = pilot.replay(record["output_dir"])
    assert replay["forecast"] == record["forecast"] and replay["new_forecast_issued"] is False
    assert before == {p.relative_to(bundle): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    raw = Path(record["output_dir"]) / "snapshot/raw.csv"
    raw.write_text(raw.read_text() + "\n")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        pilot.replay(record["output_dir"])


@pytest.mark.parametrize("failure", ["empty", "stale", "missing_adjusted", "missing_model", "changed_model", "changed_protocol"])
def test_failed_attempt_retains_reason_without_forecast(prepared, monkeypatch, failure):
    config, bundle = prepared
    response = provider_response()
    if failure == "empty":
        response = pd.DataFrame()
    elif failure == "stale":
        response = response.iloc[:-1]
    elif failure == "missing_adjusted":
        response = response.drop(columns="Adj Close")
    elif failure == "missing_model":
        (bundle / "model.json").rename(bundle / "unavailable_model.json")
    elif failure == "changed_model":
        (bundle / "model.json").write_text("{}")
    elif failure == "changed_protocol":
        (bundle / "source/prospective_protocol.md").write_text("changed")
    monkeypatch.setattr(data.yf, "download", lambda **kw: response)
    record = pilot.run_pilot(config)
    assert record["status"] == "failed" and record["error"]
    assert "forecast" not in record
    assert (Path(record["output_dir"]) / "pilot_record.json").exists()
    with pytest.raises(ValueError, match="successful"):
        pilot.replay(record["output_dir"])
