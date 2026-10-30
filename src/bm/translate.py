"""Translate a bm-ir scope into SMT-LIB.

Every definition becomes two functions of all the scope's inputs, in input
order: `|<name>|` gives its value and `|<name>.defined|` says whether it has
one. Sorts: money, integer and date are `Int` (pence, whole numbers, days since
1970-01-01); decimal is `Real`; bool is `Bool`.

Each expression translates to a pair (value, defined), following Catala's
default calculus (`Interpreter.evaluate_expr` in Catala 1.3.0):

- `default {exceptions, just, cons}` is defined if any exception is, with the
  value of the one that is. If none is, it is defined when `just` holds and
  `cons` is defined, with the value of `cons`. Two defined exceptions are a
  conflict, which is an error in Catala, so the value there does not matter.
- `pure e` is defined, `empty` is not.
- `error_on_empty e` takes the value of `e`, and an undefined `e` is an error.

Errors become obligations: a Bool term over the inputs that holds exactly when
evaluation reaches the node and the error happens there. Reaching a node
depends on the conditions above it: the branch of an `if`, and in a `default`,
`just` is evaluated only when no exception is defined, `cons` only when `just`
also holds.

Rounding follows Catala's `o_mult_mon_rat`: the exact product is rounded to the
nearest penny, halves away from zero. Money times a decimal is linear only when
the decimal is a constant, or an `ite` tree of constants such as a rate that
depends on the date; the product is then distributed into the branches.

`translate(scope, relaxed=True)` is for scaling probes and is not the rules. It
makes money `Real` and `bm_round` the identity, so nothing is rounded to the
penny. Its results are never findings about the rules: a relaxed award can
differ from Catala's by the pennies that the rounding moves. `SmtModule.relaxed`
says which translation a module is.
"""

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Literal

from bm import ir, units
from bm.ir import Pos, Var

SORTS = {"money": "Int", "integer": "Int", "date": "Int", "decimal": "Real", "bool": "Bool"}
BM_ROUND = (
    "(define-fun bm_round ((q Real)) Int"
    " (ite (>= q 0.0) (to_int (+ q 0.5)) (- (to_int (+ (- q) 0.5)))))"
)
# The relaxed translation: no rounding, and money is Real.
BM_ROUND_RELAXED = "(define-fun bm_round ((q Real)) Real q)"
RELAXED_SORTS = {**SORTS, "money": "Real"}


class TranslateError(ValueError):
    """The scope cannot be translated exactly."""


class UnsupportedOperator(TranslateError):
    def __init__(self, op: str, pos: Pos):
        super().__init__(f"Unsupported operator {op} at {pos}")
        self.op = op
        self.pos = pos


class NonlinearTerm(TranslateError):
    pass


@dataclass(frozen=True)
class Obligation:
    """A place where Catala can stop with an error.

    `formula` is a Bool term over the scope's inputs, as the quoted constants
    `|<input>|`, that holds exactly where the error happens. A definition's
    `.defined` function does not rule this out: at an `error_on_empty` site it
    is true even where Catala raises the error. So every query must assert
    that no obligation holds at its households, which
    `bm.household.Script.instance(defined=True)` does.
    """

    kind: Literal["empty", "conflict"]
    definition: str
    pos: Pos
    formula: str


@dataclass(frozen=True)
class SmtModule:
    """A translated scope.

    `text` defines `|<name>|` and `|<name>.defined|` for each definition, as
    functions of the inputs in order. `.defined` is true at `error_on_empty`
    sites even where Catala raises an error there, so it does not say that
    Catala returns a value. That holds only where no obligation holds, and
    every query must assert it, which `bm.household.Script.instance(defined=True)`
    does.
    """

    text: str
    inputs: list[Var]
    functions: dict[str, str]
    obligations: list[Obligation]
    # Output name to SMT sort, in the scope's order. `functions` also holds
    # internal definitions, so `bm.evaluate` reads this to know the outputs.
    outputs: dict[str, str]
    # True for the relaxed translation (see the module docstring): money is
    # `Real` and nothing is rounded. It is not the rules.
    relaxed: bool = False

    @property
    def sorts(self) -> dict[str, str]:
        """The SMT sort of each input, by name."""
        table = RELAXED_SORTS if self.relaxed else SORTS
        return {v.name: table[v.type] for v in self.inputs}


def quote(name: str) -> str:
    if "|" in name or "\\" in name:
        raise TranslateError(f"name {name!r} cannot be an SMT-LIB quoted symbol")
    return f"|{name}|"


