from importlib.metadata import version

import pytest

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


def test_z3_maximize():
    script = """
(declare-const x Int)
(assert (<= 0 x 7))
(maximize x)
(check-sat)
"""
    result = solvers.run("z3", script, 10_000)
    assert result.status == "sat"
    assert result.model == {"x": 7}


def test_z3_maximize_timeout_is_unknown():
    script = HARD.replace("(check-sat)", "(maximize x)\n(check-sat)")
    result = solvers.run("z3", script, 1)
    assert result.status == "unknown"
    assert result.model is None


def test_z3_maximize_unbounded_is_unknown():
    # Z3 answers sat with an arbitrary model (x = 0) and reason "unknown".
    script = "(declare-const x Int)\n(assert (>= x 0))\n(maximize x)\n(check-sat)"
    result = solvers.run("z3", script, 10_000)
    assert result.status == "unknown"
    assert result.model is None


def test_z3_maximize_unbounded_nonlinear_is_unknown():
    script = """
(declare-const x Int)
(declare-const y Int)
(assert (> x 0))
(assert (= y (* x x)))
(maximize y)
(check-sat)
"""
    result = solvers.run("z3", script, 1_000)
    assert result.status == "unknown"
    assert result.model is None


def test_z3_maximize_small_integer_problem_is_sat():
    script = """
(declare-const x Int)
(declare-const y Int)
(assert (<= 0 x 10))
(assert (<= 0 y 10))
(assert (<= (+ x y) 12))
(maximize (- (* 3 x) y))
(check-sat)
"""
    result = solvers.run("z3", script, 10_000)
    assert result.status == "sat"
    assert result.model == {"x": 10, "y": 0}


def test_z3_maximize_proved_optimum_is_sat():
    # A nonlinear objective that Z3 does solve: the optimum must still come back.
    script = """
(declare-const x Int)
(declare-const y Int)
(assert (and (> x 0) (< x 100000) (> y 0) (< y 100000)))
(maximize (* x y))
(check-sat)
"""
    result = solvers.run("z3", script, 10_000)
    assert result.status == "sat"
    assert result.model == {"x": 99999, "y": 99999}


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
