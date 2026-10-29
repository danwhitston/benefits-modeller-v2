import dataclasses
import re
from datetime import date
from functools import cache
from pathlib import Path

import pytest
import reference_uc

from bm import inputs, ir, solvers, translate, units
from bm.household import Script, smt_sum
from bm.strategic import (
    DEFAULT_START,
    RULES,
    START,
    JudgementResult,
    NoHousehold,
    QueryRefused,
    ReplayMismatch,
    Split,
    TimingResult,
    cases,
    check_choice,
    judgement_points,
    judgement_value,
    period_starts,
    replay,
    timing,
)
from bm.translate import apply, literal, quote

ROOT = Path(__file__).resolve().parent.parent
SCOPE = ir.load(ROOT / "build" / "uc.bm-ir.json")
SPECS = inputs.load(ROOT / "rules" / "uc.inputs.toml", SCOPE)

# Fixed households (aged 25 or over, housing costs element in pence) and totals
# of earned income in pence over the two periods, for the brute-force check.
# Each keeps the even split above nil in both LCW cases.
HOUSEHOLDS = [(True, 0), (True, 50_000), (False, 50_000)]
TOTALS = [142_001, 142_011, 85_421]


@cache
def _module() -> translate.SmtModule:
    return translate.translate(SCOPE)


@cache
def _default() -> TimingResult:
    """The default query, with every fact free, replayed through Catala."""
    return timing(_module(), SPECS)


def _fixed(aged_25: bool, housing: int) -> dict[str, int | bool]:
    return {"aged_25_or_over": aged_25, "housing_costs_element": housing}


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


BOUND = SPECS[START].bound


def test_period_starts():
    assert period_starts(date(2026, 4, 6), BOUND) == [date(2026, 4, 6), date(2026, 5, 6)]


def test_period_starts_three_periods_over_new_year():
    assert period_starts(date(2026, 12, 15), BOUND, periods=3) == [
        date(2026, 12, 15), date(2027, 1, 15), date(2027, 2, 15)]


def test_period_starts_from_the_31st():
    assert period_starts(date(2027, 1, 31), BOUND, periods=3) == [
        date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)]


def test_period_starts_from_the_31st_use_the_last_day_of_the_next_month():
    assert period_starts(date(2027, 1, 31), BOUND) == [date(2027, 1, 31), date(2027, 2, 28)]


def test_period_starts_refuse_a_second_period_outside_the_bounds():
    with pytest.raises(QueryRefused, match="2027-04-10"):
        period_starts(date(2027, 3, 10), BOUND)


def test_period_starts_refuse_a_first_period_before_the_bounds():
    with pytest.raises(QueryRefused, match="2026-04-05"):
        period_starts(date(2026, 4, 5), BOUND)


def _money(text: str) -> int:
    """Pence from a Catala money literal such as `$1,482.53`."""
    return units.pence(text.removeprefix("$").replace(",", ""))


def _catala_award_tests() -> list[tuple[str, dict[str, str], int]]:
    """Each Catala test scope's name, its inputs as written, and its asserted award."""
    text = (ROOT / "rules" / "uc_tests.catala_en").read_text()
    table = []
    for block in text.split("#[test]")[1:]:
        name = re.search(r"declaration scope (\w+)", block)[1]
        given = dict(re.findall(r"-- (\w+): (\S+)", block))
        award = re.search(r"assertion \(computation\.award = (\$[\d,.]+)\)", block)
        assert award is not None, f"{name} asserts no award"
        table.append((name, given, _money(award[1])))
    return table


def test_reference_matches_catala_table():
    table = _catala_award_tests()
    assert len(table) == 14
    for name, given, expected in table:
        # The reference model holds the 2026/27 rates only.
        assert given["assessment_period_start"] >= "|2026-04-06|", name
        got = reference_uc.award(
            _money(given["earned_income"]),
            given["aged_25_or_over"] == "true",
            given["has_lcw"] == "true",
            _money(given["housing_costs_element"]),
        )
        assert got == expected, name


