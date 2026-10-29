"""Run Z3 and cvc5 on SMT-LIB text.

Both solvers are driven through their Python packages (`z3-solver` and `cvc5`),
so no solver binary is needed. cvc5 reads text through its `InputParser`: the
script's commands are executed one by one against a `Solver` and a
`SymbolManager`, which is what the `cvc5` binary does with a file. The cvc5
binary from the GitHub release is therefore not used, and the Makefile pins no
checksum for it.

Z3 uses `Solver` and `parse_smt2_string`. Each Z3 call has a fresh
`z3.Context`, so work done earlier in the same process cannot change Z3's
search, and results do not depend on what ran before.

`optimise_and_confirm` is the one routine for an optimum. It does not use
Z3's `Optimize` engine, whose run time on the project's queries had a long
tail (measured with Z3 5.3.2 on 29 October 2026, on the timing query over 100
random seeds: a median of 0.46 s, 5.4 s at the 90th percentile and once over
30 s). Instead it searches with plain satisfiability
checks: Z3 finds a model, then is asked for a better one until it proves that
none exists, and cvc5 then confirms independently that nothing better exists.

A timeout gives status "unknown". Anything else that goes wrong, such as a
script that does not parse, raises `SolverError`.

Models cover the declared constants only, as ints and bools. A declared
constant of another sort (Real, for example) in a satisfiable script raises
`SolverError`, because the project's queries have no such constants.
"""

import re
import time
from dataclasses import dataclass
from typing import Literal

import cvc5
import z3

Status = Literal["sat", "unsat", "unknown"]
Model = dict[str, int | bool]

_SYMBOL = r"\|[^|]*\||[^\s()|]+"
_DECLARATION = re.compile(
    rf"\(\s*declare-(?:const|fun)\s+({_SYMBOL})\s+(?:\(\s*\)\s+)?([^\s()]+)\s*\)"
)
_SET_LOGIC = re.compile(r"\(\s*set-logic\b")


class SolverError(RuntimeError):
    """The script could not be run, or its model is not ints and bools."""


@dataclass(frozen=True)
class SolverResult:
    status: Status
    model: Model | None
    version: str


class SolverDisagreement(Exception):
    """Z3 and cvc5 gave different answers to the same question."""

    def __init__(self, z3_result: SolverResult, cvc5_result: SolverResult, context: str = ""):
        self.z3 = z3_result
        self.cvc5 = cvc5_result
        self.context = context
        if z3_result.status == cvc5_result.status:
            # The statuses agree, so they cannot say what differs: the context does.
            message = f"z3 and cvc5 disagree: {context}" if context else "z3 and cvc5 disagree"
        else:
            text = f"z3 says {z3_result.status} but cvc5 says {cvc5_result.status}"
            message = f"{context}: {text}" if context else text
        super().__init__(message)


@dataclass(frozen=True)
class Optimum:
    """The outcome of `optimise_and_confirm`.

    `value` and `model` are Z3's optimum, and are kept when only cvc5 could not
    confirm it (`status` "unknown", `confirmed` False). They are None when Z3
    did not prove an optimum: the script is infeasible, or Z3 answered unknown
    or ran out of time before proving that nothing better exists.
    """

    status: Literal["optimal", "unknown", "infeasible"]
    value: int | None
    model: Model | None
    versions: dict[str, str]
    confirmed: bool


OBJECTIVE = "bm.objective"


def optimise_and_confirm(
    lines: list[str],
    objective: str,
    direction: Literal["max", "min"],
    timeout_ms: int,
    context: str = "",
    max_checks: int = 200,
) -> Optimum:
    """Z3 optimises the SMT-LIB term `objective`; cvc5 confirms nothing is better.

    `lines` are the script's commands without `(check-sat)`; the list is not
    changed. The objective is declared as `|bm.objective|`, so its value is
    read from the model.

    Z3 searches with plain satisfiability checks, all within `timeout_ms` and
    at most `max_checks` of them.
    Its first model gives a value v. Each later check asks for an objective at
    least some target beyond v: the targets gallop away from v, doubling the
    step, until one is unsat, then bisect between the best value found and
    that target. A wide objective, such as earnings over a range of pence,
    takes about two checks per bit of the range. The search ends when Z3
    proves that nothing above the maximum (or below the minimum) is sat.
    cvc5 is then asked, as an independent check, for a value above the maximum
    (or below the minimum) within the same lines, and must answer unsat.

    Raises `SolverDisagreement`, carrying `context`, if cvc5 finds one. If Z3's
    first check is unsat the status is "infeasible". If any Z3 check is
    unknown, or the time runs out before Z3 proves the optimum, the status is
    "unknown" with no value: an unbounded objective ends this way, at the
    latest after `max_checks` checks. If cvc5 is unknown the status is
    "unknown" and Z3's optimum is kept. Neither unknown is ever read as an
    optimum.

    The timing figures in the module docstring were measured by a milestone 2
    reviewer, not by the code's author.
    """
    if direction not in ("max", "min"):
        raise ValueError(f"direction must be 'max' or 'min', not {direction!r}")
    name = f"|{OBJECTIVE}|"
    base = [*lines, f"(declare-const {name} Int)", f"(assert (= {name} {objective}))"]
    # The search works on sign * objective, so that better is always larger.
    sign = 1 if direction == "max" else -1
    at_least = ">=" if direction == "max" else "<="
    deadline = time.monotonic() + timeout_ms / 1000
    checks = 0

    def z3_check(target: int | None) -> SolverResult:
        nonlocal checks
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms < 1 or checks >= max_checks:
            return SolverResult("unknown", None, _z3_version())
        checks += 1
        extra = [] if target is None else [f"(assert ({at_least} {name} {_int(sign * target)}))"]
        return run("z3", "\n".join([*base, *extra, "(check-sat)"]) + "\n", remaining_ms)

    def unknown() -> Optimum:
        # cvc5 does not run, so its version is read from the package.
        return Optimum("unknown", None, None, versions(), False)

    first = z3_check(None)
    if first.status == "unsat":
        return Optimum("infeasible", None, None, versions(), False)
    if first.status == "unknown":
        return unknown()
    model = first.model
    best = sign * model[OBJECTIVE]  # the best value found so far, as sign * objective
    above: int | None = None  # the least value proved out of reach, once one is
    step = 1
    while True:
        if above is None:
            target = best + step
            step *= 2
        elif above == best + 1:
            break
        else:
            target = best + (above - best) // 2
        found = z3_check(target)
        if found.status == "unknown":
            return unknown()
        if found.status == "unsat":
            above = target
            proof = found  # Z3's unsat for the last target
        else:
            model = found.model
            best = sign * model[OBJECTIVE]
    value = sign * best

    better = ">" if direction == "max" else "<"
    confirm = "\n".join([*base, f"(assert ({better} {name} {_int(value)}))", "(check-sat)"]) + "\n"
    cvc5_result = run("cvc5", confirm, timeout_ms)
    if cvc5_result.status == "sat":
        what = f"cvc5 finds an objective {'above' if direction == 'max' else 'below'} {value}"
        raise SolverDisagreement(proof, cvc5_result, f"{context}: {what}" if context else what)
    return Optimum(
        "optimal" if cvc5_result.status == "unsat" else "unknown",
        value,
        model,
        {"z3": proof.version, "cvc5": cvc5_result.version},
        cvc5_result.status == "unsat",
    )


