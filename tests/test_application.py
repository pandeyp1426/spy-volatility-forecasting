"""Application routing must preserve workflow arguments and safety boundaries."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from spy_volatility import application, pipeline


@pytest.mark.parametrize("strategy", list(application.ExperimentRunner.workflows))
def test_runner_routes_exactly_one_workflow(tmp_path, monkeypatch, strategy):
    path = tmp_path / "experiment.toml"
    path.write_text(f'[experiment]\nstrategy = "{strategy}"\n', encoding="utf-8")
    definition = application.ExperimentRunner.workflows[strategy]
    calls = []

    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return {"selected": strategy}

    def import_selected(name, package):
        assert name == f".{definition.module}"
        assert package == "spy_volatility"
        return SimpleNamespace(**{definition.function: execute})

    monkeypatch.setattr(application, "import_module", import_selected)
    validated = {"validated": True}
    monkeypatch.setattr(pipeline, "load_config", lambda p: validated)
    result = application.ExperimentRunner(path, offline=True).run()
    expected = (path.resolve(), validated) if definition.validated_config else (path.resolve(),)
    assert calls == [(expected, {"offline": True} if definition.accepts_offline else {})]
    assert result == {"selected": strategy}


def test_unknown_strategy_never_imports_or_executes_workflow(tmp_path, monkeypatch):
    path = tmp_path / "bad.toml"
    path.write_text('[experiment]\nstrategy = "typo"\n', encoding="utf-8")
    monkeypatch.setattr(application, "import_module", lambda *a: pytest.fail("Workflow imported"))
    with pytest.raises(ValueError, match="Unknown experiment strategy"):
        application.ExperimentRunner(path).run()


def test_legacy_entry_point_delegates_to_runner(monkeypatch):
    calls = []
    def run(self):
        calls.append((self.config_path, self.offline))
        return {"compatible": True}
    monkeypatch.setattr(application.ExperimentRunner, "run", run)
    assert pipeline.run_phase1(Path("old.toml"), offline=True) == {"compatible": True}
    assert calls == [(Path("old.toml"), True)]
