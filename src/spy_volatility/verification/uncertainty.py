"""Independently reconstruct saved dependence-aware bootstrap calculations.

This verifier reads permitted development predictions, identity metadata and
saved bootstrap indices. It neither imports the producer nor fits a model.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


DATE_COLUMNS = ["forecast_date", "target_start", "target_end"]
METRICS = ["mae_pp", "mse_pp2", "rmse_pp", "bias_pp"]
SUBSETS = ["within_year", "original"]


def _require(condition, message):
    if not condition:
        raise ValueError("Uncertainty verification: " + message)


def _close(actual, expected, label):
    _require(np.shape(actual) == np.shape(expected), f"{label}: shape differs")
    _require(np.allclose(actual, expected, rtol=1e-10, atol=1e-12, equal_nan=True),
             f"{label}: saved values differ from independent arithmetic")


def _read_csv(path, dates=()):
    return pd.read_csv(path, parse_dates=list(dates), float_precision="round_trip")


def _integer(values, label):
    numeric = np.asarray(values, dtype=float)
    _require(np.isfinite(numeric).all() and (numeric == np.floor(numeric)).all(),
             f"{label}: expected finite integer identities")
    return numeric.astype(np.int64)


def _booleans(values, label):
    converted = values.map(lambda value: str(value).lower())
    _require(converted.isin(["true", "false"]).all(), f"{label}: expected explicit booleans")
    return converted.eq("true")


def _source_arrays(output, protocol):
    """Rebuild full original-session grids, both masks and all paired losses."""
    source = _read_csv(output / "source_predictions.csv", DATE_COLUMNS)
    assignments = _read_csv(output / "source_split_assignments.csv", DATE_COLUMNS)
    reserved = pd.read_csv(output / "source_reserved_identities.csv", usecols=["row_id"])
    required = {"row_id", "session_number", "fold", "variant", "model", "prediction", "observed", "partition", *DATE_COLUMNS}
    _require(not source.empty and required.issubset(source), "source prediction schema is incomplete")
    _require(not source[list(required)].isna().any().any(), "source has missing identity or value fields")
    _require(source.partition.eq("evaluation").all(), "only saved evaluation predictions may enter bootstrap")
    _require({"row_id", "session_number", "partition", *DATE_COLUMNS}.issubset(assignments),
             "assignment schema is incomplete")
    _require(assignments.partition.isin(["train", "validation", "test"]).all(),
             "assignment roles differ from the preserved pooled split")
    _require(assignments.row_id.is_unique and assignments.session_number.is_unique
             and assignments.forecast_date.is_unique, "assignment identities are not one-to-one")
    for table, label in ((source, "source"), (assignments, "assignments")):
        for column in ("row_id", "session_number"):
            table[column] = _integer(table[column], f"{label} {column}")
            _require(table[column].ge(0).all(), f"{label}: negative identity")
        _require(not table[DATE_COLUMNS].isna().any().any(), f"{label}: missing dates")
        for column in DATE_COLUMNS:
            _require(table[column].dt.tz is None
                     and table[column].eq(table[column].dt.normalize()).all(),
                     f"{label}: use timezone-free session dates at midnight")
        _require((table.forecast_date < table.target_start).all()
                 and (table.target_start <= table.target_end).all(), f"{label}: invalid future target dates")
    source["fold"] = _integer(source.fold, "source fold")
    _require(source.fold.eq(source.forecast_date.dt.year).all(), "fold differs from forecast year")
    values = source[["prediction", "observed"]].to_numpy(float)
    _require(np.isfinite(values).all() and (values >= 0).all(), "invalid source predictions or observations")
    _require(not source.duplicated(["row_id", "variant", "model"]).any(), "duplicate model prediction identity")
    for column in ("fold", "session_number", *DATE_COLUMNS, "observed"):
        _require(source.groupby("row_id")[column].nunique().eq(1).all(), f"models disagree on {column}")
    reserved_ids = set(_integer(reserved.row_id, "reserved identities"))
    _require(len(reserved_ids) == len(reserved), "duplicate reserved identity")
    _require(set(assignments.loc[assignments.partition.eq("test"), "row_id"]) == reserved_ids,
             "reserved identity metadata disagrees with assignments")
    _require(not set(source.row_id).intersection(reserved_ids), "reserved identity entered bootstrap")
    model_keys = sorted(set(map(tuple, source[["variant", "model"]].to_numpy())))
    _require(model_keys == [tuple(key) for key in protocol["model_keys"]], "model keys differ from saved protocol")
    folds = sorted(int(value) for value in source.fold.unique())
    _require(folds == protocol["folds"], "folds differ from saved protocol")
    _require(protocol["subsets"] == SUBSETS and protocol["metrics"] == METRICS,
             "subset or metric ordering differs from frozen protocol")
    common_ids = set(source.row_id)
    for key, group in source.groupby(["variant", "model"]):
        _require(set(group.row_id) == common_ids, f"model {key} has unpaired identities")
    reference = source.drop_duplicates("row_id").set_index("row_id")
    allowed = assignments.set_index("row_id")
    _require(common_ids.issubset(allowed.index), "source identity missing from original grid")
    aligned = allowed.loc[reference.index]
    _require(aligned.partition.isin(["train", "validation"]).all(), "source includes an impermissible identity role")
    for column in ("session_number", *DATE_COLUMNS):
        _require(np.array_equal(reference[column].to_numpy(), aligned[column].to_numpy()),
                 f"source {column} disagrees with assignment metadata")

    grids, masks, losses, counts = [], [], [], []
    for fold in folds:
        grid = assignments.loc[assignments.forecast_date.dt.year.eq(fold)].sort_values("session_number")
        _require(len(grid) > 0 and np.all(np.diff(grid.session_number.to_numpy()) == 1),
                 f"{fold}: grid must include consecutive original sessions")
        _require(grid.forecast_date.is_monotonic_increasing, f"{fold}: sessions disagree with dates")
        present = grid.row_id.isin(common_ids).to_numpy()
        contained = (grid.target_start.dt.year.eq(fold) & grid.target_end.dt.year.eq(fold)).to_numpy()
        mask = np.stack([present & contained, present])
        loss = np.zeros((len(grid), len(model_keys), 3), dtype=float)
        positions = {int(row_id): position for position, row_id in enumerate(grid.row_id)}
        for index, key in enumerate(model_keys):
            part = source.loc[source.fold.eq(fold) & source.variant.eq(key[0]) & source.model.eq(key[1])]
            loc = [positions[int(row_id)] for row_id in part.row_id]
            error = 100.0 * (part.prediction.to_numpy(float) - part.observed.to_numpy(float))
            loss[loc, index, 0] = np.abs(error)
            loss[loc, index, 1] = error * error
            loss[loc, index, 2] = error
        _require(np.isfinite(loss).all(), f"{fold}: nonfinite calculated loss")
        grids.append(grid)
        masks.append(mask)
        losses.append(loss)
        counts.append(mask.sum(axis=1))
    original_counts = np.stack(counts, axis=1)
    _require((original_counts.sum(axis=1) > 0).all(), "a complete original subset is empty")
    weights = original_counts / original_counts.sum(axis=1, keepdims=True)
    points = np.zeros((len(SUBSETS), len(model_keys), 4), dtype=float)
    for year_index, (mask, loss) in enumerate(zip(masks, losses)):
        for subset in range(len(SUBSETS)):
            if not original_counts[subset, year_index]:
                continue
            means = loss[mask[subset]].mean(axis=0)
            points[subset, :, [0, 1, 3]] += weights[subset, year_index] * means.T
    points[:, :, 2] = np.sqrt(points[:, :, 1])
    return {"source": source, "grids": grids, "masks": masks, "losses": losses,
            "counts": original_counts, "weights": weights, "points": points,
            "model_keys": model_keys, "folds": folds, "reserved_n": len(reserved_ids)}


def _reconstruct_draws(saved, arrays, replicates):
    """Use index-frequency matrices, an independent route to all saved draws."""
    scores = np.zeros((len(SUBSETS), replicates, len(arrays["model_keys"]), 4), dtype=float)
    counts = np.zeros((len(SUBSETS), replicates, len(arrays["folds"])), dtype=np.int64)
    for year_index, fold in enumerate(arrays["folds"]):
        grid = arrays["grids"][year_index]
        indices = saved[f"indices_{fold}"]
        _require(indices.shape == (replicates, len(grid)), f"{fold}: resampling index dimensions differ")
        _require(np.issubdtype(indices.dtype, np.integer) and indices.min() >= 0
                 and indices.max() < len(grid), f"{fold}: resampling indices exceed original grid")
        frequencies = np.stack([np.bincount(row, minlength=len(grid)) for row in indices])
        mask, loss = arrays["masks"][year_index], arrays["losses"][year_index]
        for subset in range(len(SUBSETS)):
            counts[subset, :, year_index] = frequencies @ mask[subset].astype(np.int64)
            if arrays["weights"][subset, year_index] == 0:
                continue
            total = frequencies @ (loss * mask[subset, :, None, None]).reshape(len(grid), -1)
            total = total.reshape(replicates, len(arrays["model_keys"]), 3)
            denominator = counts[subset, :, year_index, None, None]
            with np.errstate(divide="ignore", invalid="ignore"):
                means = total / denominator
            for output_index, loss_index in ((0, 0), (1, 1), (3, 2)):
                scores[subset, :, :, output_index] += arrays["weights"][subset, year_index] * means[:, :, loss_index]
    scores[:, :, :, 2] = np.sqrt(scores[:, :, :, 1])
    return scores, counts


def _expected_indices(size, replicates, length, seed, year):
    """Replay the specified uniform-start/geometric-continuation generator."""
    generator = np.random.default_rng(np.random.SeedSequence([seed, length, year]))
    result = np.empty((replicates, size), dtype=np.int32)
    result[:, 0] = generator.integers(0, size, size=replicates)
    for position in range(1, size):
        restart = generator.random(replicates) < 1.0 / length
        fresh = generator.integers(0, size, size=replicates)
        continued = (result[:, position - 1] + 1) % size
        result[:, position] = np.where(restart, fresh, continued)
    return result


def _comparison_specs(model_keys):
    keys = set(model_keys)
    references = [("fixed", "baseline"), ("comparator", "baseline_5")]
    _require(set(references).issubset(keys), "both historical benchmarks must be present")
    comparisons = []
    for model in model_keys:
        if model[1] in ("baseline", "baseline_5"):
            continue
        model_references = list(references)
        if model[0] in ("tuned", "volatility_only"):
            _require(("fixed", model[1]) in keys, "variant lacks its fixed model comparator")
            model_references.append(("fixed", model[1]))
        for reference in model_references:
            name = f"{model[0]}:{model[1]}_vs_{reference[0]}:{reference[1]}"
            comparisons.append((name, model_keys.index(model), model_keys.index(reference),
                                model == ("fixed", "ridge") and reference in references))
    return comparisons


def _interval(values, confidence):
    valid = np.isfinite(values)
    n_valid, n_invalid = int(valid.sum()), int((~valid).sum())
    if n_invalid or n_valid < 2:
        return np.nan, np.nan, n_valid, n_invalid
    tail = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(values, [tail, 1.0 - tail], method="linear")
    return float(lower), float(upper), n_valid, n_invalid


def _check_interval_row(row, estimate, replicates, confidence, primary, label, *, family=False):
    lower, upper, n_valid, n_invalid = _interval(replicates, confidence)
    for field, expected in (("estimate", estimate), ("ci_lower", lower), ("ci_upper", upper),
                            ("n_valid", n_valid), ("n_invalid", n_invalid),
                            ("confidence_level", confidence)):
        _close(row[field], expected, f"{label}/{field}")
    _require(row["primary_analysis"] == primary, f"{label}: primary-analysis designation differs")
    availability = str(row["availability"]).lower()
    _require(availability == "available" if n_invalid == 0 and n_valid >= 2 else
             any(word in availability for word in ("invalid", "unavailable", "insufficient")),
             f"{label}: interval availability differs")
    if family:
        adjusted = _interval(replicates, 0.975)[:2] if primary else (np.nan, np.nan)
        _close(row["familywise_lower"], adjusted[0], f"{label}/familywise_lower")
        _close(row["familywise_upper"], adjusted[1], f"{label}/familywise_upper")


def _verify_provenance(output, protocol):
    """Check copied evidence against the original parent's recorded hashes."""
    parent_path = output / "source_parent_run_record.json"
    record_path = output / "run_record.json"
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    _require(parent.get("status") == "success"
             and parent.get("experiment") == "retrospective_temporal"
             and parent.get("final_test_evaluated") is False
             and parent.get("reserved_rows_excluded") is True
             and parent.get("calculation_verification_passed") is True,
             "parent must be a verified successful temporal development run")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    _require(digest(parent_path) == record.get("source_run_record_sha256"),
             "copied source run record hash differs")
    input_map = {"temporal_predictions.csv": "source_predictions.csv",
                 "source_split_assignments.csv": "source_split_assignments.csv",
                 "reserved_identities.csv": "source_reserved_identities.csv"}
    if (output / "source_temporal_membership.csv").exists():
        input_map["temporal_membership.csv"] = "source_temporal_membership.csv"
    for original, copied in input_map.items():
        _require(digest(output / copied) == parent.get("artifact_sha256", {}).get(original),
                 f"copied source artifact hash differs: {original}")
        if "source_artifact_sha256" in record:
            _require(digest(output / copied) == record["source_artifact_sha256"].get(original),
                     f"run provenance differs for {original}")
    frozen = json.loads((output / "frozen_protocol.json").read_text(encoding="utf-8"))
    configuration = frozen["config"]
    _require(configuration == record.get("config"), "frozen and run configurations differ")
    config_path = output / "source" / "experiment.toml"
    if config_path.exists():
        _require(digest(config_path) == frozen.get("config_sha256") == record.get("config_sha256"),
                 "copied frozen configuration hash differs")
    uncertainty = configuration["uncertainty"]
    for field in ("subsets", "block_lengths", "primary_block_length", "n_resamples", "seed", "confidence_level"):
        _require(uncertainty[field] == protocol[field], f"protocol disagrees with frozen {field}")
    _require(uncertainty.get("interval") == "percentile"
             and uncertainty.get("annual_weights") == "fixed_original_eligible_counts"
             and uncertainty.get("invalid_draw_policy") == "retain_draw_and_withhold_interval",
             "frozen interval/weight/invalid-draw rules differ")
    return len(input_map)


