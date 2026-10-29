"""Catala's interpreter and Z3 must agree on every output of the UC scope.

`evaluate.outputs` runs the translated SMT-LIB in Z3. `catala_run.outputs` runs
the rules in Catala's own interpreter. Any difference is a translator bug.
"""

from datetime import date
from functools import cache
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bm import catala_run, evaluate, inputs, ir, translate

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "rules" / "uc.catala_en"
UC_IR = ROOT / "build" / "uc.bm-ir.json"
UC_BOUNDS = ROOT / "rules" / "uc.inputs.toml"
SCOPE = "UniversalCredit"


def days(d: date) -> int:
    return (d - date(1970, 1, 1)).days


@cache
def _loaded():
    scope = ir.load(UC_IR)
    return translate.translate(scope), inputs.bounds(inputs.load(UC_BOUNDS, scope))


def household(start: date, earned: int, aged_25: bool, lcw: bool) -> dict[str, int | bool]:
    return {
        "assessment_period_start": days(start),
        "earned_income": earned,
        "aged_25_or_over": aged_25,
        "has_lcw": lcw,
    }


def assert_agree(inputs: dict[str, int | bool]) -> None:
    """Both engines give the same outputs, or both stop with an error."""
    module, _ = _loaded()
    try:
        z3_result = evaluate.outputs(module, inputs)
    except evaluate.EvaluationError:
        with pytest.raises(catala_run.CatalaRuntimeError):
            catala_run.outputs(RULES, SCOPE, inputs)
        return
    try:
        catala_result = catala_run.outputs(RULES, SCOPE, inputs)
    except catala_run.CatalaRuntimeError as error:
        pytest.fail(f"Catala stopped but Z3 did not, at {inputs}: {error}")
    assert set(catala_result) >= set(module.outputs)
    for name in module.outputs:
        assert catala_result[name] == z3_result[name], (
            f"{name} differs at {inputs}: Catala {catala_result[name]}, Z3 {z3_result[name]}"
        )


@st.composite
def households(draw):
    _, bounds = _loaded()
    return {
        "assessment_period_start": draw(
            st.integers(
                bounds["assessment_period_start"].min, bounds["assessment_period_start"].max
            )
        ),
        "earned_income": draw(
            st.integers(bounds["earned_income"].min, bounds["earned_income"].max)
        ),
        "aged_25_or_over": draw(st.booleans()),
        "has_lcw": draw(st.booleans()),
    }


@settings(max_examples=200, deadline=None)
@given(households())
def test_interpreter_matches_z3(inputs):
    assert_agree(inputs)


# The nine cases in rules/uc_tests.catala_en, all starting on 1 May 2026:
# (earned income in pence, aged 25 or over, has LCW).
TABLE_ROWS = [
    (0, True, True),
    (71000, True, True),
    (100000, True, True),
    (71010, True, True),
    (71001, True, True),
    (148253, True, True),
    (148254, True, True),
    (50000, True, False),
    (100000, False, False),
]

WORK_ALLOWANCE = 71000
EDGE_EARNINGS = [0, 1000000, WORK_ALLOWANCE - 1, WORK_ALLOWANCE, WORK_ALLOWANCE + 1]


@pytest.mark.parametrize(("earned", "aged_25", "lcw"), TABLE_ROWS)
def test_interpreter_matches_z3_edges_table(earned, aged_25, lcw):
    assert_agree(household(date(2026, 5, 1), earned, aged_25, lcw))


@pytest.mark.parametrize("start", [date(2026, 4, 6), date(2026, 5, 1), date(2027, 4, 5)])
@pytest.mark.parametrize("aged_25", [False, True])
@pytest.mark.parametrize("lcw", [False, True])
@pytest.mark.parametrize("earned", EDGE_EARNINGS)
def test_interpreter_matches_z3_edges(start, aged_25, lcw, earned):
    assert_agree(household(start, earned, aged_25, lcw))


def test_interpreter_errors_before_parameter_dates():
    inputs = household(date(2026, 4, 5), 100000, True, True)
    with pytest.raises(catala_run.CatalaRuntimeError):
        catala_run.outputs(RULES, SCOPE, inputs)
    with pytest.raises(evaluate.EvaluationError):
        evaluate.outputs(_loaded()[0], inputs)


def test_interpreter_money_is_exact_pence():
    result = catala_run.outputs(RULES, SCOPE, household(date(2026, 5, 1), 71010, True, True))
    assert result == {
        "standard_allowance": 42490,
        "work_allowance": 71000,
        "earnings_deduction": 6,
        "award": 42484,
    }
