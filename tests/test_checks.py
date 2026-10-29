"""Household generation and the three-way check: Catala, Z3 and PolicyEngine UK."""

import re
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path

import pytest

from bm import catala_run, checks, evaluate, households, inputs, ir, translate

ROOT = Path(__file__).resolve().parent.parent
UC_IR = ROOT / "build" / "uc.bm-ir.json"
UC_BOUNDS = ROOT / "rules" / "uc.inputs.toml"
UC_TESTS = ROOT / "rules" / "uc_tests.catala_en"
EPOCH = date(1970, 1, 1)


@cache
def _loaded():
    scope = ir.load(UC_IR)
    return translate.translate(scope), inputs.bounds(inputs.load(UC_BOUNDS, scope))


def household(start: date, earned: int, aged_25: bool, lcw: bool) -> dict[str, int | bool]:
    return {
        "assessment_period_start": (start - EPOCH).days,
        "earned_income": earned,
        "aged_25_or_over": aged_25,
        "has_lcw": lcw,
    }


def _catala_test_rows() -> list[tuple[date, int, bool, bool]]:
    """The inputs of each test scope in rules/uc_tests.catala_en, in file order."""
    rows = []
    for block in re.findall(r"output of Uc\.UniversalCredit with \{(.*?)\}", UC_TESTS.read_text(), re.S):
        fields = dict(re.findall(r"--\s*(\w+):\s*(\S+)", block))
        rows.append(
            (
                date.fromisoformat(fields["assessment_period_start"].strip("|")),
                int(Decimal(fields["earned_income"].lstrip("$").replace(",", "")) * 100),
                fields["aged_25_or_over"] == "true",
                fields["has_lcw"] == "true",
            )
        )
    return rows


def test_table_rows_match_catala_tests():
    rows = _catala_test_rows()
    assert len(rows) == 9
    assert [(households.TABLE_START, *r) for r in households.TABLE_ROWS] == rows


# The smallest earnings with an award of 0, worked from the table's rates
# (standard allowance 424.90 or 338.58, work allowance 710.00 with LCW, taper
# 55%, deduction rounded half up to the penny):
# - 25 or over, LCW: 710.00 + 772.54 = 1,482.54, the table's "award reaches zero".
# - 25 or over, no LCW: 55% x 772.54 = 424.897 -> 424.90, but 55% x 772.53 = 424.8915 -> 424.89.
# - under 25, no LCW: 55% x 615.60 = 338.58 exactly, but 55% x 615.59 = 338.5745 -> 338.57.
# - under 25, LCW: 710.00 + 615.60 = 1,325.60.
LAST_PENNY = {
    (True, True): 148_254,
    (True, False): 77_254,
    (False, False): 61_560,
    (False, True): 132_560,
}


@pytest.mark.parametrize(("aged_25", "lcw"), list(LAST_PENNY))
def test_last_penny_earnings(aged_25, lcw):
    module, bounds = _loaded()
    found = households.last_penny_earnings(module, bounds, aged_25, lcw)
    assert type(found) is int
    assert found == LAST_PENNY[(aged_25, lcw)]
    at = household(households.TABLE_START, found, aged_25, lcw)
    below = household(households.TABLE_START, found - 1, aged_25, lcw)
    assert evaluate.outputs(module, at)["award"] == 0
    assert evaluate.outputs(module, below)["award"] == 1


def test_generate_composition():
    module, bounds = _loaded()
    generated = households.generate(bounds, n_random=50, seed=1)
    keys = {"assessment_period_start", "earned_income", "aged_25_or_over", "has_lcw"}
    seen = set()
    for h in generated:
        assert set(h) == keys
        assert type(h["assessment_period_start"]) is int and type(h["earned_income"]) is int
        assert type(h["aged_25_or_over"]) is bool and type(h["has_lcw"]) is bool
        for name, bound in bounds.items():
            assert bound.min <= h[name] <= bound.max
        seen.add(tuple(sorted(h.items())))
    assert len(seen) == len(generated), "households are not repeated"

    def has(start, earned, aged_25, lcw):
        return tuple(sorted(household(start, earned, aged_25, lcw).items())) in seen

    for row in _catala_test_rows():
        assert has(*row)
    for (aged_25, lcw), earned in LAST_PENNY.items():
        assert has(households.TABLE_START, earned, aged_25, lcw)
        assert has(households.TABLE_START, earned - 1, aged_25, lcw)
        allowance = 71_000 if lcw else 0
        for e in (allowance - 1, allowance, allowance + 1):
            if e >= 0:
                assert has(households.TABLE_START, e, aged_25, lcw)
    random_part = generated[-50:]
    for h in random_part:
        top = LAST_PENNY[(h["aged_25_or_over"], h["has_lcw"])] + households.RANDOM_MARGIN
        assert h["earned_income"] <= top
    # Most random households reach the taper; the margin keeps some past it.
    awards = [evaluate.outputs(module, h)["award"] for h in random_part]
    assert sum(a > 0 for a in awards) >= 40
    assert any(a == 0 for a in awards)
    assert random_part == households.generate(bounds, n_random=50, seed=1)[-50:]
    assert generated[-50:] != households.generate(bounds, n_random=50, seed=2)[-50:]


