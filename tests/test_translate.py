import json
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest
import z3

from bm import evaluate, ir, solvers, translate

ROOT = Path(__file__).resolve().parent.parent
UC_IR = ROOT / "build" / "uc.bm-ir.json"
FIXTURES = ROOT / "exporter" / "test"


def days(d: date) -> int:
    return (d - date(1970, 1, 1)).days


# Builders for small bm-ir documents, in the shapes Catala exports.

POS = {"file": "test.catala_en", "line": 1}


def lit(type_, value, line=1):
    return {"k": "lit", "type": type_, "value": value, "pos": {**POS, "line": line}}


def var(name):
    return {"k": "var", "name": name, "pos": POS}


def op(name, *args, line=1):
    return {"k": "op", "op": name, "args": list(args), "pos": {**POS, "line": line}}


def rule(just, value):
    """One `definition ... under condition just consequence equals value`."""
    return {
        "k": "default",
        "exceptions": [],
        "just": just,
        "cons": {"k": "pure", "arg": value, "pos": POS},
        "pos": POS,
    }


def variable(*rules):
    """The bare default Catala builds for a variable with these rules."""
    return {
        "k": "default",
        "exceptions": list(rules),
        "just": lit("bool", "false"),
        "cons": {"k": "empty", "pos": POS},
        "pos": POS,
    }


def output(value):
    """An output defined unconditionally as `value`."""
    return {
        "k": "error_on_empty",
        "arg": variable(rule(lit("bool", "true"), value)),
        "pos": POS,
    }


def document(inputs, definitions, outputs):
    return {
        "bm_ir_version": 1,
        "catala_version": "1.3.0",
        "scope": "Test",
        "inputs": [{"name": n, "type": t} for n, t in inputs],
        "outputs": outputs,
        "definitions": [{"name": n, "type": t, "expr": e} for n, t, e in definitions],
    }


def load_doc(tmp_path, doc):
    path = tmp_path / "test.bm-ir.json"
    path.write_text(json.dumps(doc))
    return ir.load(path)


def is_linear(module: translate.SmtModule, assertion: str) -> bool:
    """Whether Z3 classes the module plus one assertion as linear arithmetic."""
    decls = "".join(
        f"(declare-const |{v.name}| {translate.SORTS[v.type]})" for v in module.inputs
    )
    goal = z3.Goal()
    goal.add(z3.parse_smt2_string(module.text + decls + assertion))
    return z3.Probe("is-lira")(goal) == 1.0


# Tests


@pytest.mark.parametrize(
    ("pence", "rate", "expected"),
    [
        (10, "11/20", 6),
        (1, "11/20", 1),
        (-10, "11/20", -6),
        (-1, "1/2", -1),
        (3, "1/2", 2),
    ],
)
def test_round_half_away_from_zero(tmp_path, pence, rate, expected):
    doc = document(
        [("m", "money")],
        [("x", "money", output(op("Mult_mon_rat", var("m"), lit("decimal", rate))))],
        ["x"],
    )
    module = translate.translate(load_doc(tmp_path, doc))
    assert evaluate.outputs(module, {"m": pence}) == {"x": expected}


def test_exception_conflict_obligation():
    module = translate.translate(ir.load(FIXTURES / "exception.expected.json"))
    conflicts = [o for o in module.obligations if o.kind == "conflict"]
    assert len(conflicts) == 1
    assert conflicts[0].definition == "amount"


def test_exception_values():
    module = translate.translate(ir.load(FIXTURES / "exception.expected.json"))
    assert evaluate.outputs(module, {"high": False, "low": False}) == {"amount": 10000}
    assert evaluate.outputs(module, {"high": True, "low": False}) == {"amount": 20000}
    assert evaluate.outputs(module, {"high": False, "low": True}) == {"amount": 5000}
    with pytest.raises(evaluate.EvaluationError, match="conflict"):
        evaluate.outputs(module, {"high": True, "low": True})


# The nine cases in rules/uc_tests.catala_en, all with an assessment period
# starting on 1 May 2026: (earned income, aged 25 or over, has LCW,
# earnings deduction, award), money in pence.
UC_CASES = [
    (0, True, True, 0, 42490),
    (71000, True, True, 0, 42490),
    (100000, True, True, 15950, 26540),
    (71010, True, True, 6, 42484),
    (71001, True, True, 1, 42489),
    (148253, True, True, 42489, 1),
    (148254, True, True, 42490, 0),
    (50000, True, False, 27500, 14990),
    (100000, False, False, 55000, 0),
]


