"""Training-only exploratory summaries with original-session dependence lags."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .models import FEATURE_COLUMNS, TARGET_COLUMN, model_frame

LABELS = {
    "log_return": "Current log return", "volatility_5": "5-session historical volatility",
    "volatility_10": "10-session historical volatility",
    "volatility_20": "20-session historical volatility", "momentum_5": "5-session momentum",
    TARGET_COLUMN: "Future 5-session daily volatility", "absolute_log_return": "Absolute log return",
}
DEPENDENCE_COLUMNS = ("log_return", "absolute_log_return", "volatility_20", TARGET_COLUMN)


def session_lag_correlations(
    train: pd.DataFrame, lags: tuple[int, ...] = tuple(range(1, 21)) + (40, 60),
) -> pd.DataFrame:
    """Correlate training pairs separated by lags in original trading sessions.

    Both endpoints must be training rows. Missing sampled sessions stay
    missing: the compressed training row order is never used as a clock.
    Pair counts are descriptive and do not imply independent observations.
    """
    frame = model_frame(train)
    if "session_number" not in train:
        raise ValueError("Original session_number is required for training dependence diagnostics.")
    sessions = train["session_number"].to_numpy(dtype=float)
    if (not np.isfinite(sessions).all() or (sessions < 0).any()
            or (sessions != np.floor(sessions)).any() or (np.diff(sessions) <= 0).any()):
        raise ValueError("session_number must contain strictly increasing, nonnegative integers.")
    if not lags or any(isinstance(lag, bool) or not isinstance(lag, (int, np.integer)) or lag < 1
                       for lag in lags) or len(set(lags)) != len(lags):
        raise ValueError("lags must contain distinct positive integers in original sessions.")
    frame["absolute_log_return"] = frame["log_return"].abs()
    frame.index = pd.Index(sessions.astype(np.int64), name="session_number")
    rows = []
    for variable in DEPENDENCE_COLUMNS:
        series = frame[variable]
        for lag in lags:
            lagged = series.copy()
            lagged.index = lagged.index + lag
            pairs = pd.concat([series.rename("current"), lagged.rename("lagged")], axis=1).dropna()
            correlation = float("nan")
            if len(pairs) >= 2 and pairs["current"].nunique() > 1 and pairs["lagged"].nunique() > 1:
                correlation = float(pairs["current"].corr(pairs["lagged"]))
            rows.append({"variable": variable, "lag_sessions": int(lag),
                         "pair_count": len(pairs), "pearson": correlation})
    return pd.DataFrame(rows)


def write_training_eda(train: pd.DataFrame, output: Path) -> dict:
    """Write six-variable EDA tables and four PNG/vector PDF figure pairs.

    This function accepts only training rows. All table values are decimals;
    plots multiply by 100 to display return or daily-volatility percentages.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frame = model_frame(train)
    lag_table = session_lag_correlations(train)
    output = Path(output)
    tables = output / "tables"
    figures = output / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    summary = frame.describe(percentiles=[0.5, 0.95]).T
    summary.index.name = "variable"
    pearson = frame.corr(method="pearson")
    spearman = frame.corr(method="spearman")
    pearson.index.name = spearman.index.name = "variable"
    summary.to_csv(tables / "training_summary.csv")
    pearson.to_csv(tables / "training_pearson.csv")
    spearman.to_csv(tables / "training_spearman.csv")
    lag_table.to_csv(tables / "session_lag_correlations.csv", index=False)

    paths = []
    with plt.rc_context({"font.size": 14, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "savefig.facecolor": "white"}):
        def save(figure, name):
            for suffix in ("png", "pdf"):
                destination = figures / f"{name}.{suffix}"
                figure.savefig(destination, dpi=180, bbox_inches="tight")
                paths.append(destination.relative_to(output).as_posix())
            plt.close(figure)

        target_pp = 100.0 * frame[TARGET_COLUMN]
        fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.6), constrained_layout=True)
        axes[0].hist(target_pp, bins=50, color="#246A8D", edgecolor="white", linewidth=0.3)
        axes[0].set(xlabel="Future daily volatility (%)", ylabel="Training rows", title="Observed target distribution")
        ordered = np.sort(target_pp.to_numpy())
        axes[1].plot(ordered, np.arange(1, len(ordered) + 1) / len(ordered), color="#246A8D")
        for quantile, style in ((0.5, "--"), (0.95, ":")):
            axes[1].axvline(target_pp.quantile(quantile), color="#BC5B36", linestyle=style,
                            label=f"{quantile:.0%} quantile")
        axes[1].set(xlabel="Future daily volatility (%)", ylabel="Empirical cumulative proportion",
                    title="Full range retained", ylim=(0, 1.02))
        axes[1].legend(frameon=False, fontsize=11, loc="lower right")
        save(fig, "training_distribution")

        fig, axes = plt.subplots(2, 3, figsize=(11, 6.4), constrained_layout=True)
        for axis, column in zip(axes.flat, FEATURE_COLUMNS):
            axis.scatter(100.0 * frame[column], target_pp, s=7, alpha=0.25, color="#246A8D", linewidths=0)
            axis.set(xlabel=f"{LABELS[column].replace(' historical', chr(10)+'historical')} (%)", ylabel="Future daily volatility (%)",
                     title=f"Pearson r = {pearson.loc[column, TARGET_COLUMN]:.3f}")
        axes.flat[-1].axis("off")
        axes.flat[-1].text(0.04, 0.86,
                          "Training rows only\n\nAssociation is not forecast accuracy.\n"
                          "Correlated predictors share information.\n"
                          "No iid significance tests are applied.",
                          transform=axes.flat[-1].transAxes, va="top", fontsize=12, linespacing=1.6)
        save(fig, "training_scatter")

        fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, constrained_layout=True)
        axes[0].scatter(frame.index, 100.0 * frame["log_return"], s=5, alpha=0.6, color="#246A8D", linewidths=0)
        axes[0].axhline(0, color="#777777", linewidth=0.6)
        axes[0].set(ylabel="Log return (%)", title="Training observations on their actual forecast dates")
        for column, color, label in (("volatility_20", "#246A8D", "20-session historical"),
                                     (TARGET_COLUMN, "#BC5B36", "Future 5-session target")):
            axes[1].scatter(frame.index, 100.0 * frame[column], s=5, alpha=0.5,
                            color=color, linewidths=0, label=label)
        axes[1].set(xlabel="Forecast date", ylabel="Daily volatility (%)")
        axes[1].legend(frameon=False, markerscale=2)
        save(fig, "training_history")

        fig, axes = plt.subplots(2, 2, figsize=(10.5, 6.2), constrained_layout=True)
        for axis, variable in zip(axes.flat, DEPENDENCE_COLUMNS):
            values = lag_table.loc[lag_table["variable"] == variable]
            axis.plot(values["lag_sessions"], values["pearson"], "o-", color="#246A8D", markersize=3, linewidth=1)
            axis.axhline(0, color="#777777", linewidth=0.6)
            axis.set(xlabel="Lag in original trading sessions", ylabel="Pearson correlation", ylim=(-1.05, 1.05),
                     title=f"{LABELS[variable]}\nTraining pairs per lag: {values['pair_count'].min()}–{values['pair_count'].max()}")
        save(fig, "training_dependence")

    return {
        "partition": "train", "n_rows": len(frame),
        "variables": list(frame.columns), "table_units": "Decimal returns and daily-return volatility.",
        "figure_units": "Percent returns and daily-return volatility (decimal times 100).",
        "target_summary": {key: float(value) for key, value in summary.loc[TARGET_COLUMN].items()},
        "target_pearson": {key: float(value) for key, value in pearson[TARGET_COLUMN].items()},
        "target_spearman": {key: float(value) for key, value in spearman[TARGET_COLUMN].items()},
        "session_lag_method": "Pairs separated by original session_number; both endpoints training; no iid significance claims.",
        "tables": [f"tables/{name}.csv" for name in
                   ("training_summary", "training_pearson", "training_spearman", "session_lag_correlations")],
        "figures": paths,
    }
