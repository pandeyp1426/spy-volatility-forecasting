"""Small, auditable calculations for the Phase 1 historical baseline.

All volatilities are sample standard deviations (ddof=1) in unannualized
daily-return units. A row dated t is a forecast made after t closes.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


def _positive_integer(value: int, name: str, minimum: int = 1) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}.")


def _check_index(frame: pd.Series | pd.DataFrame) -> None:
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("A DatetimeIndex of trading dates is required.")
    if index.tz is not None or index.hasnans:
        raise ValueError("Trading dates must be timezone-naive and nonmissing.")
    if not index.is_unique or not index.is_monotonic_increasing:
        raise ValueError("Trading dates must be unique and in chronological order.")


def build_features(
    prices: pd.Series,
    windows: Iterable[int] = (5, 10, 20),
    horizon: int = 5,
    momentum_window: int = 5,
    baseline_window: int = 20,
) -> pd.DataFrame:
    """Build complete forecast examples from audited adjusted closing prices.

    ``volatility_w`` uses returns r_(t-w+1), ..., r_t. The target uses
    r_(t+1), ..., r_(t+horizon), and never enters an input calculation.
    ``session_number`` is the position in the original audited price series.
    The caller must audit the exchange calendar before calling this function.
    """
    if not isinstance(prices, pd.Series):
        raise ValueError("prices must be a pandas Series of adjusted closing prices.")
    _check_index(prices)
    windows = tuple(windows)
    if not windows or len(set(windows)) != len(windows):
        raise ValueError("windows must contain distinct rolling-window lengths.")
    for window in windows:
        _positive_integer(window, "volatility window", 2)
    _positive_integer(horizon, "horizon", 2)
    _positive_integer(momentum_window, "momentum_window")
    _positive_integer(baseline_window, "baseline_window", 2)
    try:
        values = prices.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Adjusted prices must be numeric.") from exc
    if not np.isfinite(values.to_numpy()).all() or (values <= 0).any():
        raise ValueError("Adjusted prices must all be finite and strictly positive.")

    returns = np.log(values / values.shift(1))
    examples = pd.DataFrame({"log_return": returns})
    for window in windows:
        examples[f"volatility_{window}"] = returns.rolling(window).std(ddof=1)
    examples[f"momentum_{momentum_window}"] = returns.rolling(momentum_window).sum()
    examples["baseline"] = returns.rolling(baseline_window).std(ddof=1)
    # The rolling value at t+horizon contains exactly the next horizon returns.
    examples["target"] = returns.rolling(horizon).std(ddof=1).shift(-horizon)
    dates = pd.Series(prices.index, index=prices.index)
    examples["target_start"] = dates.shift(-1)
    examples["target_end"] = dates.shift(-horizon)
    examples["session_number"] = np.arange(len(prices), dtype=np.int64)
    examples = examples.dropna().copy()
    examples.index.name = "forecast_date"
    if examples.empty:
        raise ValueError("No complete examples: more prices are needed for history and future targets.")
    return examples


def split_examples(
    examples: pd.DataFrame,
    train_start: str,
    validation_start: str,
    test_start: str,
    test_end: str,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Split chronologically, purging labels that reach the next partition.

    Boundaries are inclusive starts and an exclusive test end. Purging uses
    the first actual forecast date in the next partition, including when a
    boundary falls on a weekend or exchange holiday. Test performance is not
    calculated by this function.
    """
    _check_index(examples)
    required = {"target_start", "target_end"}
    if not required.issubset(examples.columns):
        raise ValueError("Examples must include target_start and target_end dates.")
    boundaries = tuple(pd.Timestamp(value) for value in (train_start, validation_start, test_start, test_end))
    if any(pd.isna(value) or value.tz is not None for value in boundaries):
        raise ValueError("Split boundaries must be nonmissing, timezone-naive dates.")
    if not all(left < right for left, right in zip(boundaries, boundaries[1:])):
        raise ValueError("Split boundaries must increase: train, validation, test, test_end.")
    if examples[["target_start", "target_end"]].isna().any().any():
        raise ValueError("Target window dates must not be missing.")
    partitions = {
        name: examples.loc[(examples.index >= start) & (examples.index < end)].copy()
        for name, start, end in zip(("train", "validation", "test"), boundaries, boundaries[1:])
    }
    for name, partition in partitions.items():
        if partition.empty:
            raise ValueError(f"The {name} partition has no complete examples; check data coverage and split dates.")
    before = {name: len(partition) for name, partition in partitions.items()}
    before_dates = {
        name: (partition.index.min().date().isoformat(), partition.index.max().date().isoformat())
        for name, partition in partitions.items()
    }
    cutoffs = {"train": partitions["validation"].index[0], "validation": partitions["test"].index[0]}
    for name, cutoff in cutoffs.items():
        partitions[name] = partitions[name].loc[partitions[name]["target_end"] < cutoff].copy()
        if partitions[name].empty:
            raise ValueError(f"The {name} partition has no examples after purging overlapping future targets.")

    summary = {
        "boundaries": dict(zip(("train_start", "validation_start", "test_start", "test_end_exclusive"),
                               (value.date().isoformat() for value in boundaries))),
        "purge_rule": "Remove rows whose target_end >= the next partition's first actual forecast date.",
        "partitions": {},
    }
    for name, partition in partitions.items():
        summary["partitions"][name] = {
            "n_before_purge": before[name],
            "n_after_purge": len(partition),
            "n_purged": before[name] - len(partition),
            "first_forecast_before_purge": before_dates[name][0],
            "last_forecast_before_purge": before_dates[name][1],
            "first_forecast_date": partition.index.min().date().isoformat(),
            "last_forecast_date": partition.index.max().date().isoformat(),
            "first_target_start": pd.Timestamp(partition["target_start"].min()).date().isoformat(),
            "last_target_end": pd.Timestamp(partition["target_end"].max()).date().isoformat(),
            "next_partition_first_forecast": cutoffs[name].date().isoformat() if name in cutoffs else None,
        }
    return partitions, summary


