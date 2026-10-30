"""Queries over a translated scope.

`emr` finds the peak effective marginal rate: the largest fall in an output
when earnings rise by a fixed step. The scope's functions (see `bm.translate`)
are applied twice, once at earnings *e* and once at *e* + delta, with the other
inputs shared. Both applications must be households at which Catala returns a
value, so every obligation is asserted false at each. Z3 maximises the fall,
and cvc5 is then asked whether any larger fall exists, which it must deny.

The script (see `bm.household`) holds two households: the plain one, at e,
and `plus`, whose earnings are e + delta and whose other inputs equal the plain
household's. Both are within the bounds, and within `earnings_range` if given.
With earnings e and delta 100, it ends:

    (declare-const |bm.at_e| Int)
    (assert (= |bm.at_e| (|award| |a| |e| |b| |c|)))
    (declare-const |bm.at_e_plus_delta| Int)
    (assert (= |bm.at_e_plus_delta| (|award| |plus.a| |plus.e| |plus.b| |plus.c|)))

and `bm.solvers.optimise_and_confirm` maximises (- |bm.at_e| |bm.at_e_plus_delta|).
"""

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from bm import solvers
from bm.household import Script
from bm.inputs import Bound
from bm.translate import RELAXED_REFUSAL, SORTS, SmtModule, literal, quote

AT_E = "bm.at_e"
AT_E_PLUS_DELTA = "bm.at_e_plus_delta"


class NoHousehold(ValueError):
    """No household in the bounds has a value at both e and e + delta."""


@dataclass(frozen=True)
class EmrResult:
    status: Literal["found", "unknown"]
    rate: Fraction | None
    drop: int | None
    # Every input of the scope at e, in SMT units (pence, days since 1970-01-01).
    household: dict[str, int | bool] | None
    award_at_e: int | None
    award_at_e_plus_delta: int | None
    solver_versions: dict[str, str]


def _unknown() -> EmrResult:
    return EmrResult("unknown", None, None, None, None, None, solvers.versions())


def emr(
    module: SmtModule,
    bounds: dict[str, Bound],
    earnings_input: str = "earned_income",
    output: str = "award",
    delta: int = 100,
    fixed: dict[str, int | bool] | None = None,
    earnings_range: tuple[int, int] | None = None,
    timeout_ms: int = 60_000,
) -> EmrResult:
    """The largest fall in `output` when `earnings_input` rises by `delta`.

    Raises `NoHousehold` if no household in the bounds (with `fixed` and
    `earnings_range`) has a value at both e and e + delta, and
    `SolverDisagreement` if cvc5 finds a larger fall than Z3's maximum.
    If Z3 runs out of time the status is `unknown` and every other field is
    None. If cvc5 does, the status is `unknown` but Z3's maximum is returned.
    Raises `ValueError` for a relaxed module, which is not the rules.
    """
    if module.relaxed:
        raise ValueError(f"emr cannot be answered: {RELAXED_REFUSAL}")
    sorts = {v.name: SORTS[v.type] for v in module.inputs}
    if sorts.get(earnings_input) != "Int":
        raise ValueError(f"{earnings_input} is not a money, integer or date input")
    if module.outputs.get(output) != "Int":
        raise ValueError(f"{output} is not a money or integer output")
    if delta <= 0:
        raise ValueError("delta must be positive")
    fixed = fixed or {}
    if unknown := sorted(set(fixed) - set(sorts)):
        raise ValueError(f"fixed values for unknown inputs {unknown}")

    script = Script(module, bounds)
    at_e = script.instance(fixed=fixed)
    e = at_e.inputs[earnings_input]
    plus = script.instance(
        "plus",
        equal={
            name: f"(+ {e} {literal('Int', delta)})" if name == earnings_input else const
            for name, const in at_e.inputs.items()
        },
    )
    if earnings_range is not None:
        lo, hi = earnings_range
        for household in (at_e, plus):
            script.bound(household.inputs[earnings_input], Bound(sorts[earnings_input], lo, hi))
    for name, household in ((AT_E, at_e), (AT_E_PLUS_DELTA, plus)):
        script.declare(name, "Int", household.output(output))
    fall = f"(- {quote(AT_E)} {quote(AT_E_PLUS_DELTA)})"

    optimum = solvers.optimise_and_confirm(
        script.lines, fall, "max", timeout_ms, f"a fall in {output} larger than Z3's maximum"
    )
    if optimum.status == "infeasible":
        raise NoHousehold(
            "no household in the bounds has a value at both e and e + delta;"
            " run the coverage check"
        )
    if optimum.value is None:
        return _unknown()
    model = optimum.model
    drop = optimum.value
    # If cvc5 could not settle it, Z3's maximum stands unconfirmed.
    return EmrResult(
        status="found" if optimum.confirmed else "unknown",
        rate=Fraction(drop, delta),
        drop=drop,
        household=at_e.household(model),
        award_at_e=model[AT_E],
        award_at_e_plus_delta=model[AT_E_PLUS_DELTA],
        solver_versions=optimum.versions,
    )
