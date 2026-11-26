"""Read the three designated historical releases for public presentation.

A run record authenticates the few permitted tables. Pin the record itself so a
new file and matching edited manifest cannot silently enter a public release.
No directory discovery, private journal access, model fitting or network I/O.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path

import pandas as pd

from spy_volatility.workflows.sensitivity import validate_predictions_for_sensitivity


TEMPORAL = "20261027T001114_temporal_4bf4a071"
SENSITIVITY = "20261111T035209_sensitivity_f9d56993"
UNCERTAINTY = "20261112T033412_uncertainty_33ba49a1"
RECORD_HASH = {
    TEMPORAL: "cc4f30cc3e2d75790f99aff27095cc1c8c178a9248e190e6d46c46b6cd7d4308",
    SENSITIVITY: "54fbd373df72a3bc79080b19567cd9a680d8be4fa063fb2af62ec649d1ab5791",
    UNCERTAINTY: "7e817d20a27678f85b361f75a7976a1e7fe71bd89b674b423c60db3403630656",
}
TABLES = {
    TEMPORAL: ("tables/diagnostic_temporal_aggregate.csv",
               "tables/diagnostic_temporal_tail.csv", "temporal_predictions.csv"),
    SENSITIVITY: ("tables/metrics.csv", "tables/comparisons.csv"),
    UNCERTAINTY: ("tables/comparisons.csv",),
}
METHODS = {"ridge": ("fixed", "ridge"), "hv5": ("comparator", "baseline_5"),
           "hv20": ("fixed", "baseline"), "forest": ("fixed", "random_forest"),
           "boosting": ("fixed", "gradient_boosting")}
SAMPLES = {"original": "Original", "within_year": "Contained",
           "modulo_0": "Every fifth", "within_year_modulo_0": "Both"}


def _verified_bytes(path: Path, digest: str) -> bytes:
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"Historical release digest mismatch for {path.name}")
    return content


def _run(root: Path, run_id: str) -> tuple[dict, dict, list[pd.DataFrame]]:
    directory = root / "artifacts" / "runs" / run_id
    digest = RECORD_HASH[run_id]
    record = json.loads(_verified_bytes(directory / "run_record.json", digest))
    if (record["run_id"] != run_id or record["status"] != "success"
            or record["calculation_verification_passed"] is not True
            or record["final_test_evaluated"] is not False
            or record["reserved_rows_excluded"] is not True):
        raise ValueError(f"Historical release verification failed for {run_id}")
    if run_id != TEMPORAL and (record["parent_run_id"] != TEMPORAL
                               or record["source_run_record_sha256"] != RECORD_HASH[TEMPORAL]
                               or record["reserved_responses_read"] is not False):
        raise ValueError("Invalid historical release parent or reserved response access")

    files, tables = [], []
    for name in TABLES[run_id]:
        file_hash = record["artifact_sha256"][name]
        content = _verified_bytes(directory / name, file_hash)
        tables.append(pd.read_csv(BytesIO(content), float_precision="round_trip"))
        files.append({"name": name, "sha256": file_hash})
    public_source = {"run_id": run_id, "record_sha256": digest,
                     "finished_at": record["finished_at_utc"], "files": files}
    return record, public_source, tables


def _index_rows(table: pd.DataFrame, *columns: str) -> pd.DataFrame:
    indexed = table.set_index(list(columns))
    if not indexed.index.is_unique:
        raise ValueError(f"Ambiguous historical results for keys {columns}")
    return indexed


def _metric_rows(table: pd.DataFrame) -> list[dict]:
    indexed = _index_rows(table, "variant", "model")
    rows = []
    for method, key in METHODS.items():
        row = indexed.loc[key]
        rows.append({"method": method, "n": int(row.n_forecasts),
                     "mae": float(row.mae_pp), "rmse": float(row.rmse_pp),
                     "bias": float(row.bias_pp)})
    return rows


def _observations(predictions: pd.DataFrame) -> list[dict]:
    # Only the pinned annual development output can reach this reader.
    # The existing research validator checks alignment and partition before
    # projecting any values, including observed volatility.
    checked = validate_predictions_for_sensitivity(predictions)
    if not checked.forecast_date.dt.year.between(2020, 2025).all():
        raise ValueError("Unexpected forecast date in retrospective release")
    by_model = checked.set_index(["variant", "model"]).sort_index()
    series = {
        name: by_model.loc[[METHODS[name]]].set_index("forecast_date").sort_index()
        for name in ("ridge", "hv5", "hv20")
    }
    public = pd.DataFrame(index=series["ridge"].index)
    public["date"] = public.index.strftime("%Y-%m-%d")
    public["observed"] = series["ridge"].observed * 100
    for method, frame in series.items():
        public[method] = 100 * frame.prediction
        errors = 100 * (frame.prediction - frame.observed)
        public[f"{method}_signed"] = errors
        public[f"{method}_absolute"] = errors.abs()
    return public.to_dict(orient="records")


def _subsets(metrics: pd.DataFrame, comparisons: pd.DataFrame) -> tuple[list, list]:
    all_rows = metrics.query("aggregation == 'aggregate' and tail_group == 'all' and availability == 'available'")
    by_sample = _index_rows(all_rows, "subset", "variant", "model")
    samples = []
    for subset, label in SAMPLES.items():
        ridge = by_sample.loc[(subset, *METHODS["ridge"])]
        row = {"sample": label, "n": int(ridge.n_forecasts)}
        for method in ("ridge", "hv5", "hv20"):
            row[method] = float(by_sample.loc[(subset, *METHODS[method]), "rmse_pp"])
        samples.append(row)

    ridge = comparisons.query("aggregation == 'aggregate' and tail_group == 'all' "
                              "and variant == 'fixed' and model == 'ridge' and availability == 'available'")
    gains = _index_rows(ridge, "subset", "benchmark")
    offsets = []
    for offset in range(5):
        subset = f"modulo_{offset}"
        vs20 = gains.loc[(subset, "baseline")]
        vs5 = gains.loc[(subset, "baseline_5")]
        offsets.append({"offset": offset, "n": int(vs20.n_forecasts),
                        "vs20": float(vs20.relative_rmse_improvement_pct),
                        "vs5": float(vs5.relative_rmse_improvement_pct)})
    return samples, offsets


def _uncertainty(record: dict, comparisons: pd.DataFrame) -> dict:
    settings = record["config"]["uncertainty"]
    block_length = settings["primary_block_length"]
    primary = comparisons.query("subset == 'within_year' and block_length == @block_length "
                                "and metric == 'rmse_pp' and variant == 'fixed' and model == 'ridge' "
                                "and primary_analysis and availability == 'available'")
    index = _index_rows(primary, "reference_variant", "reference_model")
    intervals = []
    for method in ("hv20", "hv5"):
        row = index.loc[METHODS[method]]
        if row.n_invalid != 0 or row.n_valid != settings["n_resamples"]:
            raise ValueError("Primary bootstrap draws incomplete")
        intervals.append({"method": method, "estimate": float(row.estimate),
                          "lower": float(row.familywise_lower), "upper": float(row.familywise_upper)})
    return {"resamples": int(settings["n_resamples"]), "block_length": int(block_length),
            "n": int(record["n_contained_forecasts"]), "intervals": intervals}


def load_history(root: Path) -> dict:
    """Return only public historical fields, in volatility percent / percentage points.

    Missing or modified designated artifacts raise instead of falling back to
    different experiments. Callers decide whether to report unavailability or
    keep a previous successful export.
    """
    _, temporal_source, (aggregate, tail, predictions) = _run(root, TEMPORAL)
    _, sensitivity_source, (metrics, gains) = _run(root, SENSITIVITY)
    bootstrap, uncertainty_source, (comparisons,) = _run(root, UNCERTAINTY)
    observations = _observations(predictions)
    performance = _metric_rows(aggregate)
    high = tail.query("aggregation == 'aggregate' and tail_group == 'at_or_above_training_q95' "
                      "and availability == 'available'")
    sensitivity, offsets = _subsets(metrics, gains)
    return {"sources": [temporal_source, sensitivity_source, uncertainty_source],
            "coverage": {"start": observations[0]["date"], "end": observations[-1]["date"]},
            "performance": performance, "tail": _metric_rows(high), "sensitivity": sensitivity,
            "offsets": offsets, "uncertainty": _uncertainty(bootstrap, comparisons),
            "observations": observations}
