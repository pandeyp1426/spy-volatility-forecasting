"""Run-derived report content; no fitting, acquisition, or reserved matrix reads."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

NAMES = {"baseline": "20-session baseline", "baseline_5": "5-session comparator", "ridge": "Ridge", "random_forest": "Random Forest", "gradient_boosting": "Gradient boosting"}
LEARNED = ("ridge", "random_forest", "gradient_boosting")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tex(value):
    mapping = {"\\": r"\textbackslash{}", "_": r"\_", "%": r"\%", "&": r"\&", "#": r"\#", "$": r"\$", "{": r"\{", "}": r"\}", "^": r"\textasciicircum{}", "~": r"\textasciitilde{}"}
    return "".join(mapping.get(c, c) for c in str(value))


def write(path, content):
    Path(path).write_text(content + "\n", encoding="utf-8")


def table(path, headers, rows, alignment, long=False):
    env = "longtable" if long else "tabular"
    head = " & ".join(headers) + r" \\"
    lines = [r"\begin{"+env+r"}{@{}"+alignment+r"@{}}", r"\toprule", head, r"\midrule"]
    if long:
        lines += [r"\endfirsthead", r"\toprule", head, r"\midrule", r"\endhead"]
    lines += [" & ".join(map(str, row))+r" \\" for row in rows]
    lines += [r"\bottomrule", r"\end{"+env+"}"]
    write(path, "\n".join(lines))


def validate_pooled_narrative(record, model, summary, audit):
    """Reject inputs that contradict deliberately fixed scientific prose."""
    cfg = record["config"]
    expected = {"seed": 42, "train_fraction": .70, "validation_fraction": .15}
    if any(cfg["split"].get(k) != v for k, v in expected.items()):
        raise ValueError("Pooled report narrative requires seed 42 and 70/15/15 proportions")
    if cfg.get("research") != {"windows": [5, 10, 20], "horizon": 5, "momentum_window": 5, "baseline_window": 20}:
        raise ValueError("Pooled report narrative requires the agreed windows and target")
    if cfg["data"].get("ticker") != "SPY" or cfg["data"].get("calendar") != "NYSE":
        raise ValueError("Pooled report narrative requires SPY and NYSE sessions")
    expected_parameters = {
        "ridge": {"alpha": 1.0},
        "random_forest": {"n_estimators": 200, "max_depth": 5, "min_samples_leaf": 10, "max_features": "sqrt", "random_state": 42, "n_jobs": 1},
        "gradient_boosting": {"n_estimators": 200, "max_depth": 2, "learning_rate": .03, "min_samples_leaf": 10, "loss": "squared_error", "random_state": 42},
    }
    if model.get("model_parameters") != expected_parameters or model.get("prediction_floor") != 0:
        raise ValueError("Pooled report fixed model specifications differ from selected run")
    if (model.get("feature_columns") != ["log_return", "volatility_5", "volatility_10", "volatility_20", "momentum_5"]
            or model.get("response_column") != "future_volatility_5d"
            or model.get("test_scored") is not False
            or model.get("ridge_scaler", {}).get("fit_partition") != "train"):
        raise ValueError("Pooled report model inputs, training-only scaling or test guard differ")
    if not audit.get("passed") or not audit.get("raw_fields", {}).get("passed"):
        raise ValueError("Pooled report requires passed source quality audit")
    if not summary.get("row_ids_disjoint") or not summary.get("exhaustive"):
        raise ValueError("Pooled report requires verified split identities")


def pooled_content(run_dir, generated, metrics, eda, pearson, spearman, lag, summary, audit):
    """Write claims from the selected evidence, never hardcode model ranking."""
    improvements = [NAMES[n] for n in LEARNED if metrics.loc[n, "mae_pp"] < metrics.loc["baseline", "mae_pp"] and metrics.loc[n, "rmse_pp"] < metrics.loc["baseline", "rmse_pp"]]
    best_mae, best_rmse = metrics.mae_pp.idxmin(), metrics.rmse_pp.idxmin()
    write(generated/"pooled_interpretation.tex", tex(f"On this pooled validation sample, {len(improvements)} of the three learned models improve both MAE and RMSE over the 20-session baseline. Lowest MAE: {NAMES[best_mae]}; lowest RMSE: {NAMES[best_rmse]}. ") + "This dependent pooled sample does not establish a final winner or future-only generalization.")
    p = pd.read_csv(run_dir/"validation_predictions.csv")
    target = p["future_volatility_5d"]
    threshold = float(eda["target_summary"]["95%"])
    hi = target >= threshold
    rows = []
    for name in NAMES:
        if name not in p:
            continue
        e = 100*(p.loc[hi,name] - target[hi])
        rows.append([NAMES[name], len(e), f"{e.abs().mean():.4f}" if len(e) else "--", f"{np.sqrt((e**2).mean()):.4f}" if len(e) else "--", f"{e.mean():+.4f}" if len(e) else "--"])
    table(generated/"high_volatility.tex", ["Model", "$N$", "MAE (pp)", "RMSE (pp)", "Bias (pp)"], rows, "lrrrr")
    under = [NAMES[n] for n in LEARNED if (p.loc[hi,n] - target[hi]).mean() < 0]
    write(generated/"pooled_tail_interpretation.tex", tex(f"The training-derived 95th-percentile threshold leaves {int(hi.sum())} high-volatility validation observations. {len(under)} of the three learned models have negative average error in this group. ") + "This is an ex-post grouping by the realized target, not an observable forecasting rule. Small group size and overlapping outcomes limit certainty.")
    construction = summary["construction"]
    rows = [["Raw prices / expected sessions", f"{audit['row_count']} / {audit['expected_session_count']}"], ["Duplicate / missing expected sessions", f"{len(audit['duplicate_dates'])} / {len(audit['missing_sessions'])}"], ["Missing / nonfinite / nonpositive prices", f"{len(audit['missing_price_dates'])} / {len(audit['nonfinite_price_dates'])} / {len(audit['nonpositive_price_dates'])}"], ["Initial incomplete history", construction["initial_rows_without_complete_history"]], ["Final incomplete future target", construction["final_rows_without_complete_target"]], ["Complete rows outside forecast period", construction["complete_rows_outside_forecast_period"]], ["Eligible forecast rows", summary["n_eligible"]]]
    table(generated/"cleaning.tex", ["Audit / exclusion", "Count"], rows, "lr")
    vals = [pearson.loc[c,"future_volatility_5d"] for c in ("volatility_5","volatility_10","volatility_20")]
    ranks = [spearman.loc[c,"future_volatility_5d"] for c in ("volatility_5","volatility_10","volatility_20")]
    write(generated/"association_interpretation.tex", tex(f"Do historical windows share information about future variability? In the saved training subset, Pearson feature-target correlations across the three volatility windows range from {min(vals):.3f} to {max(vals):.3f}; Spearman correlations range from {min(ranks):.3f} to {max(ranks):.3f}. ") + "Pearson summarizes linear association and is sensitive to extreme observations; Spearman summarizes monotonic rank association. Their difference is evidence about the form and tail sensitivity of the relationship, not a formal test of nonlinearity. " + tex(f"The 5- and 10-session predictors correlate at {pearson.loc['volatility_5','volatility_10']:.3f}, consistent with their overlapping inputs. ") + "Retain the agreed predictors and assess their joint contribution through the prespecified ablation; high correlation alone does not require deletion.")
    l1 = lag[lag.lag_sessions == 1].set_index("variable")
    write(generated/"dependence_interpretation.tex", tex(f"Does return direction persist like return magnitude? At one original-session lag, training-pair correlation is {l1.loc['log_return','pearson']:.3f} for returns, {l1.loc['absolute_log_return','pearson']:.3f} for absolute returns, and {l1.loc['future_volatility_5d','pearson']:.3f} for the target; each uses {int(l1.loc['log_return','pair_count'])} pairs. ") + "Magnitude and volatility dependence motivate a forecasting comparison, while overlapping five-return targets mechanically contribute persistence. Pair counts vary by lag; none is an iid significance claim.")


def validate_development(run_dir, pooled_dir, pooled_record):
    run_dir = Path(run_dir)
    record = json.loads((run_dir/"run_record.json").read_text(encoding="utf-8"))
    if (record.get("status") != "success" or record.get("experiment") != "retrospective_temporal"
            or record.get("final_test_evaluated") is not False
            or record.get("reserved_rows_excluded") is not True
            or record.get("calculation_verification_passed") is not True):
        raise ValueError("Development report requires verified retrospective temporal run with reserved rows excluded and test unscored")
    if (record.get("source_pooled_run_id") != pooled_record["run_id"]
            or record.get("source_pooled_run_record_sha256") != sha(Path(pooled_dir)/"run_record.json")
            or record.get("snapshot_sha256") != pooled_record["snapshot_sha256"]):
        raise ValueError("Development report pooled source identity or snapshot does not match selected run")
    from .temporal import validate_temporal_config
    validate_temporal_config(record.get("config", {}))
    protocol_path = run_dir/"temporal_protocol.json"
    if not protocol_path.is_file():
        raise ValueError("Development report temporal protocol is unavailable")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    effective = {key: value for key, value in protocol.items() if key != "reserved_row_ids"}
    if effective != record["config"]:
        raise ValueError("Development report saved protocol differs from run configuration")
    summary_path = run_dir/"temporal_summary.json"
    if not summary_path.is_file():
        raise ValueError("Development report temporal summary is unavailable")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    protocol_hash = hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (summary.get("status") != "complete" or summary.get("test_scored") is not False
            or summary.get("protocol_sha256") != protocol_hash):
        raise ValueError("Development report requires complete unscored protocol-matched summary")
    for key in ("outer_years", "selection_metric", "tie_break", "high_volatility_quantile"):
        if summary.get(key) != record["config"]["temporal"][key]:
            raise ValueError(f"Development report summary differs from protocol: {key}")
    # Hash only named in-run artifacts: no reserved response matrix is opened.
    for name, expected in record.get("artifact_sha256", {}).items():
        if (Path(name).is_absolute() or ".." in Path(name).parts
                or not (run_dir/name).resolve().is_relative_to(run_dir.resolve())):
            raise ValueError(f"Development artifact path leaves run directory: {name}")
        if "reserved" in Path(name).parts:
            continue
        if not (run_dir/name).is_file() or sha(run_dir/name) != expected:
            raise ValueError(f"Development artifact hash mismatch: {name}")
    return record


def absent_development(generated):
    write(generated/"stage.tex", "This edition preserves the chronological pilot and the verified pooled comparison. No temporal development run was selected for this build. The reserved test remains unscored.")
    for name in ("development_methods", "development_results", "development_discussion", "development_appendix"):
        write(generated/f"{name}.tex", "")
    write(generated/"development_conclusion.tex", "Temporal robustness, controlled tuning and ablation are not included in this build. Their completion must be established by a named verified development run before conclusions are extended.")


def development_content(run_dir, generated, build, record):
    """Generate temporal tables/claims from a hash-checked completed development run."""
    from .temporal import validate_temporal_config
    from .diagnostics import error_metrics, validate_predictions
    run_dir = Path(run_dir)
    protocol = json.loads((run_dir/"temporal_protocol.json").read_text(encoding="utf-8"))
    validate_temporal_config(protocol)
    required = ["temporal_protocol.json", "temporal_summary.json", "temporal_predictions.csv", "temporal_folds.csv", "chosen_parameters.json", "search_results.csv", "calculation_verification.json"]
    required += [f"tables/diagnostic_{scope}_{kind}.csv" for scope in ("pooled", "temporal") for kind in ("aggregate", "year", "tail", "gap", "comparisons")]
    required += [f"figures/diagnostic_{scope}_{kind}.pdf" for scope in ("pooled", "temporal_fixed") for kind in ("scatter", "history", "errors")]
    for name in required:
        if name not in record.get("artifact_sha256", {}) or not (run_dir/name).is_file():
            raise ValueError(f"Development report required artifact unavailable or unhashed: {name}")
    predictions = validate_predictions(pd.read_csv(run_dir/"temporal_predictions.csv"))
    aggregate = pd.read_csv(run_dir/"tables/diagnostic_temporal_aggregate.csv")
    for (variant, model), frame in predictions.groupby(["variant", "model"]):
        saved = aggregate[(aggregate.variant == variant) & (aggregate.model == model)]
        if len(saved) != 1:
            raise ValueError("Development metrics do not uniquely identify each model variant")
        computed = error_metrics(frame)
        for key, value in computed.items():
            if not np.isclose(saved.iloc[0][key], value, rtol=1e-10, atol=1e-12):
                raise ValueError(f"Development metric arithmetic differs: {variant}/{model}/{key}")
    summary = json.loads((run_dir/"temporal_summary.json").read_text())
    folds = pd.read_csv(run_dir/"temporal_folds.csv").query("level == 'outer'")
    year = pd.read_csv(run_dir/"tables/diagnostic_temporal_year.csv")
    tail = pd.read_csv(run_dir/"tables/diagnostic_temporal_tail.csv")
    tail = tail[(tail.aggregation == "aggregate") & (tail.tail_group == "at_or_above_training_q95")]
    gaps = pd.read_csv(run_dir/"tables/diagnostic_temporal_gap.csv")
    gaps = gaps[gaps.aggregation == "aggregate"]
    comps = pd.read_csv(run_dir/"tables/diagnostic_temporal_comparisons.csv")
    lookup = aggregate.set_index(["variant", "model"])
    def score(variant, model, key="rmse_pp"):
        return float(lookup.loc[(variant,model),key])
    def fmt(value, signed=False):
        return "--" if pd.isna(value) else f"{value:+.4f}" if signed else f"{value:.4f}"
    def metric_rows(frame, include_variant=False):
        return [[(str(r.variant).replace("_", " ")+": " if include_variant else "")+NAMES[r.model], int(r.n_forecasts), fmt(r.mae_pp), fmt(r.rmse_pp), fmt(r.bias_pp, True)] for r in frame.itertuples()]
    for name in required:
        if name.startswith("figures/"):
            shutil.copy2(run_dir/name, build/name)
    write(generated/"stage.tex", tex(f"This edition adds a completed retrospective temporal development comparison, controlled nested tuning, a 5-session comparator, and a fixed feature ablation to the preserved pooled and chronological work. Temporal run: {record['run_id']}. ") + "All reserved pooled row identities remain excluded from new fitting, selection and scored diagnostics. The final test remains unscored.")
    table(generated/"temporal_folds.tex", ["Year", "Fit cutoff", "Train $N$", "Eval. $N$", "Boundary exclusions"], [[int(r.outer_fold), r.fit_cutoff, int(r.n_train), int(r.n_evaluation), int(r.n_boundary_excluded)] for r in folds.itertuples()], "llrrr")
    methods = r"""\subsection{Retrospective temporal development protocol}
