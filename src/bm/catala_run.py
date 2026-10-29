"""Run a Catala scope in Catala's own interpreter.

This is the reference the translator is checked against. The call is

    opam exec -- catala interpret -s <scope> -I <rules dir> <rules file>
        -F json --input=<JSON object of the scope's inputs>

run from the repository root, where the local opam switch and the standard
library live. Catala prints the outputs as one JSON object on stdout.

Value conversions, chosen from the scope's JSON schema (`catala json-schema`),
which is read once per scope and cached:

- money goes in as a decimal string of pounds such as "1000.55" and comes out
  as such a string. Both ways go through integers and `Decimal`, never `float`,
  so pence are exact. Catala's own reading of JSON numbers is avoided, because
  an integer means whole pounds and a float is inexact.
- dates go in as "YYYY-MM-DD" and come out the same way; here they are days
  since 1970-01-01.
- booleans and integers pass through unchanged.

A scope with other input or output types (decimals, structures) is not
supported yet and raises `ValueError`.
"""

import json
import re
import subprocess
from datetime import date, timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EPOCH = date(1970, 1, 1)
_PENNIES = re.compile(r"-?[0-9]+\.[0-9]{2}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class CatalaRuntimeError(RuntimeError):
    """Catala stopped with an error while evaluating the scope."""


@cache
def _types(rules: Path, scope: str) -> tuple[dict[str, str], dict[str, str]]:
    """The types of the scope's inputs and outputs: money, date, bool or integer."""
    schemas = _catala("json-schema", "-s", scope, "-I", str(rules.parent), str(rules))
    inputs, outputs = json.loads(schemas.stdout)
    return _properties(inputs, "input"), _properties(outputs, "output")


def _properties(schema: dict, kind: str) -> dict[str, str]:
    (definition,) = (
        d for name, d in schema["definitions"].items() if d.get("type") == "object"
    )
    types = {}
    for name, prop in definition["properties"].items():
        ref = prop.get("$ref", "").rsplit("/", 1)[-1]
        if ref in ("money", "date"):
            types[name] = ref
        elif prop.get("type") in ("boolean", "integer") and "$ref" not in prop:
            types[name] = "bool" if prop["type"] == "boolean" else "integer"
        else:
            raise ValueError(f"unsupported {kind} type for {name}: {prop}")
    return types


def _catala(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["opam", "exec", "--", "catala", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _to_json(kind: str, value: int | bool) -> object:
    match kind:
        case "bool" if isinstance(value, bool):
            return value
        case "integer" if isinstance(value, int) and not isinstance(value, bool):
            return value
        case "money" if isinstance(value, int) and not isinstance(value, bool):
            sign = "-" if value < 0 else ""
            pounds, pence = divmod(abs(value), 100)
            return f"{sign}{pounds}.{pence:02d}"
        case "date" if isinstance(value, int) and not isinstance(value, bool):
            return (EPOCH + timedelta(days=value)).isoformat()
    raise ValueError(f"cannot give {value!r} to Catala as {kind}")


def _from_json(kind: str, value: object) -> int | bool:
    match kind, value:
        case "bool", bool():
            return value
        case "integer", int() if not isinstance(value, bool):
            return value
        case "money", str() if _PENNIES.fullmatch(value):
            return int(Decimal(value) * 100)
        case "date", str() if _DATE.fullmatch(value):
            return (date.fromisoformat(value) - EPOCH).days
    raise ValueError(f"unexpected Catala output for a {kind}: {value!r}")


def outputs(rules: Path, scope: str, inputs: dict[str, int | bool]) -> dict[str, int | bool]:
    """Run `scope` from `rules` at `inputs` and return every output.

    Money is in pence and dates are days since 1970-01-01. Raises
    `CatalaRuntimeError` where Catala stops with an error, such as an input
    date before the first date for which a rate is defined.
    """
    rules = Path(rules).resolve()
    input_types, output_types = _types(rules, scope)
    if set(inputs) != set(input_types):
        raise ValueError(f"expected values for exactly {sorted(input_types)}, got {sorted(inputs)}")
    payload = {name: _to_json(input_types[name], value) for name, value in inputs.items()}
    done = _catala(
        "interpret",
        "-s",
        scope,
        "-I",
        str(rules.parent),
        str(rules),
        "-F",
        "json",
        f"--input={json.dumps(payload)}",
    )
    if done.returncode != 0:
        # Exit code 123 with "During evaluation" is Catala's runtime error. Anything
        # else, such as a type error or malformed input, is a bug in this call.
        if done.returncode == 123 and "During evaluation" in done.stderr:
            raise CatalaRuntimeError(" ".join(done.stderr.split()))
        raise RuntimeError(f"catala interpret failed ({done.returncode}): {done.stderr.strip()}")
    result = json.loads(done.stdout, parse_float=Decimal, parse_int=int)
    if set(result) != set(output_types):
        raise ValueError(f"unexpected outputs {sorted(result)}, expected {sorted(output_types)}")
    return {name: _from_json(output_types[name], result[name]) for name in output_types}
