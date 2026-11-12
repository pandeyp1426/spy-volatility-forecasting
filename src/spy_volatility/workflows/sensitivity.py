"""Rescore frozen temporal development forecasts under fixed identity masks.

Only saved development predictions and identity metadata are read. No price
loader, estimator, tuning routine or reserved response matrix is used here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
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

from spy_volatility.analysis.diagnostics import error_metrics, validate_predictions
from spy_volatility.infrastructure.provenance import copy_source, source_hashes


DATES = ["forecast_date", "target_start", "target_end", "fit_cutoff"]
IDENTITY = ["row_id", "fold", "session_number", *DATES]
BENCHMARKS = {"baseline": ("fixed", "baseline"),
              "baseline_5": ("comparator", "baseline_5")}
EXPECTED_GROUPS = {("fixed", "baseline"), ("comparator", "baseline_5"),
                   *((v, m) for v in ("fixed", "tuned", "volatility_only")
                     for m in ("ridge", "random_forest", "gradient_boosting"))}
INPUTS = {"temporal_predictions.csv": "source_predictions.csv",
          "reserved_identities.csv": "source_reserved_identities.csv",
          "source_split_assignments.csv": "source_split_assignments.csv",
          "temporal_membership.csv": "source_temporal_membership.csv"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def validate_predictions_for_sensitivity(frame: pd.DataFrame, reserved_row_ids=()) -> pd.DataFrame:
    """Require paired, ordered annual evaluation identities and both benchmarks."""
    required = {*IDENTITY, "partition"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Sensitivity predictions require {sorted(required)}")
    checked = validate_predictions(frame)
    if checked[list(required)].isna().any().any():
        raise ValueError("Sensitivity identity metadata must be nonmissing")
    if not checked.partition.eq("evaluation").all():
        raise ValueError("Only outer evaluation predictions are allowed")
    for column in ("row_id", "fold", "session_number"):
        values = pd.to_numeric(checked[column], errors="raise").to_numpy(float)
        if not np.isfinite(values).all() or (values < 0).any() or (values != np.floor(values)).any():
            raise ValueError(f"{column} must contain nonnegative integers")
        checked[column] = values.astype(np.int64)
    for column in DATES:
        checked[column] = pd.to_datetime(checked[column], errors="raise")
        if checked[column].dt.tz is not None or not checked[column].eq(checked[column].dt.normalize()).all():
            raise ValueError("Use timezone-free session dates at midnight")
    if (checked.groupby("row_id")[[*IDENTITY[1:], "observed", "threshold"]].nunique() != 1).any().any():
        raise ValueError("Models disagree on evaluation identity metadata")
    identities = checked.drop_duplicates("row_id").sort_values("forecast_date")
    if not identities.forecast_date.is_unique or not identities.session_number.is_unique:
        raise ValueError("Forecast dates and original session numbers must identify unique rows")
    if (np.diff(identities.session_number) <= 0).any():
        raise ValueError("Original session numbers must increase with forecast dates")
    if not (checked.fold.eq(checked.forecast_date.dt.year).all()
            and (checked.fit_cutoff < checked.forecast_date).all()
            and (checked.forecast_date < checked.target_start).all()
            and (checked.target_start <= checked.target_end).all()):
        raise ValueError("Invalid annual fold, fitting cutoff or target interval")
    if checked.row_id.isin(list(reserved_row_ids)).any():
        raise ValueError("Reserved row identity entered development sensitivity")
    groups = set(map(tuple, checked[["variant", "model"]].drop_duplicates().to_numpy()))
    if not set(BENCHMARKS.values()).issubset(groups):
        raise ValueError("Both fixed baseline and comparator baseline_5 are required")
    return checked


def build_membership(frame: pd.DataFrame, horizon: int = 5, primary_residue: int = 0) -> pd.DataFrame:
    """Record included AND excluded identities for the twelve frozen subsets."""
    if horizon != 5 or primary_residue != 0:
        raise ValueError("The frozen sensitivity protocol requires horizon 5 and primary residue 0")
    checked = validate_predictions_for_sensitivity(frame)
    identities = checked[IDENTITY].drop_duplicates("row_id").sort_values("session_number").reset_index(drop=True)
    contained = (identities.target_start.dt.year.eq(identities.forecast_date.dt.year)
                 & identities.target_end.dt.year.eq(identities.forecast_date.dt.year))
    definitions = [("original", False, None), ("within_year", True, None)]
    definitions += [(f"modulo_{r}", False, r) for r in range(horizon)]
    definitions += [(f"within_year_modulo_{r}", True, r) for r in range(horizon)]
    parts = []
    for name, contain, residue in definitions:
        years_ok = contained if contain else pd.Series(True, index=identities.index)
        residue_ok = (identities.session_number.mod(horizon).eq(residue) if residue is not None
                      else pd.Series(True, index=identities.index))
        part = identities.copy()
        part.insert(0, "subset", name)
        part.insert(1, "primary", residue is None or residue == primary_residue)
        part["included"] = years_ok & residue_ok
        part["exclusion_reason"] = np.select(
            [~years_ok & ~residue_ok, ~years_ok, ~residue_ok],
            ["outcome_crosses_year;residue_mismatch", "outcome_crosses_year", "residue_mismatch"],
            default="included")
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def summarize_sensitivity(frame: pd.DataFrame, membership: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Recompute paired aggregate, annual and ex-post tail scores for every mask."""
    frame = validate_predictions_for_sensitivity(frame)
    expected = build_membership(frame)
    # A caller cannot silently substitute a favorable mask or compressed index.
    columns = ["subset", "row_id", "included", "primary"]
    left = membership[columns].sort_values(["subset", "row_id"]).reset_index(drop=True)
    right = expected[columns].sort_values(["subset", "row_id"]).reset_index(drop=True)
    if not left.equals(right):
        raise ValueError("Membership differs from the frozen sensitivity masks")
    model_groups = sorted(set(map(tuple, frame[["variant", "model"]].to_numpy())))
    folds = sorted(frame.fold.unique())
    metrics, comparisons, audits = [], [], []
    for subset, mask in expected.groupby("subset", sort=False):
        primary = bool(mask.primary.iloc[0])
        selected = mask.loc[mask.included].sort_values("session_number")
        data = frame.loc[frame.row_id.isin(selected.row_id)]
        starts, ends = selected.target_start.to_numpy(), selected.target_end.to_numpy()
        overlaps = int(np.count_nonzero(starts[1:] <= np.maximum.accumulate(ends)[:-1])) if len(selected) else 0
        if "modulo" in subset and overlaps:
            raise ValueError(f"Target intervals overlap in {subset}")
        gap = np.diff(selected.session_number.to_numpy())
        audits.append({"subset": subset, "primary": primary, "n_forecasts": len(selected),
                       "n_excluded": len(mask) - len(selected),
                       "n_outcomes_crossing_year": int((selected.target_end.dt.year != selected.forecast_date.dt.year).sum()),
                       "n_overlapping_predecessors": overlaps,
                       "minimum_session_gap": int(gap.min()) if len(gap) else np.nan})
        for aggregation, fold in [("aggregate", None), *(("fold", int(f)) for f in folds)]:
            scope = data if fold is None else data.loc[data.fold.eq(fold)]
            for tail in ("all", "below_training_q95", "at_or_above_training_q95"):
                group = scope
                if tail == "below_training_q95":
                    group = scope.loc[scope.observed < scope.threshold]
                elif tail == "at_or_above_training_q95":
                    group = scope.loc[scope.observed >= scope.threshold]
                scores = {key: error_metrics(group.loc[group.variant.eq(key[0]) & group.model.eq(key[1])])
                          for key in model_groups}
                context = {"subset": subset, "primary": primary, "aggregation": aggregation,
                           "fold": fold, "tail_group": tail}
                for (variant, model), score in scores.items():
                    available = score["n_forecasts"] > 0
                    label = {**context, "variant": variant, "model": model}
                    metrics.append({**label, **score, "availability": "available" if available else "empty; unavailable"})
                    for benchmark, key in BENCHMARKS.items():
                        base = scores[key]
                        row = {**label, "benchmark": benchmark, "n_forecasts": score["n_forecasts"],
                               "availability": "available" if available else "empty; unavailable"}
                        for metric in ("mae", "rmse"):
                            value, denominator = score[f"{metric}_pp"], base[f"{metric}_pp"]
                            row[f"delta_{metric}_pp"] = value - denominator
                            row[f"relative_{metric}_improvement_pct"] = (
                                100.0 * (1.0 - value / denominator) if denominator > 0 else np.nan)
                            if available and denominator == 0:
                                row["availability"] = "zero benchmark error; relative improvement unavailable"
                        comparisons.append(row)
    return {"metrics": pd.DataFrame(metrics), "comparisons": pd.DataFrame(comparisons),
            "audit": pd.DataFrame(audits)}


