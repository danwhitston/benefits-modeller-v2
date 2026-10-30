"""Strategic queries: what the input labels decide.

A strategic query asks what a party can gain by timing or by a judgement, over
households the caller leaves free. The labels in `rules/uc.inputs.toml` decide
how each input is treated:

- **Judgement points.** An input whose `controlled_by` includes
  `decision_maker`, and which the caller has not fixed, is a judgement point.
  An input with `applies_when` is fixed False when the point it names is fixed
  False (`close_fixed`, which every query calls first). The query expands the
  judgement points into every combination of their values, one case per
  combination, and refuses above a cap (default 8).
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

**Value of a judgement point** (`judgement_value`). For a Boolean judgement
point, in the first period only, the value to a household of the decision
maker's finding is award(point true) - award(point false), in pence. Two
households, `yes` and `no`, share every fact (`fact.<name>` constants, as
above) and differ only in the point. Both awards must be above nil, because the
end of an award is not modelled. The query finds the largest and the smallest
value over the households the caller leaves free:

    (declare-const |bm.value| Int)
    (assert (= |bm.value| (- |bm.award.yes| |bm.award.no|)))

The value is left unbounded. A lower bound of 0 would be sound for the largest,
because LCW only adds a work allowance, but it would be unsound for the smallest,
where it could hide a negative value, and the queries are fast without one.
"""

import calendar
import itertools
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from bm import catala_run, solvers, units
from bm.household import Instance, Script, smt_sum
from bm.inputs import Bound, InputSpec, bounds
from bm.translate import RELAXED_REFUSAL, SmtModule, literal

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
    """The unfixed inputs the decision maker controls, in scope order.

    `fixed` should be the output of `close_fixed`, so that an input whose
    `applies_when` point is fixed False is itself fixed, and so not a point.
    """
    return [
        name
        for name, spec in specs.items()
        if "decision_maker" in spec.controlled_by and name not in fixed
    ]


def close_fixed(
    specs: dict[str, InputSpec], fixed: dict[str, int | bool]
) -> dict[str, int | bool]:
    """`fixed`, plus each unfixed input whose `applies_when` point is fixed False, as False.

    An input that applies only when another is true cannot matter once that
    other is fixed False, so it is fixed False too. If it were left free it
    would become a free fact in the query, which is wrong. Every query must call
    this once, at the top, on the caller's fixed values and use the result
    throughout (for `judgement_points`, `cases` and the facts). A point fixed
    True leaves its dependants free, and a dependant the caller fixed keeps the
    caller's value. Returns a new dict. Changes nothing when no spec has an
    `applies_when`, as for `rules/uc.inputs.toml`.
    """
    closed = dict(fixed)
    for name, spec in specs.items():
        parent = spec.applies_when
        if parent is not None and name not in fixed and parent in fixed and not fixed[parent]:
            closed[name] = False
    return closed


def cases(
    specs: dict[str, InputSpec], points: list[str], cap: int = DEFAULT_CASE_CAP
) -> list[dict[str, bool]]:
    """Every combination of the points' values, with True first.

    With no points there is one empty case. A point whose `applies_when` names
    another of the points is skipped in the combinations where that point is
    False, and is fixed False there, so each case still gives every point a
    value. A point whose `applies_when` names an input that is not among the
    points (the caller fixed it True) is free. Refuses a point that is not a
    Boolean input, a condition that chains, and more than `cap` cases.
    """
    for point in points:
        spec = specs.get(point)
        if spec is None or spec.type != "bool":
            kind = "not an input" if spec is None else f"a {spec.type} input"
            raise QueryRefused(f"judgement point {point} must be a Boolean input, but is {kind}")
    parents = {
        point: specs[point].applies_when
        for point in points
        if specs[point].applies_when in points
    }
    if chained := sorted(set(parents) & set(parents.values())):
        raise QueryRefused(f"judgement points {chained} have conditions that chain")
    # A parent with k children gives 1 case when False and 2**k when True.
    children = {
        parent: sum(1 for p in parents.values() if p == parent) for parent in set(parents.values())
    }
    count = 2 ** (len(points) - len(parents) - len(children))
    for k in children.values():
        count *= 1 + 2**k
    if count > cap:
        raise QueryRefused(
            f"{len(points)} judgement points give {count} cases, above the cap of {cap}"
        )
    found: dict[tuple[bool, ...], dict[str, bool]] = {}
    for values in itertools.product((True, False), repeat=len(points)):
        case = dict(zip(points, values, strict=True))
        for child, parent in parents.items():
            if not case[parent]:
                case[child] = False
        found.setdefault(tuple(case.values()), case)
    return list(found.values())


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


