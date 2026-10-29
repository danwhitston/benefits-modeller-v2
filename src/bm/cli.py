"""The `bm` command.

    bm translate IR -o OUT.smt2
    bm coverage IR --bounds TOML
    bm query emr IR --bounds TOML [--delta 100] [--timeout-ms 60000] [--json]
    bm check IR --bounds TOML [--n-random 50] [--seed 1]
    bm report IR --bounds TOML [--json] [--n-random 50] [--seed 1]

Every command but `translate` takes `--rules` and prints a provenance block
(`bm.provenance`). It first checks that the IR was exported from the current
rules by the running Catala, and fails (exit 1) if not.

Exit status: 0 when there are no errors, 1 on any failure (a missing file, a
solver disagreement, a coverage gap, an unexplained mismatch), and 2 when a
result is unknown, for example after a timeout. A failure takes precedence.
`--rules` names the rules directory recorded in the provenance block and
checked against the IR; it defaults to the directory of the bounds file.
"""

import argparse
import json
import sys
from pathlib import Path

from bm import bounds as bounds_mod
from bm import coverage, ir, provenance, queries, report, solvers, translate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bm", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    def with_ir(p: argparse.ArgumentParser, bounds: bool = True) -> None:
        p.add_argument("ir", type=Path, help="bm-ir JSON file written by `make export`")
        if bounds:
            p.add_argument("--bounds", type=Path, required=True, help="inputs bounds TOML")
            p.add_argument(
                "--rules", type=Path, help="rules directory (default: the bounds file's directory)"
            )

    def with_timeout(p: argparse.ArgumentParser) -> None:
        p.add_argument("--timeout-ms", type=int, default=60_000)

    def with_check(p: argparse.ArgumentParser) -> None:
        p.add_argument("--n-random", type=int, default=50)
        p.add_argument("--seed", type=int, default=1)

    t = commands.add_parser("translate", help="write the scope as SMT-LIB")
    with_ir(t, bounds=False)
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
    return args.rules or args.bounds.resolve().parent


def _load(args: argparse.Namespace):
    # Provenance first, so that an IR exported from other rules, or by another
    # Catala, fails here rather than as a solver result or a translator bug.
    prov = provenance.collect(_rules_dir(args), args.ir)
    scope = ir.load(args.ir)
    module = translate.translate(scope)
    return prov, module, bounds_mod.load(args.bounds, scope)


def _print_text(sections: list[list[str]]) -> None:
    print("\n\n".join("\n".join(s) for s in sections))


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
        prov_data = report.provenance_dict(prov)
        print(json.dumps({"units": report.UNITS, **data, "provenance": prov_data}, indent=2))
    else:
        text = report.emr_text(result, module.inputs, "earned_income", args.delta)
        _print_text([text, report.provenance_text(prov)])
    return 2 if result.status == "unknown" else 0


def _check(args: argparse.Namespace) -> int:
    prov, module, bounds = _load(args)
    d = report.differential(module, bounds, args.n_random, args.seed)
    _print_text([report.differential_text(d, module.inputs), report.provenance_text(prov)])
    return 1 if d.unexplained else 0


def _report(args: argparse.Namespace) -> int:
    r = report.build(
        args.ir,
        args.bounds,
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
        ("check", None): _check,
        ("report", None): _report,
    }[(args.command, getattr(args, "query", None))]
    try:
        return handler(args)
    except (OSError, ValueError, RuntimeError, solvers.SolverDisagreement) as error:
        # ValueError covers IrError, BoundsError, TranslateError and NoHousehold;
        # RuntimeError covers SolverError, CatalaRuntimeError, EvaluationError,
        # report.TranslatorBug and provenance.ProvenanceError.
        print(f"bm: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
