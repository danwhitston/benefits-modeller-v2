"""The SMT script builder, on the translated UC scope."""

from datetime import date
from functools import cache
from pathlib import Path

import pytest

from bm import inputs, ir, solvers, translate, units
from bm.household import Script, smt_sum

ROOT = Path(__file__).resolve().parent.parent
UC_IR = ROOT / "build" / "uc.bm-ir.json"
UC_BOUNDS = ROOT / "rules" / "uc.inputs.toml"


@cache
def _loaded():
    scope = ir.load(UC_IR)
    return translate.translate(scope), inputs.bounds(inputs.load(UC_BOUNDS, scope))


def test_smt_sum_shapes():
    assert smt_sum([]) == "0"
    assert smt_sum(["|a|"]) == "|a|"
    assert smt_sum(["|a|", "|b|"]) == "(+ |a| |b|)"


@pytest.mark.parametrize("solver", ["cvc5", "z3"])
def test_one_term_sum_parses_in_cvc5(solver):
    text = f"(declare-const |a| Int)\n(assert (= {smt_sum(['|a|'])} 3))\n(check-sat)\n"
    result = solvers.run(solver, text, 10_000)
    assert result.status == "sat"
    assert result.model == {"a": 3}


def test_two_instances_share_no_constants():
    module, bounds = _loaded()
    script = Script(module, bounds)
    p1 = script.instance("p1", fixed={"earned_income": 0})
    p2 = script.instance("p2", fixed={"earned_income": 100_000})
    assert p1.inputs["earned_income"] == "|p1.earned_income|"
    assert set(p1.inputs.values()).isdisjoint(p2.inputs.values())
    result = solvers.run("z3", script.text(), 10_000)
    assert result.status == "sat"
    h1, h2 = p1.household(result.model), p2.household(result.model)
    assert set(h1) == set(h2) == {v.name for v in module.inputs}
    assert h1["earned_income"] == 0
    assert h2["earned_income"] == 100_000


def test_equal_ties_instances():
    module, bounds = _loaded()
    script = Script(module, bounds)
    p1 = script.instance("p1")
    p2 = script.instance("p2", equal={"earned_income": "(+ |p1.earned_income| 100)"})
    result = solvers.run("z3", script.text(), 10_000)
    assert result.status == "sat"
    h1, h2 = p1.household(result.model), p2.household(result.model)
    assert h2["earned_income"] - h1["earned_income"] == 100


def test_output_and_plain_names():
    module, bounds = _loaded()
    script = Script(module, bounds)
    household = {
        "assessment_period_start": units.days(date(2026, 5, 1)),
        "earned_income": 0,
        "aged_25_or_over": True,
        "has_lcw": False,
        "housing_costs_element": 0,
    }
    plain = script.instance(fixed=household)
    assert plain.inputs["earned_income"] == "|earned_income|"
    award = script.declare("bm.award", "Int", plain.output("award"))
    assert award == "|bm.award|"
    script.declare("bm.standard_allowance", "Int", plain.output("standard_allowance"))
    # Any function of the module, not only the outputs: the deduction rate is
    # internal, and Real, so it is asserted rather than declared.
    assert "deduction_rate" not in module.outputs
    script.add(f"(assert (= {plain.output('deduction_rate')} 0.55))")
    assert script.text("(assert true)").endswith("(assert true)\n(check-sat)\n")
    assert "(check-sat)" not in script.lines
    result = solvers.run("cvc5", script.text(), 10_000)
    assert result.status == "sat"
    assert plain.household(result.model) == household
    # With no earnings, nothing is deducted, so the award is the standard
    # allowance.
    assert result.model["bm.award"] == result.model["bm.standard_allowance"] > 0
    with pytest.raises(KeyError):
        plain.output("not_a_function")


def test_defined_excludes_error_households():
    module, _ = _loaded()
    # The rules hold no rates before 6 April 2026, so an obligation holds here.
    # No bounds, so the date bound does not decide it.
    before = {"assessment_period_start": units.days(date(2026, 4, 5))}
    for defined, expected in ((True, "unsat"), (False, "sat")):
        script = Script(module)
        script.instance(fixed=before, defined=defined)
        assert solvers.run("z3", script.text(), 10_000).status == expected


def test_repeated_prefix_refused():
    module, _ = _loaded()
    script = Script(module)
    script.instance("p1")
    with pytest.raises(ValueError, match="p1"):
        script.instance("p1")
    script.instance()
    with pytest.raises(ValueError):
        script.instance()


def test_declared_name_clash_refused():
    module, _ = _loaded()
    script = Script(module)
    script.instance()
    with pytest.raises(ValueError, match="earned_income"):
        script.declare("earned_income", "Int")


def test_unknown_inputs_refused():
    module, bounds = _loaded()
    with pytest.raises(ValueError, match="not_an_input"):
        Script(module, {**bounds, "not_an_input": bounds["earned_income"]})
    script = Script(module)
    with pytest.raises(ValueError, match="not_an_input"):
        script.instance(fixed={"not_an_input": 1})
    with pytest.raises(ValueError, match="not_an_input"):
        script.instance("p2", equal={"not_an_input": "1"})
