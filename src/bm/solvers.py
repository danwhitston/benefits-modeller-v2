"""Run Z3 and cvc5 on SMT-LIB text.

Both solvers are driven through their Python packages (`z3-solver` and `cvc5`),
so no solver binary is needed. cvc5 reads text through its `InputParser`: the
script's commands are executed one by one against a `Solver` and a
`SymbolManager`, which is what the `cvc5` binary does with a file. The cvc5
binary from the GitHub release is therefore not used, and the Makefile pins no
checksum for it.

Z3 uses `Solver` and `parse_smt2_string`, or `Optimize` when the script holds
Z3-specific commands such as `(maximize ...)`. cvc5 is never sent those.

`optimise_and_confirm` is the one routine for an optimum: Z3 finds it and cvc5
confirms that nothing better exists.

A timeout gives status "unknown". So does a Z3 optimisation that answers sat
without proving the objective optimal, because that model is not a result.
Anything else that goes wrong, such as a script that does not parse, raises
`SolverError`.

Models cover the declared constants only, as ints and bools. A declared
constant of another sort (Real, for example) in a satisfiable script raises
`SolverError`, because the project's queries have no such constants.
"""

import re
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
_Z3_ONLY = re.compile(r"\(\s*(?:maximize|minimize|assert-soft)\b")
_INTERRUPTED = re.compile(r"cancel|timeout|memout|resource", re.IGNORECASE)
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
        text = f"z3 says {z3_result.status} but cvc5 says {cvc5_result.status}"
        super().__init__(f"{context}: {text}" if context else text)


@dataclass(frozen=True)
class Optimum:
    """The outcome of `optimise_and_confirm`.

    `value` and `model` are Z3's optimum, and are kept when only cvc5 could not
    confirm it (`status` "unknown", `confirmed` False). They are None when Z3
    found nothing, whether the script is infeasible or Z3 ran out of time.
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
) -> Optimum:
    """Z3 optimises the SMT-LIB term `objective`; cvc5 confirms nothing is better.

    `lines` are the script's commands without `(check-sat)`; the list is not
    changed. The objective is declared as `|bm.objective|`, so its value is
    read from the model. Z3 maximises or minimises it, and cvc5 is then asked
    for a value above the maximum (or below the minimum) within the same lines.

    Raises `SolverDisagreement`, carrying `context`, if cvc5 finds one. If Z3
    is unsat the status is "infeasible", and if Z3 or cvc5 is unknown the
    status is "unknown". Neither is ever read as an optimum.
    """
    if direction not in ("max", "min"):
        raise ValueError(f"direction must be 'max' or 'min', not {direction!r}")
    name = f"|{OBJECTIVE}|"
    base = [*lines, f"(declare-const {name} Int)", f"(assert (= {name} {objective}))"]
    command = "maximize" if direction == "max" else "minimize"
    z3_script = "\n".join([*base, f"({command} {name})", "(check-sat)"]) + "\n"
    z3_result = run("z3", z3_script, timeout_ms)
    if z3_result.status != "sat":
        status = "infeasible" if z3_result.status == "unsat" else "unknown"
        # cvc5 does not run, so its version is read from the package.
        return Optimum(status, None, None, versions(), False)
    value = z3_result.model[OBJECTIVE]

    better = ">" if direction == "max" else "<"
    literal = str(value) if value >= 0 else f"(- {-value})"
    confirm = "\n".join([*base, f"(assert ({better} {name} {literal}))", "(check-sat)"]) + "\n"
    cvc5_result = run("cvc5", confirm, timeout_ms)
    if cvc5_result.status == "sat":
        what = f"cvc5 finds an objective {'above' if direction == 'max' else 'below'} {value}"
        raise SolverDisagreement(z3_result, cvc5_result, f"{context}: {what}" if context else what)
    return Optimum(
        "optimal" if cvc5_result.status == "unsat" else "unknown",
        value,
        z3_result.model,
        {"z3": z3_result.version, "cvc5": cvc5_result.version},
        cvc5_result.status == "unsat",
    )


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
    try:
        if _Z3_ONLY.search(script):
            engine = z3.Optimize()
            engine.set("timeout", timeout_ms)
            engine.from_string(script)
        else:
            engine = z3.Solver()
            engine.set("timeout", timeout_ms)
            engine.add(z3.parse_smt2_string(script))
        outcome = engine.check()
    except z3.Z3Exception as error:
        raise SolverError(f"z3 could not run the script: {error}") from error
    if outcome == z3.unsat:
        return SolverResult("unsat", None, version)
    if outcome != z3.sat:
        return SolverResult("unknown", None, version)
    if isinstance(engine, z3.Optimize) and not _proved_optimal(engine):
        # Z3 can answer sat for an optimisation problem without having proved
        # the objective optimal (an unbounded objective, a nonlinear one, or a
        # run cut short). That model is not a result.
        return SolverResult("unknown", None, version)

    model = engine.model()
    values: Model = {}
    for symbol, sort in _DECLARATION.findall(re.sub(r";[^\n]*", "", script)):
        name = _unquote(symbol)
        if sort == "Int":
            values[name] = model.eval(z3.Int(name), model_completion=True).as_long()
        elif sort == "Bool":
            values[name] = z3.is_true(model.eval(z3.Bool(name), model_completion=True))
        else:
            raise SolverError(f"z3 model value for {name} has sort {sort}; expected Int or Bool")
    return SolverResult("sat", values, version)


def _proved_optimal(engine: z3.Optimize) -> bool:
    """Z3 closed the gap on every objective, so the model is an optimum.

    `reason_unknown` is not a reliable signal here: Z3 reports "unknown" next
    to some optima it has proved. The bounds are: the upper and lower bound of
    each objective are the same number exactly when the optimum is proved.
    Unbounded, unproved or infinitesimal bounds are never equal numerals.
    """
    if _INTERRUPTED.search(engine.reason_unknown()):
        return False
    ref = engine.ctx.ref()
    for i in range(len(engine.objectives())):
        # OptimizeObjective wraps the bound ASTs as reference-counted ExprRefs,
        # so no raw Z3_ast pointer is held. Whether objective i is a maximum or
        # a minimum only matters for `.value()`, which is not used here.
        objective = z3.OptimizeObjective(engine, i, False)
        upper, lower = objective.upper(), objective.lower()
        if not (z3.Z3_is_numeral_ast(ref, upper.as_ast()) and upper.eq(lower)):
            return False
    return True


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
