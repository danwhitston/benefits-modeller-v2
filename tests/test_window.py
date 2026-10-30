"""The window query: gain and loss over three assessment periods."""

import dataclasses
from datetime import date
from functools import cache
from pathlib import Path

import pytest
import reference_uc

from bm import catala_run, inputs, ir, solvers, translate, units
from bm.strategic import RULES, NoHousehold, QueryRefused, ReplayMismatch
from bm.window import (
    LAST_START,
    REALISTIC,
    WindowResult,
    periods_of,
    replay,
    window,
)

ROOT = Path(__file__).resolve().parent.parent
WINDOW_INPUTS = ROOT / "rules" / "claim_window.inputs.toml"

# Household H of the window rules' tests: aged 25 or over, with LCW and a
# housing costs element of 804 pounds.
H = {"aged_25_or_over": True, "has_lcw": True, "housing_costs_element": 80_400}
STARTS = [date(2026, 4, 6), date(2026, 5, 6), date(2026, 6, 6)]
GAIN_AND_LOSS = ("gain", "loss")


def _ir(periods: int) -> Path:
    name = "claim_window" if periods == 3 else f"claim_window{periods}"
    return ROOT / "build" / f"{name}.bm-ir.json"


@cache
def _loaded(periods: int = 3, relaxed: bool = False):
    scope = ir.load(_ir(periods))
    return translate.translate(scope, relaxed=relaxed), inputs.load(WINDOW_INPUTS, scope)


@cache
def _h_free_total() -> WindowResult:
    """Gain and loss for H in every case, with the total free."""
    module, specs = _loaded()
    return window(module, specs, fixed=H, figures=GAIN_AND_LOSS)


@cache
def _h_realistic(total: int | None, figures: tuple[str, ...] = GAIN_AND_LOSS) -> WindowResult:
    """H in the realistic case only, with the judgement points fixed."""
    module, specs = _loaded()
    return window(module, specs, fixed={**H, **REALISTIC}, total=total, figures=figures)


