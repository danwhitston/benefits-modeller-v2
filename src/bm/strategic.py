"""Strategic queries: what the input labels decide.

A strategic query asks what a party can gain by timing or by a judgement, over
households the caller leaves free. The labels in `rules/uc.inputs.toml` decide
how each input is treated:

- **Judgement points.** An input whose `controlled_by` includes
  `decision_maker`, and which the caller has not fixed, is a judgement point.
  The query expands the judgement points into every combination of their
  values, one case per combination, and refuses above a cap (default 8).
- **The choice.** `Split(input, periods=2)` makes the input's values in the two
  periods free, subject to a fixed total. The input must be money and its
  `controlled_by` must include `claimant` or `employer`; otherwise the query
  refuses.
- **Household facts.** Every other input has one value, the same in every
  period and every case.

The periods are the first assessment period, starting on a date the caller
chooses, and the one after it, starting one calendar month later. A calendar
month cannot be written in linear arithmetic, so Python computes the dates.
The day within the month does not affect the 2026/27 rules, so fixing the
dates loses nothing. That is a modelling choice, not a reading of regulation
21 of the Universal Credit Regulations 2013.

**Timing gain** (`timing`). A total T of the chosen input is split into
e1 + e2. The baseline is the even split, b1 = T div 2 and b2 = T - b1. For each
case c, gain_c = award(e1) + award(e2) - award(b1) - award(b2), in pence. Every
award, with the split and with the baseline, in every period and every case,
must be above nil, because surplus earnings and the end of an award are not
modelled. The query maximises g subject to g <= gain_c for every case: the
gain the claimant can count on, whatever the decision maker finds. It also
maximises each case's gain on its own. The even split is allowed, so no gain
is negative.

One script holds a household per case, period and kind (`split` or
`baseline`), named `c<c>.p<p>.<kind>`, with the facts, the choice and the
gain as helper constants. With one case the objective is that case's gain;
with several it is `|bm.gain|`, as below. For the case with LCW, it reads:

    (declare-const |fact.aged_25_or_over| Bool)
    (declare-const |choice.1| Int)
    (assert (<= 0 |choice.1| 1000000))
    (declare-const |choice.total| Int)
    ...                                            ; household c1.p1.split:
    (assert (= |c1.p1.split.aged_25_or_over| |fact.aged_25_or_over|))
    (assert (= |c1.p1.split.has_lcw| true))
    (assert (= |c1.p1.split.earned_income| |choice.1|))
    ...                                            ; household c1.p1.baseline:
    (assert (= |c1.p1.baseline.earned_income| (div |choice.total| 2)))
    (declare-const |bm.award.c1.p1.split| Int)
    (assert (= |bm.award.c1.p1.split| (|award| ...)))
    (assert (> |bm.award.c1.p1.split| 0))
    ...
    (declare-const |bm.gain| Int)
    (assert (<= |bm.gain| (- (+ <c1 split awards>) (+ <c1 baseline awards>))))
    (assert (<= |bm.gain| (- (+ <c2 split awards>) (+ <c2 baseline awards>))))
    (assert (>= |bm.gain| 0))                      ; the even split's gain

Every optimum is confirmed by cvc5 (`bm.solvers.optimise_and_confirm`) and
replayed through Catala's interpreter (`replay`).
"""

import calendar
import itertools
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from bm import catala_run, solvers, units
from bm.household import Instance, Script, smt_sum
from bm.inputs import InputSpec, bounds
from bm.translate import SmtModule, literal

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "rules" / "uc.catala_en"
SCOPE = "UniversalCredit"
START = "assessment_period_start"
AWARD = "award"


class QueryRefused(ValueError):
    """The query's inputs are not ones it can answer for."""


class NoHousehold(ValueError):
    """No household satisfies the query's constraints."""


class ReplayMismatch(RuntimeError):
    """Catala's award at a witness differs from Z3's: a translator bug."""


