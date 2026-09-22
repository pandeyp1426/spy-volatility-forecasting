"""One small experiment shared by the command line and notebook."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path
import platform
import sys
import tomllib
import traceback
from uuid import uuid4

import pandas as pd

from .data import get_snapshot
from .research import (
    build_features,
    evaluate_predictions,
    nonoverlapping_predictions,
    split_examples,
    validation_predictions,
)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_config(path: Path) -> dict:
    """Load explicit choices; reject inconsistent periods before using the network."""
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    for section in ("data", "research", "split", "paths"):
        if section not in config:
            raise ValueError(f"Missing configuration section: {section}")
    data, split, research = config["data"], config["split"], config["research"]
    boundaries = [data["start"], split["train_start"], split["validation_start"],
                  split["test_start"], split["test_end"], data["end"]]
    dates = [pd.Timestamp(value) for value in boundaries]
    if any(date.tzinfo is not None or date != date.normalize() for date in dates):
        raise ValueError("Use timezone-free calendar dates for configuration boundaries")
    if not (dates[0] < dates[1] < dates[2] < dates[3] < dates[4] <= dates[5]):
        raise ValueError("Require data start < train < validation < test < test end <= data end")
    if not data["ticker"] or not data["calendar"]:
        raise ValueError("A ticker and trading calendar are required")
    windows = research["windows"]
    if not isinstance(windows, list) or not windows or len(set(windows)) != len(windows):
        raise ValueError("Research windows must be a nonempty list of distinct integers")
    for value in windows + [research["horizon"], research["baseline_window"]]:
        if type(value) is not int or value < 2:
            raise ValueError("Standard-deviation windows must be integers of at least 2")
    if type(research["momentum_window"]) is not int or research["momentum_window"] < 1:
        raise ValueError("Momentum window must be a positive integer")
    return config


def _plot_results(train: pd.DataFrame, predictions: pd.DataFrame, output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, layout="constrained")
    axes[0].plot(train.index, train["log_return"] * 100, linewidth=0.6, color="#245c8a")
    axes[0].set(ylabel="Daily log return (%)", title="Training period only: returns and historical volatility")
    axes[1].plot(train.index, train["baseline"] * 100, linewidth=0.8, color="#bd621c")
    axes[1].set(ylabel="Daily volatility (%)", xlabel="Forecast date (after close)")
    for axis in axes:
        axis.grid(alpha=0.2)
    figure.savefig(output / "training_history.png", dpi=150)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(11, 4), layout="constrained")
    axis.plot(predictions.index, predictions["target"] * 100, label="Observed future daily volatility", linewidth=0.8)
    axis.plot(predictions.index, predictions["baseline"] * 100, label="Historical baseline", linewidth=0.8)
    axis.set(title="Validation only: observed volatility and baseline forecast",
             xlabel="Forecast date (after close)", ylabel="Daily volatility (%)")
    axis.legend()
    axis.grid(alpha=0.2)
    figure.savefig(output / "validation_baseline.png", dpi=150)
    plt.close(figure)


def run_phase1(config_path: str | Path = "configs/phase1.toml") -> dict:
    """Run validation baseline; return results or raise after saving failure details.

    Relative data/output paths are resolved against the config's grandparent.
    Each invocation gets a new run directory. The raw snapshot is never refreshed.
    The reserved test table is saved, but is never passed to scoring or plotting.
    """
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    root = config_path.parent.parent
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:8]
    output = root / config["paths"]["output_dir"] / run_id
    output.mkdir(parents=True, exist_ok=False)
    packages = {dist.metadata["Name"]: dist.version for dist in distributions() if dist.metadata["Name"]}
    (output / "dependencies.txt").write_text(
        "\n".join(f"{key}=={value}" for key, value in sorted(packages.items())) + "\n",
        encoding="utf-8",
    )
    source_hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "src" / "spy_volatility").glob("*.py"))
    }
    record = {
        "run_id": run_id,
        "started_at_utc": now.isoformat(),
        "status": "running",
        "config": config,
        "config_path": str(config_path),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "source_sha256": source_hashes,
        "python": sys.version,
        "platform": platform.platform(),
        "package_versions": packages,
        "final_test_evaluated": False,
        "output_dir": str(output),
    }
    write_json(output / "run_record.json", record)
    try:
        prices, metadata, audit = get_snapshot(config["data"], root / config["paths"]["snapshot_dir"])
        record["snapshot_sha256"] = metadata["sha256"]
        record["snapshot_metadata"] = metadata
        write_json(output / "data_audit.json", audit)

        examples = build_features(prices, **config["research"])
        # Earlier prices warm the windows; forecast examples start with training.
        examples = examples.loc[
            (examples.index >= config["split"]["train_start"])
            & (examples.index < config["split"]["test_end"])
        ].copy()
        splits, summary = split_examples(examples, **config["split"])
        examples.to_csv(output / "features.csv", index_label="forecast_date")
        for name, frame in splits.items():
            filename = "test_reserved.csv" if name == "test" else f"{name}.csv"
            frame.to_csv(output / filename, index_label="forecast_date")
        write_json(output / "split_summary.json", summary)

        predictions = validation_predictions(splits["validation"])
        nonoverlapping = nonoverlapping_predictions(predictions, horizon=config["research"]["horizon"])
        predictions.to_csv(output / "validation_predictions.csv", index_label="forecast_date")
        nonoverlapping.to_csv(output / "validation_nonoverlapping_predictions.csv", index_label="forecast_date")
        metrics = {
            "units": "daily-volatility percentage points",
            "validation_daily": evaluate_predictions(predictions),
            "validation_nonoverlapping": evaluate_predictions(nonoverlapping),
            "nonoverlapping_anchor": nonoverlapping.index[0].date().isoformat(),
            "nonoverlapping_stride_sessions": config["research"]["horizon"],
            "final_test": "reserved; performance not computed",
        }
        write_json(output / "metrics.json", metrics)
        _plot_results(splits["train"], predictions, output)
        record["metrics"] = metrics
        record["status"] = "success"
        record["artifacts"] = sorted(path.name for path in output.iterdir())
        return {"output_dir": str(output), "metrics": metrics, "snapshot_sha256": metadata["sha256"]}
    except Exception as error:
        record["status"] = "failed"
        record["error"] = {"type": type(error).__name__, "message": str(error)}
        if hasattr(error, "report"):
            write_json(output / "data_audit.json", error.report)
        (output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"Phase 1 failed; run record: {output / 'run_record.json'}", file=sys.stderr)
        raise
    finally:
        record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(output / "run_record.json", record)
