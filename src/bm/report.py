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
from decimal import Decimal
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
from bm.window import CaseResult, CopyWitness, Figure, WindowResult

UNITS = "money in pence; dates as days since 1970-01-01"
MISMATCH_DOC = "docs/mismatches.md"
RULES_FILE = "uc.catala_en"
MODEL_GAPS_LINE = "Model gaps that limit these findings: docs/model-gaps.md"
PROBE_MODEL_GAPS_LINE = "Model gaps that limit the model: docs/model-gaps.md"
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
    module: SmtModule, bounds: dict, n_random: int, seed: int, rules: Path | None = None
) -> Differential:
    """Run the differential check. Imported here because it loads PolicyEngine UK.

    `rules` is the rules file Catala runs, as `rules_file` returns it for the
    `--rules` directory; by default the repository's own.
    """
    from bm import checks, households

    generated = households.generate(bounds, n_random=n_random, seed=seed, module=module)
    try:
        mismatches = checks.run(generated, module=module, rules=rules or checks.RULES)
    except checks.TranslatorDisagreement as error:
        raise TranslatorBug(str(error)) from error
    explained, unexplained = [], []
    for m in mismatches:
        known = checks.rounding_stage_difference(m.household, m.catala_outputs, m.policyengine)
        (explained if known else unexplained).append(m)
    return Differential(len(generated), seed, explained, unexplained)


