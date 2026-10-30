from fractions import Fraction
import time
from importlib.metadata import version

import pytest
import z3

from bm import solvers

SOLVERS = ["z3", "cvc5"]

SAT = """
(declare-const |a b| Int)
(declare-const flag Bool)
(define-fun double ((x Int)) Int (* 2 x))
(assert (= (double |a b|) 10))
(assert flag)
(check-sat)
"""
UNSAT = SAT.replace("(check-sat)", "(assert (not flag))\n(check-sat)")

# x^3 + y^3 + z^3 = 33 with large positive variables: nothing a solver settles
# in a millisecond.
HARD = """
(declare-const x Int)
(declare-const y Int)
(declare-const z Int)
(assert (> x 1000))
(assert (> y 1000))
(assert (> z 1000))
(assert (= (+ (* x x x) (* y y y) (* z z z)) 33333333333333333))
(check-sat)
"""


@pytest.mark.parametrize("solver", SOLVERS)
def test_solver_sat_unsat(solver):
    sat = solvers.run(solver, SAT, 10_000)
    assert sat.status == "sat"
    assert sat.model == {"a b": 5, "flag": True}
    assert all(type(v) in (int, bool) for v in sat.model.values())
    assert sat.version
    unsat = solvers.run(solver, UNSAT, 10_000)
    assert unsat.status == "unsat"
    assert unsat.model is None


@pytest.mark.parametrize("solver", SOLVERS)
def test_solver_timeout_is_unknown(solver):
    result = solvers.run(solver, HARD, 1)
    assert result.status == "unknown"
    assert result.model is None


@pytest.mark.parametrize("solver", SOLVERS)
def test_real_valued_constant_is_an_error(solver):
    with pytest.raises(solvers.SolverError):
        solvers.run(solver, "(declare-const r Real)\n(assert (= r 0.5))\n(check-sat)", 10_000)


@pytest.mark.parametrize("solver", SOLVERS)
def test_malformed_script_is_an_error(solver):
    with pytest.raises(solvers.SolverError):
        solvers.run(solver, "(assert (= nothing 1))", 10_000)


def test_versions():
    versions = solvers.versions()
    assert set(versions) == {"z3", "cvc5"}
    # cvc5 reports its own build string: "1.4.2" from the macOS wheel,
    # "1.4.2-modified" from the Linux one. Both must be the locked package.
    assert versions["cvc5"].split("-")[0] == version("cvc5")
    assert versions["z3"].startswith("5.")


def test_disagreement_message_with_equal_statuses():
    text = str(solvers.SolverDisagreement(
        solvers.SolverResult("sat", {}, "z"), solvers.SolverResult("sat", {}, "c"), "ctx"))
    assert "says sat but cvc5 says sat" not in text and "ctx" in text
    assert text == "z3 and cvc5 disagree: ctx"


def test_disagreement_carries_both_results():
    a = solvers.SolverResult("sat", {"x": 1}, "z3 1")
    b = solvers.SolverResult("unsat", None, "cvc5 1")
    error = solvers.SolverDisagreement(a, b)
    assert error.z3 is a and error.cvc5 is b
    assert "sat" in str(error) and "unsat" in str(error)


BOX = ["(declare-const x Int)", "(assert (<= 0 x 7))"]


def _cvc5_answers(monkeypatch, status):
    """Make cvc5 answer `status` to everything; Z3 still runs for real."""
    real = solvers.run

    def run(solver, script, timeout_ms):
        if solver == "cvc5":
            return solvers.SolverResult(status, {"x": 8} if status == "sat" else None, "cvc5 fake")
        return real(solver, script, timeout_ms)

    monkeypatch.setattr(solvers, "run", run)


def test_optimise_max():
    result = solvers.optimise_and_confirm(BOX, "x", "max", 10_000)
    assert result.status == "optimal"
    assert result.value == 7
    assert result.model["x"] == 7
    assert result.confirmed is True
    assert set(result.versions) == {"z3", "cvc5"}


def test_optimise_min():
    result = solvers.optimise_and_confirm(BOX, "x", "min", 10_000)
    assert result.status == "optimal"
    assert result.value == 0
    assert result.confirmed is True


