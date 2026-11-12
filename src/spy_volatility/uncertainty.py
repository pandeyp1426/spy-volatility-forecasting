"""Paired, masked stationary-bootstrap uncertainty for saved development fits.

Annual weights are fixed at their original eligible counts. Missing original
sessions remain masked grid positions; no prices, reserved responses or models
are loaded to refit. Intervals condition on the previously selected fitted models.
"""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import distributions
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import traceback
from uuid import uuid4

import numpy as np
import pandas as pd

from .provenance import source_hashes
from .research import _positive_integer
from .sensitivity import (INPUTS, _json, _markdown_table, _read_source, _sha,
                          validate_predictions_for_sensitivity)


SUBSETS = ["within_year", "original"]
METRICS = ["mae_pp", "mse_pp2", "rmse_pp", "bias_pp"]
SETTINGS = {"subsets": SUBSETS, "block_lengths": [5, 10, 20, 40, 60],
            "primary_block_length": 20, "n_resamples": 5000, "seed": 42,
            "confidence_level": .95, "interval": "percentile",
            "annual_weights": "fixed_original_eligible_counts",
            "invalid_draw_policy": "retain_draw_and_withhold_interval"}


def stationary_indices(n_sessions: int, n_resamples: int, mean_block_length: int,
                       rng: np.random.Generator) -> np.ndarray:
    """Generate original-session positions with geometric, circular blocks."""
    for value, name in ((n_sessions, "n_sessions"), (n_resamples, "n_resamples"),
                        (mean_block_length, "mean_block_length")):
        _positive_integer(value, name)
    if not isinstance(rng, np.random.Generator):
        raise ValueError("Pass an explicit numpy Generator")
    indexes = np.empty((n_resamples, n_sessions), dtype=np.int32)
    indexes[:, 0] = rng.integers(0, n_sessions, size=n_resamples)
    for position in range(1, n_sessions):
        restart = rng.random(n_resamples) < 1.0 / mean_block_length
        starts = rng.integers(0, n_sessions, size=n_resamples)
        indexes[:, position] = np.where(restart, starts, (indexes[:, position - 1] + 1) % n_sessions)
    return indexes


def prepare_grids(predictions: pd.DataFrame, assignments: pd.DataFrame) -> list[dict]:
    """Keep omitted identities in full annual grids, with explicit loss masks."""
    required = ["row_id", "session_number", "forecast_date", "target_start", "target_end", "partition"]
    if not set(required).issubset(assignments.columns) or assignments.empty:
        raise ValueError("Full original assignment identity metadata is required")
    assignments = assignments[required].copy()
    if assignments.isna().any().any() or not assignments.partition.isin(["train", "validation", "test"]).all():
        raise ValueError("Invalid original assignment identity or partition")
    for column in ("row_id", "session_number"):
        values = pd.to_numeric(assignments[column], errors="raise").to_numpy(float)
        if not np.isfinite(values).all() or (values < 0).any() or (values != np.floor(values)).any():
            raise ValueError(f"{column} requires nonnegative integer identities")
        assignments[column] = values.astype(np.int64)
        if not assignments[column].is_unique:
            raise ValueError("Original identities and sessions must be unique")
    for column in ("forecast_date", "target_start", "target_end"):
        assignments[column] = pd.to_datetime(assignments[column], errors="raise")
        if assignments[column].dt.tz is not None or not assignments[column].eq(assignments[column].dt.normalize()).all():
            raise ValueError("Use timezone-free original session dates")
    assignments = assignments.sort_values("session_number")
    if (not assignments.forecast_date.is_unique or not assignments.forecast_date.is_monotonic_increasing
            or not (assignments.forecast_date < assignments.target_start).all()
            or not (assignments.target_start <= assignments.target_end).all()):
        raise ValueError("Invalid original assignment date order")
    source = validate_predictions_for_sensitivity(predictions,
                 assignments.loc[assignments.partition.eq("test"), "row_id"])
    reference = source.drop_duplicates("row_id").set_index("row_id")
    allowed = assignments.set_index("row_id")
    if not set(reference.index).issubset(allowed.index):
        raise ValueError("Prediction identities are absent from the original grid")
    for column in ("session_number", "forecast_date", "target_start", "target_end"):
        if not np.array_equal(reference[column].to_numpy(), allowed.loc[reference.index, column].to_numpy()):
            raise ValueError(f"Prediction {column} differs from original assignments")
    model_keys = sorted(set(map(tuple, source[["variant", "model"]].to_numpy())))
    grids = []
    for fold in sorted(source.fold.unique()):
        mapping = assignments.loc[assignments.forecast_date.dt.year.eq(fold)]
        sessions = mapping.session_number.to_numpy()
        if not len(sessions) or (np.diff(sessions) != 1).any():
            raise ValueError("Full annual original-session grids must be consecutive")
        present = mapping.row_id.isin(reference.index).to_numpy()
        contained = (mapping.target_start.dt.year.eq(fold) & mapping.target_end.dt.year.eq(fold)).to_numpy()
        eligible = np.stack([present & contained, present])
        losses = np.zeros((len(mapping), len(model_keys), 3))
        for m, (variant, model) in enumerate(model_keys):
            group = source.loc[source.fold.eq(fold) & source.variant.eq(variant) & source.model.eq(model)].set_index("row_id")
            aligned = group.reindex(mapping.row_id)
            errors = 100.0 * (aligned.prediction.to_numpy() - aligned.observed.to_numpy())
            errors = np.where(present, errors, 0.0)
            losses[:, m, :] = np.column_stack([np.abs(errors), errors * errors, errors])
        if not np.isfinite(losses).all():
            raise ValueError("Nonfinite loss calculation")
        grids.append({"fold": int(fold), "sessions": sessions, "eligible": eligible,
                      "losses": losses, "model_keys": model_keys,
                      "original_counts": eligible.sum(axis=1)})
    if (np.sum([g["original_counts"] for g in grids], axis=0) == 0).any():
        raise ValueError("Both declared scoring subsets require original observations")
    return grids


