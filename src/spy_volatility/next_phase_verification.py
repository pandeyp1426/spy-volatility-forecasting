"""Independent arithmetic and identity audit of saved temporal development evidence.

Reads only development observations and reserved identity metadata. Does not
fit models or open reserved response matrices. Folds are rebuilt with explicit
timestamp masks independently of the production fold constructor.
"""
import json
from copy import deepcopy
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from .verification import _close, _require, CalculationVerificationError


FEATURES = ["log_return", "volatility_5", "volatility_10", "volatility_20", "momentum_5"]
VOLATILITY_FEATURES = ["volatility_5", "volatility_10", "volatility_20"]
FAMILIES = ("ridge", "random_forest", "gradient_boosting")


def _read(path, dates=()):
    return pd.read_csv(path, parse_dates=list(dates), float_precision="round_trip")


def _scores(group):
    error = 100*(group.prediction.to_numpy()-group.observed.to_numpy())
    return {"n_forecasts": len(error), "mae_pp": np.abs(error).mean() if len(error) else np.nan,
            "mse_pp2": np.square(error).mean() if len(error) else np.nan,
            "rmse_pp": np.sqrt(np.square(error).mean()) if len(error) else np.nan,
            "bias_pp": error.mean() if len(error) else np.nan}


def _keys(frame, columns):
    return {tuple(None if pd.isna(value) else value for value in row)
            for row in frame[columns].itertuples(index=False, name=None)}


def _complete_table(frame, columns, expected, label):
    _require(not frame.duplicated(columns).any() and _keys(frame, columns) == expected,
             f"{label}: missing, extra or duplicate diagnostic groups")


def _metric_close(actual, expected, label):
    if pd.isna(expected):
        _require(pd.isna(actual), f"{label}: unavailable metric must remain missing")
    else:
        _close(actual, expected, label)


def _expected_grid(config):
    """Reconstruct candidate identity/parameter order from the frozen protocol."""
    parameter_order = {"ridge": ("alpha",), "random_forest": ("max_depth", "min_samples_leaf"),
                       "gradient_boosting": ("n_estimators", "learning_rate", "max_depth")}
    result = []
    for model in FAMILIES:
        keys = parameter_order[model]
        for values in product(*(config["search"][model][key] for key in keys)):
            parameters = deepcopy(config["fixed"][model])
            parameters.update(zip(keys, values))
            result.append({"candidate_id": len(result), "model": model, "parameters": parameters})
    return result


