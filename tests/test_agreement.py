"""Catala's interpreter and Z3 must agree on every output of the UC and window scopes.

`evaluate.outputs` runs the translated SMT-LIB in Z3. `catala_run.outputs` runs
the rules in Catala's own interpreter. Any difference is a translator bug.
"""

import itertools
import random
from datetime import date
from functools import cache
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bm import catala_run, evaluate, inputs, ir, strategic, translate

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


def household(
    start: date, earned: int, aged_25: bool, lcw: bool, housing: int = 0
) -> dict[str, int | bool]:
    return {
        "assessment_period_start": days(start),
        "earned_income": earned,
        "aged_25_or_over": aged_25,
        "has_lcw": lcw,
        "housing_costs_element": housing,
    }


def assert_agree(
    inputs: dict[str, int | bool], module=None, scope: str = SCOPE
) -> dict[str, int | bool] | None:
    """Both engines give the same outputs, or both stop with an error.

    Returns the outputs, or None where both stop with an error.
    """
    module = module or _loaded()[0]
    try:
        z3_result = evaluate.outputs(module, inputs)
    except evaluate.EvaluationError:
        with pytest.raises(catala_run.CatalaRuntimeError):
            catala_run.outputs(RULES, scope, inputs)
        return None
    try:
        catala_result = catala_run.outputs(RULES, scope, inputs)
    except catala_run.CatalaRuntimeError as error:
        pytest.fail(f"Catala stopped but Z3 did not, at {inputs}: {error}")
    assert set(catala_result) >= set(module.outputs)
    for name in module.outputs:
        assert catala_result[name] == z3_result[name], (
            f"{name} differs at {inputs}: Catala {catala_result[name]}, Z3 {z3_result[name]}"
        )
    return z3_result


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
        "housing_costs_element": draw(
            st.integers(
                bounds["housing_costs_element"].min, bounds["housing_costs_element"].max
            )
        ),
    }


@settings(max_examples=200, deadline=None)
@given(households())
def test_interpreter_matches_z3(inputs):
    assert_agree(inputs)


# The cases in rules/uc_tests.catala_en, all starting on 1 May 2026:
# (earned income in pence, aged 25 or over, has LCW, housing costs element).
TABLE_ROWS = [
    (0, True, True, 0),
    (71000, True, True, 0),
    (100000, True, True, 0),
    (71010, True, True, 0),
    (71001, True, True, 0),
    (148253, True, True, 0),
    (148254, True, True, 0),
    (50000, True, False, 0),
    (100000, False, False, 0),
    (0, True, True, 50000),
    (100000, True, True, 50000),
    (42710, True, True, 50000),
    (100000, True, False, 50000),
    (100000, True, True, 1),
]

WORK_ALLOWANCE = 71000
EDGE_EARNINGS = [0, 1000000, WORK_ALLOWANCE - 1, WORK_ALLOWANCE, WORK_ALLOWANCE + 1]


@pytest.mark.parametrize(("earned", "aged_25", "lcw", "housing"), TABLE_ROWS)
def test_interpreter_matches_z3_edges_table(earned, aged_25, lcw, housing):
    assert_agree(household(date(2026, 5, 1), earned, aged_25, lcw, housing))


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
        "maximum_amount": 42490,
        "award": 42484,
    }

    # With an element, the lower allowance applies and the maximum amount grows.
    with_housing = household(date(2026, 5, 1), 100000, True, True, 50000)
    assert catala_run.outputs(RULES, SCOPE, with_housing) == {
        "standard_allowance": 42490,
        "work_allowance": 42700,
        "earnings_deduction": 31515,
        "maximum_amount": 92490,
        "award": 60975,
    }


# The window: three monthly periods of the ClaimWindow scope.

