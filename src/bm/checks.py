"""The three-way check: each household through Catala, Z3 and PolicyEngine UK.

`run` evaluates every household in Catala's interpreter (`bm.catala_run`) and
in Z3 with the inputs fixed (`bm.evaluate`). Those two must agree on every
output, and must both return a value or both stop: anything else is a
translator bug and raises `TranslatorDisagreement`. If both stop, the
household is outside the rules and `RulesGiveNoValue` is raised. The award is
then compared with PolicyEngine UK's (`bm.policyengine.award`), and every
household where they differ is returned as a `Mismatch`. Nothing is filtered:
known differences are returned too, and are explained in docs/mismatches.md.

`rounding_stage_difference` is the one known difference, an open question on
the stage at which regulation 6(1) rounds. If that is decided, the predicate
and its entry in docs/mismatches.md are the only things to change.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from bm import catala_run, evaluate, ir, policyengine, translate
from bm.translate import SmtModule

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "rules" / "uc.catala_en"
UC_IR = ROOT / "build" / "uc.bm-ir.json"
SCOPE = "UniversalCredit"

# Earnings above the work allowance, in pence, at which 55% ends in exactly
# half a penny: 11x/20 has a fractional part of 1/2 exactly when x is 10 (mod 20).
HALF_PENNY_MODULUS = 20
HALF_PENNY_RESIDUE = 10


@dataclass(frozen=True)
class Mismatch:
    household: dict[str, int | bool]
    # Monthly awards in pence. `catala` and `z3` are always equal here.
    catala: int
    z3: int
    policyengine: int
    # Every output of the scope from Catala, for triage (the work allowance
    # among them). Not in the Task 6 brief's interface.
    catala_outputs: dict[str, int | bool] = field(default_factory=dict)


class TranslatorDisagreement(Exception):
    """Catala and Z3 differ at a household: a translator bug, not a mismatch."""

    def __init__(self, household: Mapping[str, int | bool], detail: str):
        self.household = dict(household)
        self.detail = detail
        super().__init__(f"at {self.household}: {detail}")


class RulesGiveNoValue(ValueError):
    """Both Catala and Z3 stop at this household, so there is nothing to compare."""


def rounding_stage_difference(
    household: Mapping[str, int | bool],
    catala: Mapping[str, int | bool],
    policyengine: int,
) -> bool:
    """The known difference in rounding stage (docs/mismatches.md, open question).

    Our rules round the regulation 22(1)(b) deduction to the penny, reading
    regulation 6(1)'s "the calculation of an amount" as that step. PolicyEngine
    UK rounds only the final award. The two differ only when the deduction ends
    in exactly half a penny, which our rules round up, so the award is 1p lower
    than PolicyEngine's. `catala` is Catala's outputs for the household; the
    work allowance is read from them.
    """
    above = int(household["earned_income"]) - int(catala["work_allowance"])
    half_penny = above > 0 and above % HALF_PENNY_MODULUS == HALF_PENNY_RESIDUE
    return half_penny and policyengine == int(catala["award"]) + 1


def run(
    households: list[dict[str, int | bool]],
    module: SmtModule | None = None,
    rules: Path = RULES,
) -> list[Mismatch]:
    """Every household where PolicyEngine UK's award differs from the rules'.

    `module` is the translated scope; by default it is read from
    build/uc.bm-ir.json (`make export`).
    """
    module = module or translate.translate(ir.load(UC_IR))
    mismatches = []
    for household in households:
        catala = _catala(rules, household)
        z3 = _z3(module, household)
        if catala is None and z3 is None:
            raise RulesGiveNoValue(f"Catala and Z3 both stop at {household}")
        if catala is None or z3 is None:
            stopped, returned = ("Catala", "Z3") if catala is None else ("Z3", "Catala")
            raise TranslatorDisagreement(household, f"{stopped} stops but {returned} does not")
        if differ := [n for n in module.outputs if catala.get(n) != z3[n]]:
            raise TranslatorDisagreement(
                household,
                "; ".join(f"{n}: Catala {catala.get(n)}, Z3 {z3[n]}" for n in differ),
            )
        inputs = {
            "assessment_period_start": int(household["assessment_period_start"]),
            "earned_income": int(household["earned_income"]),
            "aged_25_or_over": bool(household["aged_25_or_over"]),
            "has_lcw": bool(household["has_lcw"]),
        }
        pe = policyengine.award(inputs)
        if pe != catala["award"]:
            mismatches.append(
                Mismatch(dict(household), int(catala["award"]), int(z3["award"]), pe, catala)
            )
    return mismatches


def _catala(rules: Path, household: dict[str, int | bool]) -> dict[str, int | bool] | None:
    try:
        return catala_run.outputs(rules, SCOPE, household)
    except catala_run.CatalaRuntimeError:
        return None


def _z3(module: SmtModule, household: dict[str, int | bool]) -> dict | None:
    try:
        return evaluate.outputs(module, household)
    except evaluate.EvaluationError:
        return None