def validation_predictions(validation: pd.DataFrame) -> pd.DataFrame:
    """Expose the existing historical baseline; there is no model fitting."""
    _check_index(validation)
    columns = ["baseline", "target", "target_start", "target_end", "session_number"]
    if not set(columns).issubset(validation.columns):
        raise ValueError(f"Validation examples must include: {', '.join(columns)}.")
    if validation.empty:
        raise ValueError("Validation examples must not be empty.")
    return validation.loc[:, columns].copy()


def evaluate_predictions(predictions: pd.DataFrame) -> dict[str, int | float]:
    """Return MAE and RMSE in daily-volatility percentage points (x100)."""
    if predictions.empty or not {"baseline", "target"}.issubset(predictions.columns):
        raise ValueError("Nonempty baseline and target columns are required for evaluation.")
    values = predictions[["baseline", "target"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Forecast and observed volatilities must be finite and nonnegative.")
    error_pp = 100.0 * (values[:, 0] - values[:, 1])
    return {
        "mae_pp": float(np.mean(np.abs(error_pp))),
        "rmse_pp": float(np.sqrt(np.mean(error_pp**2))),
        "n_forecasts": len(predictions),
    }


def nonoverlapping_predictions(predictions: pd.DataFrame, horizon: int = 5) -> pd.DataFrame:
    """Select forecasts exactly horizon trading sessions apart from the first.

    Selection uses original session positions, rather than calendar-day gaps.
    Verify both forecast spacing and future-window separation. These checks
    deliberately fail if a selected session is missing or windows overlap.
    """
    _positive_integer(horizon, "horizon", 2)
    _check_index(predictions)
    if predictions.empty or not {"session_number", "target_start", "target_end"}.issubset(predictions.columns):
        raise ValueError("Nonempty predictions with session_number and target dates are required.")
    sessions = predictions["session_number"].to_numpy(dtype=float)
    if (not np.isfinite(sessions).all() or (sessions < 0).any()
            or (sessions != np.floor(sessions)).any() or (np.diff(sessions) <= 0).any()):
        raise ValueError("session_number must contain strictly increasing, nonnegative integers.")
    selected = predictions.loc[(sessions - sessions[0]) % horizon == 0].copy()
    if (np.diff(selected["session_number"].to_numpy()) != horizon).any():
        raise ValueError("Selected forecasts are not spaced exactly horizon trading sessions apart.")
    starts = pd.to_datetime(selected["target_start"])
    ends = pd.to_datetime(selected["target_end"])
    if starts.isna().any() or ends.isna().any() or (starts > ends).any():
        raise ValueError("Target windows must contain valid, ordered start and end dates.")
    if (starts <= selected.index).any():
        raise ValueError("Target windows must begin strictly after their forecast dates.")
    if len(selected) > 1 and (starts.iloc[1:].to_numpy() <= ends.iloc[:-1].to_numpy()).any():
        raise ValueError("Selected forecasts have overlapping future outcome windows.")
    return selected