The temporal experiment is a separately named robustness check, not a replacement
for the pooled design. All saved pooled reserved row IDs are excluded. Initial
training begins in 2015. For each annual evaluation year 2020--2025, the model is
fitted once after the last observed session of the previous year and remains fixed
throughout the year. Training labels must satisfy $\mathrm{target\_end}\le c$;
evaluation forecast dates must satisfy $t>c$, where $c$ is the actual fit cutoff.
Later folds may reuse earlier evaluation rows once their labels have become available.
\begin{center}\input{generated/temporal_folds.tex}\end{center}
The table identifies the information available at each fit and the changing sample
sizes. Boundary exclusions are based on dates, not a compressed row-count gap.
Excluding reserved identities preserves their formal role but does not undo the
underlying-return overlap or previous use of this historical period. This is
retrospective development evidence, not a pristine final or prospective test.

\subsection{Controlled improvement experiments}
The fixed specifications are evaluated first. Next, the unfitted 5-session
comparator predicts $\hat y_t=\mathrm{volatility\_5}_t$; the original 20-session
baseline remains in every comparison. The comparator tests whether a faster
historical window already accounts for an apparent machine-learning gain.

Nested selection uses the three latest complete calendar years inside each outer
training period as expanding annual validation folds (2017--2019 for outer 2020).
Every inner label must be observable by its own fit or the outer cutoff as
appropriate. Neither outer outcomes nor reserved rows select transformations or
parameters. The primary selection metric is RMSE on concatenated inner predictions;
exact ties use the lower preassigned candidate ID. Label availability, rather than a generic row-count gap, is enforced \cite{temporal_api}. This choice and the following
26-candidate grid were frozen before scoring, not attributed to the professor.
\begin{tabularx}{\linewidth}{@{}lX@{}}\toprule
Family & Search space\\\midrule
Ridge & $\alpha\in\{0.01,0.1,1,10,100\}$; training-only scaling.\\
Random Forest & Depth $\{3,5,8\}\times$ minimum leaf $\{5,10,20\}$; other fixed settings retained.\\
Gradient boosting & Trees $\{100,200\}\times$ learning rate $\{0.03,0.05\}\times$ depth $\{1,2,3\}$; other fixed settings retained.\\\bottomrule
\end{tabularx}
A separate fixed-setting ablation uses only the three volatility predictors.
It estimates the incremental predictive contribution of return and momentum on
the same temporal rows; it does not establish causation or combine favorable
post-hoc choices into an independent result.
"""
    write(generated/"development_methods.tex", methods)
    fixed = aggregate[(aggregate.variant == "fixed") | (aggregate.model == "baseline_5")]
    table(generated/"temporal_fixed.tex", ["Fixed model / comparator", "$N$", "MAE (pp)", "RMSE (pp)", "Bias (pp)"], metric_rows(fixed), "lrrrr")
    changed = aggregate[aggregate.variant.isin(["tuned", "volatility_only"])]
    table(generated/"temporal_changes.tex", ["Variant and model", "$N$", "MAE (pp)", "RMSE (pp)", "Bias (pp)"], metric_rows(changed, True), "lrrrr")
    comp_rows = []
    for r in comps[comps.model.isin(LEARNED)].itertuples():
        comp_rows.append([r.variant.replace("_", " ")+": "+NAMES[r.model], "20" if r.benchmark == "baseline" else "5", f"{r.relative_rmse_improvement_pct:+.2f}", f"{int(r.folds_rmse_improved)}/{int(r.folds_compared)}"])
    table(generated/"temporal_comparisons.tex", ["Variant and model", "Baseline window", "RMSE gain (\\%)", "Folds improved"], comp_rows, "llrr", long=True)
    gains = []
    for model in LEARNED:
        gain = 100*(1-score("fixed",model)/score("fixed","baseline"))
        wins = comps[(comps.variant == "fixed") & (comps.model == model) & (comps.benchmark == "baseline")].iloc[0]
        gains.append(f"{NAMES[model]}: {gain:+.2f}% RMSE improvement relative to the 20-session baseline, with lower RMSE in {int(wins.folds_rmse_improved)} of {int(wins.folds_compared)} years")
    tuning = []
    ablation = []
    for model in LEARNED:
        fixed_rmse, tuned_rmse = score("fixed",model), score("tuned",model)
        annual = year[(year.model == model) & year.variant.isin(["fixed", "tuned"])].pivot(index="year", columns="variant", values="rmse_pp")
        bad = [str(int(y)) for y in annual.index[annual.tuned > annual.fixed]]
        tuning.append(f"{NAMES[model]} changes RMSE by {tuned_rmse-fixed_rmse:+.4f} pp ({100*(1-tuned_rmse/fixed_rmse):+.2f}% improvement); worse years: {', '.join(bad) or 'none'}")
        ablation.append(f"{NAMES[model]} volatility-only minus all-five RMSE: {score('volatility_only',model)-fixed_rmse:+.4f} pp")
    result = "\\subsection{Fixed temporal comparison and simple comparator}\n\\begin{center}\\input{generated/temporal_fixed.tex}\\end{center}\n"
    result += tex(f"The same {summary['n_evaluation_rows']} outer development forecasts are scored for every variant. "+". ".join(gains)+". ")
    result += "Positive relative improvement denotes lower error. Scores pool squared errors before taking the square root; annual RMSE values are not averaged. Pooled and temporal samples differ, so differences in absolute scores do not isolate one causal effect.\n"
    result += "\\subsection{Nested tuning and fixed feature ablation}\n\\begin{center}\\small\\input{generated/temporal_changes.tex}\\end{center}\n"
    result += tex(". ".join(tuning)+". ")+"A negative change in pp indicates a lower error; tuning is judged on untouched outer predictions relative to the fixed setting in the same family.\n\n"
    result += tex(". ".join(ablation)+". ")+"A positive difference favors retaining return and momentum; a negative difference favors the simpler feature set in this retrospective comparison. The full settings and annual scores remain in the appendices and saved artifacts.\n"
    write(generated/"development_results.tex", result)
    table(generated/"temporal_tail.tex", ["Variant and model", "$N$", "MAE (pp)", "RMSE (pp)", "Bias (pp)"], metric_rows(tail, True), "lrrrr")
    table(generated/"temporal_gap.tex", ["Variant and model", "Fitted RMSE", "Development RMSE", "Gap (pp)"], [[r.variant.replace("_"," ")+": "+NAMES[r.model], fmt(r.training_rmse_pp), fmt(r.development_rmse_pp), fmt(r.gap_rmse_pp,True)] for r in gaps.itertuples()], "lrrr")
    fixed_tail = tail[tail.variant == "fixed"]
    under = fixed_tail[fixed_tail.model.isin(LEARNED) & (fixed_tail.bias_pp < 0)]
    best = aggregate.loc[aggregate.rmse_pp.idxmin()]
    tail_lookup = tail.set_index(["variant","model"])
    best_tail = tail_lookup.loc[(best.variant,best.model)]
    base_tail = tail_lookup.loc[("fixed","baseline")]
    discussion = "\\subsection{What the temporal diagnostics show}\n"
    discussion += tex(f"The lowest aggregate temporal RMSE is {best.rmse_pp:.4f} pp for {best.variant.replace('_',' ')} {NAMES[best.model]}. Its high-volatility RMSE is {best_tail.rmse_pp:.4f} pp, compared with {base_tail.rmse_pp:.4f} pp for the 20-session baseline. {len(under)} of three fixed learned models underpredict the high group on average. ")
    discussion += "The high group uses the training target's 95th percentile separately in each annual fold. It is defined ex post from observed outcomes, not available at forecast time. Empty groups are shown as unavailable.\n\\begin{center}\\small\\input{generated/temporal_tail.tex}\\end{center}\n"
    discussion += "\\begin{center}\\small\\input{generated/temporal_gap.tex}\\end{center}\nFitted scores describe each training fit; they are not held-out validation. Aggregation repeats observations reused in later expanding fits, so these gaps combine overfitting and differences in periods and target distributions. A larger gap alone does not identify a cause.\n"
    discussion += "\\clearpage\n\\subsection{Temporal prediction diagnostics}\nThe identity-line scatter asks whether the models capture large observed outcomes. The date view and signed errors locate departures on actual sessions. Only the fixed comparison is displayed here; all variants have separately saved figures. Points do not connect gaps left by reserved identities. These retrospective plots support error diagnosis, not explanations based on unobserved news events.\n"
    discussion += "\\begin{center}\\includegraphics[width=0.97\\linewidth]{figures/diagnostic_temporal_fixed_scatter.pdf}\\captionof{figure}{Fixed temporal development predictions against observed volatility; diagonal denotes equality.}\\end{center}\n"
    discussion += "\\begin{center}\\includegraphics[width=0.96\\linewidth]{figures/diagnostic_temporal_fixed_history.pdf}\\captionof{figure}{Fixed temporal predictions and outcomes on actual forecast dates; no line bridges omitted observations.}\\end{center}\n"
    discussion += "\\clearpage\n\\begin{center}\\includegraphics[width=0.9\\linewidth,height=0.78\\textheight,keepaspectratio]{figures/diagnostic_temporal_fixed_errors.pdf}\\captionof{figure}{Signed error by actual date and predicted level; zero indicates no error. Negative values identify underprediction.}\\end{center}\n"
    write(generated/"development_discussion.tex", discussion)
    positive = sum(score("fixed",m) < score("fixed","baseline") for m in LEARNED)
    tuned_better = sum(score("tuned",m) < score("fixed",m) for m in LEARNED)
    write(generated/"development_conclusion.tex", tex(f"The retrospective temporal comparison supports a lower aggregate RMSE than the 20-session baseline for {positive} of the three fixed learned models. Controlled tuning reduces aggregate RMSE for {tuned_better} of the three families on exactly the same outer observations. ") + "These counts do not imply uniformly improved yearly or tail performance; the preceding tables retain adverse outcomes. The next milestone is a frozen, separately reserved future-period evaluation and a justified dependence-aware uncertainty analysis, informed by the observed tail and annual failures. No new future period has been downloaded or scored here.")
    selected = json.loads((run_dir/"chosen_parameters.json").read_text())
    choice_rows = []
    for r in selected:
        p = r["parameters"]
        settings = f"alpha={p['alpha']}" if r["model"] == "ridge" else f"depth={p['max_depth']}, leaf={p['min_samples_leaf']}" if r["model"] == "random_forest" else f"trees={p['n_estimators']}, rate={p['learning_rate']}, depth={p['max_depth']}"
        choice_rows.append([r["outer_fold"], NAMES[r["model"]], tex(settings), f"{r['inner_rmse_pp']:.4f}"])
    table(generated/"chosen_parameters.tex", ["Outer year", "Model", "Selected parameters", "Inner RMSE (pp)"], choice_rows, "lllr", long=True)
    year_rows = [[int(r.year), r.variant.replace("_"," ")+": "+NAMES[r.model], int(r.n_forecasts), fmt(r.mae_pp), fmt(r.rmse_pp), fmt(r.bias_pp,True)] for r in year.itertuples()]
    table(generated/"temporal_year.tex", ["Year", "Variant and model", "$N$", "MAE", "RMSE", "Bias"], year_rows, "llrrrr", long=True)
    appendix = "\\section{Extended development results}\n\\subsection{Relative errors on identical observations}\nPositive gains mean improvement over the named window benchmark; the fold count shows stability, not significance.\\par\n\\small\\input{generated/temporal_comparisons.tex}\\normalsize\n\\subsection{Nested selections}\nInner scores select settings within each outer training period. They are not the outer evaluation scores.\\par\n\\small\\input{generated/chosen_parameters.tex}\\normalsize\n"
    appendix += tex(f"Search recorded {summary['n_search_candidates_scored']} outer-family candidate evaluations, {summary['n_fit_failures']} fit failures and {summary['elapsed_seconds']:.1f} seconds of experiment compute time. ")+"Full candidate predictions, failures and elapsed times are saved, including candidates not selected.\n"
    appendix += "\\subsection{Annual development errors}\nAll errors below are daily-volatility pp. Small per-year samples and overlapping labels limit annual comparisons.\\par\n\\small\\input{generated/temporal_year.tex}\\normalsize\n"
    appendix += "\\clearpage\\section{Pooled validation diagnostic figures}\nThese figures reuse the named pooled validation predictions, independently of the temporal sample. The high-group table in the main results identifies underprediction; these plots locate and characterize it without introducing a causal explanation.\n"
    for kind, caption in (("scatter","Observed versus predicted pooled daily volatility; the identity line marks perfect agreement."),("history","Pooled validation predictions on actual forecast dates; gaps are not joined."),("errors","Pooled validation signed errors against actual dates and predicted levels.")):
        appendix += "\\begin{center}\\includegraphics[width=0.93\\linewidth,height=0.73\\textheight,keepaspectratio]{figures/diagnostic_pooled_"+kind+".pdf}\\captionof{figure}{"+caption+"}\\end{center}\n"
        if kind != "errors": appendix += "\\clearpage\n"
    appendix += "\\clearpage\\section{Development run provenance}\n"
    appendix += tex(f"Run {record['run_id']}; source base commit {record.get('source_git',{}).get('commit','unavailable')}; selected pooled parent {record['source_pooled_run_id']}. ")+"The build record hashes both run records and all source artifacts. Exact code hashes include executing local changes rather than treating the base commit as the complete implementation.\n"
    write(generated/"development_appendix.tex", appendix)
    return required


def register_content(run_dir, generated, build, record):
    """Retain full machine records and render a compact, complete identity register."""
    names = ("experiment_register.json", "artifact_index.csv", "register_summary.json")
    for name in names:
        if name not in record.get("artifact_sha256", {}) or not (run_dir/name).is_file():
            raise ValueError(f"Development report register artifact unavailable or unhashed: {name}")
        shutil.copy2(run_dir/name, build/name)
    register = json.loads((run_dir/"experiment_register.json").read_text())
    index = pd.read_csv(run_dir/"artifact_index.csv").fillna("unavailable")
    rows = []
    for item in register.get("runs", []):
        missing = item.get("evidence_missing", [])
        detail = str(item.get("decision", "No decision recorded"))
        if missing:
            detail += "; missing: " + (", ".join(map(str, missing)) if isinstance(missing,list) else str(missing))
        rows.append([r"\path{"+str(item["run_id"])+"}", tex(item.get("status","unavailable")), tex(detail)])
    table(generated/"register_table.tex", ["Run identity", "Status", "Decision / evidence limitations"], rows, "p{0.31\\linewidth}p{0.11\\linewidth}p{0.52\\linewidth}", long=True)
    categories = []
    for category, items in index.groupby("category", sort=True):
        statuses = items.availability.astype(str).value_counts()
        description = "; ".join(f"{key}: {count}" for key,count in statuses.items())
        sample = items.iloc[0]
        categories.append([tex(category.replace("_"," ")), len(items), tex(description), tex(str(sample.purpose))])
    table(generated/"artifact_categories.tex", ["Category", "$N$", "Availability", "Purpose"], categories, "p{0.20\\linewidth}rp{0.20\\linewidth}p{0.46\\linewidth}", long=True)
    text = r"""\section{Experiment register and artifact guide}