def period_starts(first: date, bound: Bound, periods: int = 2) -> list[date]:
    """The start of each period: the same day of the next month, or its last day.

    `bound` is the bound of the start input. Refuses if any start lies outside it.
    """
    starts = [first]
    for _ in range(periods - 1):
        # Months counted from year 0, so December rolls into January.
        year, month_index = divmod(starts[-1].year * 12 + starts[-1].month, 12)
        month = month_index + 1
        day = min(first.day, calendar.monthrange(year, month)[1])
        starts.append(date(year, month, day))
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
    where Z3 found no optimum. Each value has its own status: "optimal" when
    cvc5 confirmed it, otherwise "unknown", with the value kept if only cvc5
    could not confirm it. `status` is "optimal" only when every optimisation
    is; "unknown" never means no gain. `witnesses` are the households of the
    worst-case optimum. `verification` is described at `_verification`.
    """

    status: Literal["optimal", "unknown"]
    gain: int | None
    gain_status: Literal["optimal", "unknown"]
    per_case: list[tuple[dict[str, bool], Literal["optimal", "unknown"], int | None]]
    fixed: dict[str, int | bool]
    starts: list[int]  # days since 1970-01-01, one per period
    total: int | None  # the chosen input's total over both periods
    witnesses: list[Witness]
    verification: dict[str, str | list[str]]
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
    witness differs from Z3's. `QueryRefused` also covers a relaxed module,
    which is not the rules.
    """
    if module.relaxed:
        raise QueryRefused(f"timing cannot be answered: {RELAXED_REFUSAL}")
    fixed = close_fixed(specs, fixed or {})
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
    starts = [units.days(d) for d in period_starts(first_start, specs[START].bound)]

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
        # at least 0, and saying so is sound. It is not what keeps the search
        # short: the run time of Z3's Optimize engine had a long tail with the
        # bound as well, which is why `optimise_and_confirm` no longer uses it.
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
    runs = {"gain": optimise(numbered, "in every case")}
    if len(numbered) > 1:
        for c, case in numbered:
            runs[f"case {case_label(case)}"] = optimise([(c, case)], f"in case {case}")
    # With one case, the worst case is that case's own optimisation.
    own = list(runs.values()) if len(numbered) == 1 else list(runs.values())[1:]
    robust, witnesses = runs["gain"]
    return TimingResult(
        status="optimal" if all(o.status == "optimal" for o, _ in runs.values()) else "unknown",
        gain=robust.value,
        gain_status=_status(robust),
        per_case=[(case, _status(o), o.value) for case, (o, _) in zip(all_cases, own, strict=True)],
        fixed=fixed,
        starts=starts,
        total=None if robust.model is None else robust.model["choice.total"],
        witnesses=witnesses,
        verification=_verification(rules, runs),
        versions=robust.versions,
    )


def case_label(case: dict[str, bool]) -> str:
    """A judgement case in words, such as "has_lcw yes"."""
    if not case:
        return "no judgement points"
    return ", ".join(f"{name} {'yes' if v else 'no'}" for name, v in case.items())


def _status(optimum: solvers.Optimum) -> Literal["optimal", "unknown"]:
    return "optimal" if optimum.status == "optimal" else "unknown"


def _verification(
    rules: Path | None, runs: dict[str, tuple[solvers.Optimum, list[Witness]]]
) -> dict[str, str | list[str]]:
    """Replay every optimisation's witnesses, and say what was checked.

    `runs` maps a name for each optimisation to its optimum and witnesses.
    "cvc5" is "confirmed" when cvc5 confirmed every optimum, otherwise
    "unknown". "replayed" names the optimisations whose witnesses Catala's
    interpreter replayed, and "replay" is "matched" when that is all of them,
    "matched in part" when some had no witnesses because Z3 found no optimum,
    and "not run" when none was replayed. A mismatch raises `ReplayMismatch`.
    """
    replayed = []
    if rules is not None:
        for name, (_, found) in runs.items():
            if found:
                replay(rules, found)
                replayed.append(name)
    if not replayed:
        outcome = "not run"
    else:
        outcome = "matched" if len(replayed) == len(runs) else "matched in part"
    return {
        "cvc5": "confirmed" if all(o.confirmed for o, _ in runs.values()) else "unknown",
        "replay": outcome,
        "replayed": replayed,
    }


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
    facts = _facts(script, specs, fixed, {choice.input, START, *points})

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


def _facts(
    script: Script, specs: dict[str, InputSpec], fixed: dict[str, int | bool], skip: set[str]
) -> dict[str, str]:
    """Declare `fact.<name>` for each input not in `skip`: fixed, or free within its bound."""
    facts = {}
    for name, spec in specs.items():
        if name in skip:
            continue
        sort = script.sorts[name]
        value = literal(sort, fixed[name]) if name in fixed else None
        facts[name] = script.declare(f"fact.{name}", sort, value)
        if spec.bound is not None:
            script.bound(facts[name], spec.bound)
    return facts


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