def verify_uncertainty(output: Path) -> dict:
    """Independently verify complete resampling evidence and interval tables."""
    output = Path(output)
    protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    for key in ("subsets", "metrics", "model_keys", "folds", "block_lengths", "n_resamples",
                "seed", "confidence_level", "primary_block_length"):
        _require(key in protocol, f"missing protocol field {key}")
    lengths = _integer(protocol["block_lengths"], "block lengths").tolist()
    _require(lengths == [5, 10, 20, 40, 60] and protocol["primary_block_length"] == 20,
             "block lengths differ from the frozen experiment")
    replicates = int(_integer([protocol["n_resamples"]], "replicates")[0])
    seed = int(_integer([protocol["seed"]], "seed")[0])
    _require(replicates >= 2 and seed >= 0 and protocol["confidence_level"] == .95,
             "invalid resampling count, seed or nominal coverage")
    inputs_checked = _verify_provenance(output, protocol)
    arrays = _source_arrays(output, protocol)
    model_keys, folds = arrays["model_keys"], arrays["folds"]
    specs = _comparison_specs(model_keys)
    score_table = _read_csv(output / "tables" / "scores.csv")
    comparison_table = _read_csv(output / "tables" / "comparisons.csv")
    common_columns = {"subset", "block_length", "metric", "estimate", "ci_lower", "ci_upper",
                      "n_valid", "n_invalid", "confidence_level", "primary_analysis", "availability"}
    _require((common_columns | {"variant", "model"}).issubset(score_table), "score table schema is incomplete")
    _require((common_columns | {"comparison", "variant", "model", "reference_variant", "reference_model",
                                "familywise_lower", "familywise_upper"}).issubset(comparison_table),
             "comparison table schema is incomplete")
    for table, label in ((score_table, "scores"), (comparison_table, "comparisons")):
        table["primary_analysis"] = _booleans(table.primary_analysis, f"{label} primary flags")
        table["block_length"] = _integer(table.block_length, f"{label} block lengths")
        table["n_valid"] = _integer(table.n_valid, f"{label} valid counts")
        table["n_invalid"] = _integer(table.n_invalid, f"{label} invalid counts")
        _require(table.n_valid.ge(0).all() and table.n_invalid.ge(0).all(), f"{label}: negative counts")
    score_columns = ["subset", "block_length", "variant", "model", "metric"]
    difference_columns = ["subset", "block_length", "comparison", "metric"]
    expected_scores = {(subset, length, *model, metric) for subset in SUBSETS for length in lengths
                       for model in model_keys for metric in METRICS}
    expected_comparisons = {(subset, length, name, metric) for subset in SUBSETS for length in lengths
                            for name, _, _, _ in specs for metric in METRICS[:3]}
    for table, columns, expected, label in ((score_table, score_columns, expected_scores, "scores"),
                                           (comparison_table, difference_columns, expected_comparisons, "comparisons")):
        keys = list(map(tuple, table[columns].to_numpy()))
        _require(len(keys) == len(set(keys)) and set(keys) == expected,
                 f"{label}: missing, extra or duplicate interval rows")
    invalid_by_length, indices_checked = {}, 0
    for length in lengths:
        with np.load(output / f"bootstrap_L{length}.npz", allow_pickle=False) as saved:
            _require(set(saved.files) == {"scores", "counts", *(f"indices_{fold}" for fold in folds)},
                     f"L={length}: unexpected or missing bootstrap arrays")
            for index, fold in enumerate(folds):
                regenerated = _expected_indices(len(arrays["grids"][index]), replicates, length, seed, fold)
                _require(np.array_equal(saved[f"indices_{fold}"], regenerated),
                         f"L={length}/{fold}: draws disagree with frozen generator")
                indices_checked += int(regenerated.size)
            reconstructed, counts = _reconstruct_draws(saved, arrays, replicates)
            _close(saved["scores"], reconstructed, f"L={length} replicate scores")
            _require(np.array_equal(saved["counts"], counts), f"L={length}: retained counts differ")
        invalid_by_length[str(length)] = {subset: int((~np.isfinite(reconstructed[s]).all(axis=(1, 2))).sum())
                                         for s, subset in enumerate(SUBSETS)}
        for row in score_table.loc[score_table.block_length.eq(length)].to_dict("records"):
            subset = SUBSETS.index(row["subset"])
            model = model_keys.index((row["variant"], row["model"]))
            metric = METRICS.index(row["metric"])
            primary = row["subset"] == "within_year" and length == 20
            _check_interval_row(row, arrays["points"][subset, model, metric],
                                reconstructed[subset, :, model, metric], .95, primary,
                                "/".join(map(str, (row[column] for column in score_columns))))
        spec_lookup = {name: (model, reference, primary) for name, model, reference, primary in specs}
        for row in comparison_table.loc[comparison_table.block_length.eq(length)].to_dict("records"):
            subset, metric = SUBSETS.index(row["subset"]), METRICS.index(row["metric"])
            model, reference, primary_contrast = spec_lookup[row["comparison"]]
            _require((row["variant"], row["model"]) == model_keys[model]
                     and (row["reference_variant"], row["reference_model"]) == model_keys[reference],
                     f"{row['comparison']}: comparison labels disagree")
            point = arrays["points"][subset, model, metric] - arrays["points"][subset, reference, metric]
            samples = reconstructed[subset, :, model, metric] - reconstructed[subset, :, reference, metric]
            primary = primary_contrast and row["subset"] == "within_year" and length == 20 and row["metric"] == "rmse_pp"
            _check_interval_row(row, point, samples, .95, primary,
                                "/".join(map(str, (row[column] for column in difference_columns))), family=True)
    return {"status": "passed", "passed": True, "source_inputs_hash_checked": inputs_checked,
            "source_n_forecasts": int(arrays["source"].row_id.nunique()),
            "model_variants": len(model_keys), "annual_strata": len(folds),
            "replicates_per_block_length": replicates, "block_lengths": lengths,
            "resampling_indices_checked": indices_checked, "score_interval_rows_checked": len(score_table),
            "comparison_interval_rows_checked": len(comparison_table), "invalid_draws": invalid_by_length,
            "reserved_identities_excluded": arrays["reserved_n"], "reserved_responses_read": False,
            "final_test_evaluated": False,
            "checks": ["Copied source and frozen configuration hashes",
                       "Original-session grids, paired identities and reserved exclusion",
                       "Calendar containment and fixed original annual weights",
                       "Every deterministic stationary-bootstrap index",
                       "Replicate eligible counts, loss arithmetic and nonlinear RMSE",
                       "Complete score/comparison interval grids and paired differences",
                       "Percentile endpoints, invalid-draw withholding and two-comparison adjustment"]}
