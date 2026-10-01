"""Check saved training/validation calculations directly against raw prices.

This deliberately uses explicit NumPy slices, not the production rolling,
split, sampling, or scoring functions. Reserved test tables are not opened or scored.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd


RTOL = 1e-9
ATOL = 1e-12


class CalculationVerificationError(ValueError):
    def __init__(self, report: dict):
        self.verification_report = report
        super().__init__("Saved calculation verification failed: " + report["error"])


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _close(actual, expected, label: str) -> None:
    _require(np.allclose(actual, expected, rtol=RTOL, atol=ATOL, equal_nan=False),
             f"{label} differs from the independent calculation.")


def _read_table(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col="forecast_date",
                        parse_dates=["forecast_date", "target_start", "target_end"],
                        float_precision="round_trip")
    _require(not frame.empty and frame.index.is_unique and frame.index.is_monotonic_increasing,
             f"{path.name} must have unique, ordered forecast dates.")
    return frame


def _same_predictions(actual: pd.DataFrame, expected: pd.DataFrame, label: str) -> None:
    _require(actual.index.equals(expected.index), f"{label}: forecast dates differ.")
    _require(set(actual.columns) == {"target_start", "target_end", "baseline", "target", "session_number"},
             f"{label}: unexpected or missing prediction columns.")
    for column in ("target_start", "target_end"):
        _require(actual[column].equals(expected[column]), f"{label}: {column} differs.")
    _require(np.array_equal(actual["session_number"], expected["session_number"]), f"{label}: session numbers differ.")
    for column in ("baseline", "target"):
        _close(actual[column].to_numpy(), expected[column].to_numpy(), f"{label}: {column}")


def _verify_scores(frame: pd.DataFrame, saved: dict, label: str) -> None:
    errors = (frame["baseline"].to_numpy() - frame["target"].to_numpy()) * 100
    _require(saved["n_forecasts"] == len(errors), f"{label}: forecast count differs.")
    _close(saved["mae_pp"], sum(abs(errors)) / len(errors), f"{label}: MAE units/value")
    _close(saved["rmse_pp"], np.sqrt(sum(errors * errors) / len(errors)), f"{label}: RMSE units/value")


def verify_saved_calculations(output: Path, prices: pd.Series, config: dict, metrics: dict) -> dict:
    """Fail a run on a saved calculation mismatch; return explicit check evidence.

    Check every retained training/validation feature, future label and date,
    partition completeness, baseline prediction, sampling offset and score.
    The audited snapshot supplies prices; no final-test table is opened or scored.
    Tolerances accommodate floating-point rolling and CSV round-trip differences.
    """
    report = {"passed": False, "checked_rows": {}, "checks": [], "rtol": RTOL, "atol": ATOL}
    try:
        saved_metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
        _require(saved_metrics == metrics, "Saved metrics.json differs from the run results.")
        research, split = config["research"], config["split"]
        horizon, windows = research["horizon"], research["windows"]
        baseline_window, momentum = research["baseline_window"], research["momentum_window"]
        values = prices.to_numpy(dtype=float)
        returns = np.r_[np.nan, np.log(values[1:] / values[:-1])]
        history = max(*windows, baseline_window, momentum)
        complete = np.arange(history, len(prices) - horizon)
        dates = prices.index
        next_starts = {}
        for name in ("validation", "test"):
            upper = split["test_start"] if name == "validation" else split["test_end"]
            candidates = complete[(dates[complete] >= pd.Timestamp(split[f"{name}_start"]))
                                  & (dates[complete] < pd.Timestamp(upper))]
            _require(len(candidates) > 0, f"No complete {name} forecast dates.")
            next_starts[name] = dates[candidates[0]]

        checked = {}
        for name, following in (("train", "validation"), ("validation", "test")):
            expected_positions = complete[
                (dates[complete] >= pd.Timestamp(split[f"{name}_start"]))
                & (dates[complete] < pd.Timestamp(split[f"{following}_start"]))
                & (dates[complete + horizon] < next_starts[following])
            ]
            frame = _read_table(output / f"{name}.csv")
            _require(frame.index.equals(dates[expected_positions]), f"{name}: missing, extra or unpurged forecast dates.")
            _require(pd.DatetimeIndex(frame["target_start"]).equals(dates[expected_positions + 1]),
                     f"{name}: target_start must be the next session.")
            _require(pd.DatetimeIndex(frame["target_end"]).equals(dates[expected_positions + horizon]),
                     f"{name}: target_end must be exactly horizon sessions ahead.")
            expected = {"log_return": returns[expected_positions], "session_number": expected_positions}
            for window in windows:
                expected[f"volatility_{window}"] = [
                    np.std(returns[pos - window + 1:pos + 1], ddof=1) for pos in expected_positions
                ]
            expected["momentum_" + str(momentum)] = [
                np.sum(returns[pos - momentum + 1:pos + 1]) for pos in expected_positions
            ]
            expected["baseline"] = [np.std(returns[pos - baseline_window + 1:pos + 1], ddof=1)
                                    for pos in expected_positions]
            expected["target"] = [np.std(returns[pos + 1:pos + horizon + 1], ddof=1)
                                  for pos in expected_positions]
            _require(set(frame.columns) == set(expected) | {"target_start", "target_end"},
                     f"{name}: unexpected or missing feature columns.")
            _require(np.array_equal(frame["session_number"], expected_positions), f"{name}: session numbers differ.")
            for column, calculated in expected.items():
                _close(frame[column].to_numpy(), calculated, f"{name}: {column}")
            report["checked_rows"][name] = len(frame)
            report["checks"].append(f"{name}: all saved features, targets, session dates and boundary purging")
            checked[name] = frame

        daily = _read_table(output / "validation_predictions.csv")
        spaced = _read_table(output / "validation_nonoverlapping_predictions.csv")
        _same_predictions(daily, checked["validation"], "Daily validation predictions")
        # Verified validation dates are contiguous in the raw session sequence.
        _same_predictions(spaced, daily.iloc[::horizon], "Nonoverlapping validation predictions")
        _require((spaced["target_start"].iloc[1:].to_numpy() > spaced["target_end"].iloc[:-1].to_numpy()).all(),
                 "Nonoverlapping validation outcomes overlap.")
        _require(metrics["units"] == "daily-volatility percentage points", "Incorrect metric units label.")
        _require(metrics["final_test"] == "reserved; performance not computed", "Final test must remain reserved.")
        _require(metrics["nonoverlapping_anchor"] == daily.index[0].date().isoformat(), "Incorrect sampling anchor.")
        _require(metrics["nonoverlapping_stride_sessions"] == horizon, "Incorrect sampling stride.")
        _verify_scores(daily, metrics["validation_daily"], "Daily validation")
        _verify_scores(spaced, metrics["validation_nonoverlapping"], "Nonoverlapping validation")
        report["checks"].extend(["saved validation predictions match the independently checked baseline",
                                  "nonoverlapping sampling starts at the first validation date with disjoint outcomes",
                                  "both validation MAE/RMSE values and counts match independent arithmetic"])
        report["passed"] = True
        return report
    except (ValueError, KeyError, TypeError, OSError) as error:
        report["error"] = str(error)
        raise CalculationVerificationError(report) from error
