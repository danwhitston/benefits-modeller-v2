"""The window query: what the timing of earnings does to the award over a window.

A window is a run of consecutive monthly assessment periods of the
`ClaimWindow` scope (3 periods), or of `ClaimWindow4` to `ClaimWindow6` for a
probe. A fixed total of earnings is split between the periods. The query asks,
for each case of what DWP decides, how much more (the gain) or less (the loss)
the award over the window can be through the timing alone, compared with the
even split of the same total; how far apart two splits of the same total can
be (the spread); and what a claimant paid every four weeks gains or loses when
two paydays fall in one period (the extra payday figures). The design is
`docs/superpowers/specs/2026-10-29-nil-assessment-periods-design.md`, sections
"The window and its limits" and "5. Window query".

**Copies.** One script holds several copies of the window, each a household
of the scope with the same facts, case and period starts:

- `split`, `a` and `b`: earnings free in each period, summing to the total;
- `even`: the total split as evenly as possible to the penny, the remainder in
  the earliest periods: `(div W n)` plus 1 in period k when k <= `(mod W n)`;
- `payday`: earnings (P, 2P, P) for a free payday amount P within the
  earnings bound, with the total W = 4P, so that `even` is the same four
  payments spread evenly. Only for 3 periods.

| Figure | Objective | Copies |
|---|---|---|
| gain | total_award(split) - total_award(even), maximised | split, even |
| loss | total_award(even) - total_award(split), maximised | even, split |
| spread | total_award(a) - total_award(b), maximised | a, b, and even |
| extra_payday_max | total_award(even) - total_award(payday), maximised | even, payday |
| extra_payday_min | the same, minimised | even, payday |

Each figure is optimised on its own, in each case, in its own script. The
split may equal the even split, and a may equal b, so the gain, the loss and
the spread are never negative. The spread's script holds an even copy outside
its objective, so that the spread, like the gain and the loss, ranges only
over the households and totals whose even split keeps the last-period rule.

**The last-period rule.** Every copy's award in the last period must be at
least 1p, so that the effects of a nil period (the end of the award, the
reclaim and any surplus) end inside the window, whose exit state is then the
same for every copy: a live award with no surplus. Without the rule the
solver can put the nil period last, where the surplus falls outside the window,
and the gain is overstated. Splits that break the rule are outside every
figure, and the result says so (`excluded`). Where the even split itself
breaks it, the case has no figures. Where the pattern (P, 2P, P) breaks it for
every payday amount, the case has no extra payday figure that keeps the rule.

**Lower bounds.** In a case with no claim after the award ends
(`claim_after_end` false), a loss carries on past the window until a fresh
claim, so no window bounds it. There the copy whose award is subtracted drops
the last-period rule: split in the loss, b in the spread, and payday in
`extra_payday_max`. Those figures are lower bounds (`Figure.lower_bound`). The
even copy, and every copy of the gain and of `extra_payday_min`, keep the rule
in every case.

**Facts and starts.** Household facts the caller does not fix are free, and
shared by every copy (`bm.household.facts`). The judgement points the caller
does not fix are expanded into cases (`bm.strategic.cases`). The first
period starts on a date the caller chooses, and later periods one calendar
month apart (`bm.strategic.period_starts`). Every period must begin on or
before 31 March 2027, so that the surplus earnings threshold is the nil UC
threshold plus 2,500 pounds throughout (the design's reading 6).

For the gain in one case, the script reads:

    (declare-const |fact.aged_25_or_over| Bool)    ; shared facts
    (declare-const |bm.total| Int)                 ; W, fixed or free
    (assert (<= 0 |bm.total| 3000000))
    (declare-const |split.earnings_1| Int)         ; copy split
    ...
    (assert (= |split.claim_after_end| true))      ; the case
    (assert (= (+ |split.earnings_1| |split.earnings_2| |split.earnings_3|) |bm.total|))
    (declare-const |bm.split.award_3| Int)         ; one constant per traced output
    (assert (= |bm.split.award_3| (|award_3| ...)))
    (assert (>= |bm.split.award_3| 1))             ; the last-period rule
    (declare-const |bm.split.total_award| Int)
    ...                                            ; copy even:
    (assert (= |even.earnings_1| (+ (div |bm.total| 3) (ite (<= 1 (mod |bm.total| 3)) 1 0))))
    ...

with the objective `(- |bm.split.total_award| |bm.even.total_award|)`, which
`bm.solvers.optimise_and_confirm` maximises: Z3 searches, and cvc5 confirms
that nothing larger exists. `replay` runs every witness through Catala's
interpreter.

**Probes.** A window longer than 3 periods, and a relaxed translation
(`bm.translate.translate(scope, relaxed=True)`), are refused unless the
caller passes `probe=True`. A probe's results are for measuring solver time
and are never findings. A relaxed probe is not replayed, because Catala rounds
and the relaxed translation does not.
"""

