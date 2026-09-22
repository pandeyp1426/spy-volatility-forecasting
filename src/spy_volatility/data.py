"""Download one fixed Yahoo snapshot and audit it without repairing observations."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import platform
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf


class DataAuditError(ValueError):
    """A failed price audit, with a JSON-serializable report for the run record."""

    def __init__(self, report: dict):
        self.report = report
        super().__init__("Data audit failed: " + "; ".join(report["errors"]))


class SnapshotError(ValueError):
    """An existing snapshot or its provenance cannot be verified."""


class DownloadError(RuntimeError):
    """Yahoo returned no usable response; the actual provider errors are retained."""


def _interval(start: str, end: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    for name, value in (("start", start), ("end", end)):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD).")
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    if first >= last:
        raise ValueError("The exclusive end must be after the inclusive start.")
    return first, last


def _date_strings(index: pd.Index) -> list[str]:
    return [value.isoformat() if isinstance(value, pd.Timestamp) else str(value) for value in index]


def _range(index: pd.DatetimeIndex) -> dict:
    return {
        "start": None if len(index) == 0 or pd.isna(index.min()) else index.min().isoformat(),
        "end": None if len(index) == 0 or pd.isna(index.max()) else index.max().isoformat(),
    }


def audit_prices(
    prices: pd.Series, start: str, end: str, calendar: str = "NYSE"
) -> dict:
    """Require valid prices and every exchange session in [start, end).

    The pandas_market_calendars exchange schedule is the session authority.
    This function never sorts, drops, fills, or otherwise fixes observations.
    All audit failures raise DataAuditError with the complete report attached.
    """
    first, last = _interval(start, end)
    schedule = mcal.get_calendar(calendar).schedule(
        start_date=first, end_date=last - pd.Timedelta(days=1)
    )
    expected = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    report = {
        "audit_version": 1,
        "passed": False,
        "calendar": calendar,
        "calendar_provider": "pandas_market_calendars",
        "requested_interval": {"start_inclusive": start, "end_exclusive": end},
        "row_count": int(len(prices)),
        "expected_session_count": int(len(expected)),
        "errors": [],
    }
    if not isinstance(prices.index, pd.DatetimeIndex):
        report["errors"].append("Price index must be a DatetimeIndex.")
        raise DataAuditError(report)

    dates = prices.index
    report["actual_date_range"] = _range(dates)
    report["chronological_order"] = bool(dates.is_monotonic_increasing)
    report["duplicate_dates"] = _date_strings(dates[dates.duplicated(keep=False)])
    if not report["chronological_order"]:
        report["errors"].append("Price dates are not in chronological order.")
    if report["duplicate_dates"]:
        report["errors"].append("Duplicate price dates are present.")
    if dates.hasnans:
        report["errors"].append("Missing or invalid price dates are present.")
    if dates.tz is not None:
        report["errors"].append("Daily price dates must be timezone-naive (ignore_tz=True).")
    if not dates.dropna().equals(dates.dropna().normalize()):
        report["errors"].append("Daily price dates must be midnight session labels.")

    numeric = pd.to_numeric(prices, errors="coerce")
    missing = prices.isna().to_numpy()
    values = numeric.to_numpy(dtype=float, na_value=np.nan)
    nonnumeric = np.isnan(values) & ~missing
    nonfinite = ~np.isfinite(values)
    nonpositive = values <= 0
    for key, mask, message in (
        ("missing_price_dates", missing, "Missing adjusted prices are present."),
        ("nonnumeric_price_dates", nonnumeric, "Nonnumeric adjusted prices are present."),
        ("nonfinite_price_dates", nonfinite, "Nonfinite adjusted prices are present."),
        ("nonpositive_price_dates", nonpositive, "Nonpositive adjusted prices are present."),
    ):
        report[key] = _date_strings(dates[mask])
        if mask.any():
            report["errors"].append(message)

    # Compare local date labels even when also reporting an invalid timezone.
    # The original series is never modified or repaired.
    observed = dates.tz_localize(None).normalize().dropna().unique()
    report["missing_sessions"] = _date_strings(expected.difference(observed))
    report["unexpected_sessions"] = _date_strings(observed.difference(expected))
    if report["missing_sessions"]:
        report["errors"].append("Expected exchange trading sessions are missing.")
    if report["unexpected_sessions"]:
        report["errors"].append("Prices include dates outside the expected exchange sessions.")
    if not len(prices):
        report["errors"].append("No adjusted prices are available.")
    report["passed"] = not report["errors"]
    if not report["passed"]:
        raise DataAuditError(report)
    return report


def normalize_download(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Flatten a single-ticker yfinance response while preserving all raw fields.

    Both (price, ticker) and (ticker, price) MultiIndex layouts are accepted.
    Adjusted close must be explicit; Close is never substituted for Adj Close.
    """
    if not isinstance(frame, pd.DataFrame):
        raise DownloadError("yfinance.download did not return a DataFrame.")
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        if result.columns.nlevels != 2:
            raise DownloadError("Expected two column levels for a single-ticker response.")
        field_levels = [
            level for level in range(2)
            if "Adj Close" in result.columns.get_level_values(level)
        ]
        if len(field_levels) != 1:
            raise DownloadError("The Yahoo response has no unambiguous explicit Adj Close field.")
        field_level = field_levels[0]
        symbols = result.columns.get_level_values(1 - field_level).unique()
        if len(symbols) != 1 or str(symbols[0]).upper() != ticker.upper():
            raise DownloadError(f"Expected only {ticker}; Yahoo returned ticker columns {list(symbols)!r}.")
        result.columns = result.columns.get_level_values(field_level)
    if result.columns.duplicated().any():
        raise DownloadError("The Yahoo response has duplicate field names.")
    if "Adj Close" not in result.columns:
        raise DownloadError("The Yahoo response lacks explicit Adj Close with auto_adjust=False.")
    if not isinstance(result.index, pd.DatetimeIndex):
        raise DownloadError("The Yahoo response does not use daily datetime labels.")
    result.columns = pd.Index([str(column) for column in result.columns])
    result.index.name = "Date"
    return result