@pytest.mark.parametrize(("earned", "aged_25", "lcw", "deduction", "award"), UC_CASES)
def test_uc_outputs(earned, aged_25, lcw, deduction, award):
    module = translate.translate(ir.load(UC_IR))
    result = evaluate.outputs(
        module,
        {
            "assessment_period_start": days(date(2026, 5, 1)),
            "earned_income": earned,
            "aged_25_or_over": aged_25,
            "has_lcw": lcw,
            "housing_costs_element": 0,
        },
    )
    assert result["earnings_deduction"] == deduction
    assert result["award"] == award


def test_unsupported_operator(tmp_path):
    doc = document(
        [("a", "integer")],
        [("x", "integer", output(op("Pow_int_int", var("a"), var("a"), line=42)))],
        ["x"],
    )
    with pytest.raises(translate.UnsupportedOperator, match=r"Pow_int_int.*test\.catala_en:42"):
        translate.translate(load_doc(tmp_path, doc))


def test_mult_by_decimal_input_is_nonlinear():
    # `scaled` multiplies money by the decimal input `r`.
    with pytest.raises(translate.NonlinearTerm):
        translate.translate(ir.load(FIXTURES / "arith.expected.json"))


def test_mult_distributes_over_dated_rate():
    # `deduction = income * rate`, where `rate` is 55% from 6 April 2026 and
    # undefined before.
    module = translate.translate(ir.load(FIXTURES / "internal.expected.json"))
    assert is_linear(module, "(assert (= (|deduction| |start| |income|) 0))")

    after = days(date(2026, 4, 6))
    assert evaluate.outputs(module, {"start": after, "income": 71010}) == {
        "deduction": 39056  # 55% x 710.10 = 390.555, rounded to 390.56
    }
    # Before the condition Catala stops with an error, because `rate` has no value.
    with pytest.raises(evaluate.EvaluationError, match="empty.*deduction"):
        evaluate.outputs(module, {"start": after - 1, "income": 71010})


def test_mult_distributes_over_two_dated_rates(tmp_path):
    start = var("start")
    rate = variable(
        rule(
            op(
                "And",
                op("Gte", start, lit("date", "2026-04-06")),
                op("Lt", start, lit("date", "2027-04-06")),
            ),
            lit("decimal", "11/20"),
        ),
        rule(op("Gte", start, lit("date", "2027-04-06")), lit("decimal", "3/5")),
    )
    used = {"k": "error_on_empty", "arg": var("rate"), "pos": POS}
    doc = document(
        [("start", "date"), ("income", "money")],
        [
            ("rate", "decimal", rate),
            ("deduction", "money", output(op("Mult_mon_rat", var("income"), used))),
            ("share", "money", output(op("Div_mon_rat", var("income"), used))),
        ],
        ["deduction", "share"],
    )
    module = translate.translate(load_doc(tmp_path, doc))
    assert is_linear(module, "(assert (= (|deduction| |start| |income|) 0))")

    boundary = days(date(2027, 4, 6))
    assert evaluate.outputs(module, {"start": boundary - 1, "income": 1001}) == {
        "deduction": 551,  # 1001 x 11/20 = 550.55
        "share": 1820,  # 1001 x 20/11 = 1820 exactly
    }
    assert evaluate.outputs(module, {"start": boundary, "income": 1001}) == {
        "deduction": 601,  # 1001 x 3/5 = 600.6
        "share": 1668,  # 1001 x 5/3 = 1668.33...
    }


def test_decimal_output_is_exact(tmp_path):
    doc = document(
        [],
        [("rate", "decimal", output(lit("decimal", "1/3")))],
        ["rate"],
    )
    module = translate.translate(load_doc(tmp_path, doc))
    assert evaluate.outputs(module, {}) == {"rate": Fraction(1, 3)}


