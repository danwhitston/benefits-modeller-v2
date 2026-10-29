"""Coverage checks: can any household in the bounds make Catala stop with an error?"""

from datetime import date
from functools import cache
from pathlib import Path

import pytest

from bm import coverage, evaluate, inputs, ir, solvers, translate

ROOT = Path(__file__).resolve().parent.parent
UC_IR = ROOT / "build" / "uc.bm-ir.json"
UC_BOUNDS = ROOT / "rules" / "uc.inputs.toml"
WIDE_DATES = ROOT / "tests" / "fixtures" / "uc_wide_dates.inputs.toml"


def days(d: date) -> int:
    return (d - date(1970, 1, 1)).days


@cache
def _scope():
    return ir.load(UC_IR)


@cache
def _module():
    return translate.translate(_scope())


def test_uc_coverage_clean():
    bounds = inputs.bounds(inputs.load(UC_BOUNDS, _scope()))
    assert coverage.check(_module(), bounds) == []


def test_uc_coverage_finds_date_gap():
    module = _module()
    bounds = inputs.bounds(inputs.load(WIDE_DATES, _scope()))
    findings = coverage.check(module, bounds)
    empty = [f for f in findings if f.kind == "empty"]
    assert empty
    assert all(f.status == "found" for f in empty)
    for finding in empty:
        example = finding.example
        assert set(example) == {v.name for v in module.inputs}
        assert example["assessment_period_start"] < days(date(2026, 4, 6))
        # Catala would stop with an error at the example household.
        with pytest.raises(evaluate.EvaluationError):
            evaluate.outputs(module, example)


def test_coverage_timeout_is_unknown():
    bounds = inputs.bounds(inputs.load(UC_BOUNDS, _scope()))
    findings = coverage.check(_module(), bounds, timeout_ms=1)
    # A millisecond may or may not be enough; whatever is reported is unknown
    # with no example, never a household that was not found.
    assert all(f.status == "unknown" and f.example is None for f in findings)


def test_coverage_cvc5_disagreement(monkeypatch):
    real_run = solvers.run

    def run(solver, script, timeout_ms):
        if solver == "cvc5":
            return solvers.SolverResult("sat", {}, "stub")
        return real_run(solver, script, timeout_ms)

    monkeypatch.setattr(solvers, "run", run)
    bounds = inputs.bounds(inputs.load(UC_BOUNDS, _scope()))
    with pytest.raises(solvers.SolverDisagreement):
        coverage.check(_module(), bounds)
