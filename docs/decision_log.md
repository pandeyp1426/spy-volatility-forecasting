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