def test_uc_module_shape():
    module = translate.translate(ir.load(UC_IR))
    assert module.functions == {
        "deduction_rate": "|deduction_rate|",
        "standard_allowance": "|standard_allowance|",
        "work_allowance": "|work_allowance|",
        "earnings_deduction": "|earnings_deduction|",
        "maximum_amount": "|maximum_amount|",
        "award": "|award|",
    }
    assert module.text.count("(define-fun bm_round ") == 1
    params = (
        "((|assessment_period_start| Int) (|earned_income| Int)"
        " (|aged_25_or_over| Bool) (|has_lcw| Bool) (|housing_costs_element| Int))"
    )
    assert f"(define-fun |award| {params} Int " in module.text
    assert f"(define-fun |award.defined| {params} Bool " in module.text
    kinds = sorted((o.kind, o.definition) for o in module.obligations)
    assert kinds == [
        ("conflict", "standard_allowance"),
        # Three work allowance rules, so three pairs that could conflict.
        ("conflict", "work_allowance"),
        ("conflict", "work_allowance"),
        ("conflict", "work_allowance"),
        ("empty", "award"),
        ("empty", "earnings_deduction"),
        ("empty", "earnings_deduction"),
        ("empty", "maximum_amount"),
        ("empty", "standard_allowance"),
        ("empty", "work_allowance"),
    ]


def test_empty_obligation_holds_only_where_reached(tmp_path):
    # `rate` has no value before 6 April 2026, but the branch that uses it is
    # not taken then, so Catala returns $0.00 instead of stopping.
    start = var("start")
    after = op("Gte", start, lit("date", "2026-04-06"))
    used = {"k": "error_on_empty", "arg": var("rate"), "pos": {**POS, "line": 9}}
    deduction = {
        "k": "if",
        "cond": after,
        "then": op("Mult_mon_rat", var("income"), used),
        "else": lit("money", "0"),
        "pos": POS,
    }
    doc = document(
        [("start", "date"), ("income", "money")],
        [
            ("rate", "decimal", variable(rule(after, lit("decimal", "11/20")))),
            ("deduction", "money", output(deduction)),
        ],
        ["deduction"],
    )
    module = translate.translate(load_doc(tmp_path, doc))
    boundary = days(date(2026, 4, 6))
    assert evaluate.outputs(module, {"start": boundary - 1, "income": 1000}) == {"deduction": 0}
    assert evaluate.outputs(module, {"start": boundary, "income": 1000}) == {"deduction": 550}


def rounded(exact: Fraction) -> int:
    """`exact` rounded to the nearest whole number, halves away from zero."""
    magnitude = int(abs(exact) + Fraction(1, 2))  # int() truncates towards zero
    return magnitude if exact >= 0 else -magnitude


RATE_MONEY = [0, 1, 5, 6, 122890, 10**6]
RATE_PENCE = sorted({*RATE_MONEY, *(-m for m in RATE_MONEY)})


def rate_module(tmp_path, operator, rate):
    """A scope with one output, `x = m <operator> rate`, as the rules write it."""
    doc = document(
        [("m", "money")],
        [("x", "money", output(op(operator, var("m"), lit("decimal", rate))))],
        ["x"],
    )
    return translate.translate(load_doc(tmp_path, doc))


def assert_both_solvers_give(module, pence, expected):
    """Z3 and cvc5 each find `x` equal to `expected` at `pence`, and nothing else."""
    equals = f"(= (|x| {translate.literal('Int', pence)}) {translate.literal('Int', expected)})"
    for solver in ("z3", "cvc5"):
        agree = solvers.run(solver, f"{module.text}(assert {equals})\n(check-sat)\n", 10_000)
        differ = solvers.run(solver, f"{module.text}(assert (not {equals}))\n(check-sat)\n", 10_000)
        assert (agree.status, differ.status) == ("sat", "unsat"), (solver, pence, expected)


def test_mult_by_20_over_11_matches_catala_rounding(tmp_path):
    module = rate_module(tmp_path, "Mult_mon_rat", "20/11")
    for pence in RATE_PENCE:
        assert_both_solvers_give(module, pence, rounded(Fraction(pence) * Fraction(20, 11)))