def _read_source(source: Path) -> tuple[dict, dict, pd.DataFrame]:
    record = json.loads((source / "run_record.json").read_text(encoding="utf-8"))
    if (record.get("status") != "success" or record.get("experiment") != "retrospective_temporal"
            or record.get("final_test_evaluated") is not False
            or record.get("reserved_rows_excluded") is not True
            or record.get("calculation_verification_passed") is not True
            or record.get("config", {}).get("research", {}).get("horizon") != 5):
        raise ValueError("Source must be a successful verified temporal run with reserved test excluded")
    hashes = {}
    for name in INPUTS:
        hashes[name] = _sha(source / name)
        if hashes[name] != record.get("artifact_sha256", {}).get(name):
            raise ValueError(f"Source artifact hash mismatch: {name}")
    reserved = pd.read_csv(source / "reserved_identities.csv")
    assignments = pd.read_csv(source / "source_split_assignments.csv")
    if (not reserved.partition.eq("test").all() or not reserved.row_id.is_unique
            or not assignments.row_id.is_unique
            or set(reserved.row_id) != set(assignments.loc[assignments.partition.eq("test"), "row_id"])):
        raise ValueError("Reserved identity metadata disagrees with the saved pooled map")
    predictions = pd.read_csv(source / "temporal_predictions.csv", float_precision="round_trip")
    predictions = validate_predictions_for_sensitivity(predictions, reserved.row_id)
    if set(map(tuple, predictions[["variant", "model"]].to_numpy())) != EXPECTED_GROUPS:
        raise ValueError("Expected all eleven saved temporal model/variant groups")
    original = predictions[IDENTITY].drop_duplicates("row_id").sort_values("row_id").reset_index(drop=True)
    outer = pd.read_csv(source / "temporal_membership.csv")
    outer = outer.loc[outer.level.eq("outer") & outer.partition.eq("evaluation")].rename(columns={"outer_fold": "fold"})
    for column in DATES:
        outer[column] = pd.to_datetime(outer[column])
    outer = outer[IDENTITY].sort_values("row_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(original, outer, check_dtype=False, obj="Saved outer evaluation membership")
    identity_columns = ["row_id", "session_number", "forecast_date", "target_start", "target_end"]
    allowed = assignments.loc[assignments.partition.isin(["train", "validation"])].set_index("row_id")
    if not set(original.row_id).issubset(allowed.index):
        raise ValueError("Evaluation includes an identity outside the permitted development map")
    allowed = allowed.loc[original.row_id].reset_index()
    for column in DATES[:3]:
        allowed[column] = pd.to_datetime(allowed[column])
    pd.testing.assert_frame_equal(original[identity_columns], allowed[identity_columns], check_dtype=False,
                                  obj="Saved pooled development metadata")
    return record, hashes, predictions


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    def cell(value):
        if pd.isna(value):
            return "unavailable"
        if isinstance(value, (float, np.floating)):
            return f"{value:.6f}"
        return str(value)
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    rows.extend("| " + " | ".join(cell(row[c]) for c in columns) + " |" for _, row in frame.iterrows())
    return "\n".join(rows)


def _write_report(output: Path, record: dict, tables: dict) -> None:
    metrics = tables["metrics"]
    all_scores = metrics.loc[metrics.aggregation.eq("aggregate") & metrics.tail_group.eq("all")]
    primary = all_scores.loc[all_scores.primary & (all_scores.variant.eq("fixed") | all_scores.variant.eq("comparator"))]
    offsets = all_scores.loc[all_scores.variant.eq("fixed") & all_scores.model.eq("ridge")]
    tails = metrics.loc[metrics.aggregation.eq("aggregate") & metrics.tail_group.eq("at_or_above_training_q95")
                        & metrics.primary & (metrics.variant.eq("fixed") | metrics.variant.eq("comparator"))]
    text = ["# Temporal sensitivity results", "",
            f"Run: `{record['run_id']}`. Parent: `{record['parent_run_id']}`.", "",
            "Saved development forecasts were rescored without fitting or tuning. Both target endpoints must remain in the forecast year for containment. Modulo sampling uses the original session number globally; residue 0 was fixed as primary before subset scores. All five residues are disclosed.", "",
            "## Sample and overlap audit", "", _markdown_table(tables["audit"],
                ["subset", "n_forecasts", "n_excluded", "n_outcomes_crossing_year", "n_overlapping_predecessors"]), "",
            "## Primary fixed-model and benchmark comparison", "",
            "MAE, RMSE and signed bias are daily-volatility percentage points. Aggregate RMSE uses all retained squared errors, not mean annual RMSE.", "",
            _markdown_table(primary, ["subset", "model", "n_forecasts", "mae_pp", "rmse_pp", "bias_pp"]), "",
            "## Fixed Ridge: all offsets", "",
            _markdown_table(offsets, ["subset", "n_forecasts", "mae_pp", "rmse_pp", "bias_pp"]), "",
            "## Primary high-outcome diagnostics", "",
            "Groups use each original fit's training target 95th percentile; observed equality belongs to the high group. This is ex-post diagnosis.", "",
            _markdown_table(tails, ["subset", "model", "n_forecasts", "mae_pp", "rmse_pp", "bias_pp"]), "",
            "## Evidence and limits", "",
            "`membership.csv` records every inclusion and exclusion. `tables/metrics.csv` includes all eleven variants, every original annual fold and both tail groups, including empty groups. `tables/comparisons.csv` compares each with both benchmarks on identical rows; positive relative improvement or negative model-minus-benchmark delta means lower error. `calculation_verification.json` independently checks membership and arithmetic.", "",
            "Annual containment removes cross-year outcome sharing but retains within-year overlap. Modulo subsets have disjoint scored outcome windows; shared fitted models, predictor overlap and volatility persistence remain. Offsets are dependent sensitivities, not independent replications. Different subsets change sample composition. These retrospective checks establish neither statistical significance nor future performance. Reserved responses remain unread and unscored; uncertainty estimation and a separately frozen later period remain future work.", ""]
    (output / "results.md").write_text("\n".join(text), encoding="utf-8")


def run_sensitivity(config_path: str | Path) -> dict:
    """Always offline; write a new run and never modify the source experiment."""
    config_path = Path(config_path).resolve()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    expected = {"horizon": 5, "primary_residue": 0, "residues": list(range(5)),
                "containment": "target_start_and_end_in_forecast_calendar_year",
                "sampling": "original_session_number_modulo_horizon"}
    if config.get("experiment", {}).get("strategy") != "temporal_sensitivity" or config.get("sensitivity") != expected:
        raise ValueError("Use the frozen annual containment and modulo-five sensitivity protocol")
    root = config_path.parent.parent
    source = (root / config["paths"]["temporal_run"]).resolve()
    parent, input_hashes, predictions = _read_source(source)
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S") + "_sensitivity_" + uuid4().hex[:8]
    output = root / config["paths"]["output_dir"] / run_id
    output.mkdir(parents=True, exist_ok=False)
    record = {"run_id": run_id, "experiment": "temporal_sensitivity", "status": "running",
              "started_at_utc": now.isoformat(), "parent_run_id": parent["run_id"],
              "source_run_record_sha256": _sha(source / "run_record.json"),
              "source_artifact_sha256": input_hashes, "snapshot_sha256": parent.get("snapshot_sha256"),
              "config": config, "config_sha256": _sha(config_path), "source_sha256": source_hashes(),
              "offline": True, "models_refitted": False, "reserved_responses_read": False,
              "final_test_evaluated": False, "reserved_rows_excluded": True,
              "intended_change": "Rescore saved temporal predictions under containment and global modulo-five masks",
              "command": f"python -m spy_volatility --config {config_path.relative_to(root).as_posix()} --offline",
              "python": sys.version,
              "package_versions": {d.metadata["Name"]: d.version for d in distributions() if d.metadata["Name"]},
              "limitations": ["Retrospective development; no untouched-test claim",
                              "Disjoint outcome windows do not imply independent forecast errors",
                              "Changing masks changes sample composition; no confidence intervals computed"]}
    try:
        record["source_git"] = {}
        for key, args in (("commit", ["rev-parse", "HEAD"]), ("working_tree", ["status", "--short"])):
            try:
                result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
                record["source_git"][key] = result.stdout.strip() if result.returncode == 0 else "unavailable"
            except OSError:
                record["source_git"][key] = "unavailable"
        _json(output / "run_record.json", record)
        _json(output / "frozen_protocol.json", {"recorded_before_scoring_at_utc": now.isoformat(),
                "config": config, "config_sha256": record["config_sha256"],
                "status": "retrospective protocol fixed before these subset scores; prior results already known"})
        (output / "source").mkdir()
        (output / "tables").mkdir()
        copy_source(output / "source", record["source_sha256"])
        shutil.copy2(config_path, output / "source" / "experiment.toml")
        shutil.copy2(source / "run_record.json", output / "source_parent_run_record.json")
        if _sha(output / "source_parent_run_record.json") != record["source_run_record_sha256"]:
            raise ValueError("Source run record changed while copying")
        for name, copied in INPUTS.items():
            shutil.copy2(source / name, output / copied)
            if _sha(output / copied) != input_hashes[name]:
                raise ValueError(f"Source changed while copying {name}")
        (output / "dependencies.txt").write_text("\n".join(f"{k}=={v}" for k, v in sorted(record["package_versions"].items())) + "\n", encoding="utf-8")
        membership = build_membership(predictions)
        membership.to_csv(output / "membership.csv", index=False)
        tables = summarize_sensitivity(predictions, membership)
        for name, table in tables.items():
            table.to_csv(output / "tables" / f"{name}.csv", index=False)
        from spy_volatility.verification.sensitivity import verify_sensitivity
        verification = verify_sensitivity(output)
        _json(output / "calculation_verification.json", verification)
        _write_report(output, record, tables)
        # Recheck all source evidence, including its run record, after execution.
        if (_sha(source / "run_record.json") != record["source_run_record_sha256"]
                or any(_sha(source / name) != digest for name, digest in input_hashes.items())):
            raise ValueError("Source evidence changed during the sensitivity run")
        record.update(status="success", calculation_verification_passed=True,
                      metrics={"sample_counts": tables["audit"][["subset", "n_forecasts"]].to_dict("records")})
        return {"run_id": run_id, "output_dir": str(output), "report": str(output / "results.md"),
                "test_evaluated": False, "calculation_verification_passed": True,
                "sample_counts": record["metrics"]["sample_counts"]}
    except Exception as error:
        record.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
        (output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        record["artifact_sha256"] = {p.relative_to(output).as_posix(): _sha(p) for p in sorted(output.rglob("*"))
                                      if p.is_file() and p != output / "run_record.json"}
        _json(output / "run_record.json", record)