def rules_file(rules: Path) -> Path:
    """The rules file in the directory `rules`, which replay runs through Catala.

    The provenance block describes the same directory, so the replay must
    read the same file. Raises `FileNotFoundError` if it is missing.
    """
    file = Path(rules) / RULES_FILE
    if not file.is_file():
        raise FileNotFoundError(f"no {RULES_FILE} in the rules directory {rules}")
    return file


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
    replay_rules = rules_file(rules)
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
        differential=differential(module, bounds, n_random, seed, replay_rules),
        provenance=prov,
        specs=specs,
        timing=strategic.timing(module, specs, rules=replay_rules, timeout_ms=timeout_ms),
        judgement=strategic.judgement_value(
            module, specs, point=JUDGEMENT_POINT, rules=replay_rules, timeout_ms=timeout_ms
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

def money(p: int | Fraction) -> str:
    """Pence as `£1,234.56`. A relaxed probe's witnesses hold exact fractions of a penny: those
    are shown to four decimal places of a pound, which is not a rounded award."""
    if isinstance(p, Fraction) and p.denominator != 1:
        pounds = Decimal(p.numerator) / Decimal(p.denominator) / 100
        return f"-£{-pounds:,.4f}" if pounds < 0 else f"£{pounds:,.4f}"
    return units.pounds_text(int(p))


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


def _result_line(label: str, status: str, amount: int | None) -> str:
    """One result, worded from its own status.

    An unknown result is never shown as an answer, or as nil. An unknown with
    an amount is one that Z3 proved but cvc5 could not confirm: the solvers
    keep Z3's value only then.
    """
    if status == "optimal":
        return f"{label}: {money(amount)}"
    if amount is None:
        return (
            f"{label}: UNKNOWN. Z3 did not prove a result in the time allowed. "
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


def _verification_line(verification: dict) -> str:
    cvc5 = (
        "cvc5 confirmed that nothing better exists for every result"
        if verification["cvc5"] == "confirmed"
        else "cvc5 did not confirm every result, and each UNKNOWN line says what is missing"
    )
    match verification["replay"]:
        case "matched":
            replay = "Catala's interpreter gave the same award as Z3 at every witness"
        case "matched in part":
            replay = (
                "Catala's interpreter gave the same award as Z3 at the witnesses of "
                f"{', '.join(verification['replayed'])}; the other results have no witness"
            )
        case _:
            replay = "no witness was replayed through Catala"
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
        _result_line(
            "  Gain the claimant can count on (worst case over the judgement cases)",
            result.gain_status,
            result.gain,
        )
    )
    if result.total is not None:
        out.append(f"  Total of {TIMING_INPUT} over both periods at that gain: {money(result.total)}")
    starts = ", ".join(units.to_date(d).isoformat() for d in result.starts)
    out.append(f"  Periods start: {starts}")
    out.append(_fixed_line(specs, result.fixed))
    for case, status, gain in result.per_case:
        out.append(_result_line(f"  Best gain with {strategic.case_label(case)}", status, gain))
    out.append(_verification_line(result.verification))
    if result.witnesses:
        out.append("  Households of the gain above:")
        for w in result.witnesses:
            heading = f"period {w.period} ({w.kind}), {strategic.case_label(w.case)}"
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
    out.append(_result_line("  Largest value", result.largest_status, result.largest))
    out.append(_result_line("  Smallest value", result.smallest_status, result.smallest))
    out.append(_fixed_line(specs, result.fixed))
    out.append(_verification_line(result.verification))
    for label, found in (
        ("largest", result.largest_witnesses),
        ("smallest", result.smallest_witnesses),
    ):
        if found:
            out.append(f"  Households of the {label} value:")
            for w in found:
                out += _indent(_witness_lines(specs, w, strategic.case_label(w.case)), 4)
    return out


# The window query

WINDOW_CAVEATS = [
    "Passported help (such as help with NHS costs and Healthy Start) and Council Tax Support are "
    "not modelled: only the Universal Credit award is counted.",
    "Reported earnings are taken as exact, although RTI reports can be late or wrong; reporting "
    "and any later correction are not modelled.",
    "The realistic case rests on DWP's practice of checking income each month after a nil "
    "period, and the other cases model departures from it. The £2,500 is added to the nil UC "
    "threshold to give the relevant threshold for surplus earnings, and is currently set to end "
    "on 31 March 2027 (S.I. 2015/345 regulation 5, and the Secretary of State's determination "
    "of 20 January 2026). Both are as at 29 October 2026; see docs/nil-months.md.",
]
_WINDOW_LABELS = {
    "gain": "Gain from timing alone (largest)",
    "loss": "Loss from timing alone (largest)",
    "spread": "Spread between two splits of one total (largest)",
    "extra_payday_max": "Extra payday, even spread less (P, 2P, P) (largest)",
    "extra_payday_min": "Extra payday, even spread less (P, 2P, P) (smallest)",
}
_WINDOW_DEFINITIONS = [
    "gain: how much more the award over the window can be with some split of the total than "
    "with the even split of the same total.",
    "loss: how much less it can be with some split than with the even split.",
    "spread: the largest difference between the awards over the window of two splits of the "
    "same total.",
    "extra payday: for a claimant paid every four weeks, the award over the window when the "
    "four payments are spread evenly less the award when they fall as (P, 2P, P) in the three "
    "periods; a negative amount means the (P, 2P, P) pattern pays more.",
    "pattern: one way the total is paid out over the periods. Each figure compares patterns "
    "for the same household, so only the earnings differ between them.",
]
_ACROSS_LABELS = {
    "gain": "Gain",
    "loss": "Loss",
    "spread": "Spread",
    "extra_payday_max": "Extra payday, largest figure",
    "extra_payday_min": "Extra payday, smallest figure",
}
_SHORT = {
    "gain": "gain",
    "loss": "loss",
    "spread": "spread",
    "extra_payday_max": "largest extra payday figure",
    "extra_payday_min": "smallest extra payday figure",
}
_COPY_WORDS = {
    "split": "the split",
    "even": "the even split",
    "a": "split a",
    "b": "split b",
    "payday": "the (P, 2P, P) payments",
}
_FACT_BASES = ("start", "earnings")


def _at_least(figure: Figure) -> str:
    return "at least " if figure.lower_bound else ""


def _prose(note: str) -> str:
    """A note from bm.window in the words of the report, with figure names for identifiers."""
    for name, words in (("extra_payday_max", "largest extra payday figure"), ("extra_payday_min", "smallest extra payday figure")):
        note = note.replace(f"has no {name}", f"has no {words}").replace(name, f"the {words}")
    return note.replace("the copy that", "the pattern that")


def _reason(excluded: list[str], case: CaseResult, name: str) -> str:
    """Why a figure is not available, from the note that says so, in the words of the note."""
    lead = f"In the case {strategic.case_label(case.case)}, "
    for note in excluded:
        if note.startswith(lead) and (note.endswith(f"has no {name}.") or note.endswith("has no figures.")):
            return note[len(lead):]
    return "no split keeps the last-period rule"


def _case_name(case: CaseResult) -> str:
    label = strategic.case_label(case.case) if case.case else "judgement points fixed by the caller"
    return f"{label} ({'realistic' if case.realistic else 'not the realistic case'})"


def _across(result: WindowResult) -> dict:
    """The largest and the smallest of each figure across the cases, and what was left out.

    Only settled values count: a figure that is unknown, or not available, is left out and
    counted. A largest value is a lower bound ("at least") when any figure counted for that name
    is one, since the case that is only bounded could be larger. A smallest value is one when
    the case giving it is, since the others are not smaller.
    """
    names = list(result.cases[0].figures) if result.cases else []
    out = {}
    for name in names:
        found = [(c, c.figures[name]) for c in result.cases if c.figures[name].status == "optimal"]
        left = {
            "infeasible": sum(c.figures[name].status == "infeasible" for c in result.cases),
            "unknown": sum(c.figures[name].status == "unknown" for c in result.cases),
        }
        entry = {"largest": None, "smallest": None, "left_out": left}
        if found:
            top = max(found, key=lambda cf: cf[1].value)  # the first case wins a tie
            bottom = min(found, key=lambda cf: cf[1].value)
            any_bound = any(f.lower_bound for _, f in found)
            entry["largest"] = {"case": top[0], "figure": top[1], "lower_bound": any_bound}
            entry["smallest"] = {"case": bottom[0], "figure": bottom[1], "lower_bound": bottom[1].lower_bound}
        out[name] = entry
    return out


def _across_lines(result: WindowResult) -> list[str]:
    out = [
        "Across cases",
        "  The largest and the smallest value of each figure over the cases above, and the case "
        "that gives each. A figure that is unknown or not available in a case is left out.",
    ]
    for name, entry in _across(result).items():
        left = entry["left_out"]
        gone = [f"{n} {what}" for what, n in (("not available", left["infeasible"]), ("unknown", left["unknown"])) if n]
        note = f"; left out: {', '.join(gone)}" if gone else ""
        if entry["largest"] is None:
            out.append(f"  {_ACROSS_LABELS[name]}: no value in any case{note}")
            continue
        parts = []
        for which in ("largest", "smallest"):
            found = entry[which]
            amount = f"{'at least ' if found['lower_bound'] else ''}{money(found['figure'].value)}"
            parts.append(f"{which} {amount}, in the case {_case_name(found['case'])}")
        out.append(f"  {_ACROSS_LABELS[name]}: {'; '.join(parts)}{note}")
    return out


def _figure_text(figure: Figure, reason: str) -> str:
    """One figure, worded from its own status; an unknown or missing one is never an amount."""
    match figure.status:
        case "optimal":
            return f"{_at_least(figure)}{money(figure.value)}"
        case "infeasible":
            return f"not available: {reason}"
    if figure.value is None:
        return (
            "UNKNOWN. Z3 did not prove a result in the time allowed. That is not the same "
            "as a result of nil, no gain or no loss."
        )
    return (
        f"UNKNOWN. Z3 found {_at_least(figure)}{money(figure.value)}, but cvc5 could not confirm "
        "that nothing better exists, so it is not known to be the best."
    )


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    return [
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
        for row in [headers, *rows]
    ]


def _trace_lines(starts: list[int], witness: CopyWitness) -> list[str]:
    rows = [
        [
            str(k),
            units.to_date(start).isoformat(),
            money(p.earnings),
            money(p.earnings_used),
            money(p.award),
            "yes" if p.entitled else "no",
            money(p.surplus_after),
        ]
        for k, (start, p) in enumerate(zip(starts, witness.trace, strict=True), start=1)
    ]
    headers = ["period", "starts", "earnings", "earnings used", "award", "entitled", "surplus after"]
    return _table(headers, rows)


def _facts(figure: Figure) -> dict[str, int | bool]:
    """The household facts and judgement values at a figure's optimum, shared by its copies."""
    return {
        n: v for n, v in figure.witnesses[0].inputs.items() if n.rsplit("_", 1)[0] not in _FACT_BASES
    }


def _fact_lines(specs: dict[str, InputSpec], facts: dict[str, int | bool]) -> list[str]:
    names = [n for n in specs if n in facts]
    width = max(len(n) for n in names)
    shown = [value(specs[n].type, facts[n]) for n in names]
    wide = max(len(v) for v in shown)
    out = [
        f"{n:<{width}}  {v:<{wide}}  {_controls(specs[n])}" for n, v in zip(names, shown, strict=True)
    ]
    for base, label in (("start", "start of each period"), ("earnings", "earnings in each period")):
        out.append(f"{label}: {_controls(specs[f'{base}_1'])}")
    return out


def _copy_lines(starts: list[int], figure: Figure) -> list[str]:
    out = []
    for w in figure.witnesses:
        paid = sum(p.earnings for p in w.trace)
        total = sum(p.award for p in w.trace)
        out.append(
            f"Pattern: {_COPY_WORDS[w.copy]}: earnings {money(paid)} in all, "
            f"award {money(total)} in all"
        )
        out += _indent(_trace_lines(starts, w), 2)
    return out


def _case_lines(
    result: WindowResult, specs: dict[str, InputSpec], case: CaseResult, show: bool
) -> list[str]:
    out = [f"Case: {_case_name(case)}"]
    for name, figure in case.figures.items():
        reason = _prose(_reason(result.excluded, case, name))
        out.append(f"  {_WINDOW_LABELS[name]}: {_figure_text(figure, reason)}")
    if any(f.lower_bound for f in case.figures.values()):
        out.append(
            "  \"At least\" marks a lower bound: with no claim after the award ends, a loss "
            "carries on past the window until a fresh claim, so no window bounds it."
        )
    found = {name: f for name, f in case.figures.items() if f.witnesses}
    if show and found:
        # The facts are the same at every optimum where the caller fixed them all.
        shared = len({tuple(_facts(f).items()) for f in found.values()}) == 1
        if shared:
            out.append("  Household facts, the same in every example below:")
            out += _indent(_fact_lines(specs, _facts(next(iter(found.values())))), 4)
        for name, figure in found.items():
            out.append(
                f"  One household the solver found at the {_SHORT[name]}, "
                f"{_figure_text(figure, '')} (an example of the class, not advice):"
            )
            if not shared:
                out.append("    Household facts:")
                out += _indent(_fact_lines(specs, _facts(figure)), 6)
            out += _indent(_copy_lines(result.starts, figure), 4)
    return out


def _window_verification_line(result: WindowResult) -> str:
    """The verification line, with a count of the figures replayed; the JSON lists them."""
    verification = result.verification
    cvc5 = (
        "cvc5 confirmed every figure"
        if verification["cvc5"] == "confirmed"
        else "cvc5 did not confirm every figure, and each UNKNOWN line says what is missing"
    )
    replay = verification["replay"]
    if replay == "matched":
        replay = "Catala's interpreter gave the same traced values as Z3 at every witness"
    elif replay == "matched in part":
        figures = sum(len(case.figures) for case in result.cases)
        done = len(verification["replayed"])
        rest = figures - done
        replay = (
            "Catala's interpreter gave the same traced values as Z3 at the witnesses of "
            f"{done} of {figures} figures; the other {rest} "
            f"{'has' if rest == 1 else 'have'} no witness"
        )
    elif replay == "not run":
        replay = "no witness was replayed through Catala"
    else:
        replay = f"replay through Catala {replay}"
    return f"Verification: {cvc5}; {replay}"


def window_text(result: WindowResult, specs: dict[str, InputSpec]) -> list[str]:
    """The window report as lines, with a blank line between its sections."""
    head = []
    if result.probe:
        head += [
            "PROBE: not a finding",
            "  A probe measures solver time. Its figures are not findings and are not to be quoted.",
        ]
    if result.relaxed:
        head.append(
            "  This is a relaxed translation: money is not rounded to the penny. It is not the rules."
        )
    head.append(f"Window query: timing of earnings over {result.periods} consecutive assessment periods")
    if result.status == "unknown":
        head.append(
            "  UNKNOWN: at least one figure below is not settled, which is not the same as "
            "nothing found"
        )
    if not result.probe:
        head.append(
            "  The figures say what the rules pay for a class of household and a pattern of "
            "earnings within the model's bounds. They are not advice on any particular claim."
        )
    head += [
        "  Periods start: " + ", ".join(units.to_date(d).isoformat() for d in result.starts),
        "  Total of earnings over the window: "
        + (
            f"{money(result.total)} (fixed)"
            if result.total is not None
            else "free within the bounds; each household below shows its own"
        ),
        _fixed_line(specs, result.fixed),
    ]
    reading = ["Reading the figures"]
    reading += [f"  {line}" for line in _WINDOW_DEFINITIONS]
    reading.append(
        "  A case is marked realistic when claim_after_end, claim_each_month and "
        "lcw_carries_over are all yes; a point that does not apply is ignored."
    )
    shown = [c.realistic for c in result.cases]
    if not any(shown):
        shown = [True] * len(shown)
    sections = [head, reading]
    sections += [
        _case_lines(result, specs, case, show) for case, show in zip(result.cases, shown, strict=True)
    ]
    if not all(shown):
        sections[-1].append(
            "Households for the other cases are in the --json output."
        )
    sections.append(_across_lines(result))
    sections.append(["Left out by the last-period rule"] + [f"  - {_prose(note)}" for note in result.excluded])
    sections.append([_window_verification_line(result)])
    sections.append(["Caveats"] + [f"  - {line}" for line in WINDOW_CAVEATS])
    return [line for i, section in enumerate(sections) for line in ([""] if i else []) + section]


def window_provenance_text(p: Provenance, result: WindowResult) -> list[str]:
    translation = (
        "relaxed (money is Real and nothing is rounded; not the rules)"
        if result.relaxed
        else "exact (the rules)"
    )
    return [*provenance_text(p), f"  translation      {translation}"]


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
    def state(dirty: bool) -> str:
        return "uncommitted changes" if dirty else "clean"

    return [
        "Provenance",
        f"  rules commit     {p.rules_commit} ({state(p.rules_dirty)})",
        f"  code commit      {p.code_commit} ({state(p.code_dirty)})",
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
        "gain_status": result.gain_status,
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
        "largest_status": result.largest_status,
        "smallest": result.smallest,
        "smallest_status": result.smallest_status,
        "start": result.start,
        "fixed": result.fixed,
        "largest_witnesses": [_witness_dict(specs, w) for w in result.largest_witnesses],
        "smallest_witnesses": [_witness_dict(specs, w) for w in result.smallest_witnesses],
        "verification": result.verification,
        "solver_versions": result.versions,
    }


def _window_witness_dict(
    specs: dict[str, InputSpec], starts: list[int], w: CopyWitness
) -> dict:
    return {
        "copy": w.copy,
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
        "trace": [
            {"period": k, "start": start, **dataclasses.asdict(p)}
            for k, (start, p) in enumerate(zip(starts, w.trace, strict=True), start=1)
        ],
    }


def window_json(result: WindowResult, specs: dict[str, InputSpec], prov: Provenance | None) -> dict:
    """The window report as JSON-ready data; `prov` is None only in tests of the figures."""
    translation = (
        "relaxed: money is Real and nothing is rounded; not the rules"
        if result.relaxed
        else "exact: the rules"
    )
    return _plain({
        "units": UNITS,
        "query": "window",
        "status": result.status,
        "unknown": result.status == "unknown",
        "probe": result.probe,
        "relaxed": result.relaxed,
        "periods": result.periods,
        "starts": result.starts,
        "total": result.total,
        "fixed": result.fixed,
        "cases": [
            {
                "case": case.case,
                "realistic": case.realistic,
                "figures": {
                    name: {
                        "value": figure.value,
                        "status": figure.status,
                        "lower_bound": figure.lower_bound,
                        "reason": _reason(result.excluded, case, name)
                        if figure.status == "infeasible"
                        else None,
                        "witnesses": [
                            _window_witness_dict(specs, result.starts, w) for w in figure.witnesses
                        ],
                    }
                    for name, figure in case.figures.items()
                },
            }
            for case in result.cases
        ],
        "across_cases": {
            name: {
                **{
                    which: None
                    if entry[which] is None
                    else {
                        "value": entry[which]["figure"].value,
                        "case": entry[which]["case"].case,
                        "realistic": entry[which]["case"].realistic,
                        "lower_bound": entry[which]["lower_bound"],
                    }
                    for which in ("largest", "smallest")
                },
                "left_out": entry["left_out"],
            }
            for name, entry in _across(result).items()
        },
        "excluded": result.excluded,
        "verification": result.verification,
        "solver_versions": result.versions,
        "provenance": None if prov is None else {**provenance_dict(prov), "translation": translation},
    })


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