def _case_gains(total: int, aged_25: bool, lcw: bool, housing: int) -> dict[int, int]:
    """Each first-period amount e1 whose four awards are above nil, to its gain."""
    halves = (total // 2, total - total // 2)
    baseline = [reference_uc.award(e, aged_25, lcw, housing) for e in halves]
    if min(baseline) <= 0:
        return {}
    gains = {}
    for e1 in range(total + 1):
        split = [reference_uc.award(e, aged_25, lcw, housing) for e in (e1, total - e1)]
        if min(split) > 0:
            gains[e1] = sum(split) - sum(baseline)
    return gains


def _brute_force(total: int, aged_25: bool, housing: int) -> tuple[int, dict[bool, int]]:
    """The robust gain and each LCW case's own gain, over every split.

    The robust gain is the best over e1 of the worst case, over the splits
    where every award in both cases is above nil. Each case's own gain is the
    best over e1 for that case alone.
    """
    gains = {lcw: _case_gains(total, aged_25, lcw, housing) for lcw in (True, False)}
    both = gains[True].keys() & gains[False].keys()
    robust = max(min(gains[True][e1], gains[False][e1]) for e1 in both)
    return robust, {lcw: max(g.values()) for lcw, g in gains.items()}


def _witness_gains(result: TimingResult) -> dict[bool, int]:
    """Each case's gain at the witness, from the witnesses' awards."""
    gains: dict[bool, int] = {}
    for w in result.witnesses:
        sign = 1 if w.kind == "split" else -1
        gains[w.inputs["has_lcw"]] = gains.get(w.inputs["has_lcw"], 0) + sign * w.award
    return gains


def test_timing_gain_never_negative():
    result = _default()
    assert result.status == "optimal"
    assert result.gain >= 0
    assert result.gain_status == "optimal"
    assert result.verification == {
        "cvc5": "confirmed",
        "replay": "matched",
        "replayed": ["gain", "case has_lcw yes", "case has_lcw no"],
    }
    assert [case for case, _, _ in result.per_case] == [{"has_lcw": True}, {"has_lcw": False}]
    for _, status, gain in result.per_case:
        assert status == "optimal"
        assert gain >= result.gain
    assert result.starts == [units.days(d) for d in period_starts(DEFAULT_START, BOUND)]

    # Two cases, two periods, a split and a baseline: eight households.
    assert len(result.witnesses) == 8
    facts = {
        name: result.witnesses[0].inputs[name]
        for name in ("aged_25_or_over", "housing_costs_element")
    }
    earned = {}
    for w in result.witnesses:
        assert set(w.inputs) == set(SPECS)
        assert w.inputs["has_lcw"] == w.case["has_lcw"]
        assert w.inputs["assessment_period_start"] == result.starts[w.period - 1]
        assert {name: w.inputs[name] for name in facts} == facts
        assert w.award > 0
        earned[w.case["has_lcw"], w.kind, w.period] = w.inputs["earned_income"]
    for lcw in (True, False):
        assert earned[lcw, "split", 1] == earned[True, "split", 1]
        assert earned[lcw, "split", 1] + earned[lcw, "split", 2] == result.total
        assert earned[lcw, "baseline", 1] == result.total // 2
        assert earned[lcw, "baseline", 2] == result.total - result.total // 2
    # The robust gain is the worse of the two cases at the witness.
    assert min(_witness_gains(result).values()) == result.gain


@pytest.mark.parametrize("aged_25, housing", HOUSEHOLDS)
@pytest.mark.parametrize("total", TOTALS)
def test_timing_matches_brute_force(aged_25, housing, total):
    result = timing(_module(), SPECS, fixed=_fixed(aged_25, housing), total=total, rules=None)
    robust, per_case = _brute_force(total, aged_25, housing)
    assert result.status == "optimal"
    assert result.gain == robust
    assert result.per_case == [
        ({"has_lcw": True}, "optimal", per_case[True]),
        ({"has_lcw": False}, "optimal", per_case[False]),
    ]
    assert result.total == total
    assert result.verification == {"cvc5": "confirmed", "replay": "not run", "replayed": []}
    for w in result.witnesses:
        e = w.inputs["earned_income"]
        assert w.award == reference_uc.award(e, aged_25, w.inputs["has_lcw"], housing)


def _forall_script(
    total: int, aged_25: bool, housing: int, relation: str, gain: int, first: int | None = None
) -> str:
    """A split exists such that, for every LCW finding, `gain(j) <relation> gain`.

    Built by hand from the module's functions, with `has_lcw` bound by
    `forall`, so it shares no encoding with `timing`. `first`, if given, fixes
    the split's earnings in the first period.
    """
    module = _module()
    script = Script(module)
    e1 = script.declare("test.e1", "Int", None if first is None else literal("Int", first))
    e2 = script.declare("test.e2", "Int", f"(- {literal('Int', total)} {e1})")
    for e in (e1, e2):
        script.bound(e, SPECS["earned_income"].bound)
    baseline = (literal("Int", total // 2), literal("Int", total - total // 2))
    starts = [literal("Int", units.days(d)) for d in period_starts(DEFAULT_START, BOUND)]
    j = quote("test.j")
    awards: dict[str, list[str]] = {"split": [], "baseline": []}
    above_nil = []
    for kind, earnings in (("split", (e1, e2)), ("baseline", baseline)):
        for start, e in zip(starts, earnings, strict=True):
            values = {
                "assessment_period_start": start,
                "earned_income": e,
                "aged_25_or_over": literal("Bool", aged_25),
                "has_lcw": j,
                "housing_costs_element": literal("Int", housing),
            }
            args = [values[v.name] for v in module.inputs]
            award = apply(module.functions["award"], args)
            awards[kind].append(award)
            above_nil.append(f"(> {award} 0)")
            above_nil += [
                f"(not {apply(quote(f'bm.obligation.{i}'), args)})"
                for i in range(len(module.obligations))
            ]
    gain_j = f"(- {smt_sum(awards['split'])} {smt_sum(awards['baseline'])})"
    script.add(
        f"(assert (forall (({j} Bool)) (and {' '.join(above_nil)}"
        f" ({relation} {gain_j} {literal('Int', gain)}))))"
    )
    return script.text()


def test_timing_forall_cross_check():
    # A household whose robust gain is positive, so that the cross-check
    # tests an optimum above the even split's gain of 0.
    total, (aged_25, housing) = TOTALS[0], HOUSEHOLDS[1]
    assert _brute_force(total, aged_25, housing)[0] == 1
    result = timing(_module(), SPECS, fixed=_fixed(aged_25, housing), total=total, rules=None)
    assert result.status == "optimal"
    assert result.gain == 1
    # Neither solver finds a split whose worst case beats the optimum.
    better = _forall_script(total, aged_25, housing, ">", result.gain)
    for solver in ("z3", "cvc5"):
        assert solvers.run(solver, better, 60_000).status == "unsat", solver
    # Z3 finds a split that reaches it. cvc5 answers unknown to that search
    # (cvc5 1.4.2, 29 October 2026), so it checks the split of the witness.
    reach = _forall_script(total, aged_25, housing, ">=", result.gain)
    assert solvers.run("z3", reach, 60_000).status == "sat"
    (first,) = {
        w.inputs["earned_income"] for w in result.witnesses if (w.kind, w.period) == ("split", 1)
    }
    at_witness = _forall_script(total, aged_25, housing, ">=", result.gain, first)
    assert solvers.run("cvc5", at_witness, 60_000).status == "sat"


def test_timing_with_lcw_fixed_has_one_case():
    total, (aged_25, housing) = TOTALS[0], HOUSEHOLDS[0]
    fixed = {**_fixed(aged_25, housing), "has_lcw": True}
    result = timing(_module(), SPECS, fixed=fixed, total=total, rules=None)
    expected = max(_case_gains(total, aged_25, True, housing).values())
    assert result.status == "optimal"
    assert result.gain == expected
    assert result.per_case == [({}, "optimal", expected)]
    assert len(result.witnesses) == 4
    assert all(w.case == {} and w.inputs["has_lcw"] is True for w in result.witnesses)


def test_timing_no_household():
    # Without LCW the award at 25 or over is nil from about 772.55 pounds, so
    # 2,000 pounds cannot be split with both periods above nil.
    fixed = {"housing_costs_element": 0, "aged_25_or_over": True, "has_lcw": False}
    with pytest.raises(NoHousehold):
        timing(_module(), SPECS, fixed=fixed, total=200_000, rules=None)


def test_timing_refuses_fixing_the_choice_or_the_start():
    for name, value in (("earned_income", 0), ("assessment_period_start", 20_600), ("nope", 1)):
        with pytest.raises(QueryRefused, match=name):
            timing(_module(), SPECS, fixed={name: value}, rules=None)


def test_replay_mismatch_raises():
    witness = _default().witnesses[0]
    tampered = dataclasses.replace(witness, award=witness.award + 1)
    with pytest.raises(ReplayMismatch, match=f"{witness.kind}.*period {witness.period}"):
        replay(RULES, [tampered])


def _value(fixed: dict[str, int | bool] | None = None) -> JudgementResult:
    return judgement_value(_module(), SPECS, "has_lcw", fixed=fixed)


def _assert_witnesses(result: JudgementResult, value: int, witnesses: list) -> None:
    """The witnesses are the pair whose awards differ by `value`, with the point flipped."""
    assert [(w.case, w.period, w.kind) for w in witnesses] == [
        ({"has_lcw": True}, 1, "single"),
        ({"has_lcw": False}, 1, "single"),
    ]
    yes, no = witnesses
    assert yes.inputs["has_lcw"] is True and no.inputs["has_lcw"] is False
    assert yes.award > 0 and no.award > 0
    assert yes.award - no.award == value
    # Everything but the point is the same household.
    assert {k: v for k, v in yes.inputs.items() if k != "has_lcw"} == {
        k: v for k, v in no.inputs.items() if k != "has_lcw"
    }
    assert yes.inputs["assessment_period_start"] == result.start


def test_lcw_value_no_housing():
    # 55% of the 710.00 pound work allowance without housing costs.
    result = _value({"housing_costs_element": 0})
    assert result.status == "optimal"
    assert (result.largest, result.smallest) == (39_050, 0)
    _assert_witnesses(result, 39_050, result.largest_witnesses)
    _assert_witnesses(result, 0, result.smallest_witnesses)
    assert result.smallest_witnesses[0].inputs["earned_income"] == 0
    assert result.fixed == {"housing_costs_element": 0}
    assert result.largest_status == result.smallest_status == "optimal"
    assert result.verification == {
        "cvc5": "confirmed",
        "replay": "matched",
        "replayed": ["largest", "smallest"],
    }


def test_lcw_value_with_housing():
    # 55% of the 427.00 pound work allowance when there is a housing costs element.
    result = _value({"housing_costs_element": 50_000})
    assert result.status == "optimal"
    assert (result.largest, result.smallest) == (23_485, 0)
    _assert_witnesses(result, 23_485, result.largest_witnesses)


def test_lcw_value_overall():
    # A free housing costs element can be 1p, which switches on the lower
    # work allowance, so the largest value is the one without housing costs.
    result = _value()
    assert result.status == "optimal"
    assert (result.largest, result.smallest) == (39_050, 0)


def test_judgement_refuses():
    with pytest.raises(QueryRefused, match="earned_income"):
        judgement_value(_module(), SPECS, "earned_income", rules=None)
    with pytest.raises(QueryRefused, match="nope"):
        judgement_value(_module(), SPECS, "nope", rules=None)
    # Review Focus 4: a point the caller has fixed is no longer the decision maker's.
    with pytest.raises(QueryRefused, match="has_lcw"):
        judgement_value(_module(), SPECS, "has_lcw", fixed={"has_lcw": True}, rules=None)


def test_judgement_refuses_fixing_the_start_or_an_unknown_input():
    for name in ("assessment_period_start", "nope"):
        with pytest.raises(QueryRefused, match=name):
            judgement_value(_module(), SPECS, "has_lcw", fixed={name: 0}, rules=None)


def test_judgement_unknown_is_not_a_value(monkeypatch):
    # Z3 out of time gives no value, and cvc5 unable to confirm keeps Z3's.
    real = solvers.optimise_and_confirm

    def stub(lines, objective, direction, timeout_ms, context=""):
        found = real(lines, objective, direction, timeout_ms, context)
        if direction == "max":
            return solvers.Optimum("unknown", None, None, found.versions, False)
        return dataclasses.replace(found, status="unknown", confirmed=False)

    monkeypatch.setattr(solvers, "optimise_and_confirm", stub)
    result = _value({"housing_costs_element": 0})
    assert result.status == "unknown"
    assert result.largest is None and result.largest_witnesses == []
    assert result.smallest == 0 and len(result.smallest_witnesses) == 2
    assert result.largest_status == result.smallest_status == "unknown"
    assert result.verification == {
        "cvc5": "unknown",
        "replay": "matched in part",
        "replayed": ["smallest"],
    }


def test_timing_unknown_case_leaves_the_other_statuses_alone(monkeypatch):
    # Z3 runs out of time on the case with LCW only. The worst-case gain and
    # the other case keep their own confirmed results.
    real = solvers.optimise_and_confirm

    def stub(lines, objective, direction, timeout_ms, context=""):
        if "{'has_lcw': True}" in context:
            return solvers.Optimum("unknown", None, None, solvers.versions(), False)
        return real(lines, objective, direction, timeout_ms, context)

    monkeypatch.setattr(solvers, "optimise_and_confirm", stub)
    total, (aged_25, housing) = TOTALS[0], HOUSEHOLDS[1]
    result = timing(_module(), SPECS, fixed=_fixed(aged_25, housing), total=total)
    robust, per_case = _brute_force(total, aged_25, housing)
    assert result.status == "unknown"
    assert result.gain == robust and result.gain_status == "optimal"
    assert result.per_case == [
        ({"has_lcw": True}, "unknown", None),
        ({"has_lcw": False}, "optimal", per_case[False]),
    ]
    assert result.verification == {
        "cvc5": "unknown",
        "replay": "matched in part",
        "replayed": ["gain", "case has_lcw no"],
    }


def test_judgement_no_household():
    # Without LCW the award at 25 or over is nil from about 772.55 pounds of earnings.
    fixed = {"housing_costs_element": 0, "aged_25_or_over": True, "earned_income": 200_000}
    with pytest.raises(NoHousehold):
        judgement_value(_module(), SPECS, "has_lcw", fixed=fixed, rules=None)
