"""Fixed training-only models and a common validation comparison.

The comparison deliberately has no test argument. Inputs use a five-column
allowlist and the response is mapped explicitly from the legacy name.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .research import _check_index

FEATURE_COLUMNS = (
    "log_return", "volatility_5", "volatility_10", "volatility_20", "momentum_5",
)
TARGET_COLUMN = "future_volatility_5d"
MODEL_NAMES = ("baseline", "ridge", "random_forest", "gradient_boosting")


def model_frame(examples: pd.DataFrame) -> pd.DataFrame:
    """Select the agreed numeric variables, explicitly adapting legacy target.

    Audit metadata and any duplicate baseline are never model predictors.
    Canonical and legacy target columns may coexist only when they agree.
    """
    _check_index(examples)
    if examples.empty:
        raise ValueError("Model examples must not be empty.")
    missing = set(FEATURE_COLUMNS).difference(examples.columns)
    if missing:
        raise ValueError(f"Missing agreed model predictors: {', '.join(sorted(missing))}.")
    if TARGET_COLUMN not in examples and "target" not in examples:
        raise ValueError(f"Examples must include {TARGET_COLUMN} or legacy target.")
    source = TARGET_COLUMN if TARGET_COLUMN in examples else "target"
    try:
        frame = examples.loc[:, list(FEATURE_COLUMNS)].astype(float).copy()
        frame[TARGET_COLUMN] = examples[source].astype(float)
        if TARGET_COLUMN in examples and "target" in examples:
            if not np.array_equal(frame[TARGET_COLUMN].to_numpy(),
                                  examples["target"].to_numpy(dtype=float)):
                raise ValueError("Canonical and legacy target columns disagree.")
    except (TypeError, ValueError) as exc:
        if "target columns disagree" in str(exc):
            raise
        raise ValueError("Model predictors and response must be numeric.") from exc
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError("Model predictors and response must all be finite.")
    volatility_columns = ["volatility_5", "volatility_10", "volatility_20", TARGET_COLUMN]
    if (frame[volatility_columns] < 0).any().any():
        raise ValueError("Historical and observed future volatilities must be nonnegative.")
    return frame


def compare_validation(
    train: pd.DataFrame, validation: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Fit fixed models on training rows and score the same validation rows.

    Predictions and observed targets remain decimals; MAE, RMSE and signed
    bias are daily-volatility percentage points. Prediction flooring is
    applied after fitting and its count is reported for every model.
    Row disjointness here is not a claim of nonoverlapping outcome windows.
    """
    from sklearn import __version__ as sklearn_version
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    training = model_frame(train)
    heldout = model_frame(validation)
    if training.index.intersection(heldout.index).size:
        raise ValueError("Training and validation forecast row identities must be disjoint.")
    params = {
        "ridge": {"alpha": 1.0},
        "random_forest": {
            "n_estimators": 200, "max_depth": 5, "min_samples_leaf": 10,
            "max_features": "sqrt", "random_state": 42, "n_jobs": 1,
        },
        "gradient_boosting": {
            "n_estimators": 200, "max_depth": 2, "learning_rate": 0.03,
            "min_samples_leaf": 10, "loss": "squared_error", "random_state": 42,
        },
    }
    models = {
        "ridge": Pipeline([("scaler", StandardScaler()), ("regressor", Ridge(**params["ridge"]))]),
        "random_forest": RandomForestRegressor(**params["random_forest"]),
        "gradient_boosting": GradientBoostingRegressor(**params["gradient_boosting"]),
    }
    x_train = training.loc[:, list(FEATURE_COLUMNS)]
    y_train = training[TARGET_COLUMN]
    x_validation = heldout.loc[:, list(FEATURE_COLUMNS)]
    predictions = heldout.loc[:, [TARGET_COLUMN]].copy()
    predictions.index.name = "forecast_date"
    raw_predictions = {"baseline": heldout["volatility_20"].to_numpy()}
    for name, estimator in models.items():
        estimator.fit(x_train, y_train)
        raw_predictions[name] = estimator.predict(x_validation)
    metric_rows = []
    for name in MODEL_NAMES:
        values = np.asarray(raw_predictions[name], dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"{name} produced nonfinite validation predictions.")
        predictions[name] = np.maximum(values, 0.0)
        error_pp = 100.0 * (predictions[name] - heldout[TARGET_COLUMN]).to_numpy()
        metric_rows.append({
            "model": name,
            "mae_pp": float(np.mean(np.abs(error_pp))),
            "rmse_pp": float(np.sqrt(np.mean(error_pp**2))),
            "bias_pp": float(np.mean(error_pp)),
            "n_forecasts": len(heldout),
            "n_floored": int(np.count_nonzero(values < 0.0)),
        })
    for column in ("target_start", "target_end", "session_number"):
        if column in validation:
            predictions[column] = validation[column]
    scaler = models["ridge"].named_steps["scaler"]
    record = {
        "feature_columns": list(FEATURE_COLUMNS),
        "response_column": TARGET_COLUMN,
        "response_source": {
            "train": TARGET_COLUMN if TARGET_COLUMN in train else "target",
            "validation": TARGET_COLUMN if TARGET_COLUMN in validation else "target",
        },
        "baseline_source": "volatility_20",
        "model_parameters": params,
        "sklearn_version": sklearn_version,
        "selection": "Fixed specifications; no tuning search.",
        "prediction_floor": 0.0,
        "prediction_units": "Unannualized daily-return standard deviation, decimal.",
        "metric_units": "Daily-volatility percentage points (decimal error times 100).",
        "bias_definition": "Prediction minus observed target.",
        "n_train": len(training),
        "n_validation": len(heldout),
        "test_scored": False,
        "ridge_scaler": {
            "fit_partition": "train", "n_samples_seen": int(scaler.n_samples_seen_),
            "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
        },
        "n_floored": {row["model"]: row["n_floored"] for row in metric_rows},
    }
    return predictions, pd.DataFrame(metric_rows), record