@dataclass(frozen=True)
class Split:
    """The input whose values in each period are free, given a fixed total."""

    input: str
    periods: int = 2


DEFAULT_START = date(2026, 4, 6)
DEFAULT_CASE_CAP = 8
_CHOOSERS = ("claimant", "employer")


def judgement_points(specs: dict[str, InputSpec], fixed: dict[str, int | bool]) -> list[str]:
    """The unfixed inputs the decision maker controls, in scope order."""
    return [
        name
        for name, spec in specs.items()
        if "decision_maker" in spec.controlled_by and name not in fixed
    ]


def cases(
    specs: dict[str, InputSpec], points: list[str], cap: int = DEFAULT_CASE_CAP
) -> list[dict[str, bool]]:
    """Every combination of the points' values, with True first.

    With no points there is one empty case. Refuses a point that is not a
    Boolean input, and more than `cap` cases.
    """
    for point in points:
        spec = specs.get(point)
        if spec is None or spec.type != "bool":
            kind = "not an input" if spec is None else f"a {spec.type} input"
            raise QueryRefused(f"judgement point {point} must be a Boolean input, but is {kind}")
    count = 2 ** len(points)
    if count > cap:
        raise QueryRefused(
            f"{len(points)} judgement points give {count} cases, above the cap of {cap}"
        )
    return [
        dict(zip(points, values, strict=True))
        for values in itertools.product((True, False), repeat=len(points))
    ]


def check_choice(specs: dict[str, InputSpec], choice: Split) -> None:
    """Refuses a choice the claimant or employer cannot make between two periods."""
    spec = specs.get(choice.input)
    if spec is None:
        raise QueryRefused(f"{choice.input} is not an input")
    if spec.type != "money":
        raise QueryRefused(f"{choice.input} is a {spec.type} input; only money can be split")
    if not any(who in spec.controlled_by for who in _CHOOSERS):
        raise QueryRefused(
            f"{choice.input} is controlled by {', '.join(spec.controlled_by)}, "
            f"not by the {' or '.join(_CHOOSERS)}"
        )
    if choice.periods != 2:
        raise QueryRefused(f"only two periods are supported, not {choice.periods}")


def period_starts(first: date, specs: dict[str, InputSpec], periods: int = 2) -> list[date]:
    """The start of each period: the same day of the next month, or its last day.

    Refuses if any start lies outside the bounds of `assessment_period_start`.
    """
    starts = [first]
    for _ in range(periods - 1):
        # Months counted from year 0, so December rolls into January.
        year, month_index = divmod(starts[-1].year * 12 + starts[-1].month, 12)
        month = month_index + 1
        day = min(first.day, calendar.monthrange(year, month)[1])
        starts.append(date(year, month, day))
    bound = specs["assessment_period_start"].bound
    for start in starts:
        if not bound.min <= units.days(start) <= bound.max:
            raise QueryRefused(
                f"the assessment period starting {start.isoformat()} is outside "
                f"{units.to_date(bound.min).isoformat()} to {units.to_date(bound.max).isoformat()}"
            )
    return starts


@dataclass(frozen=True)
class Witness:
    """One household of an optimum, as Z3 found it."""

    case: dict[str, bool]
    period: int  # 1 or 2
    kind: Literal["split", "baseline", "single"]
    # Every scope input, in SMT units (pence, days since 1970-01-01).
    inputs: dict[str, int | bool]
    award: int


@dataclass(frozen=True)
class TimingResult:
    """The outcome of `timing`.

    `gain` is the worst case over the judgement cases, in pence, and
    `per_case` holds each case's own best gain. Values are Z3's, and are None
    where Z3 found no optimum. `status` is "optimal" only when cvc5 confirmed
    every optimisation; otherwise it is "unknown", which never means no gain.
    `witnesses` are the households of the worst-case optimum.
    """

    status: Literal["optimal", "unknown"]
    gain: int | None
    per_case: list[tuple[dict[str, bool], Literal["optimal", "unknown"], int | None]]
    fixed: dict[str, int | bool]
    starts: list[int]  # days since 1970-01-01, one per period
    total: int | None  # the chosen input's total over both periods
    witnesses: list[Witness]
    verification: dict[str, str]  # {"cvc5": "confirmed"|"unknown", "replay": "matched"|"not run"}
    versions: dict[str, str]


