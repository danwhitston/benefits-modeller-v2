"""The window query: gain, loss, spread and extra payday over three assessment periods."""

import dataclasses
from datetime import date
from functools import cache
from pathlib import Path

import pytest
import reference_uc

from bm import catala_run, inputs, ir, solvers, translate, units
from bm.strategic import RULES, NoHousehold, QueryRefused, ReplayMismatch
from bm.window import (
    FIGURES,
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
# A household with no LCW and no housing costs element: no work allowance, and
# a nil UC threshold of 77,255p a period.
LINEAR = {"aged_25_or_over": True, "has_lcw": False, "housing_costs_element": 0}
LOWER_BOUNDS = {"loss", "spread", "extra_payday_max"}


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


@cache
def _linear() -> WindowResult:
    """Every figure for LINEAR in its 3 cases, with P fixed at 30,000p (2P below nil)."""
    module, specs = _loaded()
    return window(module, specs, fixed=LINEAR, total=120_000)


@cache
def _h_no_claim() -> WindowResult:
    """Every figure for H with no claim after the end, at a total of 7,800 pounds."""
    module, specs = _loaded()
    return window(module, specs, fixed={**H, "claim_after_end": False}, total=780_000)


def _fresh(result: WindowResult) -> WindowResult:
    """A copy whose verification `replay` can write into, leaving the cached result alone."""
    return dataclasses.replace(result, verification=dict(result.verification))


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
            no_claim = not case.case["claim_after_end"]
            assert figure.lower_bound == (name == "loss" and no_claim)
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


def test_unknown_figures_are_refused(monkeypatch):
    module, specs = _loaded()
    _no_solver(monkeypatch)
    with pytest.raises(QueryRefused, match="not a figure"):
        window(module, specs, fixed=H, figures=("profit",))
    with pytest.raises(QueryRefused, match="no figures"):
        window(module, specs, fixed=H, figures=())


@pytest.mark.parametrize("figure", ["extra_payday_max", "extra_payday_min"])
def test_extra_payday_is_refused_for_longer_windows(monkeypatch, figure):
    module, specs = _loaded(4)
    _no_solver(monkeypatch)
    with pytest.raises(QueryRefused, match="3 periods"):
        window(module, specs, fixed={**H, **REALISTIC}, figures=(figure,), probe=True)


def test_extra_payday_total_must_divide_by_4(monkeypatch):
    module, specs = _loaded()
    _no_solver(monkeypatch)
    with pytest.raises(QueryRefused, match="multiple of 4"):
        window(module, specs, fixed=H, total=100_002, figures=("extra_payday_min",))


def test_replay_mismatch_is_raised(monkeypatch):
    result = _h_realistic(100_000, ("gain",))
    real = catala_run.outputs

    def off_by_a_penny(rules, scope, values):
        found = dict(real(rules, scope, values))
        found["award_2"] += 1
        return found

    monkeypatch.setattr(catala_run, "outputs", off_by_a_penny)
    with pytest.raises(ReplayMismatch, match="award_2"):
        replay(RULES, _fresh(result))


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
    result = _fresh(_h_realistic(100_000, ("gain",)))
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
    result = window(module, specs, fixed=fixed, total=750_000)
    assert result.status == "optimal"
    by_lcw = {case.case["has_lcw"]: case for case in result.cases}
    assert by_lcw.keys() == {True, False}
    assert by_lcw[False].figures.keys() == set(FIGURES)
    for figure in by_lcw[False].figures.values():
        assert figure.status == "infeasible" and figure.value is None and not figure.witnesses
    for name, figure in by_lcw[True].figures.items():
        assert figure.status == "optimal", name
        if not name.startswith("extra_payday"):
            assert figure.value >= 0, name
    notes = [note for note in result.excluded if "no figures" in note]
    assert len(notes) == 1 and "has_lcw no" in notes[0] and "nil" in notes[0]
    assert result.verification["cvc5"] == "confirmed"
    replay(RULES, result)
    assert result.verification["replay"] == "matched"


@pytest.mark.slow
def test_spread_at_least_gain_and_loss():
    module, specs = _loaded()
    result = window(
        module, specs, fixed=H, total=780_000, figures=("gain", "loss", "spread")
    )
    assert result.status == "optimal"
    assert len(result.cases) == 6
    for case in result.cases:
        found = case.figures
        assert {f.status for f in found.values()} == {"optimal"}, case.case
        spread = found["spread"]
        assert spread.value >= max(found["gain"].value, found["loss"].value), case.case
        assert [w.copy for w in spread.witnesses] == ["a", "b"]
        assert all(sum(_earnings(w)) == 780_000 for w in spread.witnesses)


def test_extra_payday_linear_case():
    # P is 30,000p, so 2P is below the nil UC threshold of 77,255p and every
    # period of both copies stays above nil, where the award is linear in the
    # earnings: only rounding to the penny is left.
    result = _linear()
    assert result.status == "optimal"
    assert len(result.cases) == 3
    for case in result.cases:
        for name in ("extra_payday_max", "extra_payday_min"):
            figure = case.figures[name]
            assert figure.status == "optimal", (case.case, name)
            assert abs(figure.value) <= 3, (case.case, name)
            assert _earnings(_copy(figure, "payday")) == [30_000, 60_000, 30_000]
            assert _earnings(_copy(figure, "even")) == [40_000, 40_000, 40_000]
            assert [w.copy for w in figure.witnesses] == ["even", "payday"]
            assert all(p.award >= 1 for w in figure.witnesses for p in w.trace)
        # With P fixed there is one pattern, so the most and least agree.
        assert case.figures["extra_payday_max"].value == case.figures["extra_payday_min"].value


def test_no_claim_figures_are_lower_bounds():
    result = _h_no_claim()
    # lcw_carries_over is still a point, but it cannot matter without a claim.
    assert len(result.cases) == 2
    assert result.fixed["claim_each_month"] is False
    for case in result.cases:
        for name in FIGURES:
            assert case.figures[name].lower_bound == (name in LOWER_BOUNDS), (case.case, name)
    for case in _linear().cases:
        claim = case.case["claim_after_end"]
        for name in FIGURES:
            expected = name in LOWER_BOUNDS and not claim
            assert case.figures[name].lower_bound == expected, (case.case, name)


def test_lower_bound_copies_drop_the_last_period_rule():
    # At 7,800 pounds with no claim after the end, the best split for the loss
    # ends the window at nil, which only the dropped rule allows.
    result = _h_no_claim()
    for case in result.cases:
        loss = case.figures["loss"]
        assert loss.status == "optimal"
        assert _copy(loss, "split").trace[-1].award == 0
        assert _copy(loss, "even").trace[-1].award >= 1
        spread = case.figures["spread"]
        assert _copy(spread, "a").trace[-1].award >= 1
        payday = case.figures["extra_payday_max"]
        assert _copy(payday, "even").trace[-1].award >= 1
        gain = case.figures["gain"]
        assert all(w.trace[-1].award >= 1 for w in gain.witnesses)


def test_payday_pattern_ending_at_nil_is_excluded():
    # P is 195,000p, so 2P takes period 2 to nil, and with no claim after the
    # end period 3 has no award: the pattern breaks the last-period rule,
    # which extra_payday_min keeps, while the even split does not.
    result = _h_no_claim()
    assert result.status == "optimal"
    for case in result.cases:
        least = case.figures["extra_payday_min"]
        assert least.status == "infeasible" and least.value is None and not least.witnesses
        most = case.figures["extra_payday_max"]
        assert most.status == "optimal" and most.lower_bound
        assert _copy(most, "payday").trace[-1].award == 0
        assert case.figures["gain"].status == "optimal"
    assert not any("no figures" in note for note in result.excluded)
    notes = [n for n in result.excluded if "extra_payday_min" in n]
    assert len(notes) == 2 and all("payday amount" in n for n in notes)
    assert result.verification["cvc5"] == "confirmed"


def test_realistic_case_first():
    # With has_lcw free there are 9 cases, and the realistic case without LCW
    # comes late in the order of bm.strategic.cases.
    module, specs = _loaded()
    fixed = {"aged_25_or_over": True, "housing_costs_element": 0}
    result = window(module, specs, fixed=fixed, total=120_000, figures=("extra_payday_min",))
    assert len(result.cases) == 9
    assert result.cases[0].realistic
    assert [c.case["has_lcw"] for c in result.cases[:2]] == [True, False]
    assert [c.realistic for c in result.cases] == [True, True] + [False] * 7


def test_unknown_figure_is_reported(monkeypatch):
    real = solvers.optimise_and_confirm

    def loss_unknown(lines, objective, direction, timeout_ms, context="", **kwargs):
        if context.startswith("a loss"):
            return solvers.Optimum("unknown", None, None, {}, False)
        return real(lines, objective, direction, timeout_ms, context, **kwargs)

    monkeypatch.setattr(solvers, "optimise_and_confirm", loss_unknown)
    module, specs = _loaded()
    result = window(module, specs, fixed={**H, **REALISTIC}, total=100_000, figures=GAIN_AND_LOSS)
    (case,) = result.cases
    loss = case.figures["loss"]
    assert loss.value is None and loss.status == "unknown" and not loss.witnesses
    assert case.figures["gain"].status == "optimal"
    assert result.status == "unknown"
    assert result.verification["cvc5"] == "unknown"
    assert result.excluded == result.excluded[:1]  # only the general note
    replay(RULES, result)
    assert result.verification["replay"] == "matched in part"
    assert result.verification["replayed"] == ["gain, no judgement points"]


def test_replay_of_every_figure_agrees():
    result = _fresh(_h_no_claim())
    replay(RULES, result)
    assert result.verification["replay"] == "matched"
    assert len(result.verification["replayed"]) == 2 * 4  # extra_payday_min has no witness


def _payday_copies(figure):
    copies = {w.copy: _earnings(w) for w in figure.witnesses}
    p = copies["payday"][0]
    assert copies["payday"] == [p, 2 * p, p]
    assert copies["even"] == reference_uc.even_split(4 * p, 3)
    return copies


@pytest.mark.slow
@pytest.mark.parametrize("claim", [True, False], ids=["realistic", "no claim"])
def test_spread_and_payday_match_reference(claim):
    module, specs = _loaded()
    point = REALISTIC if claim else {"claim_after_end": False, "lcw_carries_over": True}
    case = REALISTIC if claim else {**point, "claim_each_month": False}
    args = (STARTS, True, True, 80_400, case)

    total = 780_000
    result = window(module, specs, fixed={**H, **point}, total=total, figures=("spread",))
    (found,) = result.cases
    spread = found.figures["spread"]
    assert spread.status == "optimal" and spread.lower_bound == (not claim)
    # With no claim after the end, copy a keeps every period above nil, so its
    # earnings are below the nil UC threshold of 2,661.36 pounds in each: only
    # a grid on which 2,600 pounds lies has a point.
    assert spread.value >= reference_uc.brute_force("spread", total, 26_000, *args)
    copies = {w.copy: _earnings(w) for w in spread.witnesses}
    assert reference_uc.figure_value("spread", copies, *args) == spread.value

    # The total is free, so P ranges over the whole earnings bound, 2P at most
    # 10,000 pounds: the grid's 4P <= 20,000 pounds covers the same range.
    payday = ("extra_payday_max", "extra_payday_min")
    result = window(module, specs, fixed={**H, **point}, figures=payday)
    (found,) = result.cases
    most, least = found.figures["extra_payday_max"], found.figures["extra_payday_min"]
    assert most.status == least.status == "optimal"
    assert most.lower_bound == (not claim) and not least.lower_bound
    assert most.value >= reference_uc.brute_force("extra_payday_max", 2_000_000, 1_000, *args)
    assert least.value <= reference_uc.brute_force("extra_payday_min", 2_000_000, 1_000, *args)
    for name, figure in zip(payday, (most, least)):
        assert reference_uc.figure_value(name, _payday_copies(figure), *args) == figure.value
    replay(RULES, result)
    assert result.verification["replay"] == "matched"


def test_seed_reaches_every_solver_call(monkeypatch):
    # A probe sets the seed once, in `window`, and every optimisation and
    # every check beneath it must carry it.
    module, specs = _loaded()
    seen = []
    real_optimise = solvers.optimise_and_confirm

    def optimise(*args, **kwargs):
        seen.append(kwargs.get("seed"))
        return real_optimise(*args, **kwargs)

    monkeypatch.setattr(solvers, "optimise_and_confirm", optimise)
    window(module, specs, fixed={**H, **REALISTIC}, total=300_000, figures=("gain",), seed=4)
    assert seen == [4]