def apply(function: str, args: list[str]) -> str:
    """The SMT-LIB application of `function` to `args`."""
    return f"({function} {' '.join(args)})" if args else function


def literal(sort: str, value: int | Fraction | bool) -> str:
    """An SMT-LIB constant of `sort`. Exact: rationals are never rounded."""
    if sort == "Bool":
        return "true" if value else "false"
    if sort == "Int":
        return str(value) if value >= 0 else f"(- {-value})"
    q = Fraction(value)
    n, d = abs(q.numerator), q.denominator
    # A denominator of the form 2^a 5^b has an exact decimal numeral, which Z3
    # reads as a constant; any other is written as a division of numerals.
    rest, k = d, 0
    for p in (2, 5):
        e = 0
        while rest % p == 0:
            rest //= p
            e += 1
        k = max(k, e)
    if rest == 1:
        digits = str(n * 10**k // d).rjust(k + 1, "0")
        text = f"{digits[:-k]}.{digits[-k:]}" if k else f"{digits}.0"
    else:
        text = f"(/ {n}.0 {d}.0)"
    return text if q >= 0 else f"(- {text})"


# Terms. The translator builds these, simplifying as it goes, and prints them
# at the end.


@dataclass(frozen=True)
class _Const:
    sort: str
    value: int | Fraction | bool


@dataclass(frozen=True)
class _Input:
    name: str
    sort: str


@dataclass(frozen=True)
class _Ref:
    """An earlier definition's value (or definedness) at the same inputs."""

    name: str
    defined: bool
    sort: str


@dataclass(frozen=True)
class _App:
    head: str
    args: tuple["_Term", ...]
    sort: str


type _Term = _Const | _Input | _Ref | _App

TRUE = _Const("Bool", True)
FALSE = _Const("Bool", False)


def _and(*xs: _Term) -> _Term:
    flat: list[_Term] = []
    for x in xs:
        if x == FALSE:
            return FALSE
        if isinstance(x, _App) and x.head == "and":
            flat.extend(x.args)
        elif x != TRUE:
            flat.append(x)
    if not flat:
        return TRUE
    return flat[0] if len(flat) == 1 else _App("and", tuple(flat), "Bool")


def _or(*xs: _Term) -> _Term:
    flat: list[_Term] = []
    for x in xs:
        if x == TRUE:
            return TRUE
        if isinstance(x, _App) and x.head == "or":
            flat.extend(x.args)
        elif x != FALSE:
            flat.append(x)
    if not flat:
        return FALSE
    return flat[0] if len(flat) == 1 else _App("or", tuple(flat), "Bool")


def _not(x: _Term) -> _Term:
    if isinstance(x, _Const):
        return _Const("Bool", not x.value)
    if isinstance(x, _App) and x.head == "not":
        return x.args[0]
    return _App("not", (x,), "Bool")


def _ite(c: _Term, a: _Term, b: _Term) -> _Term:
    if a.sort != b.sort:
        raise TranslateError(f"branches of different sorts {a.sort} and {b.sort}")
    if isinstance(c, _Const):
        return a if c.value else b
    if a == b:
        return a
    return _App("ite", (c, a, b), a.sort)


# Operators with fixed operand sorts: name -> (operand sorts, result, head).
# "M" is the sort of money: Int, or Real in the relaxed translation.
_FIXED = {
    "Not": (("Bool",), "Bool", "not"),
    "And": (("Bool", "Bool"), "Bool", "and"),
    "Or": (("Bool", "Bool"), "Bool", "or"),
    "Xor": (("Bool", "Bool"), "Bool", "xor"),
    "Minus_int": (("Int",), "Int", "-"),
    "Minus_mon": (("M",), "M", "-"),
    "Minus_rat": (("Real",), "Real", "-"),
    "Add_int_int": (("Int", "Int"), "Int", "+"),
    "Add_mon_mon": (("M", "M"), "M", "+"),
    "Add_rat_rat": (("Real", "Real"), "Real", "+"),
    "Sub_int_int": (("Int", "Int"), "Int", "-"),
    "Sub_mon_mon": (("M", "M"), "M", "-"),
    "Sub_rat_rat": (("Real", "Real"), "Real", "-"),
}
# Comparisons are untyped in Catala 1.3.0; the operands give the sort.
_COMPARE = {"Eq": "=", "Lt": "<", "Lte": "<=", "Gt": ">", "Gte": ">="}


class _Translator:
    def __init__(self, scope: ir.Scope, relaxed: bool = False):
        self.relaxed = relaxed
        self.sorts = RELAXED_SORTS if relaxed else SORTS
        self.money = self.sorts["money"]
        self.inputs = {v.name: self.sorts[v.type] for v in scope.inputs}
        self.args = [quote(v.name) for v in scope.inputs]
        # Translated definitions so far: name -> (value, defined).
        self.defs: dict[str, tuple[_Term, _Term]] = {}
        self.obligations: list[Obligation] = []
        self.current = ""

    def definition(self, d: ir.Definition) -> tuple[_Term, _Term]:
        self.current = d.name
        sort = self.sorts[d.type]
        value, defined = self.expr(d.expr, TRUE)
        if value is None:  # never has a value; any constant will do
            value = _Const(sort, False if sort == "Bool" else 0)
        if value.sort != sort:
            raise TranslateError(f"{d.name} is {d.type} but its value is {value.sort}")
        self.defs[d.name] = (value, defined)
        return value, defined

    def oblige(self, kind: Literal["empty", "conflict"], pos: Pos, formula: _Term):
        self.obligations.append(Obligation(kind, self.current, pos, self.smt(formula)))

    def expr(self, e: ir.Expr, guard: _Term) -> tuple[_Term | None, _Term]:
        """(value, defined) of `e`, evaluated when `guard` holds.

        The value is None for a term that can never have one, such as `empty`.
        """
        match e:
            case ir.Lit(type=t, value=v):
                if isinstance(v, date):
                    v = units.days(v)
                return _Const(self.sorts[t], v), TRUE
            case ir.VarRef(name=name):
                if name in self.inputs:
                    return _Input(name, self.inputs[name]), TRUE
                if name in self.defs:
                    value, defined = self.defs[name]
                    if defined != TRUE:
                        defined = _Ref(name, True, "Bool")
                    return _Ref(name, False, value.sort), defined
                raise TranslateError(f"unknown or later variable {name} at {e.pos}")
            case ir.Op():
                return self.op(e, guard)
            case ir.If(cond=cond, then=then, else_=else_):
                c, c_def = self.value(cond, guard, "Bool")
                a, a_def = self.expr(then, _and(guard, c))
                b, b_def = self.expr(else_, _and(guard, _not(c)))
                value = b if a is None else a if b is None else _ite(c, a, b)
                return value, _and(c_def, _ite(c, a_def, b_def))
            case ir.Default(exceptions=exceptions, just=just, cons=cons):
                exs = [self.expr(x, guard) for x in exceptions]
                for i in range(len(exs)):
                    for j in range(i + 1, len(exs)):
                        self.oblige("conflict", e.pos, _and(guard, exs[i][1], exs[j][1]))
                none = _and(*(_not(d) for _, d in exs))
                j_val, j_def = self.value(just, _and(guard, none), "Bool")
                c_val, c_def = self.expr(cons, _and(guard, none, j_val))
                defined = _or(*(d for _, d in exs), _and(j_def, j_val, c_def))
                # Choose the defined exception, else `cons`. Terms that can
                # never have a value drop out of the choice.
                candidates = [(d, v) for v, d in exs if v is not None]
                if c_val is not None:
                    candidates.append((TRUE, c_val))
                value = None
                for d, v in reversed(candidates):
                    value = v if value is None else _ite(d, v, value)
                return value, defined
            case ir.Pure(arg=arg):
                return self.expr(arg, guard)
            case ir.Empty():
                return None, FALSE
            case ir.ErrorOnEmpty(arg=arg):
                value, defined = self.expr(arg, guard)
                self.oblige("empty", e.pos, _and(guard, _not(defined)))
                return value, TRUE
        raise TranslateError(f"unknown expression {e!r}")

    def value(self, e: ir.Expr, guard: _Term, sort: str | None = None) -> tuple[_Term, _Term]:
        """Like `expr`, for a position that needs a value (of `sort`, if given)."""
        value, defined = self.expr(e, guard)
        if value is None:
            raise TranslateError(f"term with no value used as a value at {e.pos}")
        if sort is not None and value.sort != sort:
            raise TranslateError(f"expected {sort}, found {value.sort} at {e.pos}")
        return value, defined

    def op(self, e: ir.Op, guard: _Term) -> tuple[_Term, _Term]:
        pairs = [self.value(a, guard) for a in e.args]
        args = [v for v, _ in pairs]
        defined = _and(*(d for _, d in pairs))
        sorts = tuple(a.sort for a in args)

        def check(expected: tuple[str, ...]):
            if sorts != expected:
                raise TranslateError(f"{e.op} at {e.pos} expects {expected}, found {sorts}")

        if e.op in _FIXED:
            operands, result, head = _FIXED[e.op]
            operands = tuple(self.money if x == "M" else x for x in operands)
            result = self.money if result == "M" else result
            check(operands)
            if head == "not":
                return _not(args[0]), defined
            if head == "and":
                return _and(*args), defined
            if head == "or":
                return _or(*args), defined
            return _App(head, tuple(args), result), defined
        if e.op in _COMPARE:
            if len(sorts) != 2 or sorts[0] != sorts[1] or (
                sorts[0] == "Bool" and e.op != "Eq"
            ):
                raise TranslateError(f"{e.op} at {e.pos} cannot compare {sorts}")
            return _App(_COMPARE[e.op], tuple(args), "Bool"), defined
        if e.op in ("Mult_mon_rat", "Div_mon_rat"):
            check((self.money, "Real"))
            money, rate = args
            tree = self.constant_tree(rate)
            if tree is None:
                raise NonlinearTerm(
                    f"{e.op} at {e.pos}: the decimal operand is not a constant or"
                    " a condition on constants, so the product is not linear"
                )
            return self.distribute(e, money, tree), defined
        raise UnsupportedOperator(e.op, e.pos)

    def constant_tree(self, t: _Term) -> _Term | None:
        """`t` as an ite tree whose leaves are Real constants, or None."""
        match t:
            case _Const(sort="Real"):
                return t
            case _Ref(name=name, defined=False):
                return self.constant_tree(self.defs[name][0])
            case _App(head="ite", args=(c, a, b)):
                a, b = self.constant_tree(a), self.constant_tree(b)
                return None if a is None or b is None else _ite(c, a, b)
        return None

    def distribute(self, e: ir.Op, money: _Term, tree: _Term) -> _Term:
        if isinstance(tree, _App):  # an ite
            c, a, b = tree.args
            return _ite(c, self.distribute(e, money, a), self.distribute(e, money, b))
        if e.op == "Div_mon_rat" and tree.value == 0:
            raise TranslateError(f"division by a zero decimal at {e.pos}")
        head = "*" if e.op == "Mult_mon_rat" else "/"
        as_real = money if self.relaxed else _App("to_real", (money,), "Real")
        exact = _App(head, (as_real, tree), "Real")
        return _App("bm_round", (exact,), self.money)

    def smt(self, t: _Term) -> str:
        match t:
            case _Const(sort=sort, value=value):
                return literal(sort, value)
            case _Input(name=name):
                return quote(name)
            case _Ref(name=name, defined=defined):
                return apply(quote(f"{name}.defined" if defined else name), self.args)
            case _App(head=head, args=args):
                return f"({head} {' '.join(self.smt(a) for a in args)})"
        raise TranslateError(f"unknown term {t!r}")


def translate(scope: ir.Scope, relaxed: bool = False) -> SmtModule:
    """The SMT-LIB module for `scope`. `relaxed` is not the rules: see the module docstring."""
    names = [v.name for v in scope.inputs] + [d.name for d in scope.definitions]
    if "bm_round" in names:
        raise TranslateError("a scope variable named bm_round clashes with the preamble")
    t = _Translator(scope, relaxed)
    params = "(" + " ".join(f"({quote(v.name)} {t.sorts[v.type]})" for v in scope.inputs) + ")"
    lines = [
        f"; Scope {scope.name}, from bm-ir {ir.IR_VERSION} (Catala {scope.catala_version})",
    ]
    if relaxed:
        lines.append("; RELAXED: money is Real and nothing is rounded. Not the rules.")
    lines.append(BM_ROUND_RELAXED if relaxed else BM_ROUND)
    for d in scope.definitions:
        value, defined = t.definition(d)
        sort = t.sorts[d.type]
        lines.append(f"(define-fun {quote(d.name)} {params} {sort} {t.smt(value)})")
        lines.append(
            f"(define-fun {quote(d.name + '.defined')} {params} Bool {t.smt(defined)})"
        )
    by_name = {d.name: d for d in scope.definitions}
    return SmtModule(
        text="\n".join(lines) + "\n",
        inputs=list(scope.inputs),
        functions={d.name: quote(d.name) for d in scope.definitions},
        obligations=t.obligations,
        outputs={name: t.sorts[by_name[name].type] for name in scope.outputs},
        relaxed=relaxed,
    )
