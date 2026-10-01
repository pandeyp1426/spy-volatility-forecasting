"""Validation results and checks for the historical-volatility baseline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .research import evaluate_predictions


def write_results_report(
    output: Path,
    *,
    run_id: str,
    config: dict,
    metadata: dict,
    audit: dict,
    summary: dict,
    metrics: dict,
    verification: dict,
) -> Path:
    """Write a readable report and annual validation diagnostics.

    Only the saved validation predictions are read. Reserved test counts come
    from the split summary; reserved test outcomes are never read or scored.
    The caller must complete the data audit and independent numerical checks
    before producing this report.
    """
    if audit.get("passed") is not True or verification.get("passed") is not True:
        raise ValueError("A passing data audit and calculation verification are required for the report.")

    output = Path(output)
    predictions = pd.read_csv(
        output / "validation_predictions.csv",
        index_col="forecast_date",
        parse_dates=["forecast_date"],
        float_precision="round_trip",
    )
    if (not isinstance(predictions.index, pd.DatetimeIndex)
            or predictions.index.hasnans or not predictions.index.is_unique
            or not predictions.index.is_monotonic_increasing):
        raise ValueError("Validation forecast dates must be valid, unique, and chronological.")
    # This also rejects empty or nonfinite predictions before any report is written.
    evaluate_predictions(predictions)
    annual_rows = []
    for year, frame in predictions.groupby(predictions.index.year, sort=True):
        annual_rows.append({
            "year": int(year),
            **evaluate_predictions(frame),
            "bias_pp": float(((frame["baseline"] - frame["target"]) * 100).mean()),
        })
    annual = pd.DataFrame(annual_rows, columns=["year", "n_forecasts", "mae_pp", "rmse_pp", "bias_pp"])

    research = config["research"]
    horizon, lookback = research["horizon"], research["baseline_window"]
    checked = verification["checked_rows"]
    coverage = metadata["actual_date_range"]
    lines = [
        "# Local baseline results",
        "",
        f"Run: `{run_id}`",
        "",
        f"After each market close, the baseline uses the last {lookback} daily returns "
        f"to forecast volatility over the next {horizon} trading sessions. "
        "Volatility means how much daily returns vary; it does not predict price direction.",
        "",
        "## Reliability checks",
        "",
        f"Data audit: **passed** ({audit['row_count']:,} price rows). "
        f"Independent calculation checks: **passed** ({checked['train']:,} training rows "
        f"and {checked['validation']:,} validation rows).",
        "",
        "Calculation checks cover training and validation only; reserved test outcomes remain unscored.",
        "",
        *[f"- {check}" for check in verification["checks"]],
        "",
        f"Numerical tolerance: relative `{verification['rtol']}`, absolute `{verification['atol']}`.",
        "",
        "## Validation results",
        "",
        "Errors below are in **daily-volatility percentage points**, without annualization. "
        "Lower MAE and RMSE are better. MAE is the average absolute error; "
        "RMSE gives larger errors more weight.",
        "",
        "| Forecast sample | Count | MAE | RMSE |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, key in (("Every trading session", "validation_daily"),
                       (f"Every {horizon} trading sessions (nonoverlapping)", "validation_nonoverlapping")):
        values = metrics[key]
        lines.append(f"| {label} | {values['n_forecasts']:,} | {values['mae_pp']:.4f} | {values['rmse_pp']:.4f} |")
    lines.extend([
        "",
        f"The nonoverlapping sample starts on {metrics['nonoverlapping_anchor']}.",
        "",
        "### By forecast year",
        "",
        "These daily-sample diagnostics show variation across years; they are not a model-selection rule. "
        "Positive bias means forecasts were too high on average; negative bias means too low.",
        "",
        "| Year | Count | MAE | RMSE | Bias |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for row in annual.itertuples(index=False):
        lines.append(f"| {row.year} | {row.n_forecasts:,} | {row.mae_pp:.4f} | {row.rmse_pp:.4f} | {row.bias_pp:+.4f} |")
    lines.extend([
        "",
        "[Annual diagnostics CSV](validation_by_year.csv)",
        "",
        "## Data split",
        "",
        "| Period | Forecast dates retained | Rows retained | Rows purged | Use |",
        "| --- | --- | ---: | ---: | --- |",
    ])
    for name, purpose in (("train", "Training history"), ("validation", "Baseline evaluation"),
                          ("test", "Reserved; performance not computed")):
        part = summary["partitions"][name]
        lines.append(
            f"| {name.title()} | {part['first_forecast_date']} to {part['last_forecast_date']} "
            f"| {part['n_after_purge']:,} | {part['n_purged']:,} | {purpose} |"
        )
    lines.extend([
        "",
        "Purging removes earlier forecasts whose future outcome window reaches the next period.",
        "",
        "## Plots",
        "",
        "![Training returns and historical volatility](training_history.png)",
        "",
        "![Validation forecast and observed volatility](validation_baseline.png)",
        "",
        "## Snapshot and interpretation",
        "",
        f"Snapshot: `{config['paths']['snapshot_dir']}` (relative to the project root). "
        f"Adjusted-price coverage: {coverage['start'][:10]} to {coverage['end'][:10]}.",
        "",
        f"Snapshot SHA-256: `{metadata['sha256']}`.",
        "",
        "[Run record](run_record.json) · [Data audit](data_audit.json) · "
        "[Calculation verification](calculation_verification.json) · [Metrics](metrics.json)",
        "",
        "Passing checks support reproducible data handling and baseline calculations. "
        "They do not prove that the forecast is accurate enough for a practical use, "
        "or that a machine-learning model improves it. Daily forecasts share future observations, "
        "so their errors are dependent; even the nonoverlapping sample can remain serially dependent.",
        "",
        "Baseline calculations are verified. Model comparison remains a separate step; "
        "the reserved test period remains unscored.",
        "",
    ])
    annual.to_csv(output / "validation_by_year.csv", index=False)
    report_path = output / "results.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
