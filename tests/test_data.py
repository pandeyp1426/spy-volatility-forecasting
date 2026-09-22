"""Artificial, deterministic fixtures only: these tests do not contact Yahoo."""

import json
import logging

import numpy as np
import pandas as pd
import pytest

from spy_volatility.data import (
    DataAuditError,
    DownloadError,
    SnapshotError,
    audit_prices,
    get_snapshot,
    normalize_download,
)


@pytest.fixture
def prices():
    # Artificial prices for every NYSE session in this short requested interval.
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"])
    return pd.Series(np.arange(7, dtype=float) + 100, index=dates, name="Adj Close")


@pytest.fixture
def config():
    return {"ticker": "SPY", "start": "2024-01-02", "end": "2024-01-11", "calendar": "NYSE"}


def audit(prices):
    return audit_prices(prices, "2024-01-02", "2024-01-11")


def test_audit_complete_nyse_sessions(prices):
    report = audit(prices)
    assert report["passed"]
    assert report["expected_session_count"] == 7
    assert report["missing_sessions"] == []
    assert report["unexpected_sessions"] == []


@pytest.mark.parametrize("position", [0, 3, -1])
def test_audit_missing_sessions_including_request_edges(prices, position):
    missing_date = prices.index[position]
    with pytest.raises(DataAuditError) as caught:
        audit(prices.drop(missing_date))
    assert caught.value.report["missing_sessions"] == [missing_date.isoformat()]


@pytest.mark.parametrize("value,key", [(np.nan, "missing_price_dates"), (np.inf, "nonfinite_price_dates"), (-np.inf, "nonfinite_price_dates"), (0, "nonpositive_price_dates"), (-1, "nonpositive_price_dates")])
def test_audit_bad_prices(prices, value, key):
    prices.iloc[2] = value
    with pytest.raises(DataAuditError) as caught:
        audit(prices)
    assert prices.index[2].isoformat() in caught.value.report[key]


def test_audit_order_and_duplicates_without_repair(prices):
    bad = pd.concat([prices.iloc[1:], prices.iloc[:2]])
    original = bad.copy()
    with pytest.raises(DataAuditError) as caught:
        audit(bad)
    assert not caught.value.report["chronological_order"]
    assert len(caught.value.report["duplicate_dates"]) == 2
    pd.testing.assert_series_equal(bad, original)


def test_audit_weekend_is_unexpected(prices):
    bad = pd.concat([prices, pd.Series([101.0], index=pd.to_datetime(["2024-01-06"]))]).sort_index()
    with pytest.raises(DataAuditError) as caught:
        audit(bad)
    assert caught.value.report["unexpected_sessions"] == ["2024-01-06T00:00:00"]


def test_exchange_holiday_is_not_missing():
    # Christmas Day is excluded by the exchange calendar, including at the edge.
    fixture = pd.Series([100.0], index=pd.to_datetime(["2023-12-26"]))
    assert audit_prices(fixture, "2023-12-25", "2023-12-27")["passed"]


@pytest.mark.parametrize("reverse_levels", [False, True])
def test_normalize_single_ticker_multiindex(prices, reverse_levels):
    raw = pd.DataFrame({"Close": prices + 2, "Adj Close": prices})
    raw.columns = pd.MultiIndex.from_tuples([(column, "SPY") for column in raw.columns])
    if reverse_levels:
        raw.columns = raw.columns.swaplevel()
    result = normalize_download(raw, "SPY")
    np.testing.assert_array_equal(result["Adj Close"], prices)
    assert list(result.columns) == ["Close", "Adj Close"]


def test_explicit_adjusted_close_required(prices):
    with pytest.raises(DownloadError, match="explicit Adj Close"):
        normalize_download(prices.to_frame("Close"), "SPY")


def test_multiple_tickers_rejected(prices):
    raw = pd.DataFrame({("Adj Close", "SPY"): prices, ("Adj Close", "QQQ"): prices})
    with pytest.raises(DownloadError, match="Expected only SPY"):
        normalize_download(raw, "SPY")


