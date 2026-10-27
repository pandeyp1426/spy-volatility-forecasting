"""Prespecified retrospective annual development experiments.

The caller supplies development rows after removing the saved pooled reserved
identities. This module never opens a reserved response file. Calendar cutoffs
come from the full audited price index, not from compressed development rows.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from itertools import product
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from .models import FEATURE_COLUMNS, TARGET_COLUMN, model_frame
from .research import _check_index

VOLATILITY_COLUMNS = ("volatility_5", "volatility_10", "volatility_20")
FAMILIES = ("ridge", "random_forest", "gradient_boosting")
FIXED_PARAMETERS = {
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
SEARCH_SPACE = {
    "ridge": {"alpha": [0.01, 0.1, 1.0, 10.0, 100.0]},
    "random_forest": {"max_depth": [3, 5, 8], "min_samples_leaf": [5, 10, 20]},
    "gradient_boosting": {
        "n_estimators": [100, 200], "learning_rate": [0.03, 0.05], "max_depth": [1, 2, 3],
    },
}
PREDICTION_COLUMNS = [
    "forecast_date", "row_id", "session_number", "target_start", "target_end",
    "fold", "variant", "model", "prediction", "observed", "threshold", "partition", "fit_cutoff",
]
MEMBERSHIP_COLUMNS = [
    "outer_fold", "inner_fold", "level", "partition", "row_id", "forecast_date",
    "session_number", "target_start", "target_end", "fit_cutoff", "outer_fit_cutoff",
]


def validate_temporal_config(config: dict) -> None:
    """Reject protocol drift, including changed grids or fixed specifications."""
    expected = {
        "training_start": "2015-01-01", "outer_years": list(range(2020, 2026)),
        "inner_year_count": 3, "selection_metric": "rmse_pp", "tie_break": "lowest_candidate_id",
        "high_volatility_quantile": 0.95, "prediction_floor": 0.0,
    }
    temporal = config.get("temporal", {})
    for key, value in expected.items():
        if temporal.get(key) != value:
            raise ValueError(f"Temporal protocol {key} must equal prespecified {value!r}.")
    if config.get("fixed") != FIXED_PARAMETERS:
        raise ValueError("Fixed temporal model parameters must preserve the original comparison.")
    if config.get("search") != SEARCH_SPACE:
        raise ValueError("Temporal search must preserve the ordered 26-candidate prespecified grid.")


def candidate_grid(config: dict) -> list[dict]:
    """Enumerate the frozen grid in family/parameter order for deterministic ties."""
    validate_temporal_config(config)
    candidates = []
    for family in FAMILIES:
        space = SEARCH_SPACE[family]
        for values in product(*(space[key] for key in space)):
            parameters = deepcopy(config["fixed"][family])
            parameters.update(dict(zip(space, values)))
            candidates.append({"candidate_id": len(candidates), "model": family, "parameters": parameters})
    return candidates


def _validate_development(development: pd.DataFrame, price_dates: pd.DatetimeIndex) -> None:
    model_frame(development)
    required = {"row_id", "session_number", "target_start", "target_end"}
    if not required.issubset(development):
        raise ValueError("Development rows need row_id, session_number, target_start and target_end metadata.")
    _check_index(pd.Series(index=price_dates, dtype=float))
    if price_dates.empty:
        raise ValueError("Full audited price dates must not be empty.")
    identifiers = development["row_id"]
    if identifiers.isna().any() or not identifiers.is_unique:
        raise ValueError("Development row_id must be nonmissing and unique.")
    sessions = development["session_number"].to_numpy(dtype=float)
    if (not np.isfinite(sessions).all() or (sessions < 0).any()
            or (sessions != np.floor(sessions)).any() or (sessions >= len(price_dates)).any()
            or (np.diff(sessions) <= 0).any()):
        raise ValueError("Development session_number must be increasing original price positions.")
    positions = sessions.astype(np.int64)
    if not price_dates.take(positions).equals(development.index):
        # Index names are not required to match.
        if not np.array_equal(price_dates.take(positions).to_numpy(), development.index.to_numpy()):
            raise ValueError("Forecast dates do not match original price session positions.")
    for column, offset in (("target_start", 1), ("target_end", 5)):
        actual = pd.to_datetime(development[column])
        if (positions + offset >= len(price_dates)).any():
            raise ValueError("Development rows require complete original future target sessions.")
        if actual.isna().any() or not np.array_equal(actual.to_numpy(), price_dates.take(positions + offset).to_numpy()):
            raise ValueError(f"{column} must match the original five-session target window.")


def annual_fold(
    development: pd.DataFrame, price_dates: pd.DatetimeIndex, year: int,
    *, training_start: str = "2015-01-01", outcome_cutoff: pd.Timestamp | None = None,
) -> dict:
    """Build one expanding fold with explicit label-availability exclusions.

    Inner evaluation labels additionally need to be known by the outer fit
    cutoff. A label ending exactly at a fit cutoff is available after close.
    """
    start = pd.Timestamp(year=year, month=1, day=1)
    stop = pd.Timestamp(year=year + 1, month=1, day=1)
    earlier_prices = price_dates[price_dates < start]
    if earlier_prices.empty:
        raise ValueError(f"No actual price session precedes evaluation year {year}.")
    cutoff = earlier_prices[-1]
    target_ends = pd.to_datetime(development["target_end"])
    history = (development.index >= pd.Timestamp(training_start)) & (development.index <= cutoff)
    training = history & (target_ends <= cutoff)
    evaluation_year = (development.index >= start) & (development.index < stop)
    evaluation = evaluation_year.copy()
    if outcome_cutoff is not None:
        evaluation &= target_ends <= pd.Timestamp(outcome_cutoff)
    train = development.loc[training].copy()
    evaluation_frame = development.loc[evaluation].copy()
    if train.empty or evaluation_frame.empty:
        raise ValueError(f"Year {year} has no permitted training or evaluation rows.")
    if not (pd.to_datetime(train["target_end"]) <= cutoff).all():
        raise AssertionError("Training labels are unavailable at the fitting cutoff.")
    if not (evaluation_frame.index > cutoff).all():
        raise AssertionError("Evaluation dates must follow the fitting cutoff.")
    excluded = development.loc[history & ~training].copy()
    excluded["reason"] = "training_label_unavailable_at_fit_cutoff"
    if outcome_cutoff is not None:
        inner_excluded = development.loc[evaluation_year & ~evaluation].copy()
        inner_excluded["reason"] = "inner_evaluation_label_unavailable_at_outer_cutoff"
        excluded = pd.concat([excluded, inner_excluded]).sort_index()
    return {"year": int(year), "fit_cutoff": cutoff, "train": train,
            "evaluation": evaluation_frame, "excluded": excluded,
            "outcome_cutoff": outcome_cutoff}


def _make_estimator(model: str, parameters: dict):
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if model == "ridge":
        return Pipeline([("scaler", StandardScaler()), ("regressor", Ridge(**parameters))])
    if model == "random_forest":
        return RandomForestRegressor(**parameters)
    if model == "gradient_boosting":
        return GradientBoostingRegressor(**parameters)
    raise ValueError(f"Unknown learned-model family: {model}.")


def fit_predict(
    train: pd.DataFrame, evaluation: pd.DataFrame, model: str,
    parameters: dict, features: tuple[str, ...] = FEATURE_COLUMNS,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Fit only on train, returning fitted-train and evaluation predictions."""
    training, heldout = model_frame(train), model_frame(evaluation)
    if train.index.intersection(evaluation.index).size:
        raise ValueError("Fit and evaluation row identities must be disjoint.")
    if features not in (FEATURE_COLUMNS, VOLATILITY_COLUMNS):
        raise ValueError("Only the full or prespecified volatility-only feature allowlist is permitted.")
    start = perf_counter()
    if model in ("baseline", "baseline_5"):
        source = "volatility_20" if model == "baseline" else "volatility_5"
        train_values = training[source].to_numpy()
        evaluation_values = heldout[source].to_numpy()
        record = {"model": model, "parameters": {}, "feature_columns": [source], "fitted": False}
    else:
        estimator = _make_estimator(model, parameters)
        x_train, x_evaluation = training[list(features)], heldout[list(features)]
        estimator.fit(x_train, training[TARGET_COLUMN])
        train_values = np.asarray(estimator.predict(x_train), dtype=float)
        evaluation_values = np.asarray(estimator.predict(x_evaluation), dtype=float)
        record = {"model": model, "parameters": deepcopy(parameters), "feature_columns": list(features), "fitted": True}
        if model == "ridge":
            scaler = estimator.named_steps["scaler"]
            record["scaler"] = {
                "fit_partition": "train", "n_samples_seen": int(scaler.n_samples_seen_),
                "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
            }
    if not np.isfinite(train_values).all() or not np.isfinite(evaluation_values).all():
        raise ValueError(f"{model} produced nonfinite predictions.")
    record.update({"n_train": len(train), "n_evaluation": len(evaluation),
                   "prediction_floor": 0.0,
                   "n_train_floored": int(np.count_nonzero(train_values < 0)),
                   "n_evaluation_floored": int(np.count_nonzero(evaluation_values < 0)),
                   "elapsed_seconds": perf_counter() - start})
    return np.maximum(train_values, 0.0), np.maximum(evaluation_values, 0.0), record


