# Research decisions

## 2026-10-23 — integrate the pooled experiment

- Preserved the chronological pilot, config, raw cached snapshot and previous artifacts.
- Retained after-close forecasts, five explicit predictors, decimal units, sample SD (`ddof=1`), and the five future-session response. Legacy `target` maps explicitly to `future_volatility_5d`.
- Added `pooled_random` as a separate configuration using one `default_rng(42).permutation(N)`, floor 70%, floor 15%, then remainder. This supersedes the October 14 report's proposed two-call `train_test_split`, which would yield different membership.
- Kept Ridge, Random Forest and gradient boosting settings fixed as stated in the handoff; scaling fits only training data. No tuning search or seed search.
- The requested newer EDA ZIP was not available; the user confirmed they did not think they had it. Used the existing immutable yfinance snapshot, not a fresh download or reconstructed archive. Exact reproduction of the missing package is unavailable.
- Preserved the supplied October 14 source and progress ZIP plus handoff under `artifacts/source_materials/`, with SHA-256 manifest. The extracted historical metrics in `report/historical/` retain their archive hash and are labeled archived results.
- Documented both shared target returns and held-out outcome returns entering later training features. Every validation and reserved test target overlaps training outcomes in this realized split. No claim of independent or future-only evaluation.
- EDA uses training rows only; lag pairs use original session positions, with pair counts. No iid significance claims.
- Maintained `report/main.tex` and `references.bib` as the cumulative report source. Numeric tables and figures are copied from a named verified run into a preserved build bundle; dated/current PDFs have the same bytes. No scheduled job, publication or test scoring was added.
- Temporal robustness remains proposed. Exact cutoffs, evaluation dates, allowed row roles, fitting schedule and label-availability purge must be agreed before execution; reserved pooled rows cannot silently be repurposed.

## Reconciliation notes

The original snapshot has 2,807 prices, hash `2e65e0a45ec8e6bc81339f2fe3f07a3069c905f8e613e7eda723cb96121e16bf`, acquired via yfinance on 2026-09-22 UTC. The handoff describes a different Yahoo chart-endpoint JSON/CSV snapshot. A different CSV schema alone changes hashes; without the missing bytes and version record, data revisions and environment effects cannot be separated.

The current snapshot produces the same eligible/split counts as the handoff. Baseline and Ridge errors are very close to its rounded references; forest and boosting differ slightly. The model execution contains no reference-score constants. Report-only reference values live in `report/historical/handoff_reference.json` and are clearly identified as rounded quoted values.

The old chronological pilot used OLS and `max_features=1.0` for the forest; the new experiment uses Ridge and `max_features="sqrt"`. These experiments have different validation samples, so their score levels cannot be directly ranked.

## Weekly update rule

Preserve the research question and definitions. Update relevant sections as evidence changes, retain decisions here, distinguish completed experiments from proposals, and use the same cumulative source. Keep final test evaluation outside routine analysis and report commands.

## 2026-10-24 — verified cumulative edition

Final designated pooled run: `20261024T163643_pooled_b62233b3`. Full suite: 70 passing tests; final focused checks: 15 passing tests. Six core outputs are byte-identical across repeated offline runs. The seven-page cumulative report was compiled, rendered, and visually reviewed page by page; dated/current PDFs match. The final test remains unscored. Evidence: `artifacts/integration_verification_2026-10-24.json`.

## 2026-10-24 — preregistered retrospective temporal development phase

Recorded before computing this phase's scores. Starting checkout: `7a8c55aa19b85782ecec7786438cc95e150a1819`, clean. The user explicitly authorized implementation of `SPY_Codex_Next_Phase.md`. The following default is adopted as a project choice from that task, not a protocol attributed to the supervisor.

