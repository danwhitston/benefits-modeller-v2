"""The effective marginal rate query over the UC scope."""

from fractions import Fraction
from functools import cache
from pathlib import Path

import pytest

from bm import bounds as bounds_mod
from bm import evaluate, ir, queries, solvers, translate
from bm.bounds import Bound
from bm.ir import Pos, Var
from bm.translate import Obligation, SmtModule

ROOT = Path(__file__).resolve().parent.parent
UC_IR = ROOT / "build" / "uc.bm-ir.json"
UC_BOUNDS = ROOT / "rules" / "uc.inputs.toml"


@cache
def _loaded():
    scope = ir.load(UC_IR)
    return translate.translate(scope), bounds_mod.load(UC_BOUNDS, scope)


def check_household(result: queries.EmrResult, delta: int) -> None:
    """The household is complete, and Catala's awards at e and e + delta match."""
    module, bounds = _loaded()
    household = result.household
    assert set(household) == {v.name for v in module.inputs}
    at_e = evaluate.outputs(module, household)
    at_e_plus = evaluate.outputs(
        module, {**household, "earned_income": household["earned_income"] + delta}
    )
    assert at_e["award"] == result.award_at_e
    assert at_e_plus["award"] == result.award_at_e_plus_delta
    assert result.drop == result.award_at_e - result.award_at_e_plus_delta
    assert result.rate == Fraction(result.drop, delta)
    for name, bound in bounds.items():
        assert bound.min <= household[name] <= bound.max
    assert household["earned_income"] + delta <= bounds["earned_income"].max
    assert set(result.solver_versions) == {"z3", "cvc5"}


def test_emr_peak_is_taper():
    module, bounds = _loaded()
    result = queries.emr(module, bounds)
    assert result.status == "found"
    assert result.rate == Fraction(55, 100)
    assert result.drop == 55
    assert result.award_at_e_plus_delta >= 0
    assert result.household["earned_income"] + 100 <= 1_000_000
    check_household(result, 100)


def test_emr_zero_within_work_allowance():
    module, bounds = _loaded()
    result = queries.emr(
        module, bounds, fixed={"has_lcw": True}, earnings_range=(0, 71_000 - 100)
    )
    assert result.status == "found"
    assert result.rate == 0
    assert result.household["has_lcw"] is True
    assert 0 <= result.household["earned_income"] <= 71_000 - 200
    check_household(result, 100)


def test_emr_penny_step_noise():
    module, bounds = _loaded()
    result = queries.emr(module, bounds, delta=1)
    assert result.status == "found"
    assert result.rate == 1
    check_household(result, 1)


def test_emr_upper_bound():
    module, bounds = _loaded()
    result = queries.emr(module, bounds, earnings_range=(999_800, 1_000_000), delta=100)
    assert result.status == "found"
    assert 999_800 <= result.household["earned_income"] <= 999_900
    assert result.rate == 0
    check_household(result, 100)


def test_emr_timeout_is_unknown():
    module, bounds = _loaded()
    result = queries.emr(module, bounds, timeout_ms=1)
    assert result.status == "unknown"
    assert result.rate is None
    assert result.household is None


WIDE_DATES = ROOT / "tests" / "fixtures" / "uc_wide_dates.inputs.toml"


def test_emr_excludes_households_catala_rejects():
    module, _ = _loaded()
    wide = bounds_mod.load(WIDE_DATES, ir.load(UC_IR))
    # Before 6 April 2026 no rate applies, so Catala stops with an error and
    # no household is left to compare.
    with pytest.raises(queries.NoHousehold):
        start = wide["assessment_period_start"].min
        queries.emr(module, wide, fixed={"assessment_period_start": start})
    # Over the wide range, the household found is one Catala accepts.
    result = queries.emr(module, wide)
    assert result.rate == Fraction(55, 100)
    evaluate.outputs(module, result.household)


def _stub_cvc5(monkeypatch, status, model=None):
    real_run = solvers.run

    def run(solver, script, timeout_ms):
        if solver == "cvc5":
            return solvers.SolverResult(status, model, "stub")
        return real_run(solver, script, timeout_ms)

    monkeypatch.setattr(solvers, "run", run)


def test_emr_cvc5_larger_fall_is_disagreement(monkeypatch):
    module, bounds = _loaded()
    _stub_cvc5(monkeypatch, "sat", {})
    with pytest.raises(solvers.SolverDisagreement):
        queries.emr(module, bounds)


def test_emr_cvc5_unknown_leaves_maximum_unconfirmed(monkeypatch):
    module, bounds = _loaded()
    _stub_cvc5(monkeypatch, "unknown")
    result = queries.emr(module, bounds)
    assert result.status == "unknown"
    assert result.rate == Fraction(55, 100)


def test_emr_guards_obligations_at_e_plus_delta():
    """A synthetic scope with an earnings-dependent gap, so the guard at e + delta
    matters: without it the largest drop would be 1000 (stepping into the gap),
    and renaming by prefix would also rewrite earned_income_partner, giving 50."""
    params = "((|earned_income| Int) (|earned_income_partner| Int))"
    module = SmtModule(
        text=f"(define-fun |award| {params} Int (+ (ite (< |earned_income| 500000) 1000 0)"
        " (ite (< |earned_income_partner| 100) 50 0)))\n",
        inputs=[Var("earned_income", "money"), Var("earned_income_partner", "money")],
        functions={"award": "|award|"},
        obligations=[
            Obligation("empty", "award", Pos("x.catala_en", 1), "(>= |earned_income| 500000)")
        ],
        outputs={"award": "Int"},
    )
    bounds = {n: Bound("money", 0, 1_000_000) for n in ("earned_income", "earned_income_partner")}
    result = queries.emr(module, bounds)
    assert result.status == "found"
    assert result.drop == 0
