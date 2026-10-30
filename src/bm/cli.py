"""The `bm` command.

    bm translate IR -o OUT.smt2
    bm coverage IR --inputs TOML
    bm query emr IR --inputs TOML [--delta 100] [--timeout-ms 60000] [--json]
    bm query timing IR --inputs TOML [--start YYYY-MM-DD] [--total POUNDS]
        [--fix NAME=VALUE ...] [--cap 8] [--timeout-ms 60000] [--json]
    bm query window IR --inputs TOML [--start YYYY-MM-DD] [--total POUNDS]
        [--fix NAME=VALUE ...] [--cap 12] [--probe] [--relaxed] [--timeout-ms 60000] [--json]
    bm query judgement IR NAME --inputs TOML [--start YYYY-MM-DD]
        [--fix NAME=VALUE ...] [--timeout-ms 60000] [--json]
    bm check IR --inputs TOML [--n-random 50] [--seed 1]
    bm report IR --inputs TOML [--json] [--n-random 50] [--seed 1]

Every command but `translate` takes `--rules` and prints a provenance block
(`bm.provenance`). It first checks that the IR was exported from the current
rules by the running Catala, and fails (exit 1) if not.

Exit status: 0 when there are no errors, 1 on any failure (a missing file, a
solver disagreement, a coverage gap, an unexplained mismatch), and 2 when a
result is unknown, for example after a timeout. A failure takes precedence.
Every `--json` output has a top-level `"unknown"` flag, and every text output
ends by pointing to docs/model-gaps.md.

`--fix NAME=VALUE` gives an input a value: money in pounds with two decimal
places (`500.00`), a date as `YYYY-MM-DD`, a Boolean as `true` or `false`.
`--total` takes pounds in the same form. A bad name or value exits 1.
`--rules` names the rules directory recorded in the provenance block and
checked against the IR. Catala's interpreter runs the same rules, for the
replay of a witness and for the differential check. It defaults to the
directory of the inputs file.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from bm import (
    coverage,
    inputs,
    ir,
    provenance,
    queries,
    report,
    solvers,
    strategic,
    translate,
    units,
    window,
)
from bm.inputs import InputSpec

_POUNDS = re.compile(r"-?[0-9]+\.[0-9]{2}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bm", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    def with_ir(p: argparse.ArgumentParser, has_inputs: bool = True) -> None:
        p.add_argument("ir", type=Path, help="bm-ir JSON file written by `make export`")
        if has_inputs:
            p.add_argument("--inputs", type=Path, required=True, help="inputs TOML")
            p.add_argument(
                "--rules", type=Path, help="rules directory (default: the inputs file's directory)"
            )

    def with_timeout(p: argparse.ArgumentParser) -> None:
        p.add_argument("--timeout-ms", type=int, default=60_000)

    def with_check(p: argparse.ArgumentParser) -> None:
        p.add_argument("--n-random", type=int, default=50)
        p.add_argument("--seed", type=int, default=1)

    t = commands.add_parser("translate", help="write the scope as SMT-LIB")
    with_ir(t, has_inputs=False)
    t.add_argument("-o", "--output", type=Path, required=True)

    c = commands.add_parser("coverage", help="find households where Catala stops with an error")
    with_ir(c)
    with_timeout(c)

    q = commands.add_parser("query", help="ask the solvers a question")
    kinds = q.add_subparsers(dest="query", required=True)
    e = kinds.add_parser("emr", help="peak effective marginal rate")
    with_ir(e)
    with_timeout(e)
    e.add_argument("--delta", type=int, default=100, help="earnings rise, in pence")
    e.add_argument("--json", action="store_true")

    def with_fix(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--start",
            default=strategic.DEFAULT_START.isoformat(),
            help="start of the first assessment period, YYYY-MM-DD (default: %(default)s)",
        )
        p.add_argument(
            "--fix",
            action="append",
            default=[],
            metavar="NAME=VALUE",
            help="give an input a value: money as 500.00, a date as YYYY-MM-DD, a Boolean as "
            "true or false; repeat for more than one",
        )

    ti = kinds.add_parser("timing", help="most the claimant can gain by timing earnings")
    with_ir(ti)
    with_timeout(ti)
    with_fix(ti)
    ti.add_argument("--total", help="fix the total of earnings over both periods, in pounds")
    ti.add_argument("--cap", type=int, default=strategic.DEFAULT_CASE_CAP, help="most judgement cases")
    ti.add_argument("--json", action="store_true")

    w = kinds.add_parser(
        "window",
        help="what the timing of earnings does to the award over consecutive periods",
        description="Gain, loss, spread and extra payday figures over a window of assessment "
        "periods. The window's length is that of the IR: 3 periods for a finding. Findings use "
        "the exact rules at 3 periods; --probe marks a run for measuring solver time, which is "
        "not a finding, and a longer window or --relaxed is refused without it. A longer window "
        "leaves out the extra payday figures. The text shows the households at the optimum for "
        "the realistic cases only (all cases where none is realistic); --json shows them all.",
    )
    with_ir(w)
    with_timeout(w)
    with_fix(w)
    w.add_argument("--total", help="fix the total of earnings over the window, in pounds")
    w.add_argument("--cap", type=int, default=window.DEFAULT_CASE_CAP, help="most judgement cases")
    w.add_argument("--probe", action="store_true", help="mark the run as a probe, not a finding")
    w.add_argument(
        "--relaxed", action="store_true", help="relaxed translation, for probes only: not the rules"
    )
    w.add_argument("--json", action="store_true")

    j = kinds.add_parser("judgement", help="what a decision maker's finding is worth")
    with_ir(j)
    j.add_argument("name", help="the Boolean judgement point, such as has_lcw")
    with_timeout(j)
    with_fix(j)
    j.add_argument("--json", action="store_true")

    k = commands.add_parser("check", help="compare Catala, Z3 and PolicyEngine UK")
    with_ir(k)
    with_check(k)

    r = commands.add_parser("report", help="peak rate, coverage, differential check, provenance")
    with_ir(r)
    with_check(r)
    with_timeout(r)
    r.add_argument("--json", action="store_true")
    return parser


def _rules_dir(args: argparse.Namespace) -> Path:
    return args.rules or args.inputs.resolve().parent


def _load_specs(args: argparse.Namespace, relaxed: bool = False):
    # Provenance first, so that an IR exported from other rules, or by another
    # Catala, fails here rather than as a solver result or a translator bug.
    prov = provenance.collect(_rules_dir(args), args.ir)
    scope = ir.load(args.ir)
    module = translate.translate(scope, relaxed=relaxed)
    return prov, module, inputs.load(args.inputs, scope)


def _load(args: argparse.Namespace):
    prov, module, specs = _load_specs(args)
    return prov, module, inputs.bounds(specs)


def _print_text(sections: list[list[str]]) -> None:
    sections = [*sections, [report.MODEL_GAPS_LINE]]
    print("\n\n".join("\n".join(s) for s in sections))


def _money(option: str, text: str) -> int:
    if not _POUNDS.fullmatch(text):
        raise ValueError(f"{option}: {text!r} is not money in pounds with two decimal places, such as 500.00")
    return units.pence(text)


def _date(option: str, text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{option}: {text!r} is not a date such as 2026-04-06") from None


def parse_fixed(specs: dict[str, InputSpec], items: list[str]) -> dict[str, int | bool]:
    """The `--fix NAME=VALUE` items as values in SMT units, read by each input's type.

    Raises `ValueError`, with a one-line message, for an unknown name, a name
    given twice, or a value that is not valid for the input's type.
    """
    fixed: dict[str, int | bool] = {}
    for item in items:
        name, equals, text = item.partition("=")
        if not equals:
            raise ValueError(f"--fix {item!r}: expected NAME=VALUE")
        option = f"--fix {name}"
        if name not in specs:
            raise ValueError(f"{option}: {name} is not an input; the inputs are {', '.join(specs)}")
        if name in fixed:
            raise ValueError(f"{option}: {name} is given twice")
        match specs[name].type:
            case "money":
                fixed[name] = _money(option, text)
            case "date":
                fixed[name] = units.days(_date(option, text))
            case "bool" if text in ("true", "false"):
                fixed[name] = text == "true"
            case "bool":
                raise ValueError(f"{option}: {text!r} is not true or false")
            case "integer" if re.fullmatch(r"-?[0-9]+", text):
                fixed[name] = int(text)
            case kind:
                raise ValueError(f"{option}: {text!r} is not a valid {kind} value")
    return fixed


def _translate(args: argparse.Namespace) -> int:
    module = translate.translate(ir.load(args.ir))
    args.output.write_text(module.text)
    print(f"wrote {args.output}")
    return 0


def _coverage(args: argparse.Namespace) -> int:
    prov, module, bounds = _load(args)
    findings = coverage.check(module, bounds, timeout_ms=args.timeout_ms)
    _print_text([report.coverage_text(findings, module.inputs), report.provenance_text(prov)])
    if any(f.status == "found" for f in findings):
        return 1
    return 2 if findings else 0


def _query_emr(args: argparse.Namespace) -> int:
    prov, module, bounds = _load(args)
    result = queries.emr(module, bounds, delta=args.delta, timeout_ms=args.timeout_ms)
    if args.json:
        data = report.emr_dict(result, args.delta, "earned_income")
        _print_json(args, data, prov)
    else:
        text = report.emr_text(result, module.inputs, "earned_income", args.delta)
        _print_text([text, report.provenance_text(prov)])
    return 2 if result.status == "unknown" else 0


def _print_json(args: argparse.Namespace, data: dict, prov) -> None:
    print(json.dumps({"units": report.UNITS, **data, "provenance": report.provenance_dict(prov)}, indent=2))


def _query_timing(args: argparse.Namespace) -> int:
    rules = report.rules_file(_rules_dir(args))
    prov, module, specs = _load_specs(args)
    result = strategic.timing(
        module,
        specs,
        first_start=_date("--start", args.start),
        fixed=parse_fixed(specs, args.fix),
        total=None if args.total is None else _money("--total", args.total),
        cap=args.cap,
        rules=rules,
        timeout_ms=args.timeout_ms,
    )
    if args.json:
        _print_json(args, report.timing_dict(result, specs), prov)
    else:
        _print_text([report.timing_text(result, specs), report.provenance_text(prov)])
    return 2 if result.status == "unknown" else 0


def _query_window(args: argparse.Namespace) -> int:
    rules = report.rules_file(_rules_dir(args))
    prov, module, specs = _load_specs(args, relaxed=args.relaxed)
    # The extra payday figures compare a pattern over exactly 3 periods.
    longer = window.periods_of(module) != window.FINDING_PERIODS
    result = window.window(
        module,
        specs,
        first_start=_date("--start", args.start),
        total=None if args.total is None else _money("--total", args.total),
        fixed=parse_fixed(specs, args.fix),
        figures=tuple(f for f in window.FIGURES if not (longer and f in window.PAYDAY)),
        probe=args.probe,
        cap=args.cap,
        timeout_ms=args.timeout_ms,
    )
    window.replay(rules, result)
    if args.json:
        print(json.dumps(report.window_json(result, specs, prov), indent=2))
    else:
        _print_text([report.window_text(result, specs), report.window_provenance_text(prov, result)])
    return 2 if result.status == "unknown" else 0


def _query_judgement(args: argparse.Namespace) -> int:
    rules = report.rules_file(_rules_dir(args))
    prov, module, specs = _load_specs(args)
    result = strategic.judgement_value(
        module,
        specs,
        point=args.name,
        start=_date("--start", args.start),
        fixed=parse_fixed(specs, args.fix),
        rules=rules,
        timeout_ms=args.timeout_ms,
    )
    if args.json:
        _print_json(args, report.judgement_dict(result, specs), prov)
    else:
        _print_text([report.judgement_text(result, specs), report.provenance_text(prov)])
    return 2 if result.status == "unknown" else 0


def _check(args: argparse.Namespace) -> int:
    rules = report.rules_file(_rules_dir(args))
    prov, module, bounds = _load(args)
    d = report.differential(module, bounds, args.n_random, args.seed, rules)
    _print_text([report.differential_text(d, module.inputs), report.provenance_text(prov)])
    return 1 if d.unexplained else 0


def _report(args: argparse.Namespace) -> int:
    r = report.build(
        args.ir,
        args.inputs,
        rules=_rules_dir(args),
        n_random=args.n_random,
        seed=args.seed,
        timeout_ms=args.timeout_ms,
    )
    print(report.to_json(r) if args.json else report.to_text(r), end="")
    return report.exit_code(r)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handler = {
        ("translate", None): _translate,
        ("coverage", None): _coverage,
        ("query", "emr"): _query_emr,
        ("query", "timing"): _query_timing,
        ("query", "window"): _query_window,
        ("query", "judgement"): _query_judgement,
        ("check", None): _check,
        ("report", None): _report,
    }[(args.command, getattr(args, "query", None))]
    try:
        return handler(args)
    except (OSError, ValueError, RuntimeError, solvers.SolverDisagreement) as error:
        # ValueError covers IrError, InputsError, TranslateError and NoHousehold;
        # RuntimeError covers SolverError, CatalaRuntimeError, EvaluationError,
        # report.TranslatorBug and provenance.ProvenanceError.
        print(f"bm: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