def _request_settings(data_config: dict) -> dict:
    ticker = str(data_config.get("ticker", "SPY")).upper()
    if not re.fullmatch(r"[A-Z0-9.^=\-]+", ticker):
        raise ValueError("Configure exactly one Yahoo ticker without spaces or commas.")
    start, end = data_config["start"], data_config["end"]
    _interval(start, end)
    return {
        "tickers": ticker,
        "start": start,
        "end": end,
        "interval": "1d",
        "auto_adjust": False,
        "back_adjust": False,
        "repair": False,
        "keepna": True,
        "actions": True,
        "threads": False,
        "ignore_tz": True,
        "group_by": "column",
        "progress": False,
        "prepost": False,
        "rounding": False,
        "timeout": 30,
        "multi_level_index": False,
    }


def _versions() -> dict:
    versions = {"python": platform.python_version()}
    for package in ("numpy", "pandas", "yfinance", "pandas_market_calendars"):
        versions[package] = importlib.metadata.version(package)
    return versions


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _download(settings: dict) -> pd.DataFrame:
    messages: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(self.format(record))

    logger = logging.getLogger("yfinance")
    handler = Capture()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    caught: list = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            frame = yf.download(**settings)
    except Exception as error:
        details = "\n".join(messages + [str(item.message) for item in caught])
        raise DownloadError(
            f"yfinance.download failed: {type(error).__name__}: {error}"
            + (f"\nProvider diagnostics:\n{details}" if details else "")
        ) from error
    finally:
        logger.removeHandler(handler)
    if frame is None or frame.empty:
        details = "\n".join(messages + [str(item.message) for item in caught])
        raise DownloadError(
            "yfinance.download returned an empty response."
            + (f"\nProvider diagnostics:\n{details}" if details else " No provider error was reported.")
        )
    return normalize_download(frame, settings["tickers"])