def _prediction_rows(frame, predictions, *, fold, variant, model, threshold, partition, fit_cutoff):
    result = frame.loc[:, ["row_id", "session_number", "target_start", "target_end"]].copy()
    result.insert(0, "forecast_date", frame.index)
    result["fold"] = fold
    result["variant"] = variant
    result["model"] = model
    result["prediction"] = predictions
    result["observed"] = model_frame(frame)[TARGET_COLUMN].to_numpy()
    result["threshold"] = threshold
    result["partition"] = partition
    result["fit_cutoff"] = fit_cutoff
    return result.reset_index(drop=True).loc[:, PREDICTION_COLUMNS]


def _scores(observed, predictions) -> dict:
    error = 100.0 * (np.asarray(predictions) - np.asarray(observed))
    return {"n_forecasts": len(error), "mae_pp": float(np.mean(np.abs(error))),
            "rmse_pp": float(np.sqrt(np.mean(error**2))),
            "bias_pp": float(np.mean(error))}


def choose_candidate(results: pd.DataFrame, model: str) -> dict:
    """Use concatenated inner RMSE, with exact ties broken by candidate ID."""
    valid = results.loc[(results["model"] == model) & (results["status"] == "complete")].copy()
    valid = valid.loc[np.isfinite(valid["rmse_pp"])]
    if valid.empty:
        raise ValueError(f"No complete inner candidate is available for {model}.")
    return valid.sort_values(["rmse_pp", "candidate_id"], kind="stable").iloc[0].to_dict()


