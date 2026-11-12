"""Independent arithmetic for a single pilot; no labels, fitting or scoring."""
from __future__ import annotations

import math
import statistics

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from spy_volatility.core.models import FEATURE_COLUMNS
from spy_volatility.verification.base import ATOL, RTOL


def verify_pilot(prices: pd.Series, features: pd.DataFrame, model: dict,
                 predictions: dict, scaled: list[float], returns: pd.Series) -> dict:
    """Compare scalar log/slice/sample-SD arithmetic and restored sklearn state.

    No estimator is fitted. The five future returns are never accessed.
    """
    if len(prices) != 21 or list(features.columns) != list(FEATURE_COLUMNS) or len(features) != 1:
        raise ValueError("Verification requires 21 prices and one ordered five-feature row")
    if model["features"] != list(FEATURE_COLUMNS):
        raise ValueError("Frozen feature order differs")
    p = prices.tolist()
    r = [math.log(p[i] / p[i - 1]) for i in range(1, 21)]
    expected = [r[-1], *(statistics.stdev(r[-n:]) for n in (5, 10, 20)), math.fsum(r[-5:])]
    z = [(value - mean) / scale for value, mean, scale in
         zip(expected, model["scaler_mean"], model["scaler_scale"], strict=True)]
    raw = math.fsum(value * coef for value, coef in zip(z, model["ridge_coefficients"], strict=True))
    raw += model["ridge_intercept"]
    final = max(raw, model["prediction_floor"])
    checks = {}

    def check(name, actual, wanted):
        np.testing.assert_allclose(actual, wanted, rtol=RTOL, atol=ATOL, equal_nan=False,
                                   err_msg=name)
        checks[name] = {"passed": True, "max_absolute_difference":
                        float(np.max(np.abs(np.asarray(actual) - np.asarray(wanted))))}

    check("all_20_log_returns", returns.to_numpy(), r)
    for i, name in enumerate(FEATURE_COLUMNS):
        check(name, features.iloc[0, i], expected[i])
    check("momentum_telescoping_log_ratio", expected[-1], math.log(p[-1] / p[-6]))
    check("stored_scaler", scaled, z)
    check("raw_ridge_scalar_sum", predictions["ridge_raw"], raw)
    check("zero_floor", predictions["ridge"], final)
    check("benchmark_20", predictions["baseline"], statistics.stdev(r[-20:]))
    check("benchmark_5", predictions["baseline_5"], statistics.stdev(r[-5:]))

    scaler = StandardScaler()
    scaler.mean_ = np.array(model["scaler_mean"])
    scaler.scale_ = np.array(model["scaler_scale"])
    scaler.n_features_in_ = 5
    ridge = Ridge(alpha=model["alpha"])
    ridge.coef_ = np.array(model["ridge_coefficients"])
    ridge.intercept_ = model["ridge_intercept"]
    ridge.n_features_in_ = 5
    sklearn_z = scaler.transform(features.to_numpy())
    check("sklearn_scaler_without_fit", sklearn_z[0], z)
    check("sklearn_ridge_without_fit", ridge.predict(sklearn_z)[0], raw)
    return {"passed": True, "rtol": RTOL, "atol": ATOL, "checks": checks,
            "feature_order": list(FEATURE_COLUMNS), "independent_features": expected,
            "independent_scaled_features": z, "independent_raw_ridge": raw,
            "future_outcomes_read": False, "model_fitted": False}
