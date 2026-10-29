"""Input bounds for a scope, read from a TOML file such as rules/uc.inputs.toml.

Each non-boolean input needs a table `[inputs.<name>]` with `type`, `min` and
`max`. Money is a decimal string in pounds, for example "10000.00"; dates are
TOML dates; integers are TOML integers. Bounds are inclusive and are held in
the translator's units: pence for money, days since 1970-01-01 for dates.
"""

import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from bm import units
from bm.ir import Scope



class BoundsError(ValueError):
    pass


@dataclass(frozen=True)
class Bound:
    type: str
    min: int
    max: int


def load(path: Path, scope: Scope) -> dict[str, Bound]:
    data = tomllib.loads(Path(path).read_text())
    if set(data) != {"inputs"}:
        raise BoundsError(f"{path}: expected only an [inputs] table, found {sorted(data)}")
    tables = data["inputs"]
    types = {v.name: v.type for v in scope.inputs}
    if unknown := sorted(set(tables) - set(types)):
        raise BoundsError(f"{path}: bounds for unknown inputs {unknown}")
    if missing := [n for n, t in types.items() if t != "bool" and n not in tables]:
        raise BoundsError(f"{path}: no bounds for inputs {missing}")
    return {name: _bound(path, name, types[name], tables[name]) for name in tables}


def _bound(path: Path, name: str, ir_type: str, table: dict) -> Bound:
    where = f"{path}: [inputs.{name}]"
    if set(table) != {"type", "min", "max"}:
        raise BoundsError(f"{where} must have exactly the keys type, min and max")
    if table["type"] != ir_type:
        raise BoundsError(f"{where} has type {table['type']!r}, but the input is {ir_type}")
    if ir_type not in ("money", "date", "integer"):
        raise BoundsError(f"{where}: bounds on {ir_type} inputs are not supported")
    lo, hi = (_value(where, ir_type, table[k]) for k in ("min", "max"))
    if lo > hi:
        raise BoundsError(f"{where}: min is greater than max")
    return Bound(ir_type, lo, hi)


def _value(where: str, ir_type: str, value: object) -> int:
    match ir_type, value:
        case "money", str():
            try:
                return units.pence(value)
            except ValueError:
                pass
        case "date", date() if not isinstance(value, datetime):
            return units.days(value)
        case "integer", int() if not isinstance(value, bool):
            return value
    raise BoundsError(f"{where}: {value!r} is not a valid {ir_type} bound")