The complete machine register and exact artifact index are copied into this
edition's source bundle. They retain successful, failed, superseded, historical
and unavailable evidence; absence is recorded rather than filled from rounded
numbers. The compact register below lists every discovered run identity and
its decision or missing evidence. The JSON records research question, parent,
intended change, snapshot, code, configuration, seeds, membership, fit/evaluation
dates, model settings, units, results, interpretation and limitations when available.
\small\input{generated/register_table.tex}\normalsize

\subsection{How the evidence is organized}
\small\input{generated/artifact_categories.tex}\normalsize
The accompanying \code{artifact\_index.csv} lists exact local paths, producing
run/command, subset, units, purpose, interpretation, limitations, availability
and hash for each artifact. Local ignored artifacts are not claimed to be
GitHub downloads. The reproducibility command below requires the preserved
snapshot and the named pooled run; the generated development folder contains
all new predictions and diagnostics. Package or preserve the build directory
and its indexed inputs when sharing an edition.

The raw snapshot establishes the exact input version, while its quality audit
checks internal consistency. Feature tables and row maps establish definitions
and roles. Boundary and overlap audits identify information sharing. Training
EDA suggests structure without measuring forecasting skill. Saved predictions
support aggregate, year and tail scores. Search records preserve every candidate,
including failures and negative results. Verification establishes numerical and
engineering agreement, not scientific generalization. The build record links
this PDF to selected runs and source hashes.
"""
    write(generated/"register.tex", text)