import dataclasses
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from bm import catala_run, solvers, units
from bm.household import Instance, Script, facts, smt_sum
from bm.inputs import Bound, InputSpec, bounds
from bm.strategic import (
    DEFAULT_START,
    NoHousehold,
    QueryRefused,
    ReplayMismatch,
    case_label,
    cases,
    close_fixed,
    judgement_points,
    period_starts,
)
from bm.translate import RELAXED_REFUSAL, SmtModule, literal

SCOPE = "ClaimWindow"
DEFAULT_CASE_CAP = 12
LAST_START = date(2027, 3, 31)
FIGURES = ("gain", "loss", "spread", "extra_payday_max", "extra_payday_min")
REALISTIC = {"claim_after_end": True, "claim_each_month": True, "lcw_carries_over": True}

FINDING_PERIODS = 3
MAX_PERIODS = 6
PAYDAY = ("extra_payday_max", "extra_payday_min")
# The copies of each figure: the objective is the first copy's total award less
# the second's.
_COPIES = {
    "gain": ("split", "even"),
    "loss": ("even", "split"),
    "spread": ("a", "b"),
    "extra_payday_max": ("even", "payday"),
    "extra_payday_min": ("even", "payday"),
}
# Copies a figure's script holds outside its objective.
_ALSO = {"spread": ("even",)}
_DIRECTION: dict[str, Literal["max", "min"]] = {
    name: "min" if name == "extra_payday_min" else "max" for name in _COPIES
}
# The copy that drops the last-period rule, in a case with no claim after the
# end, making the figure a lower bound.
_SUBTRACTED = {"loss": "split", "spread": "b", "extra_payday_max": "payday"}
# The per-period outputs a witness trace records, besides the earnings.
_TRACED = (
    "earnings_used",
    "award",
    "entitled",
    "surplus_after",
    "nil_uc_threshold",
    "relevant_threshold",
)
_EARNINGS = re.compile(r"earnings_([0-9]+)")
_LAST_RULE = (
    "Splits whose last period has an award below 1p are outside every figure"
    " (the last-period rule), so that the effects of a nil period end inside the window."
    " In a case with no claim after the award ends, the copy that the loss, the spread"
    " and extra_payday_max subtract is exempt, and those figures are lower bounds."
)
_RELAXED_SKIP = (
    "skipped: the relaxed translation does not round to the penny, and Catala does,"
    " so the two are not expected to agree"
)


@dataclass(frozen=True)
class PeriodTrace:
    """One period of a copy, in pence, as Z3 found it."""

    earnings: int
    earnings_used: int
    award: int
    entitled: bool
    surplus_after: int
    nil_uc_threshold: int
    relevant_threshold: int


@dataclass(frozen=True)
class CopyWitness:
    """One copy of the window at an optimum."""

    copy: str  # "split", "even", "a", "b" or "payday"
    inputs: dict[str, int | bool]  # every ClaimWindow input, in SMT units
    trace: list[PeriodTrace]


