"""Inventory preserved experiment evidence without opening reserved responses.

The register describes what the files establish, and labels absent provenance
as unavailable. It does not infer a debugging intention or reconstruct a result
from a rounded reference. Older artifacts are only read, never changed.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


REGISTER_FILES = {"experiment_register.json", "experiment_register.md", "artifact_index.csv",
                  "artifact_index.md", "register_summary.json"}
QUESTION = "Can after-close information forecast SPY's next-five-session daily-return SD better than recent historical volatility?"


def _json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {"value": value}
    except (OSError, ValueError) as error:
        return {"read_error": str(error)}


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _without_test_results(value):
    if isinstance(value, dict):
        return {key: _without_test_results(item) for key, item in value.items()
                if not any(word in key.lower() for word in ("test", "reserved"))}
    if isinstance(value, list):
        return [_without_test_results(item) for item in value]
    return value


def _run_entry(directory: Path, root: Path, selected: str | None) -> dict:
    path = directory / "run_record.json"
    record = _json(path)
    config = record.get("config", record.get("configuration", {}))
    split = config.get("split", {})
    temporal = config.get("temporal", {})
    strategy = config.get("experiment", {}).get("strategy", split.get("strategy", "chronological"))
    status = record.get("status", "record missing" if not path.exists() else "unreadable record")
    role = "selected" if directory.name == selected else "historical"
    if record.get("superseded_by"):
        role = "superseded"
    if status not in ("success", "completed"):
        role = "failed" if status == "failed" else "incomplete"
    missing = []
    if not record or record.get("read_error"):
        missing.append("Readable run_record.json")
    source = record.get("source_git", {})
    code_commit = source.get("commit", record.get("source_commit", "unavailable"))
    if code_commit == "unavailable":
        missing.append("Code commit (source hashes may still be recorded)")
    temporal_summary = record.get("temporal_summary") or _json(directory / "temporal_summary.json")
    metrics = record.get("metrics") or _json(directory / "metrics.json")
    if not metrics and temporal_summary.get("metrics"):
        metrics = {"units": temporal_summary.get("metric_units", "daily-volatility percentage points"),
                   "temporal_development": temporal_summary["metrics"]}
    if not metrics:
        missing.append("Saved metrics; no results reconstructed")
    model = _json(directory / "model_record.json") or _json(directory / "temporal_model_records.json")
    if not model and (directory / "model_records.json").is_file():
        model = {"fixed": config.get("fixed", {}), "search": config.get("search", {}),
                 "chosen_parameters": _json(directory / "chosen_parameters.json").get("value", []),
                 "all_fit_records": _relative(directory / "model_records.json", root)}
    summary = _json(directory / "split_summary.json") or temporal_summary
    membership = [p.name for p in directory.glob("*.csv")
                  if any(term in p.name for term in ("membership", "assignments", "boundary"))]
    if not membership and not summary:
        missing.append("Explicit membership or split summary")
    limitations = ["The retained test is unscored; this inventory never opens its response matrix.",
                   "Engineering verification does not establish scientific generalization."]
    limitations.extend(record.get("limitations", []))
    if strategy == "pooled_random":
        limitations.append("Random row separation permits overlapping outcome returns and future training information.")
    elif "temporal" in strategy or temporal:
        limitations.append("Retrospective expanding development evaluation; prior historical exposure and overlapping outcomes remain.")
    else:
        limitations.append("Historical chronological sample; compare only with results on matching evaluation rows.")
    if status != "success":
        limitations.append("An incomplete or failed run is not accepted empirical evidence.")
    if source.get("working_tree"):
        limitations.append("Recorded source commit had working changes; saved source hashes/bundle identify executed code.")
    results = _without_test_results(metrics) if metrics else {"availability": "unavailable"}
    interpretation = record.get("interpretation", "Saved development metrics describe this run's sample; no significance or prospective claim is inferred.")
    if status == "failed":
        interpretation = "Run failed: " + str(record.get("error", "failure details unavailable"))
    command = record.get("command", record.get("execution_command", "not recorded; see saved configuration and source"))
    return {
        "run_id": record.get("run_id", directory.name), "status": status, "role": role,
        "record_path": _relative(path, root), "research_question": record.get("research_question", record.get("question", QUESTION)),
        "parent_run": record.get("parent_run", record.get("parent_run_id", record.get("source_pooled_run_id", config.get("paths", {}).get("pooled_run", "not recorded")))),
        "intended_change": record.get("intended_change", record.get("purpose", "not recorded; configuration preserved below")),
        "dataset_sha256": record.get("snapshot_sha256", "unavailable"), "code_commit": code_commit,
        "source_sha256": record.get("source_sha256", {}), "configuration": config,
        "command": command, "seed": split.get("seed", config.get("fixed", {}).get("random_forest", {}).get("random_state", "not recorded")),
        "row_membership": {"files": membership, "summary": summary},
        "fit_evaluation_dates": record.get("fit_evaluation_dates", temporal or split or "not recorded"),
        "model_settings": model or config.get("fixed", "not recorded"),
        "metric_units": metrics.get("units", "daily-volatility percentage points; MSE where present in squared percentage points") if metrics else "unavailable",
        "results": results, "interpretation": interpretation, "limitations": limitations,
        "decision": record.get("decision", "selected for the current report" if role == "selected" else "retained as historical evidence; no retrospective decision invented"),
        "evidence_missing": missing, "superseded_by": record.get("superseded_by"),
        "test_evaluated": record.get("final_test_evaluated", "not recorded"),
    }


def _describe(path: Path) -> dict:
    text, name = path.as_posix().lower(), path.name.lower()
    info = {"category": "supporting artifact", "data_subset": "not specified", "units": "not applicable",
            "purpose": "Preserved supporting evidence", "interpretation": "Consult the producing run and source.",
            "limitations": "Availability locally does not imply the ignored artifact is published in GitHub."}
    if "reserved" in path.parts or "test_reserved" in name or "test_matrix" in name:
        info.update(category="reserved holdout", data_subset="reserved test; never evaluated",
                    purpose="Preserve formal holdout identities/outcomes", interpretation="Inventory only; contents were not opened.",
                    limitations="Row separation does not eliminate overlap with historical development information.")
    elif name == "raw.csv" or "data_audit" in name or name == "metadata.json":
        info.update(category="raw snapshot and quality audit", data_subset="full frozen price history including warm-up",
                    units="adjusted prices in dollars; audit metadata", purpose="Identify observations, acquisition and consistency checks",
                    interpretation="Internal checks establish consistency, not independent vendor accuracy.")
    elif any(word in name for word in ("split", "membership", "boundary", "overlap")):
        info.update(category="membership and boundary audit", data_subset="row identities; dates; no scored test outcomes",
                    purpose="Trace partitions and label availability", interpretation="Disjoint row IDs alone do not make outcome returns disjoint.")
    elif "prediction" in name:
        fitted = "train" in name
        info.update(category="saved predictions", data_subset="fitted training" if fitted else "development validation",
                    units="decimal daily-return volatility", purpose="Observation-level evidence behind metrics and diagnostics",
                    interpretation="Fitted training error is descriptive, not validation." if fitted else "Compare methods on identical rows and retain outcome dependence limitations.")
    elif any(word in name for word in ("search", "candidate", "selected_parameter", "ablation")):
        info.update(category="search and ablation", data_subset="inner training/development and declared outer comparisons",
                    purpose="Record prespecified candidate choices and failures", interpretation="Inner RMSE selects parameters; outer development estimates performance.")
    elif "diagnostic" in name or "metric" in name or "high_volatility" in name or "validation_by_year" in name:
        info.update(category="error diagnostics and metrics", data_subset="development (training scores labeled fitted where present)",
                    units="MAE/RMSE/bias: percentage points; MSE: squared percentage points; input/prediction axes may be percent",
                    purpose="Show overall, annual, tail and fitted/development error differences",
                    interpretation="Tail groups use realized outcomes ex post; no iid significance claim.")
    elif "training" in name or "session_lag" in name or "eda_" in name:
        info.update(category="training EDA", data_subset="saved pooled training subset",
                    units="figure/table labels; decimal inputs or percent display; correlations dimensionless",
                    purpose="Describe distribution, association and true-session dependence",
                    interpretation="Training association is not held-out forecast accuracy or causation.")
    elif "verification" in name:
        info.update(category="verification", data_subset="development calculations and structural metadata",
                    purpose="Record arithmetic and engineering checks", interpretation="Passing checks does not validate scientific generalization.")
    elif name in ("train.csv", "validation.csv", "features.csv") or "matrix" in name:
        info.update(category="feature and target table", data_subset="training" if "train" in name else "validation" if "validation" in name else "constructed rows; may include reserved outcomes",
                    units="decimal returns/volatility; dates/identities as metadata", purpose="Preserve constructed supervised examples",
                    interpretation="Windows are computed in original session order before partitioning; metadata is excluded from X.")
    elif "output/pdf" in text or path.suffix.lower() in (".tex", ".bib") or "build_record" in name:
        info.update(category="LaTeX/PDF build bundle", data_subset="named run evidence and retained historical context",
                    purpose="Trace report edition inputs, compilation and visual review", interpretation="Only successful builds support the corresponding dated PDF.")
    elif "historical" in text or "source_materials" in text:
        info.update(category="historical/source package", data_subset="historical separate experiment or reference",
                    purpose="Retain supplied prior material and source hashes", interpretation="Different snapshots and samples are not interchangeable; missing evidence remains unavailable.")
    elif "source/" in text or name in ("run_record.json", "model_record.json", "dependencies.txt"):
        info.update(category="run provenance and source", data_subset="configuration and software metadata",
                    purpose="Identify producing settings, code and package versions", interpretation="Working-tree source hashes can differ from the recorded commit.")
    return info


def _artifact(path: Path, root: Path, run_id: str, command, recorded_hash: str | None = None,
              mutable: bool = False) -> dict:
    reserved = "reserved" in path.parts or "test_reserved" in path.name or "test_matrix" in path.name
    if not path.is_file():
        digest, hash_status, availability = recorded_hash or "", "recorded only" if recorded_hash else "unavailable", "missing"
    elif reserved:
        digest, hash_status, availability = recorded_hash or "", "recorded only; reserved contents not opened", "present; unscored and unread"
    elif mutable:
        digest, hash_status, availability = "", "omitted: selected run record is self-referential mutable metadata", "present"
    else:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hash_status, availability = "computed", "present"
    return {"path": _relative(path, root), "run_id": run_id, "command": command,
            **_describe(path), "availability": availability, "sha256": digest, "hash_status": hash_status}


def _md(value) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_register(root: Path, output: Path, selected_run_id: str | None = None) -> dict:
    """Write complete local run/build inventory and a readable artifact guide."""
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    runs, artifacts, builds, seen = [], [], [], set()
    run_root = root / "artifacts/runs"
    for directory in sorted(run_root.iterdir()) if run_root.is_dir() else []:
        if not directory.is_dir():
            continue
        entry = _run_entry(directory, root, selected_run_id)
        runs.append(entry)
        record = _json(directory / "run_record.json")
        saved_hashes = record.get("artifact_sha256", {})
        files = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
        files.update(saved_hashes)
        for relative in sorted(files):
            path = directory / relative
            if path.name in REGISTER_FILES or not path.resolve().is_relative_to(directory.resolve()):
                continue
            artifacts.append(_artifact(path, root, entry["run_id"], entry["command"], saved_hashes.get(relative),
                                       mutable=directory.name == selected_run_id and relative == "run_record.json"))
            seen.add(path.resolve())
    historical = root / "report/historical"
    manifest = _json(historical / "source_manifest.json")
    if manifest:
        runs.append({"run_id": "supplied_historical_pilot", "status": "historical summary available", "role": "historical",
                     "record_path": _relative(historical / "source_manifest.json", root), "research_question": QUESTION,
                     "parent_run": "not recorded", "intended_change": "Preserved pre-integration chronological pilot",
                     "dataset_sha256": "unavailable", "code_commit": "unavailable", "configuration": {}, "seed": "not recorded",
                     "row_membership": {"files": [], "summary": {}}, "fit_evaluation_dates": "See supplied archive; not reconstructed",
                     "model_settings": "not reconstructed", "metric_units": "daily-volatility percentage points",
                     "results": {"artifact": "report/historical/pilot_validation_metrics.csv"},
                     "interpretation": "Historical sample differs from pooled and temporal development rows.",
                     "limitations": ["Summary table is preserved; raw run membership/predictions are not reconstructed."],
                     "decision": "Retain historical context", "evidence_missing": ["Complete original run record and observation-level evidence"],
                     "source_manifest": manifest})
    reference = _json(historical / "handoff_reference.json")
    if reference:
        runs.append({"run_id": "separate_chatgpt_pooled_reference", "status": "unavailable exact reproduction" if not reference.get("archive_available") else "reference only",
                     "role": "missing reference", "record_path": _relative(historical / "handoff_reference.json", root),
                     "research_question": QUESTION, "parent_run": "not recorded", "intended_change": "Separate reported pooled analysis",
                     "dataset_sha256": reference.get("raw_csv_sha256", "unavailable"), "code_commit": "unavailable",
                     "configuration": {}, "seed": "not independently verified", "row_membership": {"files": [], "summary": {}},
                     "fit_evaluation_dates": "not independently verified", "model_settings": "not independently verified",
                     "metric_units": "daily-volatility percentage points", "results": {"rounded_reference_only": reference.get("validation", {})},
                     "interpretation": "Rounded reference values are not full-precision executable evidence.",
                     "limitations": ["Different snapshot; cannot reconstruct missing predictions from rounded metrics."],
                     "decision": "Retain disclosure; no invented reproduction", "evidence_missing": ["SPY_EDA_Research_Package.zip and its raw snapshot/predictions"] if not reference.get("archive_available") else []})
        missing_archive = root / "artifacts/source_materials/SPY_EDA_Research_Package.zip"
        if not missing_archive.exists():
            artifacts.append(_artifact(missing_archive, root, "separate_chatgpt_pooled_reference", "external acquisition; unavailable"))
    for folder in (root / "data/raw", root / "report", root / "artifacts/source_materials", root / "output/pdf"):
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.resolve() in seen or path.name in REGISTER_FILES:
                continue
            run_id, command = "shared source", "see acquisition/source manifest"
            if folder == root / "output/pdf":
                parent = path.parent
                while parent != folder and parent.is_relative_to(folder):
                    build_record = parent / "build_record.json"
                    if build_record.exists():
                        record = _json(build_record)
                        run_id = record.get("run_id", "unavailable")
                        command = record.get("compiler_command", "build prepared; compiler command not recorded")
                        if path == build_record:
                            builds.append({"build_id": parent.name, "record_path": _relative(path, root),
                                           "run_id": run_id, "status": record.get("status", "unavailable"),
                                           "report_date": record.get("report_date"), "visual_review": record.get("visual_review", "not recorded"),
                                           "dated_pdf": record.get("dated_pdf"), "compiler_command": command})
                        break
                    parent = parent.parent
            artifacts.append(_artifact(path, root, run_id, command))
            seen.add(path.resolve())
    result = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "selected_run_id": selected_run_id, "runs": runs, "builds": builds,
              "limitations": ["Unknown historical intent, commits and missing outputs are labeled unavailable, never invented.",
                              "Reserved matrices are inventoried without opening their contents; historical recorded hashes are not revalidated.",
                              "Mutable selected run-record and register self-hashes are omitted to avoid circular provenance.",
                              "Paths describe locally available evidence, not guaranteed public/downloadable repository files."],
              "test_outcomes_read": False}
    register_path = output / "experiment_register.json"
    register_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    register_lines = ["# Experiment register", "", "All discoverable experiment directories are retained. Unknown intent is not reconstructed.", "",
                      "| Run | Status / role | Intended change | Interpretation / decision | Missing evidence |",
                      "| --- | --- | --- | --- | --- |"]
    for entry in runs:
        register_lines.append("| " + " | ".join(_md(value) for value in (
            entry["run_id"], f"{entry['status']} / {entry['role']}", entry["intended_change"],
            entry["interpretation"] + " " + entry["decision"], "; ".join(entry["evidence_missing"]) or "none recorded")) + " |")
    register_lines += ["", "Complete configuration, membership summaries, scores and limitations appear in experiment_register.json.",
                       "", "## Report builds", "", "| Build | Run | Status | Visual review |", "| --- | --- | --- | --- |"]
    for build in builds:
        register_lines.append("| " + " | ".join(_md(build[key]) for key in ("build_id", "run_id", "status", "visual_review")) + " |")
    (output / "experiment_register.md").write_text("\n".join(register_lines) + "\n", encoding="utf-8")
    fields = ["path", "run_id", "command", "category", "data_subset", "units", "purpose", "interpretation", "limitations", "availability", "sha256", "hash_status"]
    with (output / "artifact_index.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(artifacts)
    guide = ["# Local artifact index", "", "Exact paths are relative to the repository. Missing and reserved files are explicitly labeled.", "",
             "| Path | Producing run / command | Subset and units | Purpose and interpretation | Availability / limitations |",
             "| --- | --- | --- | --- | --- |"]
    for artifact in artifacts:
        guide.append("| " + " | ".join(_md(value) for value in (artifact["path"],
            f"{artifact['run_id']}: {artifact['command']}", f"{artifact['data_subset']}; {artifact['units']}",
            f"{artifact['purpose']}; {artifact['interpretation']}", f"{artifact['availability']}; {artifact['limitations']}")) + " |")
    (output / "artifact_index.md").write_text("\n".join(guide) + "\n", encoding="utf-8")
    summary = {"run_count": len(runs), "build_count": len(builds), "artifact_count": len(artifacts),
               "test_outcomes_read": False, "register": register_path.as_posix(),
               "readable_register": (output / "experiment_register.md").as_posix(),
               "artifact_index": (output / "artifact_index.csv").as_posix(),
               "artifact_guide": (output / "artifact_index.md").as_posix()}
    (output / "register_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