def _int(value: int) -> str:
    """An SMT-LIB integer literal, which cannot be written with a minus sign."""
    return str(value) if value >= 0 else f"(- {-value})"


def versions() -> dict[str, str]:
    return {"z3": _z3_version(), "cvc5": _cvc5_version(cvc5.Solver(cvc5.TermManager()))}


def run(solver: Literal["z3", "cvc5"], script: str, timeout_ms: int) -> SolverResult:
    match solver:
        case "z3":
            return _run_z3(script, timeout_ms)
        case "cvc5":
            return _run_cvc5(script, timeout_ms)
    raise ValueError(f"unknown solver {solver!r}")


def _z3_version() -> str:
    return z3.get_version_string()


def _cvc5_version(s: cvc5.Solver) -> str:
    version = s.getVersion()
    return version.decode() if isinstance(version, bytes) else str(version)


def _unquote(symbol: str) -> str:
    return symbol[1:-1] if symbol.startswith("|") else symbol


def _run_z3(script: str, timeout_ms: int) -> SolverResult:
    version = _z3_version()
    # A fresh context per call: Z3's shared main context keeps state between
    # calls that changes the search, so results would depend on what ran first.
    ctx = z3.Context()
    try:
        engine = z3.Solver(ctx=ctx)
        engine.set("timeout", timeout_ms)
        engine.add(z3.parse_smt2_string(script, ctx=ctx))
        outcome = engine.check()
    except z3.Z3Exception as error:
        raise SolverError(f"z3 could not run the script: {error}") from error
    if outcome == z3.unsat:
        return SolverResult("unsat", None, version)
    if outcome != z3.sat:
        return SolverResult("unknown", None, version)

    model = engine.model()
    values: Model = {}
    for symbol, sort in _DECLARATION.findall(re.sub(r";[^\n]*", "", script)):
        name = _unquote(symbol)
        if sort == "Int":
            values[name] = model.eval(z3.Int(name, ctx), model_completion=True).as_long()
        elif sort == "Bool":
            values[name] = z3.is_true(model.eval(z3.Bool(name, ctx), model_completion=True))
        else:
            raise SolverError(f"z3 model value for {name} has sort {sort}; expected Int or Bool")
    return SolverResult("sat", values, version)


def _run_cvc5(script: str, timeout_ms: int) -> SolverResult:
    tm = cvc5.TermManager()
    engine = cvc5.Solver(tm)
    version = _cvc5_version(engine)
    engine.setOption("produce-models", "true")
    engine.setOption("tlimit-per", str(timeout_ms))
    symbols = cvc5.SymbolManager(tm)
    parser = cvc5.InputParser(engine, symbols)
    if not _SET_LOGIC.search(script):
        script = "(set-logic ALL)\n" + script
    outcome: str | None = None
    try:
        parser.setStringInput(cvc5.InputLanguage.SMT_LIB_2_6, script, "script")
        while not (command := parser.nextCommand()).isNull():
            output = command.invoke(engine, symbols)
            if str(command).startswith("(check-sat"):
                outcome = output.strip()
        if outcome is None:
            outcome = str(engine.checkSat()).strip()
    except RuntimeError as error:
        raise SolverError(f"cvc5 could not run the script: {error}") from error
    if outcome == "unsat":
        return SolverResult("unsat", None, version)
    if outcome != "sat":
        return SolverResult("unknown", None, version)

    values: Model = {}
    for term in symbols.getDeclaredTerms():
        name = _unquote(str(term))
        sort = term.getSort()
        value = engine.getValue(term)
        if sort.isBoolean():
            values[name] = value.getBooleanValue()
        elif sort.isInteger():
            values[name] = int(value.getIntegerValue())
        else:
            raise SolverError(f"cvc5 model value for {name} has sort {sort}; expected Int or Bool")
    return SolverResult("sat", values, version)