# The worked household of docs/mismatches.md: 710.10 with LCW.
HALF_PENNY = household(date(2026, 5, 1), 71_010, True, True)
HALF_PENNY_OUTPUTS = {
    "standard_allowance": 42_490,
    "work_allowance": 71_000,
    "earnings_deduction": 6,
    "award": 42_484,
}


def test_rounding_stage_difference():
    p = checks.rounding_stage_difference
    assert p(HALF_PENNY, HALF_PENNY_OUTPUTS, 42_485)
    assert not p(HALF_PENNY, HALF_PENNY_OUTPUTS, 42_484)
    assert not p(HALF_PENNY, HALF_PENNY_OUTPUTS, 42_486)
    assert not p(HALF_PENNY, HALF_PENNY_OUTPUTS, 42_483)
    # 1p above the allowance: 0.55p is not a half penny.
    one_p = {**HALF_PENNY, "earned_income": 71_001}
    assert not p(one_p, {**HALF_PENNY_OUTPUTS, "earnings_deduction": 1, "award": 42_489}, 42_490)
    # 30p above: 16.5p is.
    thirty_p = {**HALF_PENNY, "earned_income": 71_030}
    assert p(thirty_p, {**HALF_PENNY_OUTPUTS, "earnings_deduction": 17, "award": 42_473}, 42_474)
    # The work allowance comes from the outputs. With none, all 710.10 counts:
    # 71,010 is 10 (mod 20), a half penny again.
    no_lcw = {**HALF_PENNY, "has_lcw": False}
    assert p(no_lcw, {**HALF_PENNY_OUTPUTS, "work_allowance": 0, "award": 3_434}, 3_435)
    # And with a 710.00 allowance, 0.10 of earnings is below it.
    ten_p = {**HALF_PENNY, "earned_income": 10}
    assert not p(ten_p, {**HALF_PENNY_OUTPUTS, "earnings_deduction": 0, "award": 42_490}, 42_491)


def _decimal_literals(expr) -> set:
    match expr:
        case ir.Lit(type="decimal", value=v):
            return {v}
        case ir.Lit() | ir.VarRef() | ir.Empty():
            return set()
        case ir.Op(args=args):
            return set().union(*map(_decimal_literals, args))
        case ir.If(cond=c, then=t, else_=e):
            return _decimal_literals(c) | _decimal_literals(t) | _decimal_literals(e)
        case ir.Default(exceptions=xs, just=j, cons=c):
            return set().union(*map(_decimal_literals, xs), _decimal_literals(j), _decimal_literals(c))
        case ir.Pure(arg=a) | ir.ErrorOnEmpty(arg=a):
            return _decimal_literals(a)
    raise TypeError(expr)


def test_taper_matches_rules():
    # The predicate's half-penny test assumes the rules' taper. A new rate must
    # fail here, not quietly explain other mismatches.
    (rate,) = [d for d in ir.load(UC_IR).definitions if d.name == "deduction_rate"]
    assert _decimal_literals(rate.expr) == {checks.TAPER}


def test_run_logs_rounding_stage_household():
    (m,) = checks.run([HALF_PENNY])
    assert (m.household, m.catala, m.z3, m.policyengine) == (HALF_PENNY, 42_484, 42_484, 42_485)
    assert m.catala_outputs == HALF_PENNY_OUTPUTS
    assert checks.rounding_stage_difference(m.household, m.catala_outputs, m.policyengine)


def test_run_raises_when_catala_and_z3_differ(monkeypatch):
    real = evaluate.outputs

    def off_by_one(module, inputs):
        result = real(module, inputs)
        return {**result, "award": result["award"] + 1}

    monkeypatch.setattr(checks.evaluate, "outputs", off_by_one)
    with pytest.raises(checks.TranslatorDisagreement, match="award"):
        checks.run([household(date(2026, 5, 1), 50_000, True, False)])


def test_run_raises_when_only_z3_stops(monkeypatch):
    def stops(module, inputs):
        raise evaluate.EvaluationError("forced")

    monkeypatch.setattr(checks.evaluate, "outputs", stops)
    with pytest.raises(checks.TranslatorDisagreement, match="Z3 stops"):
        checks.run([household(date(2026, 5, 1), 50_000, True, False)])


def test_run_raises_when_only_catala_stops(monkeypatch):
    def stops(rules, scope, inputs):
        raise catala_run.CatalaRuntimeError("forced")

    monkeypatch.setattr(checks.catala_run, "outputs", stops)
    with pytest.raises(checks.TranslatorDisagreement, match="Catala stops"):
        checks.run([household(date(2026, 5, 1), 50_000, True, False)])


def test_run_raises_when_rules_give_no_value():
    # Before 6 April 2026 no rate applies, so both engines stop.
    early = household(date(2026, 4, 5), 50_000, True, False)
    with pytest.raises(catala_run.CatalaRuntimeError):
        catala_run.outputs(checks.RULES, checks.SCOPE, early)
    with pytest.raises(checks.RulesGiveNoValue):
        checks.run([early])


def test_checks_exact_match():
    _, bounds = _loaded()
    mismatches = checks.run(households.generate(bounds, n_random=50, seed=1))
    unexplained = [
        m
        for m in mismatches
        if not checks.rounding_stage_difference(m.household, m.catala_outputs, m.policyengine)
    ]
    print(
        f"\n{len(mismatches)} mismatches, {len(mismatches) - len(unexplained)} of them the "
        "rounding-stage difference logged in docs/mismatches.md"
    )
    assert unexplained == []