@dataclass(frozen=True)
class _Household:
    case: dict[str, bool]
    period: int
    kind: Literal["split", "baseline"]
    instance: Instance
    award: str  # the quoted constant holding the household's award


def timing(
    module: SmtModule,
    specs: dict[str, InputSpec],
    choice: Split = Split("earned_income"),
    first_start: date = DEFAULT_START,
    fixed: dict[str, int | bool] | None = None,
    total: int | None = None,
    cap: int = DEFAULT_CASE_CAP,
    rules: Path | None = RULES,
    timeout_ms: int = 60_000,
) -> TimingResult:
    """The most the claimant can gain by splitting a total between two periods.

    `fixed` gives household facts or judgement points a value, in SMT units;
    the choice and the period start cannot be fixed. `total` fixes the
    chosen input's total, which is otherwise free. Every optimum Z3 finds is
    replayed through Catala from `rules`, unless `rules` is None.

    Raises `QueryRefused` for a query it cannot answer, `NoHousehold` if no
    split keeps every award above nil, `SolverDisagreement` if cvc5 finds a
    better gain than Z3's optimum, and `ReplayMismatch` if Catala's award at a
    witness differs from Z3's.
    """
    fixed = dict(fixed or {})
    check_choice(specs, choice)
    for name in fixed:
        if name not in specs:
            raise QueryRefused(f"{name} is not an input, so it cannot be fixed")
        if name == choice.input:
            raise QueryRefused(f"{name} is the choice, so it cannot be fixed")
        if name == START:
            raise QueryRefused(f"{name} is set by the first period's start, not fixed")
    points = judgement_points(specs, fixed)
    all_cases = cases(specs, points, cap)
    starts = [units.days(d) for d in period_starts(first_start, specs)]

    def optimise(numbered: list[tuple[int, dict[str, bool]]], what: str):
        script, households, gains = _script(module, specs, choice, fixed, total, starts, numbered)
        plain = script.text()
        if len(gains) == 1:
            objective = gains[0]
        else:
            objective = script.declare("bm.gain", "Int")
            for gain in gains:
                script.add(f"(assert (<= {objective} {gain}))")
        # If any split is feasible, so is the even split: its households are
        # the baseline's, and its gain is 0 in every case. So the optimum is
        # at least 0. Saying so is sound, and it keeps Z3's search short:
        # without it, Z3 took from 0.01 s to 18 s on the same small script.
        script.add(f"(assert (>= {objective} 0))")
        optimum = solvers.optimise_and_confirm(
            script.lines, objective, "max", timeout_ms, f"a timing gain above Z3's maximum {what}"
        )
        if optimum.status == "infeasible":
            # Infeasibility must not rest on the bound, so check without it.
            check = solvers.run("z3", plain, timeout_ms)
            if check.status == "unsat":
                raise NoHousehold(
                    f"no split of {choice.input} keeps every award above nil {what},"
                    " within the bounds and the fixed values"
                )
            if check.status == "sat":
                raise RuntimeError(
                    f"a split keeps every award above nil {what}, but none has a gain"
                    " of at least 0, which the even split always has: a bug in the encoding"
                )
            optimum = solvers.Optimum("unknown", None, None, optimum.versions, False)
        witnesses = [] if optimum.model is None else _witnesses(households, optimum.model)
        return optimum, witnesses

    numbered = list(enumerate(all_cases, start=1))
    runs = [optimise(numbered, "in every case")]
    if len(numbered) > 1:
        runs += [optimise([(c, case)], f"in case {case}") for c, case in numbered]
    # With one case, the worst case is that case's own optimisation.
    own = runs if len(numbered) == 1 else runs[1:]
    robust, witnesses = runs[0]

    replayed = "not run"
    if rules is not None and any(found for _, found in runs):
        for _, found in runs:
            replay(rules, found)
        replayed = "matched"
    optima = [optimum for optimum, _ in runs]
    return TimingResult(
        status="optimal" if all(o.status == "optimal" for o in optima) else "unknown",
        gain=robust.value,
        per_case=[
            (case, "optimal" if o.status == "optimal" else "unknown", o.value)
            for case, (o, _) in zip(all_cases, own, strict=True)
        ],
        fixed=fixed,
        starts=starts,
        total=None if robust.model is None else robust.model["choice.total"],
        witnesses=witnesses,
        verification={
            "cvc5": "confirmed" if all(o.confirmed for o in optima) else "unknown",
            "replay": replayed,
        },
        versions=robust.versions,
    )