@dataclass(frozen=True)
class JudgementResult:
    """The outcome of `judgement_value`.

    `largest` and `smallest` are award(point true) - award(point false) in
    pence, Z3's optima, or None where Z3 found none. Each has its own status:
    "optimal" when cvc5 confirmed it, otherwise "unknown", with the value kept
    if only cvc5 could not confirm it. `status` is "optimal" only when both
    are; "unknown" never means the value is nil. Each list of witnesses holds
    the household with the point true, then the same household with it false
    (kind "single", period 1). `verification` is described at `_verification`.
    """

    point: str
    status: Literal["optimal", "unknown"]
    largest: int | None
    largest_status: Literal["optimal", "unknown"]
    smallest: int | None
    smallest_status: Literal["optimal", "unknown"]
    largest_witnesses: list[Witness]
    smallest_witnesses: list[Witness]
    fixed: dict[str, int | bool]
    start: int  # days since 1970-01-01
    verification: dict[str, str | list[str]]
    versions: dict[str, str]


def judgement_value(
    module: SmtModule,
    specs: dict[str, InputSpec],
    point: str,
    start: date = DEFAULT_START,
    fixed: dict[str, int | bool] | None = None,
    rules: Path | None = RULES,
    timeout_ms: int = 60_000,
) -> JudgementResult:
    """The largest and smallest worth of the decision maker's finding on `point`.

    The value is the award with the point true less the award with it false,
    in the assessment period starting on `start`, over every household that
    keeps both awards above nil. `fixed` gives other inputs a value, in SMT
    units. Inputs other than `point` stay free unless fixed, including any
    other judgement point, which then takes the same value in both households.
    Every optimum Z3 finds is replayed through Catala from `rules`, unless
    `rules` is None.

    Raises `QueryRefused` if `point` is not an unfixed Boolean judgement point
    or the query's inputs are otherwise not ones it can answer for,
    `NoHousehold` if no household keeps both awards above nil,
    `SolverDisagreement` if cvc5 finds a better value than Z3's optimum, and
    `ReplayMismatch` if Catala's award at a witness differs from Z3's.
    `QueryRefused` also covers a relaxed module, which is not the rules.
    """
    if module.relaxed:
        raise QueryRefused(f"judgement_value cannot be answered: {RELAXED_REFUSAL}")
    fixed = close_fixed(specs, fixed or {})
    for name in fixed:
        if name not in specs:
            raise QueryRefused(f"{name} is not an input, so it cannot be fixed")
        if name == START:
            raise QueryRefused(f"{name} is set by the period's start, not fixed")
    if point in fixed:
        raise QueryRefused(f"{point} is fixed, so it is not a judgement point to value")
    if point not in judgement_points(specs, fixed):
        reason = "not an input" if point not in specs else "not controlled by the decision maker"
        raise QueryRefused(f"{point} is {reason}, so it is not a judgement point")
    cases(specs, [point])  # refuses a point that is not Boolean
    (start_day,) = (units.days(d) for d in period_starts(start, specs[START].bound, periods=1))

    script = Script(module, bounds(specs))
    facts = _facts(script, specs, fixed, {START, point})
    households = []
    awards = []
    for value in (True, False):
        kind = "yes" if value else "no"
        equal = {**facts, START: literal("Int", start_day), point: literal("Bool", value)}
        instance = script.instance(kind, equal=equal)
        award = script.declare(f"bm.award.{kind}", "Int", instance.output(AWARD))
        script.add(f"(assert (> {award} 0))")
        households.append(_Household({point: value}, 1, "single", instance, award))
        awards.append(award)
    objective = script.declare("bm.value", "Int", f"(- {awards[0]} {awards[1]})")

    def optimise(direction: Literal["max", "min"]):
        # No bound on the value: the sign of the value is part of what the
        # query finds, and the optimisations are fast without one.
        optimum = solvers.optimise_and_confirm(
            script.lines, objective, direction, timeout_ms, f"a {direction} value for {point}"
        )
        if optimum.status == "infeasible":
            raise NoHousehold(
                "no household keeps both awards above nil, within the bounds and the fixed values"
            )
        witnesses = [] if optimum.model is None else _witnesses(households, optimum.model)
        return optimum, witnesses

    runs = {"largest": optimise("max"), "smallest": optimise("min")}
    (largest, largest_witnesses), (smallest, smallest_witnesses) = runs.values()
    return JudgementResult(
        point=point,
        status="optimal" if all(o.status == "optimal" for o, _ in runs.values()) else "unknown",
        largest=largest.value,
        largest_status=_status(largest),
        smallest=smallest.value,
        smallest_status=_status(smallest),
        largest_witnesses=largest_witnesses,
        smallest_witnesses=smallest_witnesses,
        fixed=fixed,
        start=start_day,
        verification=_verification(rules, runs),
        versions=largest.versions,
    )