def bootstrap_scores(grids: list[dict], indices_by_fold: dict[int, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Compute fixed-year-weight loss ratios; preserve undefined draws as NaN."""
    if not grids or set(indices_by_fold) != {g["fold"] for g in grids}:
        raise ValueError("Supply one resampling array for each annual grid")
    first = np.asarray(indices_by_fold[grids[0]["fold"]])
    if first.ndim != 2 or not len(first):
        raise ValueError("Resampling indices require a nonempty replicate axis")
    b, models = len(first), len(grids[0]["model_keys"])
    original = np.column_stack([g["original_counts"] for g in grids])
    if (original.sum(axis=1) == 0).any():
        raise ValueError("Cannot estimate an empty original subset")
    weights = original / original.sum(axis=1, keepdims=True)
    totals = np.zeros((2, b, models, 3))
    counts = np.zeros((2, b, len(grids)), dtype=np.int64)
    invalid = np.zeros((2, b), dtype=bool)
    for y, grid in enumerate(grids):
        indexes = np.asarray(indices_by_fold[grid["fold"]])
        n = len(grid["sessions"])
        if (indexes.shape != (b, n) or not np.issubdtype(indexes.dtype, np.integer)
                or indexes.min() < 0 or indexes.max() >= n):
            raise ValueError("Resampling index shape or range differs from the original grid")
        if grid["model_keys"] != grids[0]["model_keys"]:
            raise ValueError("Model order must be paired across annual grids")
        # Frequencies avoid materializing B x sessions x models x losses arrays.
        frequency = np.bincount((indexes + np.arange(b)[:, None] * n).ravel(),
                                minlength=b * n).reshape(b, n)
        for s in range(2):
            mask = grid["eligible"][s]
            counts[s, :, y] = frequency @ mask.astype(np.int64)
            if weights[s, y] == 0:
                continue
            sums = frequency @ (grid["losses"] * mask[:, None, None]).reshape(n, -1)
            sums = sums.reshape(b, models, 3)
            denominator = counts[s, :, y, None, None]
            means = np.divide(sums, denominator, out=np.zeros_like(sums), where=denominator > 0)
            totals[s] += weights[s, y] * means
            invalid[s] |= counts[s, :, y] == 0
    scores = np.stack([totals[..., 0], totals[..., 1], np.sqrt(totals[..., 1]), totals[..., 2]], axis=-1)
    scores[invalid] = np.nan
    return scores, counts


def comparison_spec(model_keys: list[tuple[str, str]]) -> list[dict]:
    """Preserve all learned/benchmark, tuning and fixed-ablation contrasts."""
    keys = [tuple(key) for key in model_keys]
    if len(keys) != len(set(keys)):
        raise ValueError("Model variants must be unique")
    comparisons = []

    def add(key, reference):
        if key not in keys or reference not in keys:
            return
        comparisons.append({"comparison": f"{key[0]}:{key[1]}_vs_{reference[0]}:{reference[1]}",
                            "model_index": keys.index(key), "reference_index": keys.index(reference),
                            "primary_contrast": key == ("fixed", "ridge") and reference[1] in ("baseline", "baseline_5")})

    for key in keys:
        if key[1] in ("baseline", "baseline_5"):
            continue
        for reference in (("fixed", "baseline"), ("comparator", "baseline_5")):
            add(key, reference)
    for variant in ("tuned", "volatility_only"):
        for model in ("ridge", "random_forest", "gradient_boosting"):
            add((variant, model), ("fixed", model))
    return comparisons


def _interval(values: np.ndarray, confidence: float) -> dict:
    valid = int(np.isfinite(values).sum())
    invalid = len(values) - valid
    if invalid or valid < 2:
        lower, upper = np.nan, np.nan
        availability = "invalid replicates; interval withheld" if invalid else "insufficient replicates; interval withheld"
    else:
        lower, upper = np.quantile(values, [(1 - confidence) / 2, (1 + confidence) / 2], method="linear")
        availability = "available"
    return {"ci_lower": lower, "ci_upper": upper, "n_valid": valid, "n_invalid": invalid,
            "confidence_level": confidence, "availability": availability}


def interval_tables(point_scores: np.ndarray, samples: np.ndarray, model_keys: list[tuple[str, str]],
                    block_length: int, confidence: float = .95) -> dict[str, pd.DataFrame]:
    """Paired percentile intervals; adjust only the two declared primary contrasts."""
    _positive_integer(block_length, "block_length")
    if not (0 < confidence < 1):
        raise ValueError("Confidence must be between zero and one")
    if (np.shape(point_scores) != (2, len(model_keys), 4) or samples.ndim != 4
            or samples.shape[0] != 2 or samples.shape[2:] != (len(model_keys), 4) or not samples.shape[1]
            or not np.isfinite(point_scores).all()):
        raise ValueError("Scores must match the frozen subset/model/metric axes")
    scores, contrasts = [], []
    for s, subset in enumerate(SUBSETS):
        context = {"subset": subset, "block_length": block_length}
        primary_scope = subset == "within_year" and block_length == 20
        for m, (variant, model) in enumerate(model_keys):
            for k, metric in enumerate(METRICS):
                scores.append({**context, "variant": variant, "model": model, "metric": metric,
                               "estimate": point_scores[s, m, k], "primary_analysis": primary_scope,
                               **_interval(samples[s, :, m, k], confidence)})
        for comparison in comparison_spec(model_keys):
            m, r = comparison["model_index"], comparison["reference_index"]
            for k, metric in enumerate(METRICS[:3]):
                values = samples[s, :, m, k] - samples[s, :, r, k]
                primary = primary_scope and comparison["primary_contrast"] and metric == "rmse_pp"
                family = _interval(values, 1 - (1 - confidence) / 2) if primary else None
                contrasts.append({**context, "comparison": comparison["comparison"],
                                  "variant": model_keys[m][0], "model": model_keys[m][1],
                                  "reference_variant": model_keys[r][0], "reference_model": model_keys[r][1],
                                  "metric": metric, "estimate": point_scores[s, m, k] - point_scores[s, r, k],
                                  "primary_analysis": bool(primary),
                                  "familywise_lower": family["ci_lower"] if family else np.nan,
                                  "familywise_upper": family["ci_upper"] if family else np.nan,
                                  **_interval(values, confidence)})
    return {"scores": pd.DataFrame(scores), "comparisons": pd.DataFrame(contrasts)}


def _report(output: Path, record: dict, tables: dict[str, pd.DataFrame]) -> None:
    comparison = tables["comparisons"]
    primary = comparison.loc[comparison.primary_analysis]
    sensitivity = comparison.loc[comparison.variant.eq("fixed") & comparison.model.eq("ridge") & comparison.metric.eq("rmse_pp")]
    text = ["# Dependence-aware uncertainty results", "",
            f"Run `{record['run_id']}`; source `{record['parent_run_id']}`.", "",
            "Paired stationary resampling preserves original-session gaps and uses fixed annual observation weights. Expected block length 20 and the within-year-contained sample are primary; all five block lengths and both samples are disclosed. No fits were repeated. Negative model-minus-benchmark differences favor Ridge.", "",
            "## Primary RMSE comparisons", "",
            "Differences and endpoints use daily-volatility percentage points. Intervals use a nominal 95% level; actual coverage is not guaranteed. The familywise columns use 97.5% individual intervals for the two primary comparisons (approximate 95% family coverage).", "",
            _markdown_table(primary, ["reference_model", "estimate", "ci_lower", "ci_upper", "familywise_lower", "familywise_upper", "n_invalid"]), "",
            "## Block-length and sample sensitivity", "",
            _markdown_table(sensitivity, ["subset", "block_length", "reference_model", "estimate", "ci_lower", "ci_upper", "n_invalid"]), "",
            "## Interpretation and evidence", "",
            "An interval containing zero leaves the direction of the difference unresolved under this approximation; it does not prove equality. These are approximate intervals conditional on historically selected fitted forecasts and the fixed historical year composition. They omit model fitting/selection uncertainty and dependence across years; annual stationarity and circular endpoint joins are approximations. No confirmatory significance, future-volatility prediction interval, or trading conclusion is claimed.", "",
            "`tables/scores.csv` covers all eleven model variants and four metrics; `tables/comparisons.csv` retains learned-versus-benchmark, tuned-versus-fixed and feature-ablation comparisons. `bootstrap_L*.npz` retain every original-session index, replicate score and eligible count. Invalid draws are retained and intervals withheld. `calculation_verification.json` independently reconstructs generators, masks, weighted scores and quantiles. Source inputs remain unchanged, and reserved response matrices remain unread and unscored.", "",
            "Method references: [Politis and Romano](https://users.ssc.wisc.edu/~behansen/718/Politis%20Romano.pdf); [Hardle, Horowitz and Kreiss](https://www.ssc.wisc.edu/~bhansen/718/HardleHorowitzKreiss.pdf). The annually stratified masked construction is a project-specific adaptation, not a coverage guarantee from those sources.", ""]
    (output / "results.md").write_text("\n".join(text), encoding="utf-8")


def run_uncertainty(config_path: str | Path) -> dict:
    """Freeze evidence before computing intervals; preserve immutable source runs."""
    config_path = Path(config_path).resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if config.get("experiment", {}).get("strategy") != "temporal_uncertainty" or config.get("uncertainty") != SETTINGS:
        raise ValueError("Use the frozen paired annual stationary-bootstrap protocol")
    root = config_path.parent.parent
    source = (root / config["paths"]["temporal_run"]).resolve()
    parent, input_hashes, predictions = _read_source(source)
    parent_hash = _sha(source / "run_record.json")
    assignments = pd.read_csv(source / "source_split_assignments.csv")
    grids = prepare_grids(predictions, assignments)
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S") + "_uncertainty_" + uuid4().hex[:8]
    output = root / config["paths"]["output_dir"] / run_id
    output.mkdir(parents=True, exist_ok=False)
    record = {"run_id": run_id, "experiment": "temporal_uncertainty", "status": "running",
              "started_at_utc": now.isoformat(), "config": config, "config_sha256": _sha(config_path),
              "parent_run_id": parent["run_id"], "source_run_record_sha256": parent_hash,
              "source_artifact_sha256": input_hashes, "snapshot_sha256": parent.get("snapshot_sha256"),
              "source_sha256": source_hashes(), "offline": True, "models_refitted": False,
              "reserved_responses_read": False, "reserved_rows_excluded": True, "final_test_evaluated": False,
              "python": sys.version, "package_versions": {d.metadata["Name"]: d.version for d in distributions() if d.metadata["Name"]},
              "command": f"python -m spy_volatility --config {config_path.relative_to(root).as_posix()} --offline",
              "limitations": ["Conditional on historically selected fitted models and fixed annual composition",
                              "Approximate within-year stationarity; cross-year dependence omitted",
                              "Circular endpoint joins; block lengths are sensitivity choices, not estimated optima"]}
    try:
        record["source_git"] = {}
        for key, args in (("commit", ["rev-parse", "HEAD"]), ("working_tree", ["status", "--short"])):
            try:
                result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
                record["source_git"][key] = result.stdout.strip() if result.returncode == 0 else "unavailable"
            except OSError:
                record["source_git"][key] = "unavailable"
        _json(output / "run_record.json", record)
        _json(output / "frozen_protocol.json", {"recorded_before_intervals_at_utc": now.isoformat(),
                "config": config, "config_sha256": record["config_sha256"],
                "status": "retrospective uncertainty protocol; historical scores already known"})
        (output / "source").mkdir()
        (output / "tables").mkdir()
        for path in Path(__file__).parent.glob("*.py"):
            shutil.copy2(path, output / "source" / path.name)
            if _sha(output / "source" / path.name) != record["source_sha256"][f"spy_volatility/{path.name}"]:
                raise ValueError("Executing package source changed while copying")
        shutil.copy2(config_path, output / "source" / "experiment.toml")
        shutil.copy2(source / "run_record.json", output / "source_parent_run_record.json")
        if _sha(output / "source_parent_run_record.json") != parent_hash:
            raise ValueError("Source record changed while copying")
        for name, copied in INPUTS.items():
            shutil.copy2(source / name, output / copied)
            if _sha(output / copied) != input_hashes[name]:
                raise ValueError(f"Source artifact changed while copying {name}")
        protocol = {**SETTINGS, "metrics": METRICS, "model_keys": grids[0]["model_keys"],
                    "folds": [g["fold"] for g in grids]}
        _json(output / "protocol.json", protocol)
        (output / "dependencies.txt").write_text("\n".join(f"{k}=={v}" for k, v in sorted(record["package_versions"].items())) + "\n", encoding="utf-8")
        identity_draws = {g["fold"]: np.arange(len(g["sessions"]))[None, :] for g in grids}
        points = bootstrap_scores(grids, identity_draws)[0][:, 0]
        table_parts = {"scores": [], "comparisons": []}
        for length in SETTINGS["block_lengths"]:
            indexes = {g["fold"]: stationary_indices(len(g["sessions"]), SETTINGS["n_resamples"], length,
                       np.random.default_rng(np.random.SeedSequence([SETTINGS["seed"], length, g["fold"]]))) for g in grids}
            scores, counts = bootstrap_scores(grids, indexes)
            np.savez_compressed(output / f"bootstrap_L{length}.npz", scores=scores, counts=counts,
                                **{f"indices_{fold}": values for fold, values in indexes.items()})
            tables = interval_tables(points, scores, grids[0]["model_keys"], length)
            for name in table_parts:
                table_parts[name].append(tables[name])
        tables = {name: pd.concat(parts, ignore_index=True) for name, parts in table_parts.items()}
        for name, table in tables.items():
            table.to_csv(output / "tables" / f"{name}.csv", index=False)
        metadata = []
        totals = np.sum([g["original_counts"] for g in grids], axis=0)
        for grid in grids:
            for s, subset in enumerate(SUBSETS):
                metadata.append({"fold": grid["fold"], "subset": subset, "n_grid_sessions": len(grid["sessions"]),
                                 "first_session_number": int(grid["sessions"][0]), "last_session_number": int(grid["sessions"][-1]),
                                 "n_original_eligible": int(grid["original_counts"][s]),
                                 "fixed_weight": grid["original_counts"][s] / totals[s]})
        pd.DataFrame(metadata).to_csv(output / "tables" / "annual_grid.csv", index=False)
        from .uncertainty_verification import verify_uncertainty
        verification = verify_uncertainty(output)
        _json(output / "calculation_verification.json", verification)
        _report(output, record, tables)
        if (_sha(source / "run_record.json") != parent_hash
                or any(_sha(source / name) != digest for name, digest in input_hashes.items())
                or source_hashes() != record["source_sha256"] or _sha(config_path) != record["config_sha256"]):
            raise ValueError("Source evidence or executing configuration/code changed during uncertainty run")
        record.update(status="success", calculation_verification_passed=True,
                      n_original_forecasts=int(totals[1]), n_contained_forecasts=int(totals[0]))
        return {"run_id": run_id, "output_dir": str(output), "report": str(output / "results.md"),
                "calculation_verification_passed": True, "test_evaluated": False}
    except Exception as error:
        record.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
        (output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        record["artifact_sha256"] = {p.relative_to(output).as_posix(): _sha(p) for p in sorted(output.rglob("*"))
                                      if p.is_file() and p != output / "run_record.json"}
        _json(output / "run_record.json", record)
