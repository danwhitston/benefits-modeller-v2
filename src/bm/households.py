"""Households for the three-way check (see `bm.checks`).

`generate` returns, in this order and without repeats:

1. The fourteen rows of `rules/uc_tests.catala_en` that test the
   `UniversalCredit` scope, each starting on 1 May 2026.
2. For each age band and LCW combination, and for a housing costs element of
   0 and of 500.00 pounds, the work allowance and 1p either side of it. The
   allowance is read from the translated rules, so it is 0 without LCW and
   the 1p below it falls outside the bounds and is dropped. With LCW it is
   710.00 pounds without an element and 427.00 with one.
3. For each of those combinations, the last-penny earnings: the smallest
   earnings at which the award is 0, and 1p less, where the award is the
   last penny. Z3 finds the first by minimising earnings subject to an award
   of 0 and no obligation holding (`last_penny_earnings`), and cvc5 confirms
   that no smaller earnings give an award of 0.
4. For each age band, with LCW, a housing costs element of 1p at earnings 0:
   the smallest element that is above 0.
5. `n_random` households drawn with `random.Random(seed)`. For each, the two
   booleans are drawn first, each true with probability one half, then the
   housing costs element (0 with probability one half, otherwise uniformly
   from its bounds), then the start date uniformly from its bounds, then
   earnings uniformly from the lower bound up to that household's last-penny
   earnings (found for its age band, LCW and element) plus 100 pounds (or the
   upper bound, if lower). So most random households have an award above 0
   and reach the taper, and some past the last penny have none.

Every value is a Python `int` or `bool`, in SMT units: pence, and days since
1970-01-01. Values from Z3 are converted explicitly.
"""

import random
from datetime import date
from pathlib import Path

from bm import evaluate, ir, solvers, translate, units
from bm.household import Script
from bm.inputs import Bound
from bm.translate import SmtModule

ROOT = Path(__file__).resolve().parents[2]
UC_IR = ROOT / "build" / "uc.bm-ir.json"
AWARD = "bm.award"

# The test scopes of rules/uc_tests.catala_en all start on this date.
TABLE_START = date(2026, 5, 1)
# The housing costs element of the boundary rows, in pence: 500.00 pounds.
HOUSING_BOUNDARY = 50_000
# Random earnings run up to the last-penny earnings plus this, in pence.
RANDOM_MARGIN = 10_000
# (earned income in pence, aged 25 or over, has LCW, housing costs element in
# pence), in file order.
# `test_table_rows_match_catala_tests` checks these against the file.
TABLE_ROWS = [
    (0, True, True, 0),
    (71_000, True, True, 0),
    (100_000, True, True, 0),
    (71_010, True, True, 0),
    (71_001, True, True, 0),
    (148_253, True, True, 0),
    (148_254, True, True, 0),
    (50_000, True, False, 0),
    (100_000, False, False, 0),
    (0, True, True, 50_000),
    (100_000, True, True, 50_000),
    (42_710, True, True, 50_000),
    (100_000, True, False, 50_000),
    (100_000, True, True, 1),
]
COMBINATIONS = [(aged_25, lcw) for aged_25 in (True, False) for lcw in (True, False)]


class NoLastPenny(RuntimeError):
    """The solver found no earnings in the bounds with an award of 0, or ran out of time."""


def _household(
    start: date, earned: int, aged_25: bool, lcw: bool, housing: int = 0
) -> dict[str, int | bool]:
    return {
        "assessment_period_start": units.days(start),
        "earned_income": int(earned),
        "aged_25_or_over": bool(aged_25),
        "has_lcw": bool(lcw),
        "housing_costs_element": int(housing),
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
    housing_costs_element: int = 0,
) -> int:
    """The smallest earnings in the bounds at which the award is 0.

    Every other input is fixed, and every obligation is asserted false, so the
    household is one at which Catala returns a value. Raises `NoLastPenny` if
    there is none or Z3 runs out of time, and `SolverDisagreement` if cvc5
    finds smaller earnings with an award of 0.
    """
    fixed = {
        "assessment_period_start": units.days(start),
        "aged_25_or_over": bool(aged_25_or_over),
        "has_lcw": bool(has_lcw),
        "housing_costs_element": int(housing_costs_element),
    }
    script = Script(module, bounds)
    household = script.instance(fixed=fixed)
    award = script.declare(AWARD, "Int", household.output("award"))
    script.add(f"(assert (= {award} 0))")
    earned = household.inputs["earned_income"]

    optimum = solvers.optimise_and_confirm(
        script.lines, earned, "min", timeout_ms, f"an award of 0 at {fixed}"
    )
    if optimum.status != "optimal":
        raise NoLastPenny(
            f"{optimum.status} for the smallest earnings with an award of 0 at {fixed};"
            " expected a household confirmed by both solvers"
        )
    return int(optimum.value)


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
    for earned, aged_25, lcw, housing in TABLE_ROWS:
        found.append(_household(TABLE_START, earned, aged_25, lcw, housing))

    elements = (0, HOUSING_BOUNDARY)
    for aged_25, lcw in COMBINATIONS:
        for housing in elements:
            at_nil = _household(TABLE_START, 0, aged_25, lcw, housing)
            allowance = int(evaluate.outputs(module, at_nil)["work_allowance"])
            for earned in (allowance - 1, allowance, allowance + 1):
                found.append(_household(TABLE_START, earned, aged_25, lcw, housing))
    for aged_25 in (True, False):
        found.append(_household(TABLE_START, 0, aged_25, True, 1))
    # Last-penny earnings by (aged 25 or over, LCW, housing costs element).
    # The random households add the elements they draw as they go.
    zeros: dict[tuple[bool, bool, int], int] = {}

    def zero_at(aged_25: bool, lcw: bool, housing: int) -> int:
        key = (aged_25, lcw, housing)
        if key not in zeros:
            zeros[key] = last_penny_earnings(
                module, bounds, aged_25, lcw, housing_costs_element=housing
            )
        return zeros[key]

    for aged_25, lcw in COMBINATIONS:
        for housing in elements:
            zero = zero_at(aged_25, lcw, housing)
            for earned in (zero - 1, zero):
                found.append(_household(TABLE_START, earned, aged_25, lcw, housing))
    found = [h for h in found if _within(h, bounds)]

    rng = random.Random(seed)
    dates, earnings = bounds["assessment_period_start"], bounds["earned_income"]
    housing_bound = bounds["housing_costs_element"]
    for _ in range(n_random):
        aged_25 = bool(rng.random() < 0.5)
        lcw = bool(rng.random() < 0.5)
        housing = 0 if rng.random() < 0.5 else int(rng.randint(housing_bound.min, housing_bound.max))
        start = int(rng.randint(dates.min, dates.max))
        top = min(earnings.max, zero_at(aged_25, lcw, housing) + RANDOM_MARGIN)
        found.append(
            {
                "assessment_period_start": start,
                "earned_income": int(rng.randint(earnings.min, top)),
                "aged_25_or_over": aged_25,
                "has_lcw": lcw,
                "housing_costs_element": housing,
            }
        )

    unique: dict[tuple, dict[str, int | bool]] = {}
    for h in found:
        unique.setdefault(tuple(sorted(h.items())), h)
    return list(unique.values())


def _within(h: dict[str, int | bool], bounds: dict[str, Bound]) -> bool:
    return all(b.min <= h[name] <= b.max for name, b in bounds.items())
