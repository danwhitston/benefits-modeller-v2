"""Households for the three-way check (see `bm.checks`).

`generate` returns, in this order and without repeats:

1. The nine rows of `rules/uc_tests.catala_en`, each starting on 1 May 2026.
2. For each age band and LCW combination, the work allowance and 1p either
   side of it. The allowance is read from the translated rules, so it is 0
   without LCW and the 1p below it falls outside the bounds and is dropped.
3. For each combination, the last-penny earnings: the smallest earnings at
   which the award is 0, and 1p less, where the award is the last penny.
   Z3 finds the first by minimising earnings subject to an award of 0 and no
   obligation holding (`last_penny_earnings`), and cvc5 confirms that no
   smaller earnings give an award of 0.
4. `n_random` households drawn with `random.Random(seed)`. For each, the two
   booleans are drawn first, each true with probability one half, then the
   start date uniformly from its bounds, then earnings uniformly from the
   lower bound up to that combination's last-penny earnings plus 100 pounds
   (or the upper bound, if lower). So most random households have an award
   above 0 and reach the taper, and some past the last penny have none.

Every value is a Python `int` or `bool`, in SMT units: pence, and days since
1970-01-01. Values from Z3 are converted explicitly.
"""

import random
from datetime import date
from pathlib import Path

from bm import evaluate, ir, solvers, translate
from bm.bounds import Bound
from bm.coverage import declarations
from bm.translate import SmtModule, apply, literal, quote

ROOT = Path(__file__).resolve().parents[2]
UC_IR = ROOT / "build" / "uc.bm-ir.json"
EPOCH = date(1970, 1, 1)
AWARD = "bm.award"

# The test scopes of rules/uc_tests.catala_en all start on this date.
TABLE_START = date(2026, 5, 1)
# Random earnings run up to the last-penny earnings plus this, in pence.
RANDOM_MARGIN = 10_000
# (earned income in pence, aged 25 or over, has LCW), in file order.
# `test_table_rows_match_catala_tests` checks these against the file.
TABLE_ROWS = [
    (0, True, True),
    (71_000, True, True),
    (100_000, True, True),
    (71_010, True, True),
    (71_001, True, True),
    (148_253, True, True),
    (148_254, True, True),
    (50_000, True, False),
    (100_000, False, False),
]
COMBINATIONS = [(aged_25, lcw) for aged_25 in (True, False) for lcw in (True, False)]


class NoLastPenny(RuntimeError):
    """The solver found no earnings in the bounds with an award of 0, or ran out of time."""


def _household(start: date, earned: int, aged_25: bool, lcw: bool) -> dict[str, int | bool]:
    return {
        "assessment_period_start": int((start - EPOCH).days),
        "earned_income": int(earned),
        "aged_25_or_over": bool(aged_25),
        "has_lcw": bool(lcw),
    }


def _uc_module() -> SmtModule:
    return translate.translate(ir.load(UC_IR))


def last_penny_earnings(
    module: SmtModule,
    bounds: dict[str, Bound],
    aged_25_or_over: bool,
    has_lcw: bool,
    start: date = TABLE_START,
    timeout_ms: int = 60_000,
) -> int:
    """The smallest earnings in the bounds at which the award is 0.

    Every other input is fixed, and every obligation is asserted false, so the
    household is one at which Catala returns a value. Raises `NoLastPenny` if
    there is none or Z3 runs out of time, and `SolverDisagreement` if cvc5
    finds smaller earnings with an award of 0.
    """
    sorts = {v.name: translate.SORTS[v.type] for v in module.inputs}
    args = [quote(name) for name in sorts]
    fixed = {
        "assessment_period_start": int((start - EPOCH).days),
        "aged_25_or_over": bool(aged_25_or_over),
        "has_lcw": bool(has_lcw),
    }
    lines = [module.text, *declarations(module, bounds)]
    for name, value in fixed.items():
        lines.append(f"(assert (= {quote(name)} {literal(sorts[name], value)}))")
    for ob in module.obligations:
        lines.append(f"(assert (not {ob.formula}))")
    lines.append(f"(declare-const {quote(AWARD)} Int)")
    lines.append(f"(assert (= {quote(AWARD)} {apply(module.functions['award'], args)}))")
    lines.append(f"(assert (= {quote(AWARD)} 0))")
    earned = quote("earned_income")

    z3_result = solvers.run(
        "z3", "\n".join([*lines, f"(minimize {earned})", "(check-sat)"]) + "\n", timeout_ms
    )
    if z3_result.status != "sat":
        raise NoLastPenny(
            f"z3 says {z3_result.status} for an award of 0 at {fixed}; expected a household"
        )
    found = int(z3_result.model["earned_income"])

    smaller = f"(assert (< {earned} {literal('Int', found)}))"
    cvc5_result = solvers.run("cvc5", "\n".join([*lines, smaller, "(check-sat)"]) + "\n", timeout_ms)
    if cvc5_result.status == "sat":
        raise solvers.SolverDisagreement(
            z3_result, cvc5_result, f"cvc5 finds an award of 0 below earnings of {found} at {fixed}"
        )
    if cvc5_result.status == "unknown":
        raise NoLastPenny(f"cvc5 could not confirm {found} as the smallest at {fixed}")
    return found


def generate(
    bounds: dict[str, Bound],
    n_random: int,
    seed: int,
    module: SmtModule | None = None,
) -> list[dict[str, int | bool]]:
    """The households described in the module docstring, without repeats.

    `module` is the translated UniversalCredit scope; by default it is read
    from build/uc.bm-ir.json (`make export`).
    """
    module = module or _uc_module()
    found: list[dict[str, int | bool]] = []
    for earned, aged_25, lcw in TABLE_ROWS:
        found.append(_household(TABLE_START, earned, aged_25, lcw))

    for aged_25, lcw in COMBINATIONS:
        at_nil = _household(TABLE_START, 0, aged_25, lcw)
        allowance = int(evaluate.outputs(module, at_nil)["work_allowance"])
        for earned in (allowance - 1, allowance, allowance + 1):
            found.append(_household(TABLE_START, earned, aged_25, lcw))
    zeros = {
        (aged_25, lcw): last_penny_earnings(module, bounds, aged_25, lcw)
        for aged_25, lcw in COMBINATIONS
    }
    for (aged_25, lcw), zero in zeros.items():
        for earned in (zero - 1, zero):
            found.append(_household(TABLE_START, earned, aged_25, lcw))
    found = [h for h in found if _within(h, bounds)]

    rng = random.Random(seed)
    dates, earnings = bounds["assessment_period_start"], bounds["earned_income"]
    for _ in range(n_random):
        aged_25 = bool(rng.random() < 0.5)
        lcw = bool(rng.random() < 0.5)
        start = int(rng.randint(dates.min, dates.max))
        top = min(earnings.max, zeros[(aged_25, lcw)] + RANDOM_MARGIN)
        found.append(
            {
                "assessment_period_start": start,
                "earned_income": int(rng.randint(earnings.min, top)),
                "aged_25_or_over": aged_25,
                "has_lcw": lcw,
            }
        )

    unique: dict[tuple, dict[str, int | bool]] = {}
    for h in found:
        unique.setdefault(tuple(sorted(h.items())), h)
    return list(unique.values())


def _within(h: dict[str, int | bool], bounds: dict[str, Bound]) -> bool:
    return all(b.min <= h[name] <= b.max for name, b in bounds.items())