@dataclass(frozen=True)
class Figure:
    """One figure in one case.

    `value` is Z3's optimum in pence, or None where there is none. `status` is
    "optimal" when cvc5 confirmed it; "unknown" when Z3 found no optimum in
    time, or cvc5 could not confirm Z3's (the value is then kept); and
    "infeasible" when both solvers found that no copies keep the last-period
    rule: the even split breaks it, so the case has no figures, or, for an
    extra payday figure, every payday amount does (`WindowResult.excluded`
    says which). "unknown" never means no gain, no loss or no difference.
    `lower_bound` is True where the figure is a lower bound ("at least"): the
    loss, the spread and `extra_payday_max` in a case with no claim after the
    end, whatever the status. `witnesses` hold the copies at the optimum, in
    the order of the objective (not the spread's even copy).
    """

    value: int | None
    status: Literal["optimal", "unknown", "infeasible"]
    lower_bound: bool
    witnesses: list[CopyWitness]


@dataclass(frozen=True)
class CaseResult:
    """The figures in one case of the judgement points.

    `realistic` is True when the case agrees with `REALISTIC` on every point it
    gives a value, and the caller fixed no point of `REALISTIC` otherwise. A
    point the case holds False only because the point it applies to is False
    (such as `lcw_carries_over` without LCW) does not count, since it cannot
    matter there.
    """

    case: dict[str, bool]
    realistic: bool
    figures: dict[str, Figure]


@dataclass(frozen=True)
class WindowResult:
    """The outcome of `window`.

    `status` is "optimal" when every figure is "optimal" or "infeasible", and
    "unknown" otherwise. `starts` are days since 1970-01-01, one per period.
    `total` is the total of earnings when the caller fixed it, and None when it
    was free (each witness then shows its own). `fixed` is the caller's fixed
    values with those that `close_fixed` adds. `cases` are in the order of
    `bm.strategic.cases`, with the realistic ones moved first. `excluded` says
    in words what the last-period rule left out: always a general note on the
    rule first, then one note for each case whose even split breaks it, and
    one for each extra payday figure that no payday amount keeps it for.

    `verification` has "cvc5": "confirmed" when cvc5 confirmed every figure
    (an optimum, or that no copies keep the last-period rule), otherwise
    "unknown";
    and "replay" and "replayed", which `replay` fills in: "not run" until it
    runs.
    """

    status: Literal["optimal", "unknown"]
    periods: int
    probe: bool
    relaxed: bool
    starts: list[int]
    total: int | None
    fixed: dict[str, int | bool]
    cases: list[CaseResult]
    excluded: list[str]
    verification: dict[str, str | list[str]]
    versions: dict[str, str]


def periods_of(module: SmtModule) -> int:
    """The window's length: the number of `earnings_<k>` inputs, for k from 1."""
    found = sorted(int(m[1]) for v in module.inputs if (m := _EARNINGS.fullmatch(v.name)))
    if not found or found != list(range(1, len(found) + 1)):
        raise QueryRefused(
            f"the scope's earnings inputs are {found or 'none'}, not earnings_1 to earnings_n"
        )
    return len(found)


def scope_of(periods: int) -> str:
    """The Catala scope of a window of `periods` periods."""
    return SCOPE if periods == FINDING_PERIODS else f"ClaimWindow{periods}"


