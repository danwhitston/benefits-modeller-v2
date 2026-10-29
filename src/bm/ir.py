"""Loader for bm-ir v0, the JSON form of a Catala scope (see docs/bm-ir.md)."""

import json
import re
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from pathlib import Path

IR_VERSION = 0
TYPES = ("money", "decimal", "integer", "bool", "date")


class IrError(ValueError):
    """The document is not valid bm-ir."""


class UnsupportedIrVersion(IrError):
    pass


@dataclass(frozen=True)
class Pos:
    file: str
    line: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class Var:
    name: str
    type: str


# Expressions. Literal values are parsed: money and integer to `int` (money in
# pence), decimal to `Fraction`, bool to `bool`, date to `datetime.date`.


@dataclass(frozen=True)
class Lit:
    type: str
    value: int | Fraction | bool | date
    pos: Pos


@dataclass(frozen=True)
class VarRef:
    name: str
    pos: Pos


@dataclass(frozen=True)
class Op:
    op: str
    args: tuple[Expr, ...]
    pos: Pos


@dataclass(frozen=True)
class If:
    cond: Expr
    then: Expr
    else_: Expr
    pos: Pos


@dataclass(frozen=True)
class Default:
    exceptions: tuple[Expr, ...]
    just: Expr
    cons: Expr
    pos: Pos


@dataclass(frozen=True)
class Pure:
    arg: Expr
    pos: Pos


@dataclass(frozen=True)
class Empty:
    pos: Pos


@dataclass(frozen=True)
class ErrorOnEmpty:
    arg: Expr
    pos: Pos


type Expr = Lit | VarRef | Op | If | Default | Pure | Empty | ErrorOnEmpty


@dataclass(frozen=True)
class Definition:
    name: str
    type: str
    expr: Expr


@dataclass(frozen=True)
class Scope:
    name: str
    catala_version: str
    inputs: list[Var]
    outputs: list[str]
    definitions: list[Definition]


def load(path: Path) -> Scope:
    return parse(json.loads(Path(path).read_text()))


def parse(data: dict) -> Scope:
    version = data.get("bm_ir_version")
    # `False == 0` and `0.0 == 0` in Python, so the type is checked as well.
    if type(version) is not int or version != IR_VERSION:
        raise UnsupportedIrVersion(
            f"bm_ir_version {version!r} is not supported (expected {IR_VERSION})"
        )
    inputs = [Var(v["name"], _type(v["type"])) for v in data["inputs"]]
    definitions = [
        Definition(d["name"], _type(d["type"]), _expr(d["expr"]))
        for d in data["definitions"]
    ]
    outputs = list(data["outputs"])
    names = [v.name for v in inputs] + [d.name for d in definitions]
    if len(set(names)) != len(names):
        raise IrError(f"duplicate scope variable names in {names}")
    defined = {d.name for d in definitions}
    if unknown := [o for o in outputs if o not in defined]:
        raise IrError(f"outputs without a definition: {unknown}")
    return Scope(
        name=data["scope"],
        catala_version=data["catala_version"],
        inputs=inputs,
        outputs=outputs,
        definitions=definitions,
    )


def _type(t: str) -> str:
    if t not in TYPES:
        raise IrError(f"unknown type {t!r}")
    return t


def _pos(p: dict) -> Pos:
    return Pos(p["file"], int(p["line"]))


_INT = re.compile(r"-?[0-9]+")
_RAT = re.compile(r"(-?[0-9]+)/([0-9]+)")


def _literal(type_: str, value: str, pos: Pos) -> int | Fraction | bool | date:
    if type_ in ("money", "integer") and _INT.fullmatch(value):
        return int(value)
    if type_ == "decimal" and (m := _RAT.fullmatch(value)):
        num, den = int(m[1]), int(m[2])
        if den > 0 and Fraction(num, den).denominator == den:
            return Fraction(num, den)
    if type_ == "bool" and value in ("true", "false"):
        return value == "true"
    if type_ == "date" and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    raise IrError(f"invalid {type_} literal {value!r} at {pos}")


def _expr(e: dict) -> Expr:
    pos = _pos(e["pos"])
    match e["k"]:
        case "lit":
            type_ = _type(e["type"])
            return Lit(type_, _literal(type_, e["value"], pos), pos)
        case "var":
            return VarRef(e["name"], pos)
        case "op":
            return Op(e["op"], tuple(_expr(a) for a in e["args"]), pos)
        case "if":
            return If(_expr(e["cond"]), _expr(e["then"]), _expr(e["else"]), pos)
        case "default":
            return Default(
                tuple(_expr(x) for x in e["exceptions"]),
                _expr(e["just"]),
                _expr(e["cons"]),
                pos,
            )
        case "pure":
            return Pure(_expr(e["arg"]), pos)
        case "empty":
            return Empty(pos)
        case "error_on_empty":
            return ErrorOnEmpty(_expr(e["arg"]), pos)
        case k:
            raise IrError(f"unknown expression kind {k!r} at {pos}")
