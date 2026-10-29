"""The scope's inputs, read from a TOML file such as rules/uc.inputs.toml.

The file is the one list of the scope's inputs. Every input has a table
`[inputs.<name>]` with:

- `type`, which must match the input's type in the IR;
- `min` and `max` for money, date and integer inputs, and neither for Booleans.
  Money is a decimal string in pounds, for example "10000.00"; dates are TOML
  dates; integers are TOML integers. Bounds are inclusive and are held in the
  translator's units: pence for money, days since 1970-01-01 for dates;
- `controlled_by`: a non-empty list drawn from `CONTROLLED_BY`, naming who can
  change the input's value;
- `checked_by`: one of `CHECKED_BY`, naming how the value is checked.
"""

import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from bm import units
from bm.ir import Scope

CONTROLLED_BY = ("claimant", "employer", "landlord", "decision_maker", "nobody")
CHECKED_BY = (
    "third_party_data",
    "documentary_evidence",
    "claimant_declaration",
    "assessment",
    "dwp_records",
)
BOUNDED = ("money", "date", "integer")


class InputsError(ValueError):
    """The inputs file is not valid, or does not match the scope's inputs."""


@dataclass(frozen=True)
class Bound:
    type: str
    min: int
    max: int


@dataclass(frozen=True)
class InputSpec:
    name: str
    type: str
    # None for Boolean inputs, which have no range.
    bound: Bound | None
    controlled_by: tuple[str, ...]
    checked_by: str


def load(path: Path, scope: Scope) -> dict[str, InputSpec]:
    """One spec per input of `scope`, in the scope's input order."""
    data = tomllib.loads(Path(path).read_text())
    if set(data) != {"inputs"}:
        raise InputsError(f"{path}: expected only an [inputs] table, found {sorted(data)}")
    tables = data["inputs"]
    types = {v.name: v.type for v in scope.inputs}
    if unknown := sorted(set(tables) - set(types)):
        raise InputsError(f"{path}: unknown inputs {unknown}")
    if missing := [n for n in types if n not in tables]:
        raise InputsError(f"{path}: no entry for inputs {missing}")
    return {name: _spec(path, name, types[name], tables[name]) for name in types}


def bounds(specs: dict[str, InputSpec]) -> dict[str, Bound]:
    """The bounds of the inputs that have one."""
    return {name: spec.bound for name, spec in specs.items() if spec.bound is not None}


def _spec(path: Path, name: str, ir_type: str, table: dict) -> InputSpec:
    where = f"{path}: [inputs.{name}]"
    if ir_type not in (*BOUNDED, "bool"):
        raise InputsError(f"{where}: {ir_type} inputs are not supported")
    expected = {"type", "controlled_by", "checked_by"}
    if ir_type in BOUNDED:
        expected |= {"min", "max"}
    if missing := sorted(expected - set(table)):
        raise InputsError(f"{where} is missing keys {missing}")
    if extra := sorted(set(table) - expected):
        raise InputsError(f"{where} has unexpected keys {extra} for a {ir_type} input")
    if table["type"] != ir_type:
        raise InputsError(f"{where} has type {table['type']!r}, but the input is {ir_type}")
    bound = None
    if ir_type in BOUNDED:
        lo, hi = (_value(where, ir_type, table[k]) for k in ("min", "max"))
        if lo > hi:
            raise InputsError(f"{where}: min is greater than max")
        bound = Bound(ir_type, lo, hi)
    return InputSpec(
        name,
        ir_type,
        bound,
        _controlled_by(where, table["controlled_by"]),
        _checked_by(where, table["checked_by"]),
    )


def _controlled_by(where: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise InputsError(f"{where}: controlled_by must be a non-empty list, not {value!r}")
    for item in value:
        if item not in CONTROLLED_BY:
            raise InputsError(f"{where}: unknown controlled_by {item!r}; use {CONTROLLED_BY}")
    return tuple(value)


def _checked_by(where: str, value: object) -> str:
    if value not in CHECKED_BY:
        raise InputsError(f"{where}: unknown checked_by {value!r}; use {CHECKED_BY}")
    return value


def _value(where: str, ir_type: str, value: object) -> int:
    match ir_type, value:
        case "money", str():
            try:
                return units.pence(value)
            except ValueError as error:
                raise InputsError(f"{where}: {value!r} is not a valid money bound") from error
        case "date", date() if not isinstance(value, datetime):
            return units.days(value)
        case "integer", int() if not isinstance(value, bool):
            return value
    raise InputsError(f"{where}: {value!r} is not a valid {ir_type} bound")