def window(
    module: SmtModule,
    specs: dict[str, InputSpec],
    *,
    first_start: date = DEFAULT_START,
    total: int | None = None,
    fixed: dict[str, int | bool] | None = None,
    figures: tuple[str, ...] = FIGURES,
    probe: bool = False,
    cap: int = DEFAULT_CASE_CAP,
    timeout_ms: int = 60_000,
    seed: int | None = None,
) -> WindowResult:
    """Each figure in each case, for a window of the module's length.

    `total` fixes the total of earnings over the window, in pence; it is
    otherwise free within the earnings bound times the number of periods. For
    the extra payday figures the total is 4P: a fixed total fixes P, and must
    be a multiple of 4.
    `fixed` gives household facts or judgement points a value, in SMT units;
    the starts and the earnings cannot be fixed. `timeout_ms` applies to each
    optimisation (one per figure and case). `seed`, when given, is passed to
    every solver check (see `bm.solvers.run`), for probes that measure how
    solver time varies with the search. The result is not replayed: call
    `replay` for that.

    Raises `QueryRefused`, before any solver runs, for a window longer than 3
    periods or a relaxed module without `probe`, an extra payday figure for a
    window longer than 3 periods (even with `probe`) or with a fixed total
    that is not a multiple of 4, a start whose last period is after
    `LAST_START` or outside the inputs' bounds, more cases than `cap`, or
    inputs it cannot answer for. Raises `NoHousehold` when the even split ends
    the window at nil in every case, and `SolverDisagreement` when the solvers
    disagree: cvc5 finds better than Z3's optimum, or one finds copies that
    keep the last-period rule where the other proves there are none.
    """
    for name in figures:
        if name not in FIGURES:
            raise QueryRefused(f"{name} is not a figure; the figures are {', '.join(FIGURES)}")
    if not figures:
        raise QueryRefused("no figures were asked for")
    periods = periods_of(module)
    if not FINDING_PERIODS <= periods <= MAX_PERIODS:
        raise QueryRefused(
            f"a window of {periods} periods is outside {FINDING_PERIODS} to {MAX_PERIODS}"
        )
    payday = [name for name in figures if name in PAYDAY]
    if payday and periods != FINDING_PERIODS:
        raise QueryRefused(
            f"{', '.join(payday)} compare the pattern (P, 2P, P), which needs a window of"
            f" {FINDING_PERIODS} periods, not {periods}"
        )
    if payday and total is not None and total % 4:
        raise QueryRefused(
            f"{', '.join(payday)} need a total of 4P, so a fixed total must be a multiple"
            f" of 4 pence, not {total}"
        )
    if periods > FINDING_PERIODS and not probe:
        raise QueryRefused(
            f"a window of {periods} periods is for a probe only, not a finding:"
            f" findings use {FINDING_PERIODS} periods (pass probe=True)"
        )
    if module.relaxed and not probe:
        raise QueryRefused(f"the window query cannot be answered: {RELAXED_REFUSAL}")
    per_period = {f"{base}_{k}" for base in ("start", "earnings") for k in range(1, periods + 1)}
    given = dict(fixed or {})
    for name in given:
        if name not in specs:
            raise QueryRefused(f"{name} is not an input, so it cannot be fixed")
        if name in per_period:
            raise QueryRefused(f"{name} is set by the query, so it cannot be fixed")
    closed = close_fixed(specs, given)
    points = judgement_points(specs, closed)
    all_cases = cases(specs, points, cap)
    starts = _starts(first_start, specs, periods)
    earnings = specs["earnings_1"].bound
    whole = Bound("money", periods * earnings.min, periods * earnings.max)
    if total is not None and not whole.min <= total <= whole.max:
        raise QueryRefused(
            f"the total {total} is outside {whole.min} to {whole.max} pence,"
            f" {periods} times the earnings bound"
        )

    ordered = sorted(
        ((case, _realistic(specs, given, case)) for case in all_cases), key=lambda c: not c[1]
    )
    build = _Builder(module, specs, closed, starts, periods, total, whole, seed)
    for case in all_cases:
        build.claim_after_end(case)  # refuses, before any solver, where it has no value
    results = []
    excluded = [_LAST_RULE]
    whom = _whom(given, total)
    for case, realistic in ordered:
        found = {name: build.figure(name, case, timeout_ms) for name in figures}
        if build.even_verdict(case) == "excluded":
            # Both solvers proved that the even copy alone breaks the rule, so
            # no figure of the case has copies that keep it, even one whose own
            # optimisation was unknown.
            found = {
                name: dataclasses.replace(f, status="infeasible", value=None, witnesses=[])
                for name, f in found.items()
            }
            excluded.append(
                f"In the case {case_label(case)}, the even split ends the window at nil"
                f" for {whom}, so the case has no figures."
            )
        else:
            excluded.extend(
                f"In the case {case_label(case)}, no payday amount P keeps the last-period"
                f" rule on the even split of 4P and the pattern (P, 2P, P) for {whom},"
                f" so the case has no {name}."
                for name, f in found.items()
                if f.status == "infeasible"
            )
        results.append(CaseResult(case, realistic, found))
    every = [f for c in results for f in c.figures.values()]
    if all(build.even_verdict(c.case) == "excluded" for c in results):
        raise NoHousehold(
            f"the even split ends the window at nil in every case, for {_whom(given, total)}:"
            " its last period has an award below 1p, which the last-period rule excludes"
        )
    definite = all(f.status in ("optimal", "infeasible") for f in every)
    return WindowResult(
        status="optimal" if definite else "unknown",
        periods=periods,
        probe=probe,
        relaxed=module.relaxed,
        starts=starts,
        total=total,
        fixed=closed,
        cases=results,
        excluded=excluded,
        verification={
            "cvc5": "confirmed" if definite else "unknown",
            "replay": _RELAXED_SKIP if module.relaxed else "not run",
            "replayed": [],
        },
        versions=solvers.versions(),
    )


