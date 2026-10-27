"""Independent verification must reject incomplete or altered evidence."""
from pathlib import Path
import tomllib

import pandas as pd
import pytest

from spy_volatility.next_phase_verification import _complete_table, _expected_grid, _scores


def test_verifier_requires_every_expected_diagnostic_group():
    expected = {(2020, "ridge"), (2020, "baseline"), (2021, "ridge"), (2021, "baseline")}
    valid = pd.DataFrame(sorted(expected), columns=["fold", "model"])
    _complete_table(valid, ["fold", "model"], expected, "outer")
    with pytest.raises(ValueError, match="missing, extra or duplicate"):
        _complete_table(valid.iloc[:-1], ["fold", "model"], expected, "outer")
    with pytest.raises(ValueError, match="missing, extra or duplicate"):
        _complete_table(pd.concat([valid, valid.iloc[[0]]]), ["fold", "model"], expected, "outer")


def test_verifier_reconstructs_candidate_order_and_fixed_parameters():
    config = tomllib.loads((Path(__file__).resolve().parents[1] / "configs/temporal.toml").read_text())
    grid = _expected_grid(config)
    assert len(grid) == 26
    assert [item["candidate_id"] for item in grid] == list(range(26))
    assert [item["parameters"]["alpha"] for item in grid[:5]] == [.01, .1, 1, 10, 100]
    assert grid[5]["parameters"]["max_depth"] == 3
    assert grid[5]["parameters"]["min_samples_leaf"] == 5
    assert grid[-1]["parameters"]["n_estimators"] == 200
    assert grid[-1]["parameters"]["learning_rate"] == .05
    assert grid[-1]["parameters"]["max_depth"] == 3


def test_verifier_error_units_and_aggregate_squared_error():
    data = pd.DataFrame({"observed": [.010, .010], "prediction": [.012, .006]})
    result = _scores(data)
    assert result["n_forecasts"] == 2
    assert result["mae_pp"] == pytest.approx(.3)
    assert result["mse_pp2"] == pytest.approx(.1)
    assert result["rmse_pp"] == pytest.approx(.1 ** .5)
    assert result["bias_pp"] == pytest.approx(-.1)
