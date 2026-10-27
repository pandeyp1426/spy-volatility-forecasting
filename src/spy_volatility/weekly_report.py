"""Build one cumulative LaTeX report from an explicitly selected successful run.

No acquisition, training, or test evaluation occurs here. Each build retains its
source, generated tables, figures and hashes alongside the dated PDF.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from zoneinfo import ZoneInfo
from uuid import uuid4

import pandas as pd

from .models import MODEL_NAMES, TARGET_COLUMN
from .next_phase_report import (validate_pooled_narrative, pooled_content,
                                validate_development, development_content, absent_development,
                                register_content)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tex(value):
    replacements = {"\\": r"\textbackslash{}", "_": r"\_", "%": r"\%", "&": r"\&",
                    "#": r"\#", "$": r"\$", "{": r"\{", "}": r"\}"}
    return "".join(replacements.get(c, c) for c in str(value))


def table(path, headers, rows, alignment):
    lines = [r"\begin{tabular}{@{}"+alignment+r"@{}}", r"\toprule",
             " & ".join(headers)+r" \\", r"\midrule"]
    lines += [" & ".join(map(str, row))+r" \\" for row in rows]
    lines += [r"\bottomrule", r"\end{tabular}"]
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")


def prepare_report(run_dir: Path, root: Path, report_date: str | None = None,
                   development_run: Path | None = None) -> tuple[Path, dict]:
    run_dir, root = Path(run_dir).resolve(), Path(root).resolve()
    edition = date.fromisoformat(report_date) if report_date else datetime.now(ZoneInfo("America/Chicago")).date()
    record = json.loads((run_dir/"run_record.json").read_text(encoding="utf-8"))
    if (record.get("status") != "success" or record.get("final_test_evaluated") is not False
            or not record.get("calculation_verification_passed")
            or record["config"]["split"].get("strategy") != "pooled_random"):
        raise ValueError("Report requires a verified successful pooled run with test unscored")
    if (record["config"]["split"]["start"] != "2015-01-01"
            or record["config"]["split"]["end"] != "2026-01-01"
            or record["config"]["data"]["start"] != "2014-11-01"
            or record["config"]["data"]["end"] != "2026-01-01"):
        raise ValueError("This report narrative requires the agreed 2015-2025 study period")
    required = ["validation_metrics.csv", "validation_predictions.csv", "split_summary.json", "eda_summary.json", "data_audit.json",
                "model_record.json", "tables/training_pearson.csv", "tables/training_spearman.csv",
                "tables/session_lag_correlations.csv", "tables/validation_high_volatility.csv"]
    required += [f"figures/{name}.pdf" for name in ("training_distribution", "training_scatter", "training_history", "training_dependence")]
    for name in required:
        if record.get("artifact_sha256", {}).get(name) != sha(run_dir/name):
            raise ValueError(f"Run artifact hash mismatch: {name}")
    model = json.loads((run_dir/"model_record.json").read_text())
    summary = json.loads((run_dir/"split_summary.json").read_text())
    audit = json.loads((run_dir/"data_audit.json").read_text())
    validate_pooled_narrative(record, model, summary, audit)
    development_record = (validate_development(Path(development_run), run_dir, record)
                          if development_run is not None else None)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    build = root/"output/pdf/builds"/f"{edition.isoformat()}_{record['run_id']}_{stamp}"
    build.mkdir(parents=True, exist_ok=False)
    generated = build/"generated"
    generated.mkdir()
    (build/"figures").mkdir()
    for name in ("main.tex", "references.bib"):
        shutil.copy2(root/"report"/name, build/name)
    generator_dir = build/"report_generator"
    generator_dir.mkdir()
    for name in ("weekly_report.py", "next_phase_report.py"):
        shutil.copy2(Path(__file__).parent/name, generator_dir/name)
    for name in required:
        if name.startswith("figures/"):
            shutil.copy2(run_dir/name, build/name)
    metrics = pd.read_csv(run_dir/"validation_metrics.csv").set_index("model")
    summary = json.loads((run_dir/"split_summary.json").read_text())
    eda = json.loads((run_dir/"eda_summary.json").read_text())
    audit = json.loads((run_dir/"data_audit.json").read_text())
    model = json.loads((run_dir/"model_record.json").read_text())
    names = {"baseline": "20-session baseline", "ridge": "Ridge", "random_forest": "Random Forest", "gradient_boosting": "Gradient boosting"}
    table(generated/"validation.tex", ["Model", "$N$", "MAE (pp)", "RMSE (pp)", "Bias (pp)"],
          [[names[n], int(metrics.loc[n,"n_forecasts"]), f"{metrics.loc[n,'mae_pp']:.6f}",
            f"{metrics.loc[n,'rmse_pp']:.6f}", f"{metrics.loc[n,'bias_pp']:+.6f}"] for n in MODEL_NAMES], "lrrrr")
    pearson = pd.read_csv(run_dir/"tables/training_pearson.csv", index_col=0)
    spearman = pd.read_csv(run_dir/"tables/training_spearman.csv", index_col=0)
    feature_names = {"log_return": "Current log return", "volatility_5": "5-session volatility", "volatility_10": "10-session volatility",
                     "volatility_20": "20-session volatility", "momentum_5": "5-session momentum"}
    table(generated/"correlations.tex", ["Predictor vs. future volatility", "Pearson", "Spearman"],
          [[label, f"{pearson.loc[col,TARGET_COLUMN]:.3f}", f"{spearman.loc[col,TARGET_COLUMN]:.3f}"]
           for col, label in feature_names.items()], "lrr")
    overlap = summary["outcome_overlap"]
    table(generated/"overlap.tex", ["Held-out subset", "$N$", "Training outcomes", "Training features"],
          [[name.title(), overlap[name]["n_rows"], overlap[name]["rows_with_training_outcome_overlap"],
            overlap[name]["rows_with_training_feature_overlap"]] for name in ("validation", "test")], "lrrr")
    group = pd.read_csv(run_dir/"tables/validation_high_volatility.csv").set_index("model")
    table(generated/"high_volatility.tex", ["Model", "$N$", "Bias (pp)"],
          [[names[n], int(group.loc[n,"n_forecasts"]), f"{group.loc[n,'bias_pp']:+.4f}"] for n in MODEL_NAMES], "lrr")
    historical = root/"report/historical"
    historical_manifest = json.loads((historical/"source_manifest.json").read_text())
    historical_csv = historical/"pilot_validation_metrics.csv"
    if sha(historical_csv) != historical_manifest["members"][historical_csv.name]:
        raise ValueError("Historical pilot table hash differs from preserved archive member")
    pilot = pd.read_csv(historical_csv).query("sample == 'all_validation'")
    table(generated/"historical.tex", ["Archived chronological model", "$N$", "MAE (pp)", "RMSE (pp)", "Bias (pp)"],
          [[tex(r.model), int(r.n), f"{r.mae_pp:.4f}", f"{r.rmse_pp:.4f}", f"{r.bias_pp:+.4f}"] for r in pilot.itertuples()], "lrrrr")
    ref_path = root/"report/historical/handoff_reference.json"
    reference = json.loads(ref_path.read_text())
    table(generated/"discrepancies.tex", ["Model", "$\\Delta$ MAE (pp)", "$\\Delta$ RMSE (pp)"],
          [[names[n], f"{metrics.loc[n,'mae_pp']-reference['validation'][n]['mae_pp']:+.6f}",
            f"{metrics.loc[n,'rmse_pp']-reference['validation'][n]['rmse_pp']:+.6f}"] for n in MODEL_NAMES], "lrr")
    lag = pd.read_csv(run_dir/"tables/session_lag_correlations.csv")
    pooled_content(run_dir, generated, metrics, eda, pearson, spearman, lag, summary, audit)
    absent_development(generated)
    development_inputs = []
    if development_record is not None:
        development_inputs = development_content(Path(development_run), generated, build, development_record)
        register_content(Path(development_run), generated, build, development_record)
    else:
        (generated/"register.tex").write_text("No development register selected for this edition.\n", encoding="utf-8")
    macros = {"ReportDate": edition.strftime("%d %B %Y"), "RunID": record["run_id"],
              "SourceCommit": record.get("source_git",{}).get("commit","unavailable")[:12],
              "SnapshotHash": record["snapshot_sha256"],
              "SnapshotTime": record["snapshot_metadata"]["retrieved_at_utc"],
              "RawCount": audit["row_count"], "EligibleCount": summary["n_eligible"],
              "TrainingCount": summary["partitions"]["train"]["n_rows"],
              "ValidationCount": summary["partitions"]["validation"]["n_rows"],
              "TestCount": summary["partitions"]["test"]["n_rows"],
              "TargetMedian": f"{100*eda['target_summary']['50%']:.3f}",
              "TargetMean": f"{100*eda['target_summary']['mean']:.3f}",
              "TargetUpper": f"{100*eda['target_summary']['95%']:.3f}",
              "TargetMaximum": f"{100*eda['target_summary']['max']:.3f}",
              "FeatureCorrelation": f"{pearson.loc['volatility_5','volatility_10']:.3f}",
              "LagPairMin": int(lag.pair_count.min()), "LagPairMax": int(lag.pair_count.max()),
              "SklearnVersion": model["sklearn_version"], "FloorCount": sum(model["n_floored"].values()),
              "DividendCount": audit["raw_fields"]["dividend_events"], "SplitCount": audit["raw_fields"]["split_events"]}
    (generated/"macros.tex").write_text("\n".join("\\newcommand{\\"+k+"}{"+tex(v)+"}" for k,v in macros.items())+"\n", encoding="utf-8")
    manifest = {"report_date": edition.isoformat(), "timezone": "America/Chicago", "run_id": record["run_id"],
                "run_dir": str(run_dir), "run_record_sha256": sha(run_dir/"run_record.json"),
                "snapshot_sha256": record["snapshot_sha256"], "source_git": record.get("source_git"),
                "source_sha256": record["source_sha256"], "test_evaluated": False,
                "status": "prepared", "visual_review": "pending",
                "inputs": {name: sha(run_dir/name) for name in required},
                "historical_archive_sha256": historical_manifest["archive_sha256"],
                "handoff_reference_sha256": sha(ref_path)}
    manifest["report_generator_sha256"] = {p.name: sha(p) for p in generator_dir.glob("*.py")}
    if development_record is not None:
        manifest["development_run_id"] = development_record["run_id"]
        manifest["development_run_dir"] = str(Path(development_run).resolve())
        manifest["development_run_record_sha256"] = sha(Path(development_run)/"run_record.json")
        manifest["development_inputs"] = {name: sha(Path(development_run)/name) for name in development_inputs}
    manifest["build_input_sha256"] = {p.relative_to(build).as_posix(): sha(p) for p in build.rglob("*") if p.is_file()}
    (build/"build_record.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return build, manifest


def build_report(run_dir, *, root=None, report_date=None, compiler=None, render=False, development_run=None):
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    build, manifest = prepare_report(Path(run_dir), root, report_date, development_run)
    executable = compiler or shutil.which("tectonic") or str(root/".tools/tectonic/tectonic.exe")
    command = [str(executable), "--keep-logs", "main.tex"]
    result = subprocess.run(command, cwd=build, capture_output=True, text=True)
    (build/"compiler_output.txt").write_text(result.stdout+result.stderr, encoding="utf-8")
    if result.returncode or not (build/"main.pdf").is_file():
        manifest.update(status="compile_failed", compiler_command=command, compiler_exit_code=result.returncode)
        (build/"build_record.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
        raise RuntimeError(f"LaTeX failed; inspect {build / 'compiler_output.txt'}")
    output = root/"output/pdf"
    dated = output/f"SPY_Research_Report_{manifest['report_date']}_{manifest.get('development_run_id', manifest['run_id'])}.pdf"
    if dated.exists() and sha(dated) != sha(build/"main.pdf"):
        dated = output/f"{dated.stem}_{build.name.rsplit('_',1)[-1]}.pdf"
    shutil.copy2(build/"main.pdf", dated)
    current = output/"SPY_Research_Report_current.pdf"
    staged = output / f".current_{uuid4().hex}.pdf"
    shutil.copy2(build/"main.pdf", staged)
    current_path = None
    try:
        os.replace(staged, current)
        current_path = str(current)
    except PermissionError:
        staged.unlink(missing_ok=True)
        manifest["current_update_error"] = "Current PDF is open or not writable. Close its preview and rebuild; dated PDF is preserved."
    manifest.update(status="compiled", compiler_command=command, pdf_sha256=sha(dated), dated_pdf=str(dated), current_pdf=current_path)
    if render:
        import pymupdf
        pages_dir = build/"pages"
        pages_dir.mkdir()
        with pymupdf.open(build/"main.pdf") as document:
            manifest["pages"] = len(document)
            for i, page in enumerate(document):
                page.get_pixmap(matrix=pymupdf.Matrix(1.4, 1.4)).save(pages_dir/f"page-{i+1:02}.png")
    (build/"build_record.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return {"current_pdf": current_path, "dated_pdf": str(dated), "build_dir": str(build),
            "current_update_error": manifest.get("current_update_error")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--development-run", type=Path, help="Named verified retrospective temporal run using --run as its pooled parent")
    parser.add_argument("--date", help="Edition date YYYY-MM-DD; default America/Chicago today")
    parser.add_argument("--compiler", help="Tectonic executable")
    parser.add_argument("--render", action="store_true", help="Render every PDF page for visual review")
    args = parser.parse_args()
    print(json.dumps(build_report(args.run, report_date=args.date, compiler=args.compiler, render=args.render, development_run=args.development_run), indent=2))


if __name__ == "__main__":
    main()
