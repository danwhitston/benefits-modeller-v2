"""Queries over a translated scope.

`emr` finds the peak effective marginal rate: the largest fall in an output
when earnings rise by a fixed step. The scope's functions (see `bm.translate`)
are applied twice, once at earnings *e* and once at *e* + delta, with the other
inputs shared. Both applications must be households at which Catala returns a
value, so every obligation is asserted false at each. Z3 maximises the fall,
and cvc5 is then asked whether any larger fall exists, which it must deny.

The script has this shape (inputs a, e, b, c; earnings e; delta 100):

    <module.text>
    (define-fun |bm.obligation.0| ((|a| Int) (|e| Int) ...) Bool <formula>)
    (declare-const |a| Int) ...                 ; the household, bounded
    (assert (<= 0 (+ |e| 100) 1000000))         ; e + delta in the bounds too
    (assert (not (|bm.obligation.0| |a| |e| |b| |c|)))
    (assert (not (|bm.obligation.0| |a| (+ |e| 100) |b| |c|)))
    (declare-const |bm.at_e| Int)
    (assert (= |bm.at_e| (|award| |a| |e| |b| |c|)))
    (declare-const |bm.at_e_plus_delta| Int)
    (assert (= |bm.at_e_plus_delta| (|award| |a| (+ |e| 100) |b| |c|)))
    (maximize (- |bm.at_e| |bm.at_e_plus_delta|))
"""

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from bm import solvers
from bm.inputs import Bound
from bm.coverage import declarations
from bm.translate import SORTS, SmtModule, apply, literal, quote

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
    """
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

    e = quote(earnings_input)
    e_plus = f"(+ {e} {literal('Int', delta)})"
    args = [quote(name) for name in sorts]
    args_plus = [e_plus if a == e else a for a in args]
    params = "(" + " ".join(f"({quote(n)} {s})" for n, s in sorts.items()) + ")"

    lines = [module.text]
    for i, ob in enumerate(module.obligations):
        lines.append(f"(define-fun |bm.obligation.{i}| {params} Bool {ob.formula})")
    lines += declarations(module, bounds)
    ranges = [bounds[earnings_input]] if earnings_input in bounds else []
    if earnings_range is not None:
        ranges.append(Bound(sorts[earnings_input], *earnings_range))
    for r in ranges:
        lo, hi = literal("Int", r.min), literal("Int", r.max)
        lines.append(f"(assert (<= {lo} {e} {hi}))")
        lines.append(f"(assert (<= {lo} {e_plus} {hi}))")
    for name, value in fixed.items():
        lines.append(f"(assert (= {quote(name)} {literal(sorts[name], value)}))")
    for i in range(len(module.obligations)):
        lines.append(f"(assert (not {apply(f'|bm.obligation.{i}|', args)}))")
        lines.append(f"(assert (not {apply(f'|bm.obligation.{i}|', args_plus)}))")
    function = module.functions[output]
    for name, at in ((AT_E, args), (AT_E_PLUS_DELTA, args_plus)):
        lines.append(f"(declare-const {quote(name)} Int)")
        lines.append(f"(assert (= {quote(name)} {apply(function, at)}))")
    fall = f"(- {quote(AT_E)} {quote(AT_E_PLUS_DELTA)})"

    maximise = "\n".join([*lines, f"(maximize {fall})", "(check-sat)"]) + "\n"
    z3_result = solvers.run("z3", maximise, timeout_ms)
    if z3_result.status == "unknown":
        return _unknown()
    if z3_result.status == "unsat":
        raise NoHousehold(
            "no household in the bounds has a value at both e and e + delta;"
            " run the coverage check"
        )
    model = z3_result.model
    at_e, at_e_plus = model[AT_E], model[AT_E_PLUS_DELTA]
    drop = at_e - at_e_plus

    confirm = "\n".join([*lines, f"(assert (> {fall} {literal('Int', drop)}))", "(check-sat)"])
    cvc5_result = solvers.run("cvc5", confirm + "\n", timeout_ms)
    if cvc5_result.status == "sat":
        raise solvers.SolverDisagreement(
            z3_result, cvc5_result, f"cvc5 finds a fall in {output} larger than {drop}"
        )
    # If cvc5 cannot settle it, Z3's maximum stands unconfirmed.
    return EmrResult(
        status="found" if cvc5_result.status == "unsat" else "unknown",
        rate=Fraction(drop, delta),
        drop=drop,
        household={name: model[name] for name in sorts},
        award_at_e=at_e,
        award_at_e_plus_delta=at_e_plus,
        solver_versions={"z3": z3_result.version, "cvc5": cvc5_result.version},
    )
