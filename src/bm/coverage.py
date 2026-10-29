"""Coverage checks: households in the bounds at which Catala stops with an error.

Each obligation of a translated scope (see `bm.translate`) is a Bool term over
the inputs that holds where Catala raises an error: no rule applies (`empty`)
or two exceptions apply at once (`conflict`). `check` asks Z3 whether each
obligation can hold for some household in the bounds. Obligations are checked
one at a time, so a household found for one may also trip others.

A household Z3 finds is reported as it stands. A Z3 `unsat` is a claim that
there is no gap, so cvc5 is asked the same question to confirm it.
"""

from dataclasses import dataclass
from typing import Literal

from bm import solvers
from bm.bounds import Bound
from bm.ir import Pos
from bm.translate import SORTS, SmtModule, literal, quote


@dataclass(frozen=True)
class CoverageFinding:
    kind: Literal["empty", "conflict"]
    definition: str
    pos: Pos
    status: Literal["found", "unknown"]
    # Every input of the scope, in SMT units (pence, days since 1970-01-01).
    example: dict[str, int | bool] | None


def declarations(module: SmtModule, bounds: dict[str, Bound]) -> list[str]:
    """SMT-LIB lines declaring each input as a constant, within its bounds."""
    sorts = {v.name: SORTS[v.type] for v in module.inputs}
    if unknown := sorted(set(bounds) - set(sorts)):
        raise ValueError(f"bounds for unknown inputs {unknown}")
    lines = [f"(declare-const {quote(name)} {sort})" for name, sort in sorts.items()]
    for name, bound in bounds.items():
        if sorts[name] != "Int":
            raise ValueError(f"{name} is {sorts[name]}, which takes no bound")
        lines.append(
            f"(assert (<= {literal('Int', bound.min)} {quote(name)} {literal('Int', bound.max)}))"
        )
    return lines


def check(
    module: SmtModule, bounds: dict[str, Bound], timeout_ms: int = 60_000
) -> list[CoverageFinding]:
    """A finding for each obligation that holds, or may hold, within the bounds.

    Raises `SolverDisagreement` if Z3 says an obligation cannot hold and cvc5
    finds a household where it does. If cvc5 cannot settle it in time, the
    finding is `unknown`.
    """
    inputs = {v.name for v in module.inputs}
    base = [module.text, *declarations(module, bounds)]
    findings = []
    for ob in module.obligations:
        script = "\n".join([*base, f"(assert {ob.formula})", "(check-sat)"]) + "\n"

        def finding(status, example=None):
            return CoverageFinding(ob.kind, ob.definition, ob.pos, status, example)

        z3_result = solvers.run("z3", script, timeout_ms)
        if z3_result.status == "sat":
            example = {k: v for k, v in z3_result.model.items() if k in inputs}
            findings.append(finding("found", example))
            continue
        if z3_result.status == "unknown":
            findings.append(finding("unknown"))
            continue
        cvc5_result = solvers.run("cvc5", script, timeout_ms)
        if cvc5_result.status == "sat":
            raise solvers.SolverDisagreement(
                z3_result, cvc5_result, f"{ob.kind} obligation in {ob.definition} at {ob.pos}"
            )
        if cvc5_result.status == "unknown":
            findings.append(finding("unknown"))
    return findings