def _no_solver(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a solver ran before the refusal")

    monkeypatch.setattr(solvers, "optimise_and_confirm", refuse)
    monkeypatch.setattr(solvers, "run", refuse)


def _earnings(witness) -> list[int]:
    return [p.earnings for p in witness.trace]


def _copy(figure, name):
    (found,) = (w for w in figure.witnesses if w.copy == name)
    return found


def test_periods_of_reads_the_ir():
    assert periods_of(_loaded()[0]) == 3
    assert periods_of(_loaded(4)[0]) == 4


@pytest.mark.slow
def test_gain_and_loss_never_negative():
    result = _h_free_total()
    assert result.status == "optimal"
    assert result.periods == 3 and not result.probe and not result.relaxed
    assert result.total is None
    # H fixes has_lcw, so 2 cases with a claim after the end times 2 values of
    # lcw_carries_over, plus 1 without a claim times 2: 6 cases.
    assert len(result.cases) == 6
    for case in result.cases:
        for name in GAIN_AND_LOSS:
            figure = case.figures[name]
            assert figure.status == "optimal", (case.case, name)
            assert figure.value is not None and figure.value >= 0, (case.case, name)
            assert not figure.lower_bound
            assert {w.copy for w in figure.witnesses} == {"split", "even"}
    assert result.verification["cvc5"] == "confirmed"


@pytest.mark.slow
def test_realistic_case_is_first_and_flagged():
    result = _h_free_total()
    assert result.cases[0].case == REALISTIC
    assert result.cases[0].realistic
    assert [c.realistic for c in result.cases[1:]] == [False] * 5


def test_even_split_remainder():
    result = _h_realistic(100_000, ("gain",))
    (case,) = result.cases
    even = _copy(case.figures["gain"], "even")
    assert _earnings(even) == [33_334, 33_333, 33_333]
    assert [even.inputs[f"earnings_{k}"] for k in (1, 2, 3)] == [33_334, 33_333, 33_333]
    assert sum(_earnings(_copy(case.figures["gain"], "split"))) == 100_000


def test_even_split_ending_at_nil_is_refused():
    module, specs = _loaded()
    fixed = {"has_lcw": False, "housing_costs_element": 0, "aged_25_or_over": True}
    with pytest.raises(NoHousehold, match="even split ends the window at nil"):
        window(module, specs, fixed=fixed, total=900_000, figures=GAIN_AND_LOSS)


def test_start_after_31_march_2027_is_refused(monkeypatch):
    module, specs = _loaded()
    _no_solver(monkeypatch)
    with pytest.raises(QueryRefused, match="2027-03-31"):
        window(module, specs, first_start=date(2027, 2, 1), fixed=H, figures=GAIN_AND_LOSS)


def test_last_start_is_31_march_2027():
    assert date(2027, 3, 31) == LAST_START


def test_start_outside_the_bounds_is_refused(monkeypatch):
    module, specs = _loaded()
    _no_solver(monkeypatch)
    with pytest.raises(QueryRefused, match="outside"):
        window(module, specs, first_start=date(2026, 4, 5), fixed=H, figures=GAIN_AND_LOSS)


def test_no_claim_and_last_period_rule_reduce_to_above_nil():
    module, specs = _loaded()
    fixed = {**H, "claim_after_end": False, "lcw_carries_over": True}
    result = window(module, specs, fixed=fixed, total=780_000, figures=("gain",))
    (case,) = result.cases
    gain = case.figures["gain"]
    assert gain.status == "optimal"
    for copy in gain.witnesses:
        assert all(p.award >= 1 and p.entitled for p in copy.trace), copy


def test_more_than_three_periods_needs_probe(monkeypatch):
    module, specs = _loaded(4)
    _no_solver(monkeypatch)
    with pytest.raises(QueryRefused, match="probe"):
        window(module, specs, fixed=H, figures=GAIN_AND_LOSS)


def test_relaxed_needs_probe(monkeypatch):
    module, specs = _loaded(relaxed=True)
    _no_solver(monkeypatch)
    with pytest.raises(QueryRefused, match="relaxed.*probes only"):
        window(module, specs, fixed=H, figures=GAIN_AND_LOSS)


def test_more_cases_than_the_cap_are_refused(monkeypatch):
    module, specs = _loaded()
    _no_solver(monkeypatch)
    with pytest.raises(QueryRefused, match="above the cap of 5"):
        window(module, specs, fixed=H, figures=GAIN_AND_LOSS, cap=5)


def test_bad_fixed_values_and_totals_are_refused(monkeypatch):
    module, specs = _loaded()
    _no_solver(monkeypatch)
    for bad in ({"earnings_1": 0}, {"start_2": 0}, {"not_an_input": 1}):
        with pytest.raises(QueryRefused):
            window(module, specs, fixed={**H, **bad}, figures=GAIN_AND_LOSS)
    for total in (-1, 3 * 1_000_000 + 1):
        with pytest.raises(QueryRefused, match="total"):
            window(module, specs, fixed=H, total=total, figures=GAIN_AND_LOSS)


def test_figures_not_yet_built_are_not_implemented(monkeypatch):
    module, specs = _loaded()
    _no_solver(monkeypatch)
    with pytest.raises(NotImplementedError, match="spread"):
        window(module, specs, fixed=H, figures=("gain", "spread"))
    with pytest.raises(QueryRefused, match="not a figure"):
        window(module, specs, fixed=H, figures=("profit",))


def test_replay_mismatch_is_raised(monkeypatch):
    result = _h_realistic(100_000, ("gain",))
    real = catala_run.outputs

    def off_by_a_penny(rules, scope, values):
        found = dict(real(rules, scope, values))
        found["award_2"] += 1
        return found

    monkeypatch.setattr(catala_run, "outputs", off_by_a_penny)
    with pytest.raises(ReplayMismatch, match="award_2"):
        replay(RULES, result)


@pytest.mark.slow
def test_replay_agrees():
    result = _h_free_total()
    realistic = result.cases[0]
    assert realistic.realistic
    gain = realistic.figures["gain"]
    assert len(gain.witnesses) == 2
    single = dataclasses.replace(
        result, cases=[realistic], verification=dict(result.verification)
    )
    replay(RULES, single)
    assert single.verification["replay"] == "matched"


def test_replay_of_a_fixed_total_records_what_ran():
    result = _h_realistic(100_000, ("gain",))
    assert result.verification["replay"] == "not run"
    replay(RULES, result)
    assert result.verification["replay"] == "matched"
    assert result.verification["replayed"] == ["gain, no judgement points"]


@pytest.mark.slow
@pytest.mark.parametrize("figure", GAIN_AND_LOSS)
def test_gain_matches_reference(figure):
    total = 780_000
    result = _h_realistic(total)
    (case,) = result.cases
    found = case.figures[figure]
    assert found.status == "optimal"
    args = (STARTS, True, True, 80_400, REALISTIC)
    grid = reference_uc.brute_force(figure, total, 1_000, *args)
    assert found.value >= grid
    copies = {w.copy: _earnings(w) for w in found.witnesses}
    assert copies["even"] == reference_uc.even_split(total, 3)
    assert reference_uc.figure_value(figure, copies, *args) == found.value


@pytest.mark.slow
def test_relaxed_probe_runs_and_skips_replay():
    module, specs = _loaded(relaxed=True)
    result = window(
        module, specs, fixed={**H, **REALISTIC}, total=100_000, figures=("gain",), probe=True
    )
    assert result.probe and result.relaxed
    assert result.cases[0].figures["gain"].value is not None
    replay(RULES, result)
    assert result.verification["replay"].startswith("skipped")


def test_starts_are_recorded_in_days():
    result = _h_realistic(100_000, ("gain",))
    assert result.starts == [units.days(d) for d in STARTS]


def test_even_split_ending_at_nil_in_some_cases_is_excluded():
    # Without LCW there is no work allowance, so the nil UC threshold of this
    # household falls below 2,500 pounds a period and the even split is nil.
    module, specs = _loaded()
    fixed = {"aged_25_or_over": True, "housing_costs_element": 80_400, **REALISTIC}
    result = window(module, specs, fixed=fixed, total=750_000, figures=GAIN_AND_LOSS)
    assert result.status == "optimal"
    by_lcw = {case.case["has_lcw"]: case for case in result.cases}
    assert by_lcw.keys() == {True, False}
    for figure in by_lcw[False].figures.values():
        assert figure.status == "infeasible" and figure.value is None and not figure.witnesses
    for figure in by_lcw[True].figures.values():
        assert figure.status == "optimal" and figure.value >= 0
    assert any("has_lcw no" in note and "nil" in note for note in result.excluded)
    assert result.verification["cvc5"] == "confirmed"
    replay(RULES, result)
    assert result.verification["replay"] == "matched"