def _starts(first: date, specs: dict[str, InputSpec], periods: int) -> list[int]:
    """The period starts in days, refused after `LAST_START` or outside their bounds."""
    anywhere = Bound("date", units.days(date(1900, 1, 1)), units.days(date(2999, 12, 31)))
    dates = period_starts(first, anywhere, periods)
    if dates[-1] > LAST_START:
        raise QueryRefused(
            f"the window's last period would start on {dates[-1].isoformat()}, after"
            f" {LAST_START.isoformat()}: every period must begin on or before 31 March 2027,"
            " while the surplus earnings threshold is the nil UC threshold plus 2,500 pounds"
        )
    period_starts(first, specs["start_1"].bound, periods)  # refuses a start outside the bound
    for k, start in enumerate(dates, start=1):
        bound = specs[f"start_{k}"].bound
        if not bound.min <= units.days(start) <= bound.max:
            raise QueryRefused(f"start_{k}, {start.isoformat()}, is outside its bound")
    return [units.days(d) for d in dates]


def _realistic(specs: dict[str, InputSpec], given: dict[str, int | bool], case: dict) -> bool:
    for name, value in REALISTIC.items():
        if name in given:
            if given[name] != value:
                return False
            continue
        if name not in case:
            continue
        parent = specs[name].applies_when if name in specs else None
        if parent is not None and not case.get(parent, given.get(parent, True)):
            continue  # held False because it does not apply
        if case[name] != value:
            return False
    return True


def _whom(given: dict[str, int | bool], total: int | None) -> str:
    household = "the fixed values" if given else "every household within the bounds"
    return f"{household} and {'the fixed total' if total is not None else 'every total'}"


@dataclass(frozen=True)
class _Copy:
    name: str
    instance: Instance
    trace: dict[tuple[str, int], str]  # (output, period) to its quoted constant
    total: str  # the quoted constant holding total_award


