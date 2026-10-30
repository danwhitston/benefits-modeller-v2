# bm-ir: the rules interchange format

`bm-ir` is the JSON format that carries Catala rules from the Catala compiler to
the SMT-LIB translator. This page specifies version 1.

## Producer

The `bm-export` command is a Catala compiler plugin in `exporter/`. It reads one
scope of Catala's typed default calculus (`dcalc`) and writes it out node by
node. It does no arithmetic and no evaluation. The one structural change it
makes is to inline the scopes that the exported scope calls as sub-scopes (see
[Sub-scopes](#sub-scopes)). Built against Catala 1.3.0.

```
make export
```

builds the plugin and writes `build/uc.bm-ir.json` from the `UniversalCredit`
scope in `rules/uc.catala_en`. It also writes `build/claim_window.bm-ir.json`
from the `ClaimWindow` scope, and `build/claim_window4.bm-ir.json` to
`build/claim_window6.bm-ir.json` from `ClaimWindow4` to `ClaimWindow6`, which
only the scaling probe uses. By hand, for one scope:

```
opam exec -- dune build --root exporter
opam exec -- catala bm-export --plugin-dir exporter/_build/default/plugin \
  -I rules -s UniversalCredit rules/uc.catala_en -o build/uc.bm-ir.json
```

## Schema

```
Root  = {bm_ir_version: 1, catala_version: str, scope: str,
         inputs: [Var], outputs: [str],
         definitions: [{name: str, type: Type, expr: Expr}]}
Var   = {name: str, type: Type}
Type  = "money" | "decimal" | "integer" | "bool" | "date"
Pos   = {file: str, line: int}
Expr  = {k: "lit", type: Type, value: str, pos}
      | {k: "var", name: str, pos}
      | {k: "op", op: str, args: [Expr], pos}
      | {k: "if", cond: Expr, then: Expr, else: Expr, pos}
      | {k: "default", exceptions: [Expr], just: Expr, cons: Expr, pos}
      | {k: "pure", arg: Expr, pos}
      | {k: "empty", pos}
      | {k: "error_on_empty", arg: Expr, pos}
```

Object keys are unordered.

### Root

- `catala_version` is the version of the Catala compiler that ran the plugin.
- `inputs` lists the scope's `input` variables in declaration order. Only the
  exported scope's inputs appear here, not those of its sub-scopes.
- `definitions` holds one entry per scope variable, internal and output alike,
  and the definitions of its sub-scopes, in dependency order: an expression
  refers only to inputs and to definitions earlier in the list.
- `outputs` names the output variables of the exported scope, in the order of
  `definitions`. Internal variables and the variables of sub-scopes appear in
  `definitions` but not in `outputs`.

### Literals

| `type`    | `value`                                              | Example        |
|-----------|------------------------------------------------------|----------------|
| `money`   | whole pence, as an integer string                    | `"150"`        |
| `decimal` | exact `"num/den"` in lowest terms, denominator > 0   | `"11/20"`      |
| `integer` | decimal digits, with a leading `-` if negative       | `"-3"`         |
| `bool`    | `"true"` or `"false"`                                | `"true"`       |
| `date`    | `"YYYY-MM-DD"`                                       | `"2026-04-06"` |

Decimals are never written as floating-point numbers. An integral decimal is
still written as a fraction, for example `"1/1"`.

### Operators

`op` is the name of Catala's operator constructor. The exporter accepts these,
whose operands and results are all bm-ir types:

- Boolean: `Not`, `And`, `Or`, `Xor`
- Comparison: `Eq`, `Lt`, `Lte`, `Gt`, `Gte`
- Negation: `Minus_int`, `Minus_rat`, `Minus_mon`
- Arithmetic: `Add_`, `Sub_`, `Mult_` and `Div_` with the operand suffixes
  Catala defines (`int_int`, `rat_rat`, `mon_mon`, `mon_int`, `mon_rat`), for
  example `Mult_mon_rat`
- Conversion and rounding: `ToInt_rat`, `ToInt_mon`, `ToRat_int`, `ToRat_mon`,
  `ToMoney_rat`, `ToMoney_int`, `Round_rat`, `Round_mon`

Arithmetic operators carry their operand types in their names. Comparisons and
`Eq` do not, because Catala 1.3.0 types them polymorphically: the operand type
is that of the arguments, which every `lit` states and every `var` takes from
`inputs` or `definitions`.

### Default terms

`default`, `pure`, `empty` and `error_on_empty` are Catala's default calculus,
written out as Catala builds it. In outline, following Catala's own
definition: a `default` first evaluates its `exceptions`. If exactly one is
not empty, that is its value; if more than one is, evaluation fails with a
conflict. If all are empty, the value is `cons` when `just` is true, and empty
otherwise. `pure` marks a plain value as a default term. `error_on_empty` turns
an empty result into an error.

Two shapes appear in practice:

- An output variable's definition is `error_on_empty` around a `default`. Each
  `definition` in the Catala source is one `default` in `exceptions`, with the
  condition as `just` and the value under `pure` as `cons`. The outer `default`
  has `just` false and `cons` empty. Exceptions add a further level of nesting.
- An internal variable may be left as a bare `default` with no
  `error_on_empty`. References to it are then wrapped in `error_on_empty`
  where they are used. Its `type` is that of its value.

### Sub-scopes

A scope that declares a sub-scope (`p1 scope Sub`) and defines its inputs
(`definition p1.x equals ...`) is exported with the sub-scope inlined:

- Each variable of the sub-scope is named with the path of sub-scope names
  and a dot in front of its own name: `p1.x`, `p1.y`. A sub-scope of a
  sub-scope adds a further step, for example `step_1.uc.award`.
- Each input of the sub-scope becomes a definition, `p1.x`, whose expression
  is the caller's definition of it.
- Each internal and output variable of the sub-scope becomes a definition,
  `p1.y`, as it would be for the sub-scope exported on its own.
- A reference to an output of the sub-scope, `p1.y` in the Catala source, is
  a `var` node naming that definition.

A scope declared twice as a sub-scope (`p1 scope Sub` and `p2 scope Sub`) is
inlined twice, once under each name. A sub-scope's inputs must be `input`
variables: a `context` variable is a default term, not a bm-ir type, so it stops
the export (`TDefault`) in a sub-scope as in the exported scope. Only this form
is inlined. A call to a
scope inside an expression (`output of Sub with {...}`), a scope from another
module and any other application stay unsupported.

### Positions

`pos` gives the source file and the line where the node starts. `file` is
relative to the directory the export ran in, which is the repository root for
`make export`. Nodes that Catala generates rather than reads from the source,
such as the outer `default` of a definition, carry the position Catala gives
them, which is often the variable's declaration. For the definition of a
sub-scope input, it is the caller's definition of that input.

## Unsupported constructs

Any other construct (lists, structures, enumerations, functions, durations,
scope calls other than sub-scopes, assertions, other operators) stops the
export with a non-zero exit code and the message `Unsupported construct <name>
at <file>:<line>`, where `<name>` is the Catala constructor, for example
`EArray`.

## Versions

`bm_ir_version` changes whenever the shape above changes. Version 1 added
sub-scopes; version 0 had no dotted names and rejected any sub-scope. The
loader in `src/bm/ir.py` reads only the current version. The exporter is built
against one Catala version at a time; `dcalc` is an internal Catala format and
may change between Catala releases.