- Preserve the exact saved pooled map in run `20261024T163643_pooled_b62233b3`, its raw snapshot, and all previous results. Read the map's identities only to remove reserved test rows from every new fitting, tuning and evaluation sample. Never open the reserved response matrix.
- Name: `annual_expanding_development_2020_2025`. Train from 2015; outer evaluation years 2020–2025. Fit once per year at the last actual trading-session close in the preceding year. Retain training rows only when their target end is on/before that cutoff; evaluate eligible development forecast dates in the stated year and strictly after the cutoff. The final fold ends at the last eligible 2025 date. Models stay fixed within each year; later fits may use earlier evaluation rows once their labels are known.
- Run the existing fixed models first. Then compare the prespecified 5-session volatility forecast as well as the original 20-session benchmark. Never select the easier benchmark after seeing results.
- For nested tuning, use the three most recent complete calendar years inside each outer training period (2017–2019 for outer 2020). Inner training expands, uses the same label-availability rule, and inner evaluation outcomes must be fully known by the outer cutoff. Reserved IDs and all outer evaluation rows are excluded from selection.
- Primary selection metric: RMSE over concatenated inner predictions. Tie-break: lowest candidate ID in the frozen ordered grid, without rounding scores. Candidate order is Ridge alpha ascending, then forest depth/leaf lexicographic, then boosting trees/learning-rate/depth lexicographic. Select separately within each family.
- Frozen grid: Ridge alpha `[0.01,0.1,1,10,100]`; forest depth `[3,5,8]` by minimum leaf `[5,10,20]`, 200 trees and sqrt features; boosting trees `[100,200]` by learning rate `[0.03,0.05]` by depth `[1,2,3]`, minimum leaf 10 and squared-error loss. Seeds 42; forest one job. This is 26 candidates per outer fold and 3 inner refits per candidate. Save every candidate, score, failure and time; no grid enlargement follows these results.
- Prespecified ablation: fixed settings with volatility 5/10/20 only versus the full five predictors, on exactly the same outer rows. Do not combine favorable tuning/ablation choices into a post-hoc supposedly independent winner.
- Threshold for tail diagnostics: each fit's training-target 95th percentile; high group is observed target >= threshold. This is ex-post diagnosis, not an operational forecast-time rule. Empty groups remain unavailable. Fitted training errors remain descriptive.
- Report MAE/RMSE/bias/N and MSE from full-precision errors with correct units; aggregate RMSE from all squared errors, never an unweighted mean of annual RMSE. Preserve negative results and tail failures. No ordinary iid significance claims.
- This phase is retrospective robustness on reused history, not a pristine test. ID exclusion cannot undo shared returns or earlier exposure to later years. A separately frozen future-period evaluation remains deferred; no new download, final test scoring or slides are authorized here.

## 2026-10-27 — completed temporal edition and verification

- Executed offline run `20261027T001114_temporal_4bf4a071` against the preserved snapshot and pooled parent, with 2,346 development rows, 415 excluded pooled reserved identities, and 1,272 common outer evaluation observations. The 26-candidate grid produced 156 outer-family candidate evaluations, 468 inner fits, 66 outer model/comparator records and no fit failures.
- Fixed Ridge reduced aggregate RMSE against both window benchmarks; fixed forest and boosting did not. Tuning produced small aggregate RMSE reductions for all three, but Ridge and boosting had worse high-group RMSE. The 5-session comparator beat Ridge on high-group RMSE. The named run retains annual, tail, fitted-gap, ablation and negative results.
- The separately archived calculation audit `artifacts/next_phase_verification_2026-10-27.json` independently checked complete folds, training-label timing, candidate coverage and selection, model settings, feature allowlists, scaler means/scales, benchmark gains and full-precision metrics; passed with no reserved responses read. A second independent diagnostic check verified 629 saved calculations. The registry correction and its original files are preserved in `artifacts/register_revision_2026-10-26/`; no analytical outputs were changed by that revision.
- The complete suite passed **128 tests**, then the final report-focused suite passed **22 tests** after the report update. The representative real offline run, not a mocked run, completed and was verified. The cumulative 27 October edition compiled and all 18 rendered pages were visually inspected; the dated and current PDF SHA-256 values match. Build provenance and rendered pages are retained in `output/pdf/builds/2026-10-27_20261024T163643_pooled_b62233b3_20261027T052810994815/`.
- The earlier chronological pilot's 2024–2025 output remains unscored, but permitted development rows from those calendar years were used in this new analysis. They are therefore not an untouched future period for the project. The 415 saved pooled test identities remain excluded and unscored. Future-period evaluation and dependence-aware uncertainty analysis are proposed, not completed.
