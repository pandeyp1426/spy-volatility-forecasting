"""Independently audit saved temporal-sensitivity masks and arithmetic.

Only saved development predictions and reserved identity metadata are read.
This module does not import the sensitivity producer or fit any model.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


DATES = ["forecast_date", "target_start", "target_end"]
IDENTITIES = ["row_id", "fold", *DATES, "session_number"]
METRICS = ["mae_pp", "rmse_pp", "mse_pp2", "bias_pp"]
TAILS = ("all", "below_training_q95", "at_or_above_training_q95")
SUBSETS = ("original", "within_year", *(f"modulo_{r}" for r in range(5)),
           *(f"within_year_modulo_{r}" for r in range(5)))
TABLE_KEYS = ["subset", "aggregation", "fold", "tail_group", "variant", "model"]


def _require(condition, message):
    if not condition:
        raise ValueError("Sensitivity verification: " + message)


def _read(path, dates=()):
    return pd.read_csv(path, parse_dates=list(dates), float_precision="round_trip")


def _booleans(series, label):
    values = series.map(lambda value: str(value).lower())
    _require(values.isin(["true", "false"]).all(), f"{label} must contain explicit booleans")
    return values.eq("true")


def _integers(series, label):
    values = pd.to_numeric(series, errors="raise").to_numpy(float)
    _require(np.isfinite(values).all() and np.equal(values, np.floor(values)).all(),
             f"{label} must contain finite integers")
    return values.astype(np.int64)


def _score(frame):
    errors = 100.0 * (frame.prediction.to_numpy(float) - frame.observed.to_numpy(float))
    if not len(errors):
        return {"n_forecasts": 0, **dict.fromkeys(METRICS, np.nan)}
    squared = float(np.sum(errors * errors) / len(errors))
    return {"n_forecasts": len(errors), "mae_pp": float(np.sum(np.abs(errors)) / len(errors)),
            "rmse_pp": float(np.sqrt(squared)), "mse_pp2": squared,
            "bias_pp": float(np.sum(errors) / len(errors))}


def _numeric(actual, expected, label):
    if pd.isna(expected):
        _require(pd.isna(actual), f"{label}: unavailable value must remain missing")
    else:
        _require(pd.notna(actual) and np.isclose(float(actual), float(expected), rtol=1e-10, atol=1e-12),
                 f"{label}: saved value differs from independently recomputed value")


def _key(row, comparison=False):
    fold = None if pd.isna(row["fold"]) else int(row["fold"])
    result = (row["subset"], row["aggregation"], fold, row["tail_group"], row["variant"], row["model"])
    return (*result, row["benchmark"]) if comparison else result


def _check_grid(table, expected, label, *, comparison=False):
    columns = TABLE_KEYS + (["benchmark"] if comparison else [])
    _require(set(columns).issubset(table.columns), f"{label}: required grouping columns are missing")
    # Do not silently truncate a corrupted noninteger fold while constructing keys.
    _integers(table.loc[table.fold.notna(), "fold"], f"{label} fold")
    keys = [_key(row, comparison) for row in table.to_dict("records")]
    _require(len(keys) == len(set(keys)) and set(keys) == set(expected),
             f"{label}: missing, extra or duplicate groups")


def verify_sensitivity(output: Path) -> dict:
    """Rebuild all sample masks and score tables, raising on any discrepancy."""
    output = Path(output)
    source = _read(output / "source_predictions.csv", DATES)
    required = {*IDENTITIES, "variant", "model", "observed", "prediction", "threshold"}
    _require(not source.empty and required.issubset(source.columns), "source prediction schema is incomplete")
    _require(not source[list(required)].isna().any().any(), "source identities and values must be nonmissing")
    for column in ("row_id", "session_number", "fold"):
        source[column] = _integers(source[column], f"source {column}")
    for column in DATES:
        _require(source[column].dt.tz is None, f"{column} must use timezone-free session dates")
    _require(source.fold.eq(source.forecast_date.dt.year).all(), "fold differs from forecast calendar year")
    _require((source.forecast_date < source.target_start).all()
             and (source.target_start <= source.target_end).all(), "invalid future target intervals")
    values = source[["prediction", "observed", "threshold"]].to_numpy(float)
    _require(np.isfinite(values).all() and (values >= 0).all(), "source predictions, outcomes and thresholds must be finite and nonnegative")
    if "partition" in source:
        _require(source.partition.eq("evaluation").all(), "source must contain temporal evaluation predictions only")
    _require(not source.duplicated(["row_id", "variant", "model"]).any(), "duplicate source prediction identity")
    for column in [*IDENTITIES[1:], "observed", "threshold"]:
        _require(source.groupby("row_id")[column].nunique().eq(1).all(),
                 f"paired models disagree on {column}")
    _require(source.groupby("fold").threshold.nunique().eq(1).all(), "training threshold differs within a fold")
    identities = source[IDENTITIES].drop_duplicates().sort_values("row_id").reset_index(drop=True)
    _require(identities.row_id.is_unique and identities.forecast_date.is_unique
             and identities.session_number.is_unique, "source dates and sessions are not one-to-one")
    chronological = identities.sort_values("session_number")
    _require(chronological.forecast_date.is_monotonic_increasing, "session order disagrees with forecast dates")
    expected_ids = set(identities.row_id)
    groups = list(source.groupby(["variant", "model"], sort=True))
    for group, frame in groups:
        _require(set(frame.row_id) == expected_ids, f"unpaired source scoring identities for {group}")

    # Explicitly request only the identity column; reserved outcomes are never loaded.
    reserved = pd.read_csv(output / "source_reserved_identities.csv", usecols=["row_id"])
    reserved_ids = _integers(reserved.row_id, "reserved row_id")
    _require(len(set(reserved_ids)) == len(reserved_ids), "duplicate reserved identity")
    _require(not expected_ids.intersection(reserved_ids), "reserved identity entered sensitivity source")

    contained = (identities.target_start.dt.year.eq(identities.forecast_date.dt.year)
                 & identities.target_end.dt.year.eq(identities.forecast_date.dt.year))
    masks = {"original": np.ones(len(identities), dtype=bool), "within_year": contained.to_numpy()}
    for residue in range(5):
        residue_mask = identities.session_number.to_numpy() % 5 == residue
        masks[f"modulo_{residue}"] = residue_mask
        masks[f"within_year_modulo_{residue}"] = residue_mask & contained.to_numpy()
    selected_ids = {name: set(identities.loc[mask, "row_id"]) for name, mask in masks.items()}
    _require(np.stack([masks[f"modulo_{r}"] for r in range(5)]).sum(axis=0).tolist()
             == [1] * len(identities), "modulo residues do not partition original identities")
    _require(np.array_equal(np.stack([masks[f"within_year_modulo_{r}"] for r in range(5)]).sum(axis=0), contained.astype(int)),
             "combined residues do not partition contained identities")

    membership = _read(output / "membership.csv", DATES)
    membership_columns = {*IDENTITIES, "subset", "primary", "included", "exclusion_reason"}
    _require(membership_columns.issubset(membership.columns), "membership schema is incomplete")
    _require(set(membership.subset) == set(SUBSETS)
             and not membership.duplicated(["subset", "row_id"]).any(), "membership subsets are missing or duplicated")
    membership["included"] = _booleans(membership.included, "membership included")
    membership["primary"] = _booleans(membership.primary, "membership primary")
    for column in ("row_id", "session_number", "fold"):
        membership[column] = _integers(membership[column], f"membership {column}")
    primary = {}
    overlap_checks = 0
    for name in SUBSETS:
        saved = membership.loc[membership.subset.eq(name)].sort_values("row_id").reset_index(drop=True)
        _require(len(saved) == len(identities), f"{name}: membership does not cover all source identities")
        for column in IDENTITIES:
            _require(np.array_equal(saved[column].to_numpy(), identities[column].to_numpy()),
                     f"{name}: membership {column} differs from source")
        _require(np.array_equal(saved.included.to_numpy(), masks[name]), f"{name}: membership mask is incorrect")
        _require(saved.primary.nunique() == 1, f"{name}: conflicting primary flags")
        primary[name] = bool(saved.primary.iloc[0])
        _require(primary[name] == ("modulo" not in name or name.endswith("_0")),
                 f"{name}: predetermined primary flag is incorrect")
        reasons = []
        for position, identity in identities.iterrows():
            failures = []
            if name.startswith("within_year") and not contained.iloc[position]:
                failures.append("outcome_crosses_year")
            if "modulo" in name and identity.session_number % 5 != int(name.rsplit("_", 1)[1]):
                failures.append("residue_mismatch")
            reasons.append(";".join(failures) if failures else "included")
        _require(saved.exclusion_reason.tolist() == reasons,
                 f"{name}: exact inclusion/exclusion reasons differ from independent mask conditions")
        if "modulo" in name:
            residue = int(name.rsplit("_", 1)[1])
            _require(primary[name] == (residue == 0), f"{name}: predetermined primary residue flag is incorrect")
            chosen = identities.loc[masks[name]].sort_values("session_number")
            _require(chosen.session_number.diff().dropna().ge(5).all(), f"{name}: selected sessions are too close")
            _require((chosen.target_start.to_numpy()[1:]
                      > np.maximum.accumulate(chosen.target_end.to_numpy())[:-1]).all(),
                     f"{name}: target windows overlap, including across annual folds")
            overlap_checks += 1

    audit = _read(output / "tables" / "audit.csv")
    audit_columns = {"subset", "primary", "n_forecasts", "n_excluded", "n_outcomes_crossing_year",
                     "n_overlapping_predecessors", "minimum_session_gap"}
    _require(audit_columns.issubset(audit.columns)
             and audit.subset.is_unique and set(audit.subset) == set(SUBSETS), "audit subset coverage differs")
    audit["primary"] = _booleans(audit.primary, "audit primary")
    for row in audit.to_dict("records"):
        name = row["subset"]
        chosen = identities.loc[masks[name]].sort_values("session_number")
        _require(row["primary"] == primary[name], f"{name}: audit primary flag differs")
        # Count whether each interval intersects ANY preceding interval, not
        # merely its immediate predecessor. Keep the running maximum explicit
        # here so this check is independent of the producer's vectorization.
        running_end, overlaps = None, 0
        for interval in chosen.itertuples(index=False):
            if running_end is not None and interval.target_start <= running_end:
                overlaps += 1
            running_end = interval.target_end if running_end is None else max(running_end, interval.target_end)
        gaps = np.diff(chosen.session_number.to_numpy())
        expected_audit = {
            "n_forecasts": len(chosen), "n_excluded": len(identities) - len(chosen),
            "n_outcomes_crossing_year": int((~contained.loc[chosen.index]).sum()),
            "n_overlapping_predecessors": overlaps,
            "minimum_session_gap": int(min(gaps)) if len(gaps) else np.nan,
        }
        for column, value in expected_audit.items():
            _numeric(row[column], value, f"{name}: audit {column}")

    expected_metrics = {}
    folds = sorted(source.fold.unique())
    for subset in SUBSETS:
        for (variant, model), frame in groups:
            retained = frame.loc[frame.row_id.isin(selected_ids[subset])]
            scopes = [("aggregate", None, retained)] + [
                ("fold", int(fold), retained.loc[retained.fold.eq(fold)]) for fold in folds]
            for aggregation, fold, sample in scopes:
                for tail in TAILS:
                    selected = sample
                    if tail == "below_training_q95":
                        selected = sample.loc[sample.observed < sample.threshold]
                    elif tail == "at_or_above_training_q95":
                        selected = sample.loc[sample.observed >= sample.threshold]
                    expected_metrics[(subset, aggregation, fold, tail, variant, model)] = _score(selected)
    metrics = _read(output / "tables" / "metrics.csv")
    _require({"primary", "n_forecasts", "availability", *METRICS}.issubset(metrics.columns), "metric value columns are missing")
    _check_grid(metrics, expected_metrics, "metrics")
    metrics["primary"] = _booleans(metrics.primary, "metric primary")
    for row in metrics.to_dict("records"):
        key = _key(row)
        expected = expected_metrics[key]
        _require(row["primary"] == primary[row["subset"]], f"{key}: metric primary flag differs")
        for column, value in expected.items():
            _numeric(row[column], value, f"{key}: {column}")
        availability = str(row["availability"]).lower()
        _require(availability == "available" if expected["n_forecasts"] else
                 ("empty" in availability or "unavailable" in availability), f"{key}: metric availability differs")

    benchmarks = {}
    for benchmark in ("baseline", "baseline_5"):
        reference = source.loc[source.model.eq(benchmark)]
        _require(not reference.empty and reference.groupby("row_id").prediction.nunique().eq(1).all(),
                 f"{benchmark}: missing or contradictory benchmark predictions")
        benchmarks[benchmark] = str(reference.variant.iloc[0])
    comparison_keys = {(*key, benchmark) for key in expected_metrics for benchmark in benchmarks}
    comparisons = _read(output / "tables" / "comparisons.csv")
    comparison_values = ["relative_mae_improvement_pct", "relative_rmse_improvement_pct", "delta_mae_pp", "delta_rmse_pp"]
    _require({"primary", "n_forecasts", "availability", *comparison_values}.issubset(comparisons.columns),
             "comparison value columns are missing")
    _check_grid(comparisons, comparison_keys, "comparisons", comparison=True)
    comparisons["primary"] = _booleans(comparisons.primary, "comparison primary")
    for row in comparisons.to_dict("records"):
        key = _key(row)
        model_scores = expected_metrics[key]
        benchmark = row["benchmark"]
        reference_key = (*key[:4], benchmarks[benchmark], benchmark)
        reference_scores = expected_metrics[reference_key]
        _require(row["primary"] == primary[row["subset"]], f"{key}: comparison primary flag differs")
        _numeric(row["n_forecasts"], model_scores["n_forecasts"], f"{key}: comparison count")
        _require(model_scores["n_forecasts"] == reference_scores["n_forecasts"], f"{key}: unpaired comparison count")
        for metric in ("mae", "rmse"):
            model_value, baseline_value = model_scores[f"{metric}_pp"], reference_scores[f"{metric}_pp"]
            delta = model_value - baseline_value
            relative = 100.0 * (1.0 - model_value / baseline_value) if baseline_value > 0 else np.nan
            _numeric(row[f"delta_{metric}_pp"], delta, f"{key}/{benchmark}: delta {metric}")
            _numeric(row[f"relative_{metric}_improvement_pct"], relative, f"{key}/{benchmark}: relative {metric}")
        _require(pd.notna(row["availability"]) and str(row["availability"]).strip(), f"{key}: missing comparison availability")
        if not model_scores["n_forecasts"]:
            _require(any(word in str(row["availability"]).lower() for word in ("empty", "unavailable")),
                     f"{key}: empty comparison must be marked unavailable")

    return {"status": "passed", "passed": True, "source_n_forecasts": len(identities),
            "model_variants": len(groups), "subsets_checked": len(SUBSETS),
            "membership_rows_checked": len(membership), "metric_rows_checked": len(metrics),
            "comparison_rows_checked": len(comparisons), "audit_rows_checked": len(audit),
            "nonoverlap_checks": overlap_checks,
            "subset_counts": {name: len(selected_ids[name]) for name in SUBSETS},
            "reserved_rows_excluded": True, "reserved_responses_read": False,
            "final_test_evaluated": False,
            "checks": ["Source model pairing and reserved identity exclusion",
                       "Calendar containment rebuilt from saved target endpoints",
                       "Global original-session modulo masks and exhaustive residue partitions",
                       "Membership metadata, inclusion masks, exact reasons and primary flags",
                       "Complete sample/exclusion counts, calendar crossings, prefix-overlap counts and session gaps",
                       "Target interval nonoverlap within and across annual folds",
                       "Complete aggregate/fold/tail metric and comparison grids",
                       "Full-precision error arithmetic, both benchmarks and empty groups"]}