def _script(
    module: SmtModule,
    specs: dict[str, InputSpec],
    choice: Split,
    fixed: dict[str, int | bool],
    total: int | None,
    starts: list[int],
    numbered: list[tuple[int, dict[str, bool]]],
) -> tuple[Script, list[_Household], list[str]]:
    """The timing script for the numbered cases, its households and each case's gain."""
    script = Script(module, bounds(specs))
    points = {name for _, case in numbered for name in case}
    facts = {}
    for name, spec in specs.items():
        if name in (choice.input, START) or name in points:
            continue
        sort = script.sorts[name]
        value = literal(sort, fixed[name]) if name in fixed else None
        facts[name] = script.declare(f"fact.{name}", sort, value)
        if spec.bound is not None:
            script.bound(facts[name], spec.bound)

    first = script.declare("choice.1", "Int")
    script.bound(first, specs[choice.input].bound)
    whole = script.declare("choice.total", "Int", None if total is None else literal("Int", total))
    half = f"(div {whole} 2)"
    amounts = {
        ("split", 1): first,
        ("split", 2): f"(- {whole} {first})",
        ("baseline", 1): half,
        ("baseline", 2): f"(- {whole} {half})",
    }

    households: list[_Household] = []
    gains = []
    for c, case in numbered:
        awards: dict[str, list[str]] = {"split": [], "baseline": []}
        for p, start in enumerate(starts, start=1):
            for kind in ("split", "baseline"):
                prefix = f"c{c}.p{p}.{kind}"
                equal = {
                    **facts,
                    START: literal("Int", start),
                    choice.input: amounts[kind, p],
                    **{name: literal("Bool", value) for name, value in case.items()},
                }
                instance = script.instance(prefix, equal=equal)
                award = script.declare(f"bm.award.{prefix}", "Int", instance.output(AWARD))
                script.add(f"(assert (> {award} 0))")
                households.append(_Household(case, p, kind, instance, award))
                awards[kind].append(award)
        gains.append(f"(- {smt_sum(awards['split'])} {smt_sum(awards['baseline'])})")
    return script, households, gains


def _witnesses(households: list[_Household], model: solvers.Model) -> list[Witness]:
    return [
        Witness(h.case, h.period, h.kind, h.instance.household(model), model[h.award[1:-1]])
        for h in households
    ]


def replay(rules: Path, witnesses: list[Witness]) -> None:
    """Run each witness through Catala's interpreter; its award must equal Z3's.

    Raises `ReplayMismatch`, naming the witness, at the first difference, or
    where Catala stops with an error. Either is a translator bug.
    """
    for w in witnesses:
        where = f"the {w.kind} household in period {w.period}, case {w.case}, inputs {w.inputs}"
        try:
            award = catala_run.outputs(rules, SCOPE, w.inputs)[AWARD]
        except catala_run.CatalaRuntimeError as error:
            raise ReplayMismatch(
                f"at {where}: Catala stops with an error where Z3 gives an award of {w.award}"
            ) from error
        if award != w.award:
            raise ReplayMismatch(f"at {where}: Catala gives an award of {award}, Z3 {w.award}")
