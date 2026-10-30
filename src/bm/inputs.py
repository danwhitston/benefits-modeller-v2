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

Two further keys are optional:

- `per_period = true`, on a money, date or integer input named `<base>`. The
  loader replaces the entry with one for each input of the scope named
  `<base>_1`, `<base>_2` and so on, each with the same bounds and labels, so
  that one file serves scopes of different lengths. The scope's inputs must be
  exactly `<base>_1` to `<base>_n` with no gaps, and every per-period entry
  must give the same n. An entry that matches no input of the scope is
  refused, as is one that clashes with an explicit entry.
- `applies_when = "<name>"`, on a Boolean judgement point (a Boolean input
  whose `controlled_by` includes `decision_maker`). `<name>` must be another
  Boolean judgement point that has no `applies_when` itself, so conditions do
  not chain. The input matters only when `<name>` is true; see
  `bm.strategic.judgement_points`, `close_fixed` and `cases`.
"""

import re
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
    # The Boolean judgement point that must be true for this one to matter.
    applies_when: str | None = None


def load(path: Path, scope: Scope) -> dict[str, InputSpec]:
    """One spec per input of `scope`, in the scope's input order."""
    data = tomllib.loads(Path(path).read_text())
    if set(data) != {"inputs"}:
        raise InputsError(f"{path}: expected only an [inputs] table, found {sorted(data)}")
    types = {v.name: v.type for v in scope.inputs}
    tables = _expand_per_period(path, data["inputs"], types)
    if unknown := sorted(set(tables) - set(types)):
        raise InputsError(f"{path}: unknown inputs {unknown}")
    if missing := [n for n in types if n not in tables]:
        raise InputsError(f"{path}: no entry for inputs {missing}")
    specs = {name: _spec(path, name, types[name], tables[name]) for name in types}
    for name, spec in specs.items():
        if spec.applies_when is not None:
            _check_condition(path, name, spec.applies_when, specs)
    return specs


def _expand_per_period(path: Path, tables: dict, types: dict[str, str]) -> dict:
    """The tables with each per-period entry replaced by one per matching input."""
    expanded: dict = {}
    lengths: dict[str, int] = {}
    for name, table in tables.items():
        if not isinstance(table, dict) or "per_period" not in table:
            continue
        where = f"{path}: [inputs.{name}]"
        if table["per_period"] is not True:
            raise InputsError(f"{where}: per_period must be true, not {table['per_period']!r}")
        if table.get("type") not in BOUNDED:
            raise InputsError(
                f"{where}: per_period applies to money, date and integer inputs, "
                f"not {table.get('type')!r}"
            )
        pattern = re.compile(rf"{re.escape(name)}_([1-9][0-9]*)")
        matches = [n for n in types if pattern.fullmatch(n)]
        if not matches:
            raise InputsError(f"{where}: per_period entry matches no input of the scope")
        numbers = sorted(int(pattern.fullmatch(n).group(1)) for n in matches)
        if numbers != list(range(1, len(numbers) + 1)):
            raise InputsError(
                f"{where}: the scope's {name} inputs must be {name}_1 to {name}_n with no gaps, "
                f"but are numbered {numbers}"
            )
        lengths[name] = len(numbers)
        for match in matches:
            if match in tables:
                raise InputsError(
                    f"{where}: per_period would define {match}, which has its own entry"
                )
            expanded[match] = {k: v for k, v in table.items() if k != "per_period"}
    if len(set(lengths.values())) > 1:
        raise InputsError(
            f"{path}: per_period inputs must cover the same number of periods, "
            f"but the scope has {lengths}"
        )
    kept = {
        n: t for n, t in tables.items() if not (isinstance(t, dict) and "per_period" in t)
    }
    return kept | expanded


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
    elif "applies_when" in table:
        expected |= {"applies_when"}
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
    applies_when = table.get("applies_when")
    if applies_when is not None and not isinstance(applies_when, str):
        raise InputsError(f"{where}: applies_when must be an input name, not {applies_when!r}")
    return InputSpec(
        name,
        ir_type,
        bound,
        _controlled_by(where, table["controlled_by"]),
        _checked_by(where, table["checked_by"]),
        applies_when,
    )


def _check_condition(path: Path, name: str, parent: str, specs: dict[str, InputSpec]) -> None:
    where = f"{path}: [inputs.{name}]"
    if "decision_maker" not in specs[name].controlled_by:
        raise InputsError(f"{where}: applies_when needs a judgement point, and {name} is not one")
    if parent == name:
        raise InputsError(f"{where}: applies_when names the input itself")
    if parent not in specs:
        raise InputsError(f"{where}: applies_when names unknown input {parent!r}")
    spec = specs[parent]
    if spec.type != "bool":
        raise InputsError(f"{where}: applies_when must name a Boolean, but {parent} is {spec.type}")
    if "decision_maker" not in spec.controlled_by:
        raise InputsError(f"{where}: applies_when must name a judgement point, and {parent} is not")
    if spec.applies_when is not None:
        raise InputsError(
            f"{where}: {parent} has an applies_when of its own; conditions do not chain"
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
