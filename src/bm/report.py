"""The report: peak marginal rate, two strategic queries, coverage, differential check, provenance.

`build` runs the queries and returns a `Report`. `to_text` and `to_json` render
it; they show the same content. `exit_code` maps a report to the CLI exit
status: 1 if a coverage gap was found or a mismatch is unexplained, else 2 if
any result is unknown, else 0. The JSON has a top-level `"unknown"` flag, true
when any result in it is unknown.

The strategic queries (`bm.strategic`) run with their defaults: the timing gain
on `earned_income`, and the value of the decision maker's finding on `has_lcw`.
Each witness input is shown with who controls it and how it is checked, from
the labels in the inputs file. An unknown result is stated in capitals, a value
that Z3 found and cvc5 could not confirm is never presented as an answer, and a
missing value is never shown as nil.

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
from fractions import Fraction
from pathlib import Path

from bm import coverage, ir, provenance, queries, strategic, translate, units
from bm import inputs as bm_inputs  # `inputs` is a parameter name below
from bm.coverage import CoverageFinding
from bm.inputs import InputSpec
from bm.ir import Var
from bm.provenance import Provenance
from bm.queries import EmrResult
from bm.strategic import JudgementResult, TimingResult, Witness
from bm.translate import SmtModule

UNITS = "money in pence; dates as days since 1970-01-01"
MISMATCH_DOC = "docs/mismatches.md"
MODEL_GAPS_LINE = "Model gaps that limit these findings: docs/model-gaps.md"
TIMING_INPUT = "earned_income"
JUDGEMENT_POINT = "has_lcw"


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
    specs: dict[str, InputSpec]
    timing: TimingResult
    judgement: JudgementResult


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
    inputs_path: Path,
    rules: Path,
    n_random: int = 50,
    seed: int = 1,
    delta: int = 100,
    timeout_ms: int = 60_000,
) -> Report:
    # First, so that an IR that does not match the rules fails before the slow checks.
    prov = provenance.collect(rules, ir_path)
    scope = ir.load(ir_path)
    module = translate.translate(scope)
    specs = bm_inputs.load(inputs_path, scope)
    bounds = bm_inputs.bounds(specs)
    return Report(
        scope=scope.name,
        inputs=module.inputs,
        earnings_input="earned_income",
        delta=delta,
        emr=queries.emr(module, bounds, delta=delta, timeout_ms=timeout_ms),
        coverage=coverage.check(module, bounds, timeout_ms=timeout_ms),
        differential=differential(module, bounds, n_random, seed),
        provenance=prov,
        specs=specs,
        timing=strategic.timing(module, specs, timeout_ms=timeout_ms),
        judgement=strategic.judgement_value(
            module, specs, point=JUDGEMENT_POINT, timeout_ms=timeout_ms
        ),
    )


def is_unknown(report: Report) -> bool:
    """Whether any result in the report is unknown."""
    return (
        report.emr.status == "unknown"
        or report.timing.status == "unknown"
        or report.judgement.status == "unknown"
        or any(f.status == "unknown" for f in report.coverage)
    )


def exit_code(report: Report) -> int:
    if any(f.status == "found" for f in report.coverage) or report.differential.unexplained:
        return 1
    return 2 if is_unknown(report) else 0


# Formatting

money = units.pounds_text


def value(var_type: str, v: int | bool) -> str:
    match var_type:
        case "money":
            return money(v)
        case "date":
            return units.to_date(v).isoformat()
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
        label += ", unknown whether it is the peak (cvc5 could not settle it)"
    out.append(f"  {label}")
    out.append(
        f"  A rise of {money(delta)} in {earnings_input} takes the award from "
        f"{money(emr.award_at_e)} to {money(emr.award_at_e_plus_delta)}, "
        f"a fall of {money(emr.drop)}."
    )
    out.append("  Example household (earnings before the rise):")
    out += _indent(household_lines(inputs, emr.household))
    return out


def _controls(spec: InputSpec) -> str:
    return f"controlled by {', '.join(spec.controlled_by)}; checked by {spec.checked_by}"


def _case_text(case: dict[str, bool]) -> str:
    if not case:
        return "no judgement points"
    return ", ".join(f"{name} {'yes' if v else 'no'}" for name, v in case.items())


def _result_line(label: str, status: str, amount: int | None) -> str:
    """One result. An unknown result is never shown as an answer, or as nil."""
    if status == "optimal":
        return f"{label}: {money(amount)}"
    if amount is None:
        return (
            f"{label}: UNKNOWN. The solver found no result in the time allowed. "
            "That is not a result of nil."
        )
    return (
        f"{label}: UNKNOWN. Z3 found {money(amount)}, but cvc5 could not confirm that "
        "nothing better exists, so it is not known to be the best."
    )


def _fixed_line(specs: dict[str, InputSpec], fixed: dict[str, int | bool]) -> str:
    if not fixed:
        return "  Fixed by the caller: nothing; every other input is free within its bounds"
    shown = ", ".join(f"{n} {value(specs[n].type, v)}" for n, v in fixed.items())
    return f"  Fixed by the caller: {shown}"


def _verification_line(verification: dict[str, str]) -> str:
    cvc5 = (
        "cvc5 confirmed that nothing better exists"
        if verification["cvc5"] == "confirmed"
        else "cvc5 could not confirm that nothing better exists"
    )
    replay = (
        "Catala's interpreter gave the same award as Z3 at every witness"
        if verification["replay"] == "matched"
        else "no witness was replayed through Catala"
    )
    return f"  Verification: {cvc5}; {replay}"


def _witness_lines(specs: dict[str, InputSpec], w: Witness, heading: str) -> list[str]:
    names = [n for n in specs if n in w.inputs]
    width = max(len(n) for n in names)
    shown = [value(specs[n].type, w.inputs[n]) for n in names]
    wide = max(len(v) for v in shown)
    lines = [f"{heading}, award {money(w.award)}"]
    lines += [
        f"  {n:<{width}}  {v:<{wide}}  {_controls(specs[n])}"
        for n, v in zip(names, shown, strict=True)
    ]
    return lines


def timing_text(result: TimingResult, specs: dict[str, InputSpec]) -> list[str]:
    out = [f"Timing gain: splitting {TIMING_INPUT} between two assessment periods"]
    if result.status == "unknown":
        out.append("  UNKNOWN: at least one optimisation below is not settled")
    out.append(
        "  A gain is the award from a split less the award from the even split, "
        "summed over both periods."
    )
    out.append(
        _result_line("  Gain the claimant can count on (worst case over the judgement cases)", result.status, result.gain)
    )
    if result.total is not None:
        out.append(f"  Total of {TIMING_INPUT} over both periods at that gain: {money(result.total)}")
    starts = ", ".join(units.to_date(d).isoformat() for d in result.starts)
    out.append(f"  Periods start: {starts}")
    out.append(_fixed_line(specs, result.fixed))
    for case, status, gain in result.per_case:
        out.append(_result_line(f"  Best gain with {_case_text(case)}", status, gain))
    out.append(_verification_line(result.verification))
    if result.witnesses:
        out.append("  Households of the gain above:")
        for w in result.witnesses:
            heading = f"period {w.period} ({w.kind}), {_case_text(w.case)}"
            out += _indent(_witness_lines(specs, w, heading), 4)
    return out


def judgement_text(result: JudgementResult, specs: dict[str, InputSpec]) -> list[str]:
    out = [f"Value of the decision maker's finding on {result.point}"]
    if result.status == "unknown":
        out.append("  UNKNOWN: at least one optimisation below is not settled")
    out.append(
        f"  The value is the award with {result.point} yes less the award with it no, "
        f"in the assessment period starting {units.to_date(result.start).isoformat()}."
    )
    out.append(_result_line("  Largest value", result.status, result.largest))
    out.append(_result_line("  Smallest value", result.status, result.smallest))
    out.append(_fixed_line(specs, result.fixed))
    out.append(_verification_line(result.verification))
    for label, found in (
        ("largest", result.largest_witnesses),
        ("smallest", result.smallest_witnesses),
    ):
        if found:
            out.append(f"  Households of the {label} value:")
            for w in found:
                out += _indent(_witness_lines(specs, w, _case_text(w.case)), 4)
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


def provenance_text(p: Provenance) -> list[str]:
    state = "uncommitted changes" if p.rules_dirty else "clean"
    return [
        "Provenance",
        f"  rules commit     {p.rules_commit} ({state})",
        f"  code commit      {p.code_commit}",
        f"  catala           {p.catala_version} (the IR was exported with {p.ir_catala_version})",
        f"  z3               {p.z3_version}",
        f"  cvc5             {p.cvc5_version}",
        f"  policyengine-uk  {p.policyengine_uk_version}",
    ]


def provenance_dict(p: Provenance) -> dict:
    return _plain(p)


def to_text(r: Report) -> str:
    head = [f"Report for scope {r.scope}"]
    if is_unknown(r):
        head.append("UNKNOWN: at least one result below is unknown, which is not the same as nothing found")
    sections = [
        head,
        emr_text(r.emr, r.inputs, r.earnings_input, r.delta),
        timing_text(r.timing, r.specs),
        judgement_text(r.judgement, r.specs),
        coverage_text(r.coverage, r.inputs),
        differential_text(r.differential, r.inputs),
        provenance_text(r.provenance),
        [MODEL_GAPS_LINE],
    ]
    return "\n\n".join("\n".join(s) for s in sections) + "\n"


# JSON

def emr_dict(emr: EmrResult, delta: int, earnings_input: str) -> dict:
    return {
        "status": emr.status,
        "unknown": emr.status == "unknown",
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


def _witness_dict(specs: dict[str, InputSpec], w: Witness) -> dict:
    return {
        "case": w.case,
        "period": w.period,
        "kind": w.kind,
        "award": w.award,
        "inputs": {
            name: {
                "value": w.inputs[name],
                "type": spec.type,
                "controlled_by": list(spec.controlled_by),
                "checked_by": spec.checked_by,
            }
            for name, spec in specs.items()
            if name in w.inputs
        },
    }


def timing_dict(result: TimingResult, specs: dict[str, InputSpec]) -> dict:
    return {
        "query": "timing",
        "choice": TIMING_INPUT,
        "status": result.status,
        "unknown": result.status == "unknown",
        "gain": result.gain,
        "total": result.total,
        "starts": result.starts,
        "fixed": result.fixed,
        "per_case": [
            {"case": case, "status": status, "gain": gain}
            for case, status, gain in result.per_case
        ],
        "witnesses": [_witness_dict(specs, w) for w in result.witnesses],
        "verification": result.verification,
        "solver_versions": result.versions,
    }


def judgement_dict(result: JudgementResult, specs: dict[str, InputSpec]) -> dict:
    return {
        "query": "judgement",
        "point": result.point,
        "status": result.status,
        "unknown": result.status == "unknown",
        "largest": result.largest,
        "smallest": result.smallest,
        "start": result.start,
        "fixed": result.fixed,
        "largest_witnesses": [_witness_dict(specs, w) for w in result.largest_witnesses],
        "smallest_witnesses": [_witness_dict(specs, w) for w in result.smallest_witnesses],
        "verification": result.verification,
        "solver_versions": result.versions,
    }


def to_dict(r: Report) -> dict:
    d = r.differential
    return {
        "scope": r.scope,
        "units": UNITS,
        "unknown": is_unknown(r),
        "emr": emr_dict(r.emr, r.delta, r.earnings_input),
        "timing": timing_dict(r.timing, r.specs),
        "judgement": judgement_dict(r.judgement, r.specs),
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
        "provenance": provenance_dict(r.provenance),
    }


def to_json(r: Report) -> str:
    return json.dumps(to_dict(r), indent=2) + "\n"