def _verify_gap_and_comparisons(output, scope, evaluation, training):
    """Independently check saved fitted-score gaps and benchmark comparisons."""
    groups = ["variant", "model"]
    gaps = _read(output/"tables"/f"diagnostic_{scope}_gap.csv")
    expected_gaps = {("aggregate", *key, None) for key in _keys(evaluation, groups)}
    expected_gaps |= {("fold", *key) for key in _keys(evaluation, [*groups, "fold"])}
    _complete_table(gaps, ["aggregation", *groups, "fold"], expected_gaps, f"{scope}/gap")
    for row in gaps.to_dict("records"):
        observed = evaluation.loc[(evaluation.variant == row["variant"]) & (evaluation.model == row["model"])]
        fitted = training.loc[(training.variant == row["variant"]) & (training.model == row["model"])]
        if row["aggregation"] == "fold":
            observed = observed.loc[observed.fold == row["fold"]]
            fitted = fitted.loc[fitted.fold == row["fold"]]
        _require(not fitted.empty and row["availability"] == "available", "Fitted training diagnostic missing")
        train_score, score = _scores(fitted), _scores(observed)
        _require(row["training_n_forecasts"] == len(fitted) and row["development_n_forecasts"] == len(observed),
                 "Training/development gap counts differ")
        for metric in ("mae_pp", "rmse_pp", "mse_pp2", "bias_pp"):
            _metric_close(row[f"training_{metric}"], train_score[metric], f"{scope}/gap/training/{metric}")
            _metric_close(row[f"development_{metric}"], score[metric], f"{scope}/gap/development/{metric}")
            _metric_close(row[f"gap_{metric}"], score[metric] - train_score[metric], f"{scope}/gap/{metric}")
    comparisons = _read(output/"tables"/f"diagnostic_{scope}_comparisons.csv")
    expected_comparisons = {(*key, benchmark) for key in _keys(evaluation, groups)
                            for benchmark in ("baseline", "baseline_5")}
    _complete_table(comparisons, [*groups, "benchmark"], expected_comparisons, f"{scope}/comparisons")
    for row in comparisons.to_dict("records"):
        group = evaluation.loc[(evaluation.variant == row["variant"]) & (evaluation.model == row["model"])]
        baseline = evaluation.loc[evaluation.model == row["benchmark"]]
        _require(row["n_forecasts"] == len(group), "Benchmark comparison count differs")
        if baseline.empty:
            _require(row["availability"] == "benchmark unavailable" and row["folds_compared"] == 0,
                     "Unavailable benchmark must not have scored folds")
            for metric in ("mae", "rmse"):
                _require(pd.isna(row[f"relative_{metric}_improvement_pct"]) and row[f"folds_{metric}_improved"] == 0,
                         "Unavailable benchmark comparison must remain unavailable")
            continue
        _require((baseline.groupby(["fold", "row_id"]).prediction.nunique() == 1).all(),
                 "Benchmark has contradictory repeated predictions")
        baseline = baseline.drop_duplicates(["fold", "row_id"])
        _require(_keys(group, ["fold", "row_id"]) == _keys(baseline, ["fold", "row_id"]),
                 "Benchmark comparison uses different evaluation identities")
        _require(row["availability"] == "available" and row["folds_compared"] == group.fold.nunique(),
                 "Benchmark fold count or availability differs")
        actual_score, baseline_score = _scores(group), _scores(baseline)
        for metric in ("mae", "rmse"):
            denominator = baseline_score[f"{metric}_pp"]
            improvement = 100*(1-actual_score[f"{metric}_pp"]/denominator) if denominator > 0 else np.nan
            _metric_close(row[f"relative_{metric}_improvement_pct"], improvement,
                          f"{scope}/comparison/{metric} relative improvement")
            n_improved = sum(_scores(rows)[f"{metric}_pp"] < _scores(baseline.loc[baseline.fold == fold])[f"{metric}_pp"]
                             for fold, rows in group.groupby("fold"))
            _require(row[f"folds_{metric}_improved"] == n_improved, "Benchmark improved-fold count differs")