def _read_snapshot(raw_path: Path, metadata_path: Path, settings: dict, calendar: str) -> tuple:
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SnapshotError(f"Cannot read snapshot metadata: {error}") from error
    if not isinstance(metadata, dict):
        raise SnapshotError("Snapshot metadata must be a JSON object.")
    expected = {
        "schema_version": 1,
        "source": "Yahoo Finance via yfinance",
        "request_settings": settings,
        "calendar": calendar,
        "raw_file": raw_path.name,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise SnapshotError(
                f"Snapshot metadata {key!r} does not match this request. "
                "Preserve the existing snapshot and choose a new snapshot directory for a changed request."
            )
    if metadata.get("sha256") != _sha256(raw_path):
        raise SnapshotError("Raw snapshot SHA-256 does not match metadata; no download was attempted.")
    try:
        retrieved = datetime.fromisoformat(metadata["retrieved_at_utc"])
        if retrieved.utcoffset() != timezone.utc.utcoffset(retrieved):
            raise ValueError("timestamp is not UTC")
        versions = metadata["package_versions"]
        if not isinstance(versions, dict) or any(
            not isinstance(versions.get(name), str) or not versions[name]
            for name in ("python", "numpy", "pandas", "yfinance", "pandas_market_calendars")
        ):
            raise ValueError("incomplete package versions")
    except (KeyError, ValueError, TypeError) as error:
        raise SnapshotError(f"Snapshot provenance is invalid: {error}") from error
    try:
        raw = pd.read_csv(raw_path, index_col="Date", parse_dates=["Date"], float_precision="round_trip")
        raw = normalize_download(raw, settings["tickers"])
    except (OSError, ValueError, DownloadError) as error:
        raise SnapshotError(f"Cannot read raw snapshot: {error}") from error
    for key, actual in (
        ("row_count", int(len(raw))),
        ("columns", raw.columns.tolist()),
        ("actual_date_range", _range(raw.index)),
    ):
        if metadata.get(key) != actual:
            raise SnapshotError(f"Snapshot metadata {key!r} does not match its raw CSV.")
    return raw, metadata


def get_snapshot(data_config: dict, snapshot_dir: Path) -> tuple[pd.Series, dict, dict]:
    """Return adjusted prices, verified metadata, and a passing data audit.

    raw.csv and metadata.json are immutable once present. A partial, changed,
    or corrupted cache causes a visible failure, never a silent redownload.
    Changing requests requires a new snapshot directory. Audit failures retain
    the original downloaded snapshot for investigation.
    """
    settings = _request_settings(data_config)
    calendar = data_config.get("calendar", "NYSE")
    snapshot_dir = Path(snapshot_dir)
    raw_path, metadata_path = snapshot_dir / "raw.csv", snapshot_dir / "metadata.json"
    if raw_path.exists() != metadata_path.exists():
        raise SnapshotError("Incomplete snapshot: raw.csv and metadata.json must both exist. Investigate before retrying.")
    if raw_path.exists():
        raw, metadata = _read_snapshot(raw_path, metadata_path, settings, calendar)
    else:
        raw = _download(settings)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        with raw_path.open("x", encoding="utf-8", newline="") as stream:
            raw.to_csv(stream, index_label="Date")
        metadata = {
            "schema_version": 1,
            "source": "Yahoo Finance via yfinance",
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "request_settings": settings,
            "calendar": calendar,
            "raw_file": raw_path.name,
            "sha256": _sha256(raw_path),
            "actual_date_range": _range(raw.index),
            "row_count": int(len(raw)),
            "columns": raw.columns.tolist(),
            "package_versions": _versions(),
        }
        with metadata_path.open("x", encoding="utf-8") as stream:
            json.dump(metadata, stream, indent=2, allow_nan=False)
            stream.write("\n")
    prices = raw["Adj Close"].rename("adjusted_close")
    audit = audit_prices(prices, settings["start"], settings["end"], calendar)
    return prices, metadata, audit