def test_optimise_does_not_change_the_callers_lines():
    lines = list(BOX)
    solvers.optimise_and_confirm(lines, "x", "max", 10_000)
    assert lines == BOX


def test_optimise_objective_may_be_a_term():
    result = solvers.optimise_and_confirm(BOX, "(- 10 x)", "max", 10_000)
    assert result.value == 10
    assert result.model["x"] == 0


def test_optimise_infeasible():
    lines = [*BOX, "(assert (> x 3))", "(assert (< x 2))"]
    result = solvers.optimise_and_confirm(lines, "x", "max", 10_000)
    assert result.status == "infeasible"
    assert result.value is None and result.model is None
    assert result.confirmed is False
    assert set(result.versions) == {"z3", "cvc5"}


def test_optimise_z3_unknown():
    lines = HARD.replace("(check-sat)\n", "").strip().splitlines()
    result = solvers.optimise_and_confirm(lines, "x", "max", 1)
    assert result.status == "unknown"
    assert result.value is None and result.model is None
    assert result.confirmed is False
    assert set(result.versions) == {"z3", "cvc5"}


def test_optimise_disagreement(monkeypatch):
    _cvc5_answers(monkeypatch, "sat")
    with pytest.raises(solvers.SolverDisagreement, match="a widget"):
        solvers.optimise_and_confirm(BOX, "x", "max", 10_000, context="a widget")


def test_optimise_cvc5_unknown_keeps_z3(monkeypatch):
    _cvc5_answers(monkeypatch, "unknown")
    result = solvers.optimise_and_confirm(BOX, "x", "max", 10_000)
    assert result.status == "unknown"
    assert result.value == 7
    assert result.model["x"] == 7
    assert result.confirmed is False
    assert result.versions["cvc5"] == "cvc5 fake"


def _count_z3_calls(monkeypatch) -> list[int]:
    """Count the Z3 checks that `optimise_and_confirm` makes."""
    real = solvers.run
    calls = [0]

    def run(solver, script, timeout_ms):
        if solver == "z3":
            calls[0] += 1
        return real(solver, script, timeout_ms)

    monkeypatch.setattr(solvers, "run", run)
    return calls


@pytest.mark.parametrize(("direction", "expected"), [("max", 1_000_000), ("min", -1_000_000)])
def test_optimise_wide_objective_takes_few_checks(monkeypatch, direction, expected):
    # Climbing one unit at a time would take a million checks. Galloping and
    # bisection take about two per bit of the range.
    calls = _count_z3_calls(monkeypatch)
    lines = ["(declare-const x Int)", "(assert (<= (- 1000000) x 1000000))"]
    result = solvers.optimise_and_confirm(lines, "x", direction, 10_000)
    assert result.status == "optimal"
    assert result.value == expected and result.model["x"] == expected
    assert calls[0] <= 2 * 21 + 2


def test_optimise_unbounded_objective_is_unknown_and_stops(monkeypatch):
    calls = _count_z3_calls(monkeypatch)
    lines = ["(declare-const x Int)", "(assert (>= x 0))"]
    started = time.monotonic()
    result = solvers.optimise_and_confirm(lines, "x", "max", 1_000)
    assert time.monotonic() - started < 10
    assert result.status == "unknown"
    assert result.value is None and result.model is None
    assert result.confirmed is False
    assert calls[0] > 1


def test_unbounded_objective_is_unknown_within_the_check_cap():
    # An objective with no upper bound: the search gallops until the cap.
    result = solvers.optimise_and_confirm(
        ["(declare-const x Int)", "(assert (>= x 0))"], "x", "max", timeout_ms=60_000, max_checks=20
    )
    assert result.status == "unknown" and result.value is None


def test_the_check_cap_counts_z3_checks(monkeypatch):
    calls = _count_z3_calls(monkeypatch)
    lines = ["(declare-const x Int)", "(assert (>= x 0))"]
    solvers.optimise_and_confirm(lines, "x", "max", timeout_ms=60_000, max_checks=5)
    assert calls[0] == 5


def test_a_cap_above_what_the_search_needs_changes_nothing():
    result = solvers.optimise_and_confirm(BOX, "x", "max", 10_000, max_checks=200)
    assert result.status == "optimal" and result.value == 7


