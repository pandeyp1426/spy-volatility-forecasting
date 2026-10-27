"""Full-precision development diagnostics; this module never loads a test table.

Inputs are saved long-form predictions in decimal daily-volatility units. A
caller must supply each fit's training-derived 95th percentile; evaluation
outcomes never set that threshold. Tail groups are explicitly ex-post.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd


GROUPS = ["variant", "model"]
KEYS = ["fold", "row_id"]
METRICS = ["mae_pp", "rmse_pp", "mse_pp2", "bias_pp"]
REQUIRED = {*KEYS, *GROUPS, "forecast_date", "prediction", "observed", "threshold"}


def error_metrics(frame: pd.DataFrame) -> dict:
    """Errors in percentage points, with unavailable values for empty groups."""
    n = len(frame)
    if not n:
        return {"n_forecasts": 0, **dict.fromkeys(METRICS, np.nan)}
    errors = 100.0 * (frame["prediction"].to_numpy(float) - frame["observed"].to_numpy(float))
    mse = float(np.mean(errors * errors))
    return {"n_forecasts": n, "mae_pp": float(np.mean(np.abs(errors))),
            "rmse_pp": math.sqrt(mse), "mse_pp2": mse, "bias_pp": float(np.mean(errors))}


def validate_predictions(frame: pd.DataFrame, *, training: bool = False) -> pd.DataFrame:
    """Reject mixed samples, contradictory observations, or reserved partitions."""
    if frame.empty or not REQUIRED.issubset(frame.columns):
        raise ValueError(f"Nonempty long predictions require {sorted(REQUIRED)}")
    checked = frame.copy()
    checked["forecast_date"] = pd.to_datetime(checked["forecast_date"], errors="raise")
    if checked[list(REQUIRED)].isna().any().any():
        raise ValueError("Prediction identities, dates, outcomes and thresholds must be nonmissing")
    if checked["forecast_date"].dt.tz is not None:
        raise ValueError("Use timezone-free forecast session dates")
    values = checked[["prediction", "observed", "threshold"]].to_numpy(float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Predictions, outcomes and training thresholds must be finite and nonnegative")
    if "partition" in checked:
        partitions = checked["partition"].astype(str).str.lower()
        if partitions.str.contains("test|reserved", regex=True).any():
            raise ValueError("Reserved/test rows cannot enter development diagnostics")
        is_train = partitions.str.contains("train|fitted", regex=True)
        if training != bool(is_train.all()) or (not training and is_train.any()):
            raise ValueError("Fitted training and development predictions must be passed separately")
    if checked.duplicated([*KEYS, *GROUPS]).any():
        raise ValueError("Prediction row identities must be unique within each fold and model variant")
    if (checked.groupby("fold")["threshold"].nunique() != 1).any():
        raise ValueError("Each fold must use one training-derived threshold for every model")
    for column in ("observed", "forecast_date", "threshold"):
        if (checked.groupby(KEYS)[column].nunique() != 1).any():
            raise ValueError(f"Models disagree on {column} for a shared evaluation identity")
    reference = None
    for _, group in checked.groupby(GROUPS, sort=True):
        identities = set(map(tuple, group[KEYS].to_numpy()))
        if reference is not None and identities != reference:
            raise ValueError("All model variants must use identical scoring rows within each fold")
        reference = identities
    return checked.sort_values([*GROUPS, "fold", "forecast_date"]).reset_index(drop=True)


def _grouped(frame: pd.DataFrame, extra: list[str] | None = None) -> pd.DataFrame:
    keys = [*GROUPS, *(extra or [])]
    rows = []
    for values, group in frame.groupby(keys, sort=True, dropna=False):
        rows.append({**dict(zip(keys, values)), **error_metrics(group)})
    return pd.DataFrame(rows, columns=[*keys, "n_forecasts", *METRICS])


def _tail(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for scope, keys in (("aggregate", GROUPS), ("fold", [*GROUPS, "fold"])):
        for values, group in frame.groupby(keys, sort=True):
            for label, mask in (("below_training_q95", group.observed < group.threshold),
                                ("at_or_above_training_q95", group.observed >= group.threshold)):
                subset = group.loc[mask]
                rows.append({"aggregation": scope, **dict(zip(keys, values)), "tail_group": label,
                             "threshold_min_decimal": float(group.threshold.min()),
                             "threshold_max_decimal": float(group.threshold.max()),
                             "availability": "available" if len(subset) else "empty; unavailable",
                             **error_metrics(subset)})
    return pd.DataFrame(rows)


def _gap(evaluation: pd.DataFrame, training: pd.DataFrame | None) -> pd.DataFrame:
    rows = []
    for scope, keys in (("aggregate", GROUPS), ("fold", [*GROUPS, "fold"])):
        train_groups = {} if training is None else dict(tuple(training.groupby(keys, sort=True)))
        for values, group in evaluation.groupby(keys, sort=True):
            fitted = train_groups.get(values)
            train_score = error_metrics(fitted) if fitted is not None else error_metrics(group.iloc[:0])
            dev_score = error_metrics(group)
            row = {"aggregation": scope, **dict(zip(keys, values)),
                   "availability": "available" if fitted is not None else "training predictions unavailable",
                   "training_n_forecasts": train_score["n_forecasts"],
                   "development_n_forecasts": dev_score["n_forecasts"]}
            for metric in METRICS:
                row[f"training_{metric}"] = train_score[metric]
                row[f"development_{metric}"] = dev_score[metric]
                row[f"gap_{metric}"] = dev_score[metric] - train_score[metric]
            rows.append(row)
    return pd.DataFrame(rows)


def _comparisons(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (variant, model), group in frame.groupby(GROUPS, sort=True):
        score = error_metrics(group)
        for benchmark in ("baseline", "baseline_5"):
            reference = frame.loc[frame.model == benchmark]
            if not reference.empty:
                # A benchmark can be repeated across variants only if identical.
                if (reference.groupby(KEYS).prediction.nunique() != 1).any():
                    raise ValueError(f"Conflicting predictions for {benchmark}")
                reference = reference.drop_duplicates(KEYS)
            row = {"variant": variant, "model": model, "benchmark": benchmark,
                   "n_forecasts": len(group), "availability": "available" if len(reference) else "benchmark unavailable"}
            if not len(reference):
                row.update(relative_mae_improvement_pct=np.nan, relative_rmse_improvement_pct=np.nan,
                           folds_mae_improved=0, folds_rmse_improved=0, folds_compared=0)
            else:
                base_score = error_metrics(reference)
                for metric in ("mae", "rmse"):
                    denominator = base_score[f"{metric}_pp"]
                    row[f"relative_{metric}_improvement_pct"] = (
                        100 * (1 - score[f"{metric}_pp"] / denominator) if denominator > 0 else np.nan)
                    improved = 0
                    for fold, selected in group.groupby("fold"):
                        baseline = reference.loc[reference.fold == fold]
                        improved += error_metrics(selected)[f"{metric}_pp"] < error_metrics(baseline)[f"{metric}_pp"]
                    row[f"folds_{metric}_improved"] = int(improved)
                row["folds_compared"] = int(group.fold.nunique())
            rows.append(row)
    return pd.DataFrame(rows)


def _plots(frame: pd.DataFrame, folder: Path, scope: str) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = list(frame.groupby(GROUPS, sort=True))
    colors = {"fixed": "#2376a4", "tuned": "#b25d24", "volatility_only": "#6b6e39", "comparator": "#666666"}
    paths = []
    for kind in ("scatter", "history", "errors"):
        ncols = 2 if kind != "scatter" else 3
        nrows = len(groups) if kind == "errors" else math.ceil(len(groups) / ncols)
        figure, axes = plt.subplots(nrows, ncols, figsize=(13, max(3.3, nrows * 2.65)),
                                    squeeze=False, layout="constrained")
        for index, ((variant, model), group) in enumerate(groups):
            observed, prediction = 100 * group.observed, 100 * group.prediction
            errors = prediction - observed
            color = colors.get(variant, "#2376a4")
            if kind == "errors":
                left, right = axes[index]
                left.scatter(group.forecast_date, errors, s=6, alpha=.42, color=color, rasterized=True)
                right.scatter(prediction, errors, s=6, alpha=.42, color=color, rasterized=True)
                left.set(xlabel="Actual forecast date", ylabel="Signed error (pp)", title=f"{variant}: {model}")
                right.set(xlabel="Prediction (%)", ylabel="Signed error (pp)")
                for axis in (left, right):
                    axis.axhline(0, color="black", linewidth=.8)
                    axis.grid(alpha=.18)
            else:
                axis = axes.flat[index]
                axis.set_title(f"{variant}: {model}", fontsize=10)
                if kind == "scatter":
                    upper = max(float(observed.max()), float(prediction.max())) * 1.04
                    axis.scatter(observed, prediction, s=7, alpha=.4, color=color, rasterized=True)
                    axis.plot([0, upper], [0, upper], color="black", linewidth=.8)
                    axis.set(xlabel="Observed daily volatility (%)", ylabel="Prediction (%)", xlim=(0, upper), ylim=(0, upper))
                else:
                    # Points deliberately avoid connecting gaps in reserved/random subsets.
                    axis.scatter(group.forecast_date, observed, s=6, alpha=.45, color="#666666", label="Observed", rasterized=True)
                    axis.scatter(group.forecast_date, prediction, s=6, alpha=.5, color=color, label="Predicted", rasterized=True)
                    axis.set(xlabel="Actual forecast date", ylabel="Daily volatility (%)")
                    axis.legend(fontsize=7, loc="upper right")
                axis.grid(alpha=.18)
        if kind != "errors":
            for axis in list(axes.flat)[len(groups):]:
                axis.set_visible(False)
        figure.suptitle(f"{scope.replace('_', ' ').title()}: development predictions only", fontsize=12)
        for extension in ("pdf", "png"):
            path = folder / f"diagnostic_{scope}_{kind}.{extension}"
            figure.savefig(path, dpi=150)
            paths.append(path.as_posix())
        plt.close(figure)
    return paths


def write_diagnostics(predictions: pd.DataFrame, training_predictions: pd.DataFrame | None,
                      output: Path, scope: str) -> dict:
    """Write auditable tables and figures for one separately identified scope."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", scope) or "test" in scope:
        raise ValueError("Use a development diagnostic scope such as pooled or temporal")
    evaluation = validate_predictions(predictions)
    training = None if training_predictions is None else validate_predictions(training_predictions, training=True)
    if training is not None:
        eval_groups = set(map(tuple, evaluation[["fold", *GROUPS]].drop_duplicates().to_numpy()))
        train_groups = set(map(tuple, training[["fold", *GROUPS]].drop_duplicates().to_numpy()))
        if train_groups != eval_groups:
            raise ValueError("Training scores must describe the same fitted models/folds as development")
        eval_ids = set(map(tuple, evaluation[KEYS].to_numpy()))
        train_ids = set(map(tuple, training[KEYS].to_numpy()))
        if eval_ids & train_ids:
            raise ValueError("The same fold cannot fit and evaluate the same row identity")
        thresholds = evaluation.groupby("fold").threshold.first()
        if not thresholds.equals(training.groupby("fold").threshold.first()):
            raise ValueError("Training and development threshold metadata differ")
    output = Path(output)
    table_dir, figure_dir = output / "tables", output / "figures"
    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)
    evaluation["year"] = evaluation.forecast_date.dt.year
    tables = {"aggregate": _grouped(evaluation), "year": _grouped(evaluation, ["year"]),
              "fold": _grouped(evaluation, ["fold"]), "tail": _tail(evaluation),
              "gap": _gap(evaluation, training), "comparisons": _comparisons(evaluation)}
    paths = {}
    for name, table in tables.items():
        path = table_dir / f"diagnostic_{scope}_{name}.csv"
        table.to_csv(path, index=False, na_rep="")
        paths[name] = path.as_posix()
    figures = _plots(evaluation, figure_dir, scope)
    result = {"scope": scope, "unique_development_rows": int(evaluation[KEYS].drop_duplicates().shape[0]),
              "model_variants": len(tables["aggregate"]), "tables": paths, "figures": figures,
              "units": {"mae_pp": "daily-volatility percentage points", "rmse_pp": "daily-volatility percentage points",
                        "mse_pp2": "squared percentage points", "bias_pp": "daily-volatility percentage points"},
              "test_scored": False, "training_predictions_available": training is not None,
              "tail_rule": "observed >= supplied training target 95th percentile; ex-post diagnostic",
              "gap_definition": "development minus fitted training error; training score is descriptive, not validation",
              "training_aggregation": "Concatenated fitted predictions; a row reused in later annual fits appears once per fit.",
              "limitations": ["Overlapping targets are dependent; no iid significance claims.",
                              "Zero benchmark error gives unavailable relative improvement.",
                              "No lines connect missing/subsampled dates in history or signed-error plots."]}
    (output / f"diagnostic_{scope}_summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
