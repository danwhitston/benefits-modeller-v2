"""Build SMT-LIB scripts over a translated scope, one household at a time.

A `Script` starts with the module's text and one function per obligation,
`|bm.obligation.<i>|`, over the scope's inputs in order. Each `instance` is a
household: one constant per input, named `|<prefix>.<input>|`, or `|<input>|`
when the prefix is empty. Instances share nothing unless the caller ties them,
by fixing values or by making an input equal to a term over other constants.

By default an instance is a household at which Catala returns a value: every
obligation is asserted false at it. A definition's `.defined` function is not
enough for this, because it is true at `error_on_empty` sites even where Catala
stops with an error (see `bm.translate`).

A script for two households, the second earning 100 pence more:

    <module.text>
    (define-fun |bm.obligation.0| ((|a| Int) (|e| Int)) Bool <formula>)
    (declare-const |a| Int)
    (declare-const |e| Int)
    (assert (<= 0 |e| 1000000))                  ; bounds, when given
    (assert (not (|bm.obligation.0| |a| |e|)))
    (declare-const |plus.a| Int)
    (declare-const |plus.e| Int)
    (assert (= |plus.a| |a|))                    ; equal={"a": "|a|", ...}
    (assert (= |plus.e| (+ |e| 100)))
    (assert (<= 0 |plus.e| 1000000))
    (assert (not (|bm.obligation.0| |plus.a| |plus.e|)))
    (check-sat)
"""

from dataclasses import dataclass, field

from bm.inputs import Bound
from bm.translate import SmtModule, apply, literal, quote


def smt_sum(terms: list[str]) -> str:
    """The SMT-LIB sum of `terms`.

    cvc5 refuses `(+ t)` with one argument, so one term stands alone.
    """
    if not terms:
        return "0"
    if len(terms) == 1:
        return terms[0]
    return f"(+ {' '.join(terms)})"


def _obligation(i: int) -> str:
    return quote(f"bm.obligation.{i}")


@dataclass(frozen=True)
class Instance:
    """One household in a script."""

    prefix: str
    # Input name to its quoted constant, in the scope's input order.
    inputs: dict[str, str]
    module: SmtModule = field(repr=False, compare=False)

    def output(self, name: str) -> str:
        """The value of the module's function `name` at this household.

        Any function of the module, internal or output. Raises `KeyError` for
        any other name.
        """
        return apply(self.module.functions[name], list(self.inputs.values()))

    def obligation(self, i: int) -> str:
        """A Bool term that holds when obligation `i` holds at this household."""
        return apply(_obligation(i), list(self.inputs.values()))

    def household(self, model: dict[str, int | bool]) -> dict[str, int | bool]:
        """This household's inputs in `model`, keyed by input name."""
        return {name: model[const[1:-1]] for name, const in self.inputs.items()}


class Script:
    """An SMT-LIB script under construction.

    `lines` holds every line so far, without `(check-sat)`, for callers that
    add their own commands after it.
    """

    def __init__(self, module: SmtModule, bounds: dict[str, Bound] | None = None):
        self.module = module
        self.sorts = module.sorts
        self.bounds = dict(bounds or {})
        if unknown := sorted(set(self.bounds) - set(self.sorts)):
            raise ValueError(f"bounds for unknown inputs {unknown}")
        for name in self.bounds:
            if self.sorts[name] not in ("Int", "Real"):
                raise ValueError(f"{name} is {self.sorts[name]}, which takes no bound")
        self._prefixes: set[str] = set()
        self._declared: set[str] = set()
        params = "(" + " ".join(f"({quote(n)} {s})" for n, s in self.sorts.items()) + ")"
        self.lines: list[str] = [module.text]
        for i, ob in enumerate(module.obligations):
            self.lines.append(f"(define-fun {_obligation(i)} {params} Bool {ob.formula})")

    def instance(
        self,
        prefix: str = "",
        fixed: dict[str, int | bool] | None = None,
        equal: dict[str, str] | None = None,
        defined: bool = True,
    ) -> Instance:
        """Declare a household and return it.

        `fixed` gives inputs a value, in SMT units. `equal` makes inputs equal
        to SMT terms, typically over another instance's constants. Each input
        still has its own constant. Bounded inputs are kept within the script's
        bounds. When `defined` is true, no obligation holds at the household.
        Raises `ValueError` for a prefix already used, an unknown input, or an
        input that is in both `fixed` and `equal`.
        """
        if prefix in self._prefixes:
            raise ValueError(f"prefix {prefix!r} is already used in this script")
        fixed, equal = fixed or {}, equal or {}
        if both := sorted(set(fixed) & set(equal)):
            raise ValueError(f"inputs both fixed and made equal to a term: {both}")
        for given in (fixed, equal):
            if unknown := sorted(set(given) - set(self.sorts)):
                raise ValueError(f"values for unknown inputs {unknown}")
        self._prefixes.add(prefix)
        inputs = {
            name: self.declare(f"{prefix}.{name}" if prefix else name, sort)
            for name, sort in self.sorts.items()
        }
        for name, value in fixed.items():
            self.add(f"(assert (= {inputs[name]} {literal(self.sorts[name], value)}))")
        for name, term in equal.items():
            self.add(f"(assert (= {inputs[name]} {term}))")
        for name, bound in self.bounds.items():
            self.bound(inputs[name], bound, self.sorts[name])
        instance = Instance(prefix, inputs, self.module)
        if defined:
            for i in range(len(self.module.obligations)):
                self.add(f"(assert (not {instance.obligation(i)}))")
        return instance

    def declare(self, name: str, sort: str, term: str | None = None) -> str:
        """Declare a constant, equal to `term` if given, and return it quoted.

        Raises `ValueError` if the name is already declared in this script, or
        is the name of one of the module's functions (or its `.defined`
        companion), which a constant of that name would shadow.
        """
        if name in self._declared:
            raise ValueError(f"{name} is already declared in this script")
        if name.removesuffix(".defined") in self.module.functions:
            raise ValueError(f"{name} is the name of a function of the module")
        self._declared.add(name)
        const = quote(name)
        self.add(f"(declare-const {const} {sort})")
        if term is not None:
            self.add(f"(assert (= {const} {term}))")
        return const

    def bound(self, term: str, bound: Bound, sort: str = "Int") -> None:
        """Assert that `term` (of `sort`, Int or Real) lies within `bound`, inclusive."""
        lo, hi = literal(sort, bound.min), literal(sort, bound.max)
        self.add(f"(assert (<= {lo} {term} {hi}))")

    def add(self, line: str) -> None:
        self.lines.append(line)

    def text(self, *extra: str) -> str:
        """The script: every line, then `extra`, then `(check-sat)`."""
        return "\n".join([*self.lines, *extra, "(check-sat)"]) + "\n"
