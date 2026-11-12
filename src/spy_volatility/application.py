"""Application boundary: select and execute one configured research workflow."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
import tomllib
from typing import ClassVar


@dataclass(frozen=True)
class ExperimentDefinition:
    module: str
    function: str
    accepts_offline: bool = False
    validated_config: bool = False


@dataclass(frozen=True)
class ExperimentRunner:
    """Own execution settings while delegating scientific work to tested modules.

    Imports are lazy so choosing a workflow does not execute another experiment.
    Offline-only workflows retain their own safety rules regardless of this flag.
    """

    config_path: str | Path = "configs/phase1.toml"
    offline: bool = False

    workflows: ClassVar[dict[str, ExperimentDefinition]] = {
        "chronological": ExperimentDefinition("workflows.baseline", "run_chronological", True),
        "pooled_random": ExperimentDefinition("workflows.pooled", "run_pooled", True, True),
        "retrospective_temporal": ExperimentDefinition("workflows.temporal", "run_next_phase", True),
        "temporal_sensitivity": ExperimentDefinition("workflows.sensitivity", "run_sensitivity"),
        "temporal_uncertainty": ExperimentDefinition("workflows.uncertainty", "run_uncertainty"),
        "prospective_protocol": ExperimentDefinition("workflows.prospective", "freeze_prospective"),
    }

    def run(self) -> dict:
        path = Path(self.config_path).resolve()
        with path.open("rb") as stream:
            config = tomllib.load(stream)
        strategy = config.get("experiment", {}).get("strategy", config.get("split", {}).get("strategy", "chronological"))
        if strategy not in self.workflows:
            raise ValueError(f"Unknown experiment strategy: {strategy}")
        definition = self.workflows[strategy]
        execute = getattr(import_module(f".{definition.module}", __package__), definition.function)
        kwargs = {"offline": self.offline} if definition.accepts_offline else {}
        if definition.validated_config:
            from spy_volatility.workflows.baseline import load_config
            return execute(path, load_config(path), **kwargs)
        return execute(path, **kwargs)