def _json_write(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def run_temporal_experiments(
    development: pd.DataFrame, price_dates: pd.DatetimeIndex, config: dict, output: Path,
) -> dict:
    """Run fixed, simple-comparator, nested-tuning and fixed-ablation stages.

    The orchestration layer must freeze config and verify development excludes
    saved reserved IDs before calling. An optional reserved_row_ids list in
    config is checked defensively and contains identities only, not responses.
    Outputs preserve fitted training evidence separately from evaluation.
    """
    started = perf_counter()
    validate_temporal_config(config)
    _validate_development(development, price_dates)
    reserved = set(config.get("reserved_row_ids", []))
    if reserved.intersection(development["row_id"]):
        raise ValueError("Development data contain a protected reserved row identity.")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "temporal_predictions.csv").exists():
        raise FileExistsError("Use a new temporal output directory; existing predictions are preserved.")
    settings = config["temporal"]
    candidates = candidate_grid(config)
    frozen_text = json.dumps(config, sort_keys=True, separators=(",", ":"))
    _json_write(output / "temporal_protocol.json", config)
    _json_write(output / "candidate_grid.json", candidates)
    pd.DataFrame([{"candidate_id": candidate["candidate_id"], "model": candidate["model"],
                   "parameters": json.dumps(candidate["parameters"], sort_keys=True)}
                  for candidate in candidates]).to_csv(output / "candidate_grid.csv", index=False)

    predictions, training_predictions, inner_predictions = [], [], []
    memberships, exclusions, fold_records, model_records = [], [], [], []
    search_results, chosen, failures, timing = [], [], [], []
    outer_folds, inner_folds = {}, {}

    def record_membership(fold, outer_year, level, outer_cutoff):
        inner_year = fold["year"] if level == "inner" else None
        for partition in ("train", "evaluation"):
            frame = fold[partition]
            rows = frame[["row_id", "session_number", "target_start", "target_end"]].copy()
            rows.insert(0, "forecast_date", rows.index)
            rows["outer_fold"], rows["inner_fold"] = outer_year, inner_year
            rows["level"], rows["partition"] = level, partition
            rows["fit_cutoff"], rows["outer_fit_cutoff"] = fold["fit_cutoff"], outer_cutoff
            memberships.append(rows.reset_index(drop=True).loc[:, MEMBERSHIP_COLUMNS])
        excluded = fold["excluded"]
        rows = excluded[["row_id", "session_number", "target_start", "target_end", "reason"]].copy()
        rows.insert(0, "forecast_date", rows.index)
        rows["outer_fold"], rows["inner_fold"] = outer_year, inner_year
        rows["level"], rows["fit_cutoff"] = level, fold["fit_cutoff"]
        rows["outer_fit_cutoff"] = outer_cutoff
        exclusions.append(rows.reset_index(drop=True))
        fold_records.append({
            "outer_fold": outer_year, "inner_fold": inner_year, "level": level,
            "fit_cutoff": fold["fit_cutoff"].date().isoformat(),
            "outer_fit_cutoff": outer_cutoff.date().isoformat(),
            "n_train": len(fold["train"]), "n_evaluation": len(fold["evaluation"]),
            "n_boundary_excluded": len(excluded),
            "first_train_date": fold["train"].index.min().date().isoformat(),
            "last_train_target_end": pd.Timestamp(fold["train"]["target_end"].max()).date().isoformat(),
            "first_evaluation_date": fold["evaluation"].index.min().date().isoformat(),
            "last_evaluation_date": fold["evaluation"].index.max().date().isoformat(),
            "last_evaluation_target_end": pd.Timestamp(fold["evaluation"]["target_end"].max()).date().isoformat(),
        })

    # Prepare and persist all row identities before any fit or score.
    for year in settings["outer_years"]:
        fold = annual_fold(development, price_dates, year, training_start=settings["training_start"])
        outer_folds[year] = fold
        record_membership(fold, year, "outer", fold["fit_cutoff"])
        inner_folds[year] = []
        for inner_year in range(year - settings["inner_year_count"], year):
            inner = annual_fold(development, price_dates, inner_year,
                                training_start=settings["training_start"], outcome_cutoff=fold["fit_cutoff"])
            allowed_outer_ids = set(fold["train"]["row_id"])
            if not (set(inner["train"]["row_id"]) | set(inner["evaluation"]["row_id"])).issubset(allowed_outer_ids):
                raise AssertionError("Inner fitting or evaluation escaped the outer permitted training rows.")
            inner_folds[year].append(inner)
            record_membership(inner, year, "inner", fold["fit_cutoff"])
    pd.concat(memberships, ignore_index=True).to_csv(output / "temporal_membership.csv", index=False)
    pd.concat(exclusions, ignore_index=True).to_csv(output / "temporal_boundary_exclusions.csv", index=False)
    pd.DataFrame(fold_records).to_csv(output / "temporal_folds.csv", index=False)

    def flush():
        if predictions:
            pd.concat(predictions, ignore_index=True).to_csv(output / "temporal_predictions.csv", index=False)
        if training_predictions:
            pd.concat(training_predictions, ignore_index=True).to_csv(output / "temporal_training_predictions.csv", index=False)
        if inner_predictions:
            pd.concat(inner_predictions, ignore_index=True).to_csv(output / "inner_predictions.csv", index=False)
        pd.DataFrame(search_results).to_csv(output / "search_results.csv", index=False)
        pd.DataFrame(failures, columns=["stage", "outer_fold", "inner_fold", "model", "candidate_id", "error"]).to_csv(output / "fit_failures.csv", index=False)
        pd.DataFrame(timing).to_csv(output / "timing.csv", index=False)
        _json_write(output / "model_records.json", model_records)
        _json_write(output / "chosen_parameters.json", chosen)

    def fit_outer(year, variant, model, parameters, features=FEATURE_COLUMNS):
        fold = outer_folds[year]
        threshold = float(model_frame(fold["train"])[TARGET_COLUMN].quantile(settings["high_volatility_quantile"]))
        train_values, evaluation_values, record = fit_predict(fold["train"], fold["evaluation"], model, parameters, features)
        record.update({"outer_fold": year, "inner_fold": None, "variant": variant,
                       "fit_cutoff": fold["fit_cutoff"].date().isoformat(), "threshold": threshold})
        model_records.append(record)
        timing.append({"stage": variant, "outer_fold": year, "inner_fold": None,
                       "model": model, "candidate_id": None, "elapsed_seconds": record["elapsed_seconds"]})
        for partition, values, destination in (("train", train_values, training_predictions),
                                                ("evaluation", evaluation_values, predictions)):
            destination.append(_prediction_rows(fold[partition], values, fold=year, variant=variant,
                                                model=model, threshold=threshold, partition=partition,
                                                fit_cutoff=fold["fit_cutoff"]))

    try:
        # The declared sequence first isolates evaluation design with fixed settings.
        for year in settings["outer_years"]:
            for model in ("baseline", *FAMILIES):
                fit_outer(year, "fixed", model, config["fixed"].get(model, {}))
        flush()
        for year in settings["outer_years"]:
            fit_outer(year, "comparator", "baseline_5", {})
        flush()

        for year in settings["outer_years"]:
            print(f"Temporal inner search: outer {year}, {len(candidates)} frozen candidates.", flush=True)
            local_results = []
            for candidate in candidates:
                candidate_started = perf_counter()
                evaluation_parts = []
                status = "complete"
                for inner in inner_folds[year]:
                    inner_year = inner["year"]
                    try:
                        _, values, record = fit_predict(inner["train"], inner["evaluation"],
                                                        candidate["model"], candidate["parameters"])
                        threshold = float(model_frame(inner["train"])[TARGET_COLUMN].quantile(settings["high_volatility_quantile"]))
                        rows = _prediction_rows(inner["evaluation"], values, fold=inner_year,
                                                variant="inner_candidate", model=candidate["model"],
                                                threshold=threshold, partition="inner_evaluation",
                                                fit_cutoff=inner["fit_cutoff"])
                        rows["outer_fold"], rows["candidate_id"] = year, candidate["candidate_id"]
                        evaluation_parts.append(rows)
                        inner_predictions.append(rows)
                        record.update({"outer_fold": year, "inner_fold": inner_year,
                                       "variant": "inner_candidate", "candidate_id": candidate["candidate_id"],
                                       "fit_cutoff": inner["fit_cutoff"].date().isoformat(), "threshold": threshold})
                        model_records.append(record)
                        timing.append({"stage": "inner_candidate", "outer_fold": year, "inner_fold": inner_year,
                                       "model": candidate["model"], "candidate_id": candidate["candidate_id"],
                                       "elapsed_seconds": record["elapsed_seconds"]})
                    except Exception as exc:
                        status = "failed"
                        failures.append({"stage": "inner_candidate", "outer_fold": year, "inner_fold": inner_year,
                                         "model": candidate["model"], "candidate_id": candidate["candidate_id"],
                                         "error": f"{type(exc).__name__}: {exc}"})
                result = {"outer_fold": year, "candidate_id": candidate["candidate_id"], "model": candidate["model"],
                          "parameters": json.dumps(candidate["parameters"], sort_keys=True), "status": status,
                          "n_inner_folds_complete": len(evaluation_parts),
                          "elapsed_seconds": perf_counter() - candidate_started,
                          "n_forecasts": 0, "mae_pp": np.nan, "rmse_pp": np.nan, "bias_pp": np.nan}
                if status == "complete":
                    complete = pd.concat(evaluation_parts, ignore_index=True)
                    result.update(_scores(complete["observed"], complete["prediction"]))
                local_results.append(result)
                search_results.append(result)
            for model in FAMILIES:
                selected = choose_candidate(pd.DataFrame(local_results), model)
                parameters = json.loads(selected["parameters"])
                chosen.append({"outer_fold": year, "model": model, "candidate_id": int(selected["candidate_id"]),
                               "parameters": parameters, "inner_rmse_pp": float(selected["rmse_pp"]),
                               "inner_n_forecasts": int(selected["n_forecasts"]),
                               "selection_metric": settings["selection_metric"], "tie_break": settings["tie_break"]})
                fit_outer(year, "tuned", model, parameters)
            flush()

        for year in settings["outer_years"]:
            for model in FAMILIES:
                fit_outer(year, "volatility_only", model, config["fixed"][model], VOLATILITY_COLUMNS)
        flush()
    except Exception as exc:
        failures.append({"stage": "run", "outer_fold": None, "inner_fold": None, "model": None,
                         "candidate_id": None, "error": f"{type(exc).__name__}: {exc}"})
        flush()
        _json_write(output / "temporal_summary.json", {"status": "failed", "test_scored": False,
                                                       "error": f"{type(exc).__name__}: {exc}"})
        raise

    result = pd.concat(predictions, ignore_index=True)
    expected_ids = None
    for (variant, model), values in result.groupby(["variant", "model"], sort=False):
        ids = set(zip(values["fold"], values["row_id"]))
        if len(ids) != len(values) or (expected_ids is not None and ids != expected_ids):
            raise AssertionError("Outer model comparisons must use identical unique evaluation identities.")
        expected_ids = ids
    metrics = []
    for (variant, model), values in result.groupby(["variant", "model"], sort=False):
        metrics.append({"variant": variant, "model": model, **_scores(values["observed"], values["prediction"])})
    pd.DataFrame(metrics).to_csv(output / "temporal_metrics.csv", index=False)
    summary = {
        "status": "complete", "experiment": settings["name"],
        "protocol_sha256": hashlib.sha256(frozen_text.encode("utf-8")).hexdigest(),
        "outer_years": settings["outer_years"], "n_development_rows": len(development),
        "n_evaluation_rows": len(expected_ids), "n_candidates_per_outer_fold": len(candidates),
        "n_inner_folds": settings["inner_year_count"], "n_search_candidates_scored": len(search_results),
        "n_model_records": len(model_records), "n_fit_failures": len(failures),
        "elapsed_seconds": perf_counter() - started, "selection_metric": settings["selection_metric"],
        "tie_break": settings["tie_break"], "high_volatility_quantile": settings["high_volatility_quantile"],
        "test_scored": False, "feature_columns": list(FEATURE_COLUMNS),
        "ablation_feature_columns": list(VOLATILITY_COLUMNS),
        "prediction_units": "Decimal daily-return standard deviation.",
        "metric_units": "Daily-volatility percentage points (decimal error times 100).",
        "training_scores": "Descriptive in-sample fitted scores; not development validation.",
        "limitations": ["Retrospective development evaluation after historical data reuse.",
                        "Excluding reserved row identities does not remove underlying-return information overlap.",
                        "Adjacent evaluation targets overlap; no iid significance claims."],
        "metrics": metrics,
        "artifacts": sorted(path.name for path in output.iterdir() if path.is_file()),
    }
    _json_write(output / "temporal_summary.json", summary)
    return summary
