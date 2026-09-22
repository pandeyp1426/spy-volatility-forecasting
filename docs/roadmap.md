# Research roadmap

Pradeep Pandey · One-credit independent study · Dr. Augustine Twumasi

| Milestone | Work and completion evidence |
| --- | --- |
| 1. Local baseline | Freeze and audit the SPY snapshot, verify alignment and leakage checks, and report daily and nonoverlapping validation MAE/RMSE. Record actual status in [phase1_progress.md](phase1_progress.md). |
| 2. Linear regression | Fit on the purged training period using the same five features, target, and units. Fit any preprocessing only on training data. Compare validation predictions with the historical baseline on identical dates. |
| 3. Random forest | Fit a small, understandable model and a limited, documented set of candidate settings. Choose settings using validation performance; preserve the final test. Save seeds, parameters, and fitted models. |
| 4. Freeze the comparison | Discuss validation findings with Dr. Twumasi. Finalize features, settings, sampling protocol, and metrics before looking at final-test performance. Use time-ordered, purged folds inside training if additional tuning is necessary. |
| 5. One final evaluation | Evaluate the frozen baseline, regression, and random forest together once on the reserved 2024–2025 test. Report counts and both daily and nonoverlapping errors. Report limitations and failures as well as improvements. |
| 6. S3 and Python tools | After the local experiment is stable, store approved datasets, manifests, and versioned results in S3. Expose narrowly scoped Python tools that return forecasts and metrics with dates, units, model identifiers, and snapshot references. Document provider terms and AWS costs before deployment. |
| 7. Bedrock explanation interface | Add an Amazon Bedrock conversational interface that explains numbers retrieved from those Python tools. Keep calculation in Python and cite the retrieved experiment. Test explanations against saved outputs before demonstrating the interface. |

For the interface evaluation, ask fixed questions covering forecast date, forecast horizon, daily versus annualized units, model comparisons, snapshot provenance, unavailable dates, failed retrievals, and the difference between a forecast and an observed target. Check every numerical claim against tool results. The interface should state when data is unavailable and must not invent metrics or recompute them in prose.

Keep the study small: agree on dates and the forecast definition first, add two comparison models next, and treat AWS integration as a later milestone. Any change after final-test inspection needs to be identified as exploratory and cannot reuse that test as an untouched confirmation set.