class _Builder:
    """Builds and optimises the scripts of one query."""

    def __init__(self, module, specs, fixed, starts, periods, total, whole, seed=None):
        self.module = module
        self.specs = specs
        self.fixed = fixed
        self.starts = starts
        self.periods = periods
        self.total = total
        self.whole = whole
        self.seed = seed
        self.money = module.sorts["earnings_1"]  # Int, or Real when relaxed
        self._even_ok: dict[tuple, Literal["ok", "excluded", "unknown"]] = {}

    def _script(self, case: dict[str, bool]) -> tuple[Script, dict[str, str], str]:
        script = Script(self.module, bounds(self.specs))
        per_period = {f"{b}_{k}" for b in ("start", "earnings") for k in range(1, self.periods + 1)}
        shared = facts(script, self.specs, self.fixed, per_period | set(case))
        whole = script.declare(
            "bm.total", "Int", None if self.total is None else literal("Int", self.total)
        )
        if self.total is None:
            script.bound(whole, self.whole)
        base = {
            **shared,
            **{f"start_{k}": literal("Int", s) for k, s in enumerate(self.starts, start=1)},
            **{name: literal("Bool", value) for name, value in case.items()},
        }
        return script, base, whole

    def _as_money(self, term: str) -> str:
        return term if self.money == "Int" else f"(to_real {term})"

    def _copy(
        self,
        script: Script,
        name: str,
        base: dict[str, str],
        whole: str,
        pay: str | None = None,
        last_rule: bool = True,
    ) -> _Copy:
        n = self.periods
        if name == "payday":
            pattern = {1: pay, 2: f"(* 2 {pay})", 3: pay}
            shares = {f"earnings_{k}": self._as_money(term) for k, term in pattern.items()}
            instance = script.instance(name, equal={**base, **shares})
        elif name == "even":
            shares = {
                f"earnings_{k}": self._as_money(
                    f"(+ (div {whole} {n}) (ite (<= {k} (mod {whole} {n})) 1 0))"
                )
                for k in range(1, n + 1)
            }
            instance = script.instance(name, equal={**base, **shares})
        else:
            instance = script.instance(name, equal=base)
            paid = smt_sum([instance.inputs[f"earnings_{k}"] for k in range(1, n + 1)])
            script.add(f"(assert (= {paid} {self._as_money(whole)}))")
        outputs = self.module.outputs
        trace = {
            (out, k): script.declare(
                f"bm.{name}.{out}_{k}", outputs[f"{out}_{k}"], instance.output(f"{out}_{k}")
            )
            for k in range(1, n + 1)
            for out in _TRACED
        }
        total = script.declare(
            f"bm.{name}.total_award", outputs["total_award"], instance.output("total_award")
        )
        if last_rule:
            last = trace["award", n]
            script.add(f"(assert (>= {last} {literal(outputs[f'award_{n}'], 1)}))")
        return _Copy(name, instance, trace, total)

    def claim_after_end(self, case: dict[str, bool]) -> bool:
        value = case.get("claim_after_end", self.fixed.get("claim_after_end"))
        if not isinstance(value, bool):
            raise QueryRefused(
                "claim_after_end is neither fixed nor a judgement point of the case,"
                " so the lower-bound rule cannot be applied"
            )
        return value

    def _seeded(self) -> dict[str, int]:
        """The `seed` keyword for a solver call, or nothing where the caller gave none."""
        return {} if self.seed is None else {"seed": self.seed}

    def even_verdict(self, case: dict[str, bool]) -> str | None:
        """The even-copy check's verdict for the case, or None where it has not run."""
        return self._even_ok.get(tuple(sorted(case.items())))

    def figure(self, name: str, case: dict[str, bool], timeout_ms: int) -> Figure:
        lower = name in _SUBTRACTED and not self.claim_after_end(case)
        if self.even_verdict(case) == "excluded":
            return Figure(None, "infeasible", lower, [])
        script, base, whole = self._script(case)
        pay = None
        if name in PAYDAY:
            pay = script.declare(
                "bm.payday", "Int", None if self.total is None else literal("Int", self.total // 4)
            )
            script.bound(pay, self.specs["earnings_1"].bound)
            script.add(f"(assert (= {whole} (* 4 {pay})))")
        dropped = _SUBTRACTED[name] if lower else None
        copies = [
            self._copy(script, copy, base, whole, pay, last_rule=copy != dropped)
            for copy in _COPIES[name]
        ]
        for copy in _ALSO.get(name, ()):
            self._copy(script, copy, base, whole, pay)
        objective = f"(- {copies[0].total} {copies[1].total})"
        what = f"in the case {case_label(case)}"
        direction = _DIRECTION[name]
        beyond = "above Z3's maximum" if direction == "max" else "below Z3's minimum"
        optimum = solvers.optimise_and_confirm(
            script.lines,
            objective,
            direction,
            timeout_ms,
            f"a {name} {beyond} {what}",
            sort=self.money,
            **self._seeded(),
        )
        if optimum.status == "infeasible":
            even = self._even(case, timeout_ms)
            if even == "excluded":
                return Figure(None, "infeasible", lower, [])
            if even == "unknown":
                return Figure(None, "unknown", lower, [])
            if name not in PAYDAY:
                raise RuntimeError(
                    f"the even split keeps the last-period rule {what}, but no copies of the"
                    f" {name} do: they can all equal the even split, so this is a bug in the"
                    " encoding"
                )
            # The pattern (P, 2P, P) can break the rule where the even split keeps it.
            found = self._unsat(
                script.text(), timeout_ms, f"whether any payday amount has a {name} {what}"
            )
            if found == "sat":
                raise RuntimeError(
                    f"Z3 first found no payday amount with a {name} {what}, and then both"
                    " solvers found one"
                )
            return Figure(None, "infeasible" if found == "unsat" else "unknown", lower, [])
        witnesses = [] if optimum.model is None else [_witness(c, optimum.model) for c in copies]
        status = "optimal" if optimum.status == "optimal" else "unknown"
        return Figure(optimum.value, status, lower, witnesses)

    def _unsat(self, text: str, timeout_ms: int, what: str) -> Literal["sat", "unsat", "unknown"]:
        """Whether a script is unsat: both solvers must agree, or the answer is unknown."""
        reals = self.money == "Real"
        z3_result = solvers.run("z3", text, timeout_ms, reals=reals, **self._seeded())
        cvc5_result = solvers.run("cvc5", text, timeout_ms, reals=reals, **self._seeded())
        if {z3_result.status, cvc5_result.status} == {"sat", "unsat"}:
            raise solvers.SolverDisagreement(z3_result, cvc5_result, what)
        if z3_result.status == cvc5_result.status and z3_result.status in ("sat", "unsat"):
            return z3_result.status
        return "unknown"

    def _even(self, case: dict[str, bool], timeout_ms: int) -> str:
        """Whether the even copy alone keeps the last-period rule: both solvers must agree."""
        key = tuple(sorted(case.items()))
        if key not in self._even_ok:
            script, base, whole = self._script(case)
            self._copy(script, "even", base, whole)
            found = self._unsat(
                script.text(), timeout_ms, f"whether the even split ends the window at nil {case}"
            )
            self._even_ok[key] = {"unsat": "excluded", "sat": "ok", "unknown": "unknown"}[found]
        return self._even_ok[key]


def _witness(copy: _Copy, model: solvers.Model) -> CopyWitness:
    def value(const: str):
        return model[const[1:-1]]

    n = max(k for _, k in copy.trace)
    trace = [
        PeriodTrace(
            earnings=value(copy.instance.inputs[f"earnings_{k}"]),
            **{out: value(copy.trace[out, k]) for out in _TRACED},
        )
        for k in range(1, n + 1)
    ]
    return CopyWitness(copy.name, copy.instance.household(model), trace)


def replay(rules: Path, result: WindowResult) -> None:
    """Run every witness through Catala's interpreter; each traced value must equal Z3's.

    Every period's earnings used, award, entitlement, surplus and thresholds
    are compared. Raises `ReplayMismatch`, naming the figure, case, copy and
    output, at the first difference, or where Catala stops with an error.
    Either is a translator bug. Records what ran in `result.verification`:
    "replay" is "matched" when every figure with witnesses was replayed and
    no figure lacked them, "matched in part" when some figure had none (Z3
    found no optimum), and "not run" when none was replayed. A relaxed result
    is not replayed, and is recorded as skipped.
    """
    if result.relaxed:
        result.verification["replay"] = _RELAXED_SKIP
        result.verification["replayed"] = []
        return
    scope = scope_of(result.periods)
    replayed, wanted = [], 0
    for case in result.cases:
        for name, figure in case.figures.items():
            if figure.status == "infeasible":
                continue  # no witness exists to replay
            wanted += 1
            if not figure.witnesses:
                continue
            what = f"the {name} in the case {case_label(case.case)}"
            for witness in figure.witnesses:
                _replay_copy(rules, scope, what, witness)
            replayed.append(f"{name}, {case_label(case.case)}")
    if not replayed:
        outcome = "not run"
    else:
        outcome = "matched" if len(replayed) == wanted else "matched in part"
    result.verification["replay"] = outcome
    result.verification["replayed"] = replayed


def _replay_copy(rules: Path, scope: str, what: str, witness: CopyWitness) -> None:
    where = f"{what}, copy {witness.copy}, inputs {witness.inputs}"
    try:
        found = catala_run.outputs(rules, scope, witness.inputs)
    except catala_run.CatalaRuntimeError as error:
        raise ReplayMismatch(f"at {where}: Catala stops with an error") from error
    for k, period in enumerate(witness.trace, start=1):
        for out in _TRACED:
            catala, z3_value = found[f"{out}_{k}"], getattr(period, out)
            if catala != z3_value or type(catala) is not type(z3_value):
                raise ReplayMismatch(
                    f"at {where}: Catala gives {out}_{k} = {catala!r}, Z3 {z3_value!r}"
                )
