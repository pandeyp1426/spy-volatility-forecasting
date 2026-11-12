# Temporal evaluation sensitivity protocol

Recorded on 10 November 2026 before computing this phase's scores. This implements the two historical sensitivity checks proposed in section 7.3 of the supplied report. It is a development analysis chosen after reviewing the existing results, not a prospective preregistration or a supervisor-approved new test protocol.

## Fixed source and question

Use only the verified saved outer predictions in temporal run `20261027T001114_temporal_4bf4a071`. Preserve every original model, fitting cutoff, selected parameter and training-derived tail threshold. Do rankings and error differences persist when annual target spillover or overlapping evaluation outcome windows are removed?

No model fitting, candidate selection, data acquisition or reserved-response loading is part of this command. The original 415 pooled reserved identities remain excluded. Existing run directories are read only; write all new evidence into a fresh run.

## Subsets fixed before scoring

1. `original`: all 1,272 common outer evaluation identities, for arithmetic reconciliation.
2. `within_year`: retain a forecast only when both `target_start` and `target_end` fall in its forecast calendar year. This changes the scoring sample, not the fitted model or its training history.
3. `modulo_0` through `modulo_4`: retain `session_number % 5 == residue`, using the original frozen snapshot's session origin globally. Do not renumber after removing reserved rows, reset at annual boundaries, or select every fifth retained row.
4. `within_year_modulo_0` through `within_year_modulo_4`: combine the two restrictions.

Residue 0 is the primary nonoverlapping check, chosen without computing these subset scores. Report all five residues, including unfavorable results; none is selected as a winner. Each residue must have nonintersecting actual target intervals across the complete sample, including annual boundaries. Residues partition their parent sample exactly but are not independent replications of one another.

## Measures and evidence

Apply identical identity masks to all eleven model/variant groups. Report aggregate and annual MAE, RMSE, MSE, signed bias and N, plus both training-threshold tail groups. Keep each original fold/model/group in the table even if a restriction leaves it empty; empty scores are unavailable, never zero. Recompute aggregate RMSE from all retained squared errors. Compare every model with both historical window benchmarks on identical rows; positive relative improvements and negative model-minus-benchmark differences indicate lower error. Relative improvement is unavailable when the benchmark error is zero.

Save the frozen configuration, input hashes, copied source predictions and identity-only exclusions, inclusion/exclusion masks for every subset, sample/overlap audits, full-precision tables, execution source and environment, and an independent calculation verification. Verify original scores against the saved predictions, disjoint/exhaustive residue membership and zero target-window intersection for each modulo subset.

## Interpretation and subsequent work

Containment removes shared outcome returns across annual evaluation boundaries; within-year overlap remains. Modulo sampling removes overlap among scored future-return windows, but fitted models, predictor windows, volatility persistence and prior historical exploration remain shared. Neither restriction creates independent observations or an untouched test. Changes between subsets also reflect different sample composition. No significance claim, confidence interval, prediction interval or trading conclusion follows from these checks.

Dependence-aware uncertainty and a separately frozen later-period evaluation remain subsequent work. These sensitivity results should inform their design without silently redefining a held-out period.