def test_mult_by_11_over_20_ties(tmp_path):
    module = rate_module(tmp_path, "Mult_mon_rat", "11/20")
    # 10 x 11/20 = 5.5, 30 x 11/20 = 16.5 and -10 x 11/20 = -5.5: exact half pennies.
    for pence, expected in [(10, 6), (30, 17), (-10, -6)]:
        assert rounded(Fraction(pence) * Fraction(11, 20)) == expected
        assert_both_solvers_give(module, pence, expected)
    for pence in RATE_PENCE:
        assert_both_solvers_give(module, pence, rounded(Fraction(pence) * Fraction(11, 20)))


def test_div_by_11_over_20_matches_catala_rounding(tmp_path):
    # The rules write the nil UC threshold as `maximum_amount / 0.55`, which is
    # a division by the constant 11/20 and not a product with 20/11.
    module = rate_module(tmp_path, "Div_mon_rat", "11/20")
    for pence in RATE_PENCE:
        assert_both_solvers_give(module, pence, rounded(Fraction(pence) / Fraction(11, 20)))
    # 11 / 0.55 = 20 exactly, and 1 / 0.55 = 1.81..., which rounds up.
    assert_both_solvers_give(module, 11, 20)
    assert_both_solvers_give(module, 1, 2)


def test_relaxed_has_no_rounding(tmp_path):
    doc = document(
        [("m", "money")],
        [("x", "money", output(op("Mult_mon_rat", var("m"), lit("decimal", "11/20"))))],
        ["x"],
    )
    scope = load_doc(tmp_path, doc)
    exact = translate.translate(scope)
    relaxed = translate.translate(scope, relaxed=True)
    assert (exact.relaxed, relaxed.relaxed) == (False, True)
    assert relaxed.outputs == {"x": "Real"}
    assert evaluate.outputs(exact, {"m": 10}) == {"x": 6}
    assert evaluate.outputs(relaxed, {"m": 10}) == {"x": Fraction(11, 2)}
    assert evaluate.outputs(relaxed, {"m": -10}) == {"x": Fraction(-11, 2)}


def test_relaxed_division_has_no_rounding(tmp_path):
    scope = load_doc(
        tmp_path,
        document(
            [("m", "money")],
            [("x", "money", output(op("Div_mon_rat", var("m"), lit("decimal", "11/20"))))],
            ["x"],
        ),
    )
    relaxed = translate.translate(scope, relaxed=True)
    assert evaluate.outputs(relaxed, {"m": 1}) == {"x": Fraction(20, 11)}


WINDOW_IR = ROOT / "build" / "claim_window.bm-ir.json"


def test_relaxed_window_is_real_valued_and_agrees_where_nothing_is_rounded():
    scope = ir.load(WINDOW_IR)
    exact = translate.translate(scope)
    relaxed = translate.translate(scope, relaxed=True)
    start = days(date(2026, 4, 6))
    household = {
        "start_1": start,
        "start_2": start + 30,
        "start_3": start + 61,
        "earnings_1": 0,
        "earnings_2": 0,
        "earnings_3": 0,
        "aged_25_or_over": True,
        "housing_costs_element": 0,
        "has_lcw": False,
        "claim_after_end": False,
        "claim_each_month": False,
        "lcw_carries_over": False,
    }
    # No earnings, so the relaxed translation has nothing to round differently.
    got = evaluate.outputs(relaxed, household)
    want = evaluate.outputs(exact, household)
    assert got["total_award"] == want["total_award"]
    assert all(
        sort == ("Bool" if name.startswith("entitled") else "Real")
        for name, sort in relaxed.outputs.items()
    )
    # The threshold is a quotient, which the relaxed translation leaves exact:
    # it is within half a penny of the rounded one.
    assert abs(got["nil_uc_threshold_1"] - want["nil_uc_threshold_1"]) <= Fraction(1, 2)


def test_relaxed_window_is_optimised_over_reals():
    """A relaxed probe runs through the script and the Real objective."""
    from bm import inputs
    from bm.household import Script

    scope = ir.load(WINDOW_IR)
    bounds = inputs.bounds(inputs.load(ROOT / "rules" / "claim_window.inputs.toml", scope))
    script = Script(translate.translate(scope, relaxed=True), bounds)
    household = script.instance()
    result = solvers.optimise_and_confirm(
        script.lines, household.output("total_award"), "max", 60_000, sort="Real"
    )
    # Three periods at the largest maximum amount: 424.90 + 804.00 = 1,228.90.
    assert (result.status, result.value, result.confirmed) == ("optimal", 3 * 122890, True)