def verify_next_phase(output: Path, prices: pd.Series, config: dict):
    report = {"passed": False, "reserved_response_files_read": False, "checks": []}
    try:
        dates = ["forecast_date", "target_start", "target_end"]
        dev = _read(output/"development.csv", dates).set_index("row_id", drop=False)
        reserved = _read(output/"reserved_identities.csv", dates)
        split = _read(output/"source_split_assignments.csv", dates)
        sealed = set(reserved.row_id)
        _require(set(dev.row_id) == set(split.loc[split.partition != "test", "row_id"]), "Development IDs differ from saved source roles")
        _require(sealed == set(split.loc[split.partition == "test", "row_id"]), "Reserved identities changed")
        _require(not set(dev.row_id) & sealed and dev.row_id.is_unique, "Reserved or duplicate development ID")
        pos = dev.session_number.to_numpy(dtype=int)
        raw = prices.to_numpy()
        returns = np.r_[np.nan, np.log(raw[1:]/raw[:-1])]
        for key, shift in (("forecast_date", 0), ("target_start", 1), ("target_end", 5)):
            _require(np.array_equal(dev[key], prices.index[pos+shift]), f"Development {key} alignment")
        _close(dev.log_return, returns[pos], "Development return")
        for window in (5, 10, 20):
            _close(dev[f"volatility_{window}"], [np.std(returns[p-window+1:p+1], ddof=1) for p in pos], f"Development window {window}")
        _close(dev.target, [np.std(returns[p+1:p+6], ddof=1) for p in pos], "Development future response")
        _close(dev.momentum_5, [sum(returns[p-4:p+1]) for p in pos], "Development momentum")
        membership = _read(output/"temporal_membership.csv", dates+["fit_cutoff", "outer_fit_cutoff"])
        boundary = _read(output/"temporal_boundary_exclusions.csv", dates+["fit_cutoff", "outer_fit_cutoff"])
        _require(not set(membership.row_id) & sealed, "Reserved ID in inner/outer membership")
        fold_data = {}
        expected_exclusions = set()
        for year in config["temporal"]["outer_years"]:
            outer_cutoff = prices.index[prices.index.year < year][-1]
            for level, fold_year in [("outer", year)]+[("inner", y) for y in range(year-3, year)]:
                cutoff = prices.index[prices.index.year < fold_year][-1]
                history = (dev.forecast_date >= pd.Timestamp("2015-01-01")) & (dev.forecast_date <= cutoff)
                train = dev.loc[history & (dev.target_end <= cutoff)]
                eval_mask = dev.forecast_date.dt.year == fold_year
                if level == "inner":
                    eval_mask &= dev.target_end <= outer_cutoff
                evaluation = dev.loc[eval_mask]
                key = (year, level, fold_year if level == "inner" else None)
                fold_data[key] = (train, evaluation, cutoff)
                selected = membership.loc[(membership.outer_fold == year) & (membership.level == level)]
                if level == "inner":
                    selected = selected.loc[selected.inner_fold == fold_year]
                for name, expected in (("train", train), ("evaluation", evaluation)):
                    actual = selected.loc[selected.partition == name]
                    _require(len(actual) == len(expected) and set(actual.row_id) == set(expected.row_id), f"{key}: {name} membership mismatch")
                    _require((actual.fit_cutoff == cutoff).all(), "Wrong actual trading-session cutoff")
                    _require((actual.outer_fit_cutoff == outer_cutoff).all(), "Wrong outer cutoff")
                    reference = dev.loc[actual.row_id]
                    for column in dates+["session_number"]:
                        _require(np.array_equal(actual[column], reference[column]), "Saved membership metadata differs")
                for rid in dev.loc[history & (dev.target_end > cutoff), "row_id"]:
                    expected_exclusions.add((*key, int(rid), "training_label_unavailable_at_fit_cutoff"))
                if level == "inner":
                    for rid in dev.loc[(dev.forecast_date.dt.year == fold_year) & (dev.target_end > outer_cutoff), "row_id"]:
                        expected_exclusions.add((*key, int(rid), "inner_evaluation_label_unavailable_at_outer_cutoff"))
                    outer_train = dev.loc[(dev.forecast_date <= outer_cutoff) & (dev.target_end <= outer_cutoff)]
                    _require((set(train.row_id)|set(evaluation.row_id)).issubset(set(outer_train.row_id)), "Inner/outer data separation failed")
        actual_exclusions = {(int(r.outer_fold), r.level, int(r.inner_fold) if pd.notna(r.inner_fold) else None,
                              int(r.row_id), r.reason) for r in boundary.itertuples()}
        _require(actual_exclusions == expected_exclusions and len(boundary) == len(expected_exclusions), "Boundary exclusions incomplete or incorrect")
        pred = _read(output/"temporal_predictions.csv", dates+["fit_cutoff"])
        fitted = _read(output/"temporal_training_predictions.csv", dates+["fit_cutoff"])
        inner = _read(output/"inner_predictions.csv", dates+["fit_cutoff"])
        expected_variants = {("fixed", n) for n in ("baseline", *FAMILIES)}
        expected_variants |= {("comparator", "baseline_5")}
        expected_variants |= {(variant, model) for variant in ("tuned", "volatility_only") for model in FAMILIES}
        expected_outer_groups = {(year, *pair) for year in config["temporal"]["outer_years"] for pair in expected_variants}
        for frame, kind in ((pred, "evaluation"), (fitted, "train")):
            _require(_keys(frame, ["fold", "variant", "model"]) == expected_outer_groups,
                     f"Missing or unexpected outer {kind} model/fold group")
        grid = _expected_grid(config)
        _require(json.loads((output/"candidate_grid.json").read_text()) == grid,
                 "Saved candidate grid differs from frozen protocol")
        candidates = {candidate["candidate_id"]: candidate for candidate in grid}
        search = _read(output/"search_results.csv")
        expected_search = {(year, candidate["candidate_id"], candidate["model"])
                           for year in config["temporal"]["outer_years"] for candidate in grid}
        _complete_table(search, ["outer_fold", "candidate_id", "model"], expected_search, "Inner candidate search")
        _require(set(search.status).issubset({"complete", "failed"}), "Unknown candidate completion status")
        allowed_inner = {(year, candidate_id, fold, model) for year, candidate_id, model in expected_search
                         for fold in range(year-3, year)}
        actual_inner = _keys(inner, ["outer_fold", "candidate_id", "fold", "model"])
        _require(actual_inner.issubset(allowed_inner), "Unexpected inner candidate/fold group")
        for row in search.itertuples():
            _require(json.loads(row.parameters) == candidates[row.candidate_id]["parameters"],
                     "Candidate search parameters differ from frozen grid")
            successful = {group for group in actual_inner if group[0] == row.outer_fold and group[1] == row.candidate_id}
            _require(row.n_inner_folds_complete == len(successful), "Candidate successful-fold count differs")
            if row.status == "complete":
                _require(successful == {(row.outer_fold, row.candidate_id, year, row.model)
                                        for year in range(row.outer_fold-3, row.outer_fold)},
                         "Complete candidate is missing an inner evaluation fold")
            else:
                _require(len(successful) < 3 and pd.isna(row.rmse_pp), "Failed candidate must not have a selection score")
        for frame, kind in ((pred, "evaluation"), (fitted, "train"), (inner, "inner_evaluation")):
            _require(not set(frame.row_id) & sealed, "Reserved row in scored predictions")
            _require(np.isfinite(frame[["prediction", "observed", "threshold"]]).all().all(), "Nonfinite scored value")
            _require((frame.prediction >= 0).all() and (frame.partition == kind).all(), "Incorrect prediction floor or role")
            _close(frame.observed, dev.loc[frame.row_id, "target"], "Saved observed responses")
            keys = ["outer_fold", "candidate_id", "fold", "model"] if kind == "inner_evaluation" else ["fold", "variant", "model"]
            for identity, group in frame.groupby(keys):
                if kind == "inner_evaluation":
                    outer, _, inner_year, _ = identity
                    train, evaluation, cutoff = fold_data[(outer, "inner", inner_year)]
                    expected = evaluation
                else:
                    year, _, _ = identity
                    train, evaluation, cutoff = fold_data[(year, "outer", None)]
                    expected = train if kind == "train" else evaluation
                _require(group.row_id.is_unique and set(group.row_id) == set(expected.row_id), "Scoring identities differ from permitted folds")
                _require((group.fit_cutoff == cutoff).all(), "Prediction fit timestamp differs")
                for col in dates+["session_number"]:
                    _require(np.array_equal(group[col], dev.loc[group.row_id,col]), "Prediction metadata differs")
                _close(group.threshold, np.repeat(train.target.quantile(.95), len(group)), "Training-only tail threshold")
        for model, column in (("baseline", "volatility_20"), ("baseline_5", "volatility_5")):
            sub = pred.loc[pred.model == model]
            _close(sub.prediction, dev.loc[sub.row_id, column], "Historical comparator predictions")
        _require(len(search) == 26*len(config["temporal"]["outer_years"]), "Wrong number of search candidates")
        for row in search.itertuples():
            if row.status != "complete":
                continue  # Failed candidates remain recorded and ineligible.
            selected = inner.loc[(inner.outer_fold == row.outer_fold) & (inner.candidate_id == row.candidate_id)]
            _require(selected.fold.nunique() == 3 and len(selected) == row.n_forecasts, "Incomplete inner OOF sample")
            for metric, value in _scores(selected).items():
                if metric != "mse_pp2":
                    _close(getattr(row, metric), value, f"Candidate {row.candidate_id}: {metric}")
        chosen = json.loads((output/"chosen_parameters.json").read_text())
        chosen_keys = {(row["outer_fold"], row["model"]) for row in chosen}
        _require(len(chosen_keys) == len(chosen) and chosen_keys == {
            (year, model) for year in config["temporal"]["outer_years"] for model in FAMILIES}, "Missing or duplicate family selection")
        selected_parameters = {}
        for selected in chosen:
            options = search.loc[(search.outer_fold == selected["outer_fold"]) & (search.model == selected["model"]) & (search.status == "complete")]
            best = options.sort_values(["rmse_pp", "candidate_id"], kind="stable").iloc[0]
            _require(best.candidate_id == selected["candidate_id"] and json.loads(best.parameters) == selected["parameters"], "Selected candidate violates RMSE/tie-break rule")
            selected_parameters[(selected["outer_fold"], selected["model"])] = selected["parameters"]
        model_records = json.loads((output/"model_records.json").read_text())
        actual_records = [(row["outer_fold"], row["inner_fold"], row["variant"], row["model"], row.get("candidate_id"))
                          for row in model_records]
        expected_records = {(year, None, variant, model, None) for year, variant, model in expected_outer_groups}
        expected_records |= {(year, fold, "inner_candidate", model, candidate_id)
                             for year, candidate_id, fold, model in actual_inner}
        _require(len(set(actual_records)) == len(actual_records) and set(actual_records) == expected_records,
                 "Missing, duplicate or unexpected fitted model record")
        for record in model_records:
            key = (record["outer_fold"], "inner" if record["inner_fold"] is not None else "outer", record["inner_fold"])
            train, evaluation, cutoff = fold_data[key]
            _require(record["n_train"] == len(train) and record["n_evaluation"] == len(evaluation), "Fitted model sample counts differ")
            expected_features = VOLATILITY_FEATURES if record["variant"] == "volatility_only" else FEATURES
            if record["model"] in ("baseline", "baseline_5"):
                expected_features = ["volatility_20" if record["model"] == "baseline" else "volatility_5"]
                expected_parameters = {}
            elif record["variant"] == "inner_candidate":
                expected_parameters = candidates[record["candidate_id"]]["parameters"]
            elif record["variant"] == "tuned":
                expected_parameters = selected_parameters[(record["outer_fold"], record["model"])]
            else:
                expected_parameters = config["fixed"][record["model"]]
            _require(record["feature_columns"] == expected_features, "Fitted model feature allowlist differs")
            _require(record["parameters"] == expected_parameters, "Fitted model parameters differ from declared variant")
            _require(pd.Timestamp(record["fit_cutoff"]) == cutoff, "Fitted model cutoff differs")
            _close(record["threshold"], train.target.quantile(.95), "Fitted model training-only tail threshold")
            if record["model"] == "ridge":
                x = train[record["feature_columns"]].to_numpy()
                scaler = record["scaler"]
                _require(scaler["fit_partition"] == "train" and scaler["n_samples_seen"] == len(train), "Scaler fit scope differs")
                _close(scaler["mean"], x.mean(axis=0), "Training-only scaler means")
                # StandardScaler uses population variance and unit scale for
                # numerically constant columns; reproduce its error bound.
                variance, mean = np.var(x, axis=0, ddof=0), np.mean(x, axis=0)
                eps = np.finfo(np.float64).eps
                constant = variance <= len(x)*eps*variance + (len(x)*mean*eps)**2
                scale = np.sqrt(variance)
                scale[constant] = 1.0
                _close(scaler["scale"], scale, "Training-only scaler scales")
        for scope, frame, training in (("temporal",pred,fitted),
                                       ("temporal_fixed",pred.loc[pred.variant == "fixed"],fitted.loc[fitted.variant == "fixed"]),
                                       ("pooled", _read(output/"pooled_validation_predictions.csv", ["forecast_date"]),
                                        _read(output/"pooled_training_predictions.csv", ["forecast_date"]))):
            for suffix, keys in (("aggregate",["variant","model"]),("fold",["variant","model","fold"]),
                                 ("year",["variant","model","year"])):
                stats = _read(output/"tables"/f"diagnostic_{scope}_{suffix}.csv")
                frame = frame.assign(year=frame.forecast_date.dt.year)
                _complete_table(stats, keys, _keys(frame, keys), f"{scope}/{suffix}")
                for row in stats.to_dict("records"):
                    group = frame
                    for k in keys:
                        group = group.loc[group[k] == row[k]]
                    for metric, value in _scores(group).items():
                        _close(row[metric], value, f"{scope}/{suffix}/{metric}")
            tails = _read(output/"tables"/f"diagnostic_{scope}_tail.csv")
            expected_tails = {("aggregate", *key, None, tail) for key in _keys(frame, ["variant", "model"])
                              for tail in ("below_training_q95", "at_or_above_training_q95")}
            expected_tails |= {("fold", *key, tail) for key in _keys(frame, ["variant", "model", "fold"])
                               for tail in ("below_training_q95", "at_or_above_training_q95")}
            _complete_table(tails, ["aggregation", "variant", "model", "fold", "tail_group"],
                            expected_tails, f"{scope}/tail")
            for row in tails.to_dict("records"):
                group = frame.loc[(frame.variant == row["variant"]) & (frame.model == row["model"])]
                if row["aggregation"] == "fold":
                    group = group.loc[group.fold.astype(str) == str(row["fold"])] if scope == "pooled" else group.loc[group.fold == int(row["fold"])]
                high = group.observed >= group.threshold
                group = group.loc[high if row["tail_group"] == "at_or_above_training_q95" else ~high]
                for metric, value in _scores(group).items():
                    if pd.isna(value):
                        _require(pd.isna(row[metric]), "Empty diagnostic group must remain unavailable")
                    else:
                        _close(row[metric], value, "Tail metric arithmetic")
            _verify_gap_and_comparisons(output, scope, frame, training)
        report.update(passed=True, n_development_rows=len(dev), n_reserved_identities=len(sealed),
                      n_outer_prediction_rows=len(pred), n_inner_prediction_rows=len(inner),
                      n_search_candidates=len(search), n_chosen_models=len(chosen),
                      checks=["development windows independently sliced from raw prices",
                              "exact original reserved identities excluded from all fit and evaluation sets",
                              "outer and inner membership/cutoffs/boundary exclusions independently rebuilt",
                              "training labels and inner evaluation labels available at fitting cutoffs",
                              "prediction identities, thresholds, model counts and baseline arithmetic",
                              "complete outer model/fold coverage and complete candidate/inner-fold coverage",
                              "inner candidate metrics and deterministic family selection",
                              "complete model records, fixed/tuned parameters and feature allowlists",
                              "Ridge scaler sample counts, training-only means and scales",
                              "complete aggregate, annual/fold, tail metrics and units from full-precision errors",
                              "fitted training/development gaps and benchmark relative/fold improvements"])
        return report
    except (ValueError, KeyError, TypeError, OSError, AssertionError) as error:
        report["error"] = str(error)
        raise CalculationVerificationError(report) from error
