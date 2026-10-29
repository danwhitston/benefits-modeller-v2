"""Evaluate a translated scope at fixed inputs, using Z3."""

from fractions import Fraction

import z3

from bm.translate import SORTS, SmtModule, apply, literal, quote


class EvaluationError(RuntimeError):
    """Catala would stop with an error at these inputs."""


def outputs(module: SmtModule, inputs: dict[str, int | bool]) -> dict[str, int | bool | Fraction]:
    """Every output of `module` at `inputs`, given in SMT units (pence, days).

    Raises `EvaluationError` if any obligation holds, because Catala would then
    stop with an error instead of returning outputs.
    """
    names = [v.name for v in module.inputs]
    if set(inputs) != set(names):
        raise ValueError(f"expected values for exactly {names}, got {sorted(inputs)}")
    args = [quote(n) for n in names]
    lines = [module.text]
    for v in module.inputs:
        sort, value = SORTS[v.type], inputs[v.name]
        if (sort == "Bool") != isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{v.name} is {v.type}, got {value!r}")
        lines.append(f"(declare-const {quote(v.name)} {sort})")
        lines.append(f"(assert (= {quote(v.name)} {literal(sort, value)}))")
    for i, ob in enumerate(module.obligations):
        lines.append(f"(declare-const |bm.obligation.{i}| Bool)")
        lines.append(f"(assert (= |bm.obligation.{i}| {ob.formula}))")
    for name, sort in module.outputs.items():
        lines.append(f"(declare-const |bm.output.{name}| {sort})")
        lines.append(f"(assert (= |bm.output.{name}| {apply(module.functions[name], args)}))")

    solver = z3.Solver()
    solver.add(z3.parse_smt2_string("\n".join(lines)))
    if (status := solver.check()) != z3.sat:
        raise RuntimeError(f"Z3 could not evaluate the module: {status}")
    model = solver.model()

    def get(name: str, sort: str):
        const = {"Int": z3.Int, "Real": z3.Real, "Bool": z3.Bool}[sort](name)
        return model.eval(const, model_completion=True)

    if failures := [
        f"{ob.kind} at {ob.pos} in {ob.definition}"
        for i, ob in enumerate(module.obligations)
        if z3.is_true(get(f"bm.obligation.{i}", "Bool"))
    ]:
        raise EvaluationError("Catala would stop with an error: " + "; ".join(failures))

    result: dict[str, int | bool | Fraction] = {}
    for name, sort in module.outputs.items():
        v = get(f"bm.output.{name}", sort)
        if sort == "Int":
            result[name] = v.as_long()
        elif sort == "Real":
            result[name] = Fraction(v.numerator_as_long(), v.denominator_as_long())
        else:
            result[name] = z3.is_true(v)
    return result
