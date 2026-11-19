"""Mature five-session labels and guarded per-forecast errors; no model fitting."""
import math
import statistics

import numpy as np
import pandas as pd

from spy_volatility.core.data import audit_prices
from spy_volatility.verification.base import ATOL, RTOL


SCORE_NOT_BEFORE = pd.Timestamp("2028-01-10", tz="America/Chicago")


def study_for(origin: str, targets: list[str]) -> str:
    year = pd.Timestamp(origin).year
    if len(targets) != 5 or any(pd.Timestamp(d).year != year for d in targets):
        raise ValueError("Operational origins require five targets contained in their calendar year")
    if year not in (2026, 2027):
        raise ValueError("Only separate 2026 pilots and the frozen 2027 study are supported")
    return "formal_2027" if year == 2027 else "pilot_2026"


def realized_volatility(prices: pd.Series, sessions: pd.DatetimeIndex,
                        target_close: pd.Timestamp, now: pd.Timestamp) -> dict:
    now, target_close = pd.Timestamp(now), pd.Timestamp(target_close)
    if now.tz is None or target_close.tz is None or now <= target_close:
        raise ValueError("The full five-session target has not closed")
    if len(sessions) != 6 or len(prices) != 6 or not prices.index.equals(sessions):
        raise ValueError("Outcome needs origin plus exactly five consecutive target prices")
    audit_prices(prices, sessions[0].date().isoformat(),
                 (sessions[-1] + pd.Timedelta(days=1)).date().isoformat(), "NYSE")
    returns = np.log(prices.astype(float) / prices.astype(float).shift(1)).iloc[1:]
    observed = float(returns.std(ddof=1))
    p = prices.tolist()
    independent = [math.log(p[i] / p[i-1]) for i in range(1, 6)]
    expected = statistics.stdev(independent)
    np.testing.assert_allclose(returns, independent, rtol=RTOL, atol=ATOL)
    np.testing.assert_allclose(observed, expected, rtol=RTOL, atol=ATOL)
    mean_return = float(returns.mean())
    np.testing.assert_allclose(mean_return, math.fsum(independent) / 5, rtol=RTOL, atol=ATOL)
    return {"observed_volatility": observed, "returns": returns.tolist(), "future_mean_return": mean_return, "ddof": 1,
            "units": "decimal daily log-return standard deviation; not annualized",
            "verification": {"passed": True, "independent_sample_sd": expected,
                             "absolute_difference": abs(observed - expected), "rtol": RTOL, "atol": ATOL}}


def forecast_errors(forecast: dict, observed: float, now: pd.Timestamp) -> dict:
    # Derive study from dates; a caller cannot relabel 2027 predictions as pilots.
    study = study_for(forecast["forecast_session"], forecast["target_sessions"])
    instant = pd.Timestamp(now)
    if instant.tz is None:
        raise ValueError("Scoring time must be timezone-aware")
    if study == "formal_2027" and instant < SCORE_NOT_BEFORE:
        raise ValueError("Formal 2027 errors are embargoed until 2028-01-10 America/Chicago")
    predictions = np.array([forecast["predictions"][n] for n in ("ridge", "baseline", "baseline_5")])
    if not np.isfinite(observed) or observed < 0 or not np.isfinite(predictions).all() or (predictions < 0).any():
        raise ValueError("Invalid forecast or observed volatility")
    signed = 100 * (predictions - observed)
    result = {}
    for name, value, error in zip(("ridge", "baseline", "baseline_5"), predictions, signed, strict=True):
        independent = 100 * (float(value) - float(observed))
        np.testing.assert_allclose(error, independent, rtol=RTOL, atol=ATOL)
        result[name] = {"signed_error_pp": float(error), "absolute_error_pp": float(abs(error)),
                        "squared_error_pp2": float(error ** 2)}
    return {"study": study, "units": "daily-volatility percentage points",
            "definition": "100 * (prediction - observed)", "errors": result, "verification_passed": True}


def aggregate_errors(cases: list[dict], study: str, now: pd.Timestamp) -> dict:
    """Common-row descriptive metrics; all formal comparisons remain embargoed.

    Membership is supplied explicitly by the operational selection policy.
    Revisions cannot be counted as additional independent origins.
    """
    if study not in ("pilot_2026", "manual_pilot_2026", "formal_2027"):
        raise ValueError("Unknown evaluation sample")
    if pd.Timestamp(now).tz is None:
        raise ValueError("Scoring time must be timezone-aware")
    if study == "formal_2027" and pd.Timestamp(now) < SCORE_NOT_BEFORE:
        raise ValueError("Formal 2027 aggregate scoring is embargoed until 2028-01-10 America/Chicago")
    origins = [c["forecast"]["forecast_session"] for c in cases]
    if len(set(origins)) != len(origins):
        raise ValueError("Duplicate origins in the evaluation sample")
    expected_study = "formal_2027" if study == "formal_2027" else "pilot_2026"
    for case in cases:
        f = case["forecast"]
        if study_for(f["forecast_session"], f["target_sessions"]) != expected_study:
            raise ValueError("Pilot and formal observations must not be mixed")
    scores = [forecast_errors(c["forecast"], c["observed"], now) for c in cases]
    metrics = {}
    for name in ("ridge", "baseline", "baseline_5"):
        errors = np.array([s["errors"][name]["signed_error_pp"] for s in scores])
        if not len(errors):
            metrics[name] = {"n": 0, "mae_pp": None, "mse_pp2": None, "rmse_pp": None, "bias_pp": None}
            continue
        mse = float(np.mean(errors ** 2))
        metrics[name] = {"n": len(errors), "mae_pp": float(np.mean(abs(errors))), "mse_pp2": mse,
                         "rmse_pp": float(np.sqrt(mse)), "bias_pp": float(np.mean(errors))}
        expected = [math.fsum(abs(float(e)) for e in errors) / len(errors),
                    math.fsum(float(e)**2 for e in errors) / len(errors),
                    math.sqrt(math.fsum(float(e)**2 for e in errors) / len(errors)),
                    math.fsum(float(e) for e in errors) / len(errors)]
        np.testing.assert_allclose([metrics[name][k] for k in ("mae_pp", "mse_pp2", "rmse_pp", "bias_pp")], expected,
                                   rtol=RTOL, atol=ATOL)
    return {"study": study, "origins": origins, "metrics": metrics, "verification_passed": True,
            "units": "MAE/RMSE/bias: daily-volatility pp; MSE: pp squared",
            "interpretation": "Descriptive common-sample errors; no accuracy percentage or significance claim"}