def test_optimise_small_integer_problem():
    lines = [
        "(declare-const x Int)",
        "(declare-const y Int)",
        "(assert (<= 0 x 10))",
        "(assert (<= 0 y 10))",
        "(assert (<= (+ x y) 12))",
    ]
    result = solvers.optimise_and_confirm(lines, "(- (* 3 x) y)", "max", 10_000)
    assert result.status == "optimal" and result.value == 30
    assert (result.model["x"], result.model["y"]) == (10, 0)


def test_optimise_z3_unknown_during_the_search_gives_no_value(monkeypatch):
    # Z3 finds a first model, then cannot settle whether a better one exists.
    real = solvers.run
    seen = []

    def run(solver, script, timeout_ms):
        seen.append(solver)
        if solver == "z3" and len(seen) > 1:
            return solvers.SolverResult("unknown", None, "z3 fake")
        return real(solver, script, timeout_ms)

    monkeypatch.setattr(solvers, "run", run)
    result = solvers.optimise_and_confirm(BOX, "x", "max", 10_000)
    assert result.status == "unknown"
    assert result.value is None and result.model is None
    assert result.confirmed is False
    assert "cvc5" not in seen


def test_optimise_nonlinear_objective():
    lines = [
        "(declare-const x Int)",
        "(declare-const y Int)",
        "(assert (and (> x 0) (< x 100000) (> y 0) (< y 100000)))",
    ]
    result = solvers.optimise_and_confirm(lines, "(* x y)", "max", 10_000)
    assert result.status == "optimal"
    assert result.value == 99999 * 99999


def test_z3_runs_in_a_fresh_context(monkeypatch):
    # Work done earlier in the process must not change Z3's search, so each
    # call has a context of its own, never Z3's shared main context.
    real = z3.Solver
    contexts = []

    def solver(*args, **kwargs):
        engine = real(*args, **kwargs)
        contexts.append(engine.ctx)
        return engine

    monkeypatch.setattr(z3, "Solver", solver)
    for _ in range(2):
        assert solvers.run("z3", SAT, 10_000).model == {"a b": 5, "flag": True}
    assert len(contexts) == 2 and contexts[0] is not contexts[1]
    assert all(c is not z3.main_ctx() for c in contexts)


REAL_BOX = ["(declare-const x Real)", "(assert (<= 0.0 x 2.5))"]


@pytest.mark.parametrize("direction", ["max", "min"])
def test_real_objective_gives_the_largest_reachable_integer(direction):
    # The supremum of x is 5/2 and its infimum is 0. The value is the integer
    # the search proves reachable that is furthest in the direction: 2 for the
    # maximum and 0 for the minimum.
    result = solvers.optimise_and_confirm(REAL_BOX, "x", direction, 10_000, sort="Real")
    assert result.status == "optimal" and result.confirmed
    assert result.value == (2 if direction == "max" else 0)
    assert isinstance(result.model["x"], Fraction)
    assert Fraction(result.value) - 1 < result.model["x"] < Fraction(5, 2) + 1
    assert result.model["bm.objective"] == result.model["x"]


def test_real_objective_below_an_integer_is_not_confirmed_optimal_early():
    # x < 3 exactly: no real value reaches 3, but every integer below is reachable.
    lines = ["(declare-const x Real)", "(assert (and (<= 0.0 x) (< x 3.0)))"]
    result = solvers.optimise_and_confirm(lines, "x", "max", 10_000, sort="Real")
    assert (result.status, result.value, result.confirmed) == ("optimal", 2, True)


def test_real_sort_must_be_named():
    with pytest.raises(solvers.SolverError):
        solvers.optimise_and_confirm(REAL_BOX, "x", "max", 10_000)
    with pytest.raises(ValueError):
        solvers.optimise_and_confirm(REAL_BOX, "x", "max", 10_000, sort="Float")


@pytest.mark.parametrize("solver", SOLVERS)
def test_real_constants_are_read_as_fractions_when_asked(solver):
    script = "(declare-const r Real)\n(assert (= r (/ 11.0 2.0)))\n(check-sat)"
    result = solvers.run(solver, script, 10_000, reals=True)
    assert result.model == {"r": Fraction(11, 2)}
    assert isinstance(result.model["r"], Fraction)
