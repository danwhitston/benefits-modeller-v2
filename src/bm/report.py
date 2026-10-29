"""The report: peak marginal rate, coverage, differential check and provenance.

`build` runs the queries and returns a `Report`. `to_text` and `to_json` render
it; they show the same content. `exit_code` maps a report to the CLI exit
status: 1 if a coverage gap was found or a mismatch is unexplained, else 2 if
any result is unknown, else 0.

Mismatches between Catala, Z3 and PolicyEngine UK are split by
`checks.rounding_stage_difference`, the predicate for a known, logged class of
1p differences (see docs/mismatches.md). Only an unexplained mismatch fails.

In the JSON, money is in pence and dates are days since 1970-01-01, as in the
solvers and the other modules; `units` says so. The rate is the exact fraction
as a string such as "11/20". The text shows money in pounds, dates as ISO
dates, and the rate as a percentage, exact where it can be.
"""

import dataclasses
import json
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

from bm import bounds as bounds_mod
from bm import coverage, ir, provenance, queries, translate
from bm.coverage import CoverageFinding
from bm.ir import Var
from bm.provenance import Provenance
from bm.queries import EmrResult
from bm.translate import SmtModule

UNITS = "money in pence; dates as days since 1970-01-01"
EPOCH = date(1970, 1, 1)
MISMATCH_DOC = "docs/mismatches.md"


@dataclass(frozen=True)
class Differential:
    """Outcome of the differential check over `n_households` households."""

    n_households: int
    seed: int
    explained: list
    unexplained: list

    @property
    def total(self) -> int:
        return len(self.explained) + len(self.unexplained)


@dataclass(frozen=True)
class Report:
    scope: str
    inputs: list[Var]
    earnings_input: str
    delta: int
    emr: EmrResult
    coverage: list[CoverageFinding]
    differential: Differential
    provenance: Provenance


class TranslatorBug(RuntimeError):
    """Catala and Z3 disagree at a household: a translator bug, not a mismatch."""


def differential(
    module: SmtModule, bounds: dict, n_random: int, seed: int
) -> Differential:
    """Run the differential check. Imported here because it loads PolicyEngine UK."""
    from bm import checks, households

    generated = households.generate(bounds, n_random=n_random, seed=seed, module=module)
    try:
        mismatches = checks.run(generated, module=module)
    except checks.TranslatorDisagreement as error:
        raise TranslatorBug(str(error)) from error
    explained, unexplained = [], []
    for m in mismatches:
        known = checks.rounding_stage_difference(m.household, m.catala_outputs, m.policyengine)
        (explained if known else unexplained).append(m)
    return Differential(len(generated), seed, explained, unexplained)


def build(
    ir_path: Path,
    bounds_path: Path,
    rules: Path,
    n_random: int = 50,
    seed: int = 1,
    delta: int = 100,
    timeout_ms: int = 60_000,
) -> Report:
    scope = ir.load(ir_path)
    module = translate.translate(scope)
    bounds = bounds_mod.load(bounds_path, scope)
    return Report(
        scope=scope.name,
        inputs=module.inputs,
        earnings_input="earned_income",
        delta=delta,
        emr=queries.emr(module, bounds, delta=delta, timeout_ms=timeout_ms),
        coverage=coverage.check(module, bounds, timeout_ms=timeout_ms),
        differential=differential(module, bounds, n_random, seed),
        provenance=provenance.collect(rules),
    )


def exit_code(report: Report) -> int:
    if any(f.status == "found" for f in report.coverage) or report.differential.unexplained:
        return 1
    if report.emr.status == "unknown" or any(f.status == "unknown" for f in report.coverage):
        return 2
    return 0


# Formatting

