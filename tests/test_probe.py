"""The scaling probe's row function: the probe scopes keep working."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import probe_window  # noqa: E402


@pytest.mark.slow
def test_probe_runs_at_four_periods():
    row = probe_window.probe_row(4, "exact", 1, "gain", timeout_s=60)
    assert row["status"] == "optimal"
    assert (row["periods"], row["mode"], row["seed"], row["figure"]) == (4, "exact", 1, "gain")
    assert isinstance(row["value"], int) and row["value"] > 0
    assert row["z3_checks"] >= 1 and row["cvc5_runs"] >= 1
    assert row["seconds"] > 0


@pytest.mark.slow
def test_probe_runs_relaxed_at_three_periods():
    row = probe_window.probe_row(3, "relaxed", 2, "loss", timeout_s=60)
    assert row["status"] == "optimal"
    assert row["mode"] == "relaxed"
    assert row["seed"] == 2


def test_probe_refuses_an_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        probe_window.probe_row(3, "rounded", 1, "gain")


def test_probe_leaves_the_solver_module_as_it_found_it():
    before = probe_window.solvers.run
    with pytest.raises(ValueError):
        probe_window.probe_row(3, "rounded", 1, "gain")
    with probe_window._Timer():
        pass
    assert probe_window.solvers.run is before