def test_snapshot_saved_and_reused_without_network(tmp_path, monkeypatch, config, prices):
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame({"Close": prices + 2, "Adj Close": prices, "Volume": 1000})

    monkeypatch.setattr("spy_volatility.data.yf.download", download)
    actual, metadata, report = get_snapshot(config, tmp_path)
    assert report["passed"]
    assert len(metadata["sha256"]) == 64
    assert metadata["source"] == "Yahoo Finance via yfinance"
    assert metadata["columns"] == ["Close", "Adj Close", "Volume"]
    assert metadata["package_versions"]["yfinance"]
    assert metadata["retrieved_at_utc"].endswith("+00:00")
    assert calls[0]["auto_adjust"] is False
    assert calls[0]["back_adjust"] is False
    assert calls[0]["repair"] is False
    assert calls[0]["keepna"] is True
    assert calls[0]["multi_level_index"] is False
    assert calls[0]["actions"] is True
    assert calls[0]["threads"] is False
    pd.testing.assert_series_equal(actual, prices.rename("adjusted_close").rename_axis("Date"))
    cached, cached_metadata, cached_report = get_snapshot(config, tmp_path)
    assert len(calls) == 1
    pd.testing.assert_series_equal(actual, cached)
    assert metadata == cached_metadata
    assert report == cached_report


def test_snapshot_rejects_hash_change(tmp_path, monkeypatch, config, prices):
    monkeypatch.setattr("spy_volatility.data.yf.download", lambda **kwargs: prices.to_frame())
    get_snapshot(config, tmp_path)
    with (tmp_path / "raw.csv").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(SnapshotError, match="SHA-256"):
        get_snapshot(config, tmp_path)


@pytest.mark.parametrize("field,replacement", [("row_count", 99), ("columns", ["Close"]), ("actual_date_range", {"start": "2000-01-01", "end": "2000-01-02"}), ("package_versions", {}), ("retrieved_at_utc", "2024-01-02T00:00:00")])
def test_snapshot_rejects_inconsistent_metadata(tmp_path, monkeypatch, config, prices, field, replacement):
    monkeypatch.setattr("spy_volatility.data.yf.download", lambda **kwargs: prices.to_frame())
    get_snapshot(config, tmp_path)
    path = tmp_path / "metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata[field] = replacement
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(SnapshotError):
        get_snapshot(config, tmp_path)


def test_changed_request_does_not_replace_snapshot(tmp_path, monkeypatch, config, prices):
    monkeypatch.setattr("spy_volatility.data.yf.download", lambda **kwargs: prices.to_frame())
    get_snapshot(config, tmp_path)
    original = (tmp_path / "raw.csv").read_bytes()
    with pytest.raises(SnapshotError, match="request_settings"):
        get_snapshot({**config, "end": "2024-01-12"}, tmp_path)
    assert (tmp_path / "raw.csv").read_bytes() == original


def test_failed_audit_preserves_snapshot_for_investigation(tmp_path, monkeypatch, config, prices):
    monkeypatch.setattr("spy_volatility.data.yf.download", lambda **kwargs: prices.iloc[1:].to_frame())
    with pytest.raises(DataAuditError):
        get_snapshot(config, tmp_path)
    assert (tmp_path / "raw.csv").exists()
    assert (tmp_path / "metadata.json").exists()


def test_empty_download_preserves_actual_provider_error(tmp_path, monkeypatch, config):
    def download(**kwargs):
        logging.getLogger("yfinance").error("Artificial fixture: provider HTTP 429 rate limit")
        return pd.DataFrame()

    monkeypatch.setattr("spy_volatility.data.yf.download", download)
    with pytest.raises(DownloadError, match="provider HTTP 429 rate limit"):
        get_snapshot(config, tmp_path)
    assert not (tmp_path / "raw.csv").exists()


def test_partial_snapshot_never_redownloads(tmp_path, monkeypatch, config):
    (tmp_path / "raw.csv").write_text("Date,Adj Close\n", encoding="utf-8")

    def forbidden_download(**kwargs):
        pytest.fail("A partial cache must never trigger a network download.")

    monkeypatch.setattr("spy_volatility.data.yf.download", forbidden_download)
    with pytest.raises(SnapshotError, match="Incomplete snapshot"):
        get_snapshot(config, tmp_path)