def money(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    pounds, rest = divmod(abs(pence), 100)
    return f"{sign}£{pounds:,}.{rest:02d}"


def value(var_type: str, v: int | bool) -> str:
    match var_type:
        case "money":
            return money(v)
        case "date":
            return (EPOCH + timedelta(days=v)).isoformat()
        case "bool":
            return "yes" if v else "no"
    return str(v)


def household_lines(inputs: list[Var], household: dict[str, int | bool]) -> list[str]:
    width = max(len(v.name) for v in inputs)
    return [f"{v.name:<{width}}  {value(v.type, household[v.name])}" for v in inputs]


def percent(rate: Fraction) -> str:
    """Exact where the percentage is a whole number or a short decimal."""
    pct = rate * 100
    if pct.denominator == 1:
        return f"{pct.numerator}%"
    return f"{float(pct):.2f}% (exactly {rate} of the rise)"


def _indent(lines: list[str], by: int = 4) -> list[str]:
    return [" " * by + line for line in lines]


def emr_text(emr: EmrResult, inputs: list[Var], earnings_input: str, delta: int) -> list[str]:
    out = ["Peak effective marginal rate"]
    if emr.rate is None:
        out.append("  unknown: the solver ran out of time before finding one")
        return out
    label = percent(emr.rate)
    if emr.status == "unknown":
        label += ", unknown whether it is the peak (cvc5 ran out of time)"
    out.append(f"  {label}")
    out.append(
        f"  A rise of {money(delta)} in {earnings_input} takes the award from "
        f"{money(emr.award_at_e)} to {money(emr.award_at_e_plus_delta)}, "
        f"a fall of {money(emr.drop)}."
    )
    out.append("  Example household (earnings before the rise):")
    out += _indent(household_lines(inputs, emr.household))
    return out


def coverage_text(findings: list[CoverageFinding], inputs: list[Var]) -> list[str]:
    out = ["Coverage"]
    if not findings:
        out.append("  no gaps: no household in the bounds makes Catala stop with an error")
        return out
    for f in findings:
        what = {"empty": "no rule applies", "conflict": "two exceptions apply"}[f.kind]
        out.append(f"  {f.status}: {what} for {f.definition} ({f.pos})")
        if f.example is not None:
            out += _indent(household_lines(inputs, f.example), 6)
    return out


def differential_text(d: Differential, inputs: list[Var]) -> list[str]:
    out = [
        "Differential check (Catala, Z3 and PolicyEngine UK)",
        f"  {d.n_households} households, seed {d.seed}",
        f"  mismatches: {d.total} ({len(d.explained)} explained, {len(d.unexplained)} unexplained)",
    ]
    if d.explained:
        out.append(f"  explained mismatches are a known class of 1p difference: see {MISMATCH_DOC}")
    for label, group in (("explained", d.explained), ("UNEXPLAINED", d.unexplained)):
        for m in group:
            awards = (
                f"catala {money(m.catala)}, z3 {money(m.z3)}, "
                f"policyengine {money(m.policyengine)}"
            )
            out.append(f"  {label}: award {awards}")
            out += _indent(household_lines(inputs, m.household), 6)
    return out


def _provenance_text(r: Report) -> list[str]:
    p = r.provenance
    state = "uncommitted changes" if p.rules_dirty else "clean"
    return [
        "Provenance",
        f"  rules commit  {p.rules_commit} ({state})",
        f"  catala        {p.catala_version}",
        f"  z3            {p.z3_version}",
        f"  cvc5          {p.cvc5_version}",
    ]


def to_text(r: Report) -> str:
    sections = [
        [f"Report for scope {r.scope}"],
        emr_text(r.emr, r.inputs, r.earnings_input, r.delta),
        coverage_text(r.coverage, r.inputs),
        differential_text(r.differential, r.inputs),
        _provenance_text(r),
    ]
    return "\n\n".join("\n".join(s) for s in sections) + "\n"


# JSON

def emr_dict(emr: EmrResult, delta: int, earnings_input: str) -> dict:
    return {
        "status": emr.status,
        "rate": None if emr.rate is None else str(emr.rate),
        "delta": delta,
        "earnings_input": earnings_input,
        "drop": emr.drop,
        "household": emr.household,
        "award_at_e": emr.award_at_e,
        "award_at_e_plus_delta": emr.award_at_e_plus_delta,
        "solver_versions": emr.solver_versions,
    }


def _plain(x):
    """A dataclass or container as JSON-ready data."""
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: _plain(getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_plain(v) for v in x]
    if isinstance(x, Fraction):
        return str(x)
    return x


def to_dict(r: Report) -> dict:
    d = r.differential
    return {
        "scope": r.scope,
        "units": UNITS,
        "emr": emr_dict(r.emr, r.delta, r.earnings_input),
        "coverage": {
            "gaps_found": any(f.status == "found" for f in r.coverage),
            "findings": [
                {
                    "kind": f.kind,
                    "definition": f.definition,
                    "pos": str(f.pos),
                    "status": f.status,
                    "example": f.example,
                }
                for f in r.coverage
            ],
        },
        "mismatches": {
            "households": d.n_households,
            "seed": d.seed,
            "total": d.total,
            "explained": _plain(d.explained),
            "unexplained": _plain(d.unexplained),
            "explained_see": MISMATCH_DOC,
        },
        "provenance": _plain(r.provenance),
    }


def to_json(r: Report) -> str:
    return json.dumps(to_dict(r), indent=2) + "\n"
