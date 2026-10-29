from datetime import date
from pathlib import Path

import pytest

from bm import inputs, ir
from bm.strategic import (
    QueryRefused,
    Split,
    cases,
    check_choice,
    judgement_points,
    period_starts,
)

ROOT = Path(__file__).resolve().parent.parent
SPECS = inputs.load(ROOT / "rules" / "uc.inputs.toml", ir.load(ROOT / "build" / "uc.bm-ir.json"))


def test_judgement_points_from_labels():
    assert judgement_points(SPECS, {}) == ["has_lcw"]
    assert judgement_points(SPECS, {"has_lcw": True}) == []


def test_cases():
    assert cases(SPECS, ["has_lcw"]) == [{"has_lcw": True}, {"has_lcw": False}]
    assert cases(SPECS, []) == [{}]
    with pytest.raises(QueryRefused):
        cases(SPECS, ["has_lcw"], cap=1)


def test_cases_refuse_a_point_that_is_not_boolean():
    with pytest.raises(QueryRefused, match="earned_income"):
        cases(SPECS, ["earned_income"])


def test_check_choice():
    check_choice(SPECS, Split("earned_income"))
    for bad in (
        Split("has_lcw"),
        Split("housing_costs_element"),  # controlled by the landlord
        Split("nope"),
        Split("earned_income", periods=3),
    ):
        with pytest.raises(QueryRefused):
            check_choice(SPECS, bad)


def test_period_starts():
    assert period_starts(date(2026, 4, 6), SPECS) == [date(2026, 4, 6), date(2026, 5, 6)]


def test_period_starts_from_the_31st_use_the_last_day_of_the_next_month():
    assert period_starts(date(2027, 1, 31), SPECS) == [date(2027, 1, 31), date(2027, 2, 28)]


def test_period_starts_refuse_a_second_period_outside_the_bounds():
    with pytest.raises(QueryRefused, match="2027-04-10"):
        period_starts(date(2027, 3, 10), SPECS)


def test_period_starts_refuse_a_first_period_before_the_bounds():
    with pytest.raises(QueryRefused, match="2026-04-05"):
        period_starts(date(2026, 4, 5), SPECS)