WINDOW_IR = ROOT / "build" / "claim_window.bm-ir.json"
WINDOW_BOUNDS = ROOT / "rules" / "claim_window.inputs.toml"
WINDOW = "ClaimWindow"
PERIODS = 3
# Starts one calendar month apart.
STARTS = [days(date(2026, 4, 6)), days(date(2026, 5, 6)), days(date(2026, 6, 6))]
HOUSING_PENCE = [0, 1, 804_00]
EARNINGS_MAX = 10_000_00
SAMPLES_PER_CONFIGURATION = 4


@cache
def _window():
    scope = ir.load(WINDOW_IR)
    return translate.translate(scope), inputs.load(WINDOW_BOUNDS, scope)


def window_household(
    aged_25: bool, housing: int, case: dict[str, bool], earnings: tuple[int, ...]
) -> dict[str, int | bool]:
    return {
        **{f"start_{k + 1}": STARTS[k] for k in range(PERIODS)},
        **{f"earnings_{k + 1}": earnings[k] for k in range(PERIODS)},
        "aged_25_or_over": aged_25,
        "housing_costs_element": housing,
        **case,
    }


@cache
def _thresholds(aged_25: bool, housing: int, has_lcw: bool) -> tuple[int, int]:
    """Catala's nil UC threshold and relevant threshold for the first period."""
    case = {
        "has_lcw": has_lcw,
        "claim_after_end": False,
        "claim_each_month": False,
        "lcw_carries_over": False,
    }
    result = catala_run.outputs(
        RULES, WINDOW, window_household(aged_25, housing, case, (0,) * PERIODS)
    )
    return result["nil_uc_threshold_1"], result["relevant_threshold_1"]


@pytest.mark.slow
def test_claim_window_agrees_with_catala():
    """Catala and Z3 agree on every output, for households near the thresholds.

    The earnings in each period are the nil UC threshold or the relevant
    threshold, or a penny either side of one, as Catala works them out for the
    household. For the nil UC threshold the range runs down three pence, to
    reach the last earnings at which the rounded award is still at least 1p.
    The households cross age, the housing element and every judgement case
    (which includes the finding of limited capability for work).
    """
    module, specs = _window()
    fixed = strategic.close_fixed(specs, {})
    points = strategic.judgement_points(specs, fixed)
    case_list = strategic.cases(specs, points, cap=12)
    assert len(case_list) == 9

    households = []
    for i, (aged_25, housing, case) in enumerate(
        itertools.product([True, False], HOUSING_PENCE, case_list)
    ):
        nil, relevant = _thresholds(aged_25, housing, case["has_lcw"])
        assert nil < relevant
        offsets = [(nil, d) for d in range(-3, 2)] + [(relevant, d) for d in (-1, 0, 1)]
        near = sorted({min(max(t + d, 0), EARNINGS_MAX) for t, d in offsets})
        every = list(itertools.product(near, repeat=PERIODS))
        # Every configuration has a household that ends the award on a surplus
        # in the first period, one that is entitled in the first period and
        # ends the award in the second, and one that is entitled throughout;
        # the others are a seeded sample.
        picks = [
            (relevant + 1, nil + 1, nil - 1),
            (nil - 3, nil + 1, relevant + 1),
            (nil - 3, nil - 3, nil - 3),
        ]
        picks += random.Random(i).sample(every, SAMPLES_PER_CONFIGURATION - len(picks))
        households += [window_household(aged_25, housing, case, e) for e in picks]
    assert len(households) >= 60

    with_nil_period = with_surplus = all_entitled = 0
    for household in households:
        result = assert_agree(household, module, WINDOW)
        assert result is not None, f"both engines stopped with an error at {household}"
        entitled = [result[f"entitled_{k + 1}"] for k in range(PERIODS)]
        with_nil_period += not all(entitled)
        all_entitled += all(entitled)
        with_surplus += any(result[f"surplus_after_{k + 1}"] > 0 for k in range(PERIODS))
    print(
        f"window agreement: {len(households)} households,"
        f" {with_nil_period} with a nil period, {all_entitled} entitled throughout,"
        f" {with_surplus} with a surplus"
    )
    assert all_entitled >= 10
    assert with_nil_period >= 10
    assert with_surplus >= 10
