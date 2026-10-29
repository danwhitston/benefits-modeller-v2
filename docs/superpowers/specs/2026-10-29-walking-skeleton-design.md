# Milestone 1: walking skeleton

Design for the first milestone of benefits-modeller v2. It builds on [the brief](../../v2-brief.md) and answers several of the brief's open questions for this milestone.

Written 29 October 2026. Claims about legislation and external tools give the date they were checked.

## Goal

Prove the whole pipeline end to end on the thinnest useful slice of Universal Credit:

Catala rules → exported intermediate representation → SMT-LIB → Z3 and cvc5 → a finding with an example household → checked against Catala's own interpreter and against PolicyEngine UK.

The milestone's query has an answer that can be worked out by hand. That is deliberate. A known answer tests the pipeline; any disagreement is a bug, not a discovery. The first finding that cannot be worked out by hand belongs to milestone 2.

v1 built each layer in turn and never reached a working whole. Its report recorded that an end-to-end slice would have been the better order. This milestone takes that order.

## Decisions

| Question | Decision |
|---|---|
| What comes first (brief, open question 1) | An end-to-end slice through every layer, with a few hand-written Catala rules |
| Which intermediate representation (question 2) | Typed default calculus (`dcalc`), read through a Catala compiler plugin |
| How to model money (question 3) | Exactly as Catala does: integer pence, exact rationals for decimals, one rounding step per money-times-decimal operation |
| Which PolicyEngine engine (question 7) | The Python package `policyengine-uk` |
| How to generate test households (question 8, in part) | Solver-generated households near each boundary, plus random households. Survey records come with population work. |
| How to present findings (question 9, for now) | A command-line report and JSON |
| Ground truth | The regulation text. Differential tests require an exact match, and each mismatch is triaged and logged. |
| Quantifier tractability (question 6) | A separate spike with hand-written SMT, run alongside the skeleton |

Questions 4 (where input labels live) and 5 (how to represent a judgement point) stay open until milestone 2.

## Scope

The skeleton models a single claimant in one monthly assessment period. Inputs:

- **Age band:** under 25, or 25 or over. This sets the standard allowance (Universal Credit Regulations 2013, [reg. 36](https://www.legislation.gov.uk/uksi/2013/376/regulation/36); checked 29 October 2026).
- **Limited capability for work (LCW):** yes or no. A single claimant with no responsibility for a child gets a work allowance only if they have LCW ([reg. 22(1)(b)](https://www.legislation.gov.uk/uksi/2013/376/regulation/22); checked 29 October 2026). The separate LCW element was taken out of regulation 27 from 3 April 2017 by S.I. 2017/204 ([reg. 27](https://www.legislation.gov.uk/uksi/2013/376/regulation/27); checked 29 October 2026), so in this slice LCW opens the work allowance and adds no amount. Claims that keep the pre-2017 element under transitional provisions are out of scope.
- **Monthly earned income.**

Fixed assumptions, stated in the rules file: no housing costs element (so the higher work allowance applies), no child, no unearned income, capital below the limit.

Parameters are written as date-dependent values from the start, using the 2026/27 rates, each cited to its source in the rules file. As checked on 29 October 2026, these are:

- the higher work allowance of £710.00 (reg. 22(2), as substituted by S.I. 2026/148)
- a 55% deduction of earnings above the work allowance (reg. 22(1)(b))
- standard allowances of £338.58 (under 25) and £424.90 (25 or over) (reg. 36, as substituted by S.I. 2026/113)

Earlier years' values can be added later without changing the rules' structure. That is also how the 2018/19 worked examples used in v1 could become regression tests.

### The known answer

In this slice the award is the standard allowance less 55% of earnings above the work allowance (or of all earnings, without LCW), and not less than zero. So:

- the effective marginal rate is 0% while earnings are within the work allowance
- it is 55% where earnings exceed the work allowance and the award is still above zero
- the peak is 55%

Rounding (reg. 6) can make the marginal rate over a 1p step look like 0% or 100%. So the marginal-rate query measures the change over a step Δ that defaults to £1. Over a £1 step the 55p deduction is exact, so the rate has no rounding noise.

## Components

1. **`rules/`**: the rules, in Catala's English syntax. One scope computes the award from the inputs above. Each block sits next to the regulation text it implements. A sibling file, `uc.inputs.toml`, gives each input's bounds (for example, earnings from £0 to £10,000 a month), because Catala has no range types.
2. **`exporter/`**: an OCaml plugin for the Catala compiler, pinned to Catala 1.3.0. It runs the compiler's passes up to typed default calculus and writes it as JSON in a format this project defines and documents, `bm-ir` version 0. The JSON records the Catala version and the source position of every expression. The plugin only serialises: it holds no semantics. An unsupported construct stops it with an error that names the construct.
3. **`src/bm/`**: a Python package, managed with uv.
   - `translate`: reads `bm-ir` and writes SMT-LIB. Each scope output becomes a function over the inputs. Default logic becomes nested conditionals with an explicit check that no two exceptions apply at once. Money is `Int` (pence), decimals are exact rationals, and rounding is half away from zero, which can be written in linear arithmetic.
   - `queries`: the marginal-rate query. It instantiates the award function at earnings *e* and *e* + Δ and asks Z3 to maximise the fall in award. It returns the rate, the earnings and the full example household. cvc5 then checks that no larger fall exists.
   - `coverage`: for every default in the rules, checks that no input within bounds leaves it empty and that no two exceptions conflict. This is the brief's "do the rules cover every case" query.
   - `checks`: runs each test household through Catala's interpreter, through Z3 with the inputs fixed, and through PolicyEngine UK, and compares the three results.
   - `report` and `cli`: the `bm` command.
4. **`spike/`**: see [The spike](#the-spike).

## Data flow

1. `catala typecheck` over `rules/`.
2. `catala bm-export -s UniversalCredit rules/uc.catala_en` writes `build/uc.bm-ir.json`.
3. `bm translate` writes `build/uc.smt2`.
4. `bm coverage` and `bm query emr --delta 100` run the solvers.
5. `bm check` generates households and compares Catala, Z3 and PolicyEngine.
6. `bm report` prints the findings as text and JSON.

Every result records the git commit of the rules, the Catala version, and the Z3 and cvc5 versions, so that any finding can be reproduced.

## Error handling

Failures are always loud. None is read as "nothing found".

- **Exporter or translator:** an unsupported construct, or an unknown `bm-ir` version, stops the run.
- **Solver timeout or *unknown*:** reported as *unknown*, never as an absence of findings. Timeouts are configurable.
- **Z3 and cvc5 disagree:** the run stops and shows both answers.
- **Catala runtime error on a household** (an empty default or conflicting exceptions): treated as a bug in the rules.
- **Catala's interpreter and Z3 disagree:** treated as a bug in the translator.
- **Our result and PolicyEngine's disagree:** triaged against the regulation text, then logged in `docs/mismatches.md` as one of: our error (fixed), PolicyEngine's error (logged, and reported upstream where useful), or a deliberate difference (with the regulation reference).

## Testing

Development is test-first. One layer of tests per kind of risk:

- **Rules:** Catala test scopes run with `clerk test`. They cover a few households worked out by hand, with the arithmetic written in the test. They include rounding edge cases, where 55% of earnings above the work allowance lands on exactly half a penny.
- **Exporter:** golden-file tests under dune. One small Catala fixture per supported construct, compared with stored JSON.
- **Translator:** pytest unit tests for each construct. The main test is property-based: for generated inputs, Catala's interpreter and Z3 with the inputs fixed must agree to the penny.
- **Queries:** known-answer tests. The peak marginal rate is 55%, the rate is 0% within the work allowance, and the coverage check finds no gaps or conflicts.
- **Differential:** `bm check` against PolicyEngine UK on generated households, with an exact match required.

## Toolchain and layout

- **Python:** uv, with the version in `.python-version` (read by mise), chosen to suit `policyengine-uk`. `z3-solver` and `cvc5` come from PyPI and are pinned in the lockfile.
- **OCaml and Catala:** a local opam switch in the repository, with Catala pinned to 1.3.0. This is an exception to the workspace's mise-for-runtimes rule, because opam is the supported way to build Catala plugins. The project's `CLAUDE.md` records the exception.
- **Tasks:** a top-level `Makefile` with `build`, `export`, `test` and `check` targets.
- **CI:** GitHub Actions on each pull request, caching the opam switch and the uv environment. If installing PolicyEngine makes the run too slow, that job moves to a nightly schedule. The decision is made on measured timings.

```
rules/       uc.catala_en, uc.inputs.toml
exporter/    OCaml plugin (dune), golden tests
src/bm/      translate, queries, coverage, checks, report, cli
tests/       pytest
docs/        v2-brief.md, superpowers/specs/, mismatches.md, spike write-up
```

## The spike

The spike asks whether strategic questions that alternate quantifiers stay tractable at the size of the first version (brief, open question 6).

It uses hand-written SMT, of roughly the shape the translator will produce: two assessment periods, one claimant-controlled input (when pay is received) and one judgement point (whether two people are a couple, as found by a decision maker). The question has the form "whatever the decision maker finds, is there a choice of pay timing that gains more than £X?". It times Z3 and cvc5, both with quantifiers and with the judgement point expanded into its finite cases.

The spike code lives on its own branch and is not merged. Its write-up, with timings and a recommendation for milestone 2, is merged into `docs/`.

## Out of scope for this milestone

- Income tax and National Insurance, the benefit cap and its earnings exemption, children, housing costs, couples and more than one assessment period. These are the expected content of milestone 2, together with input labels and the first strategic query.
- Population weighting with survey data.
- Lean.

## Known limitations

- **DWP's own calculation software cannot be tested from outside.** The model follows the regulation text. Where DWP practice differs from the text, the model will not show it.
- **Where rounding happens depends on how the rules are written.** Regulation 6 rounds "the calculation of an amount". Catala rounds at each money-times-decimal step. Rules must be written with one Catala step per calculation the regulation describes. Review checks this; the compiler cannot.
- **The exporter is tied to one Catala version.** Catala does not document a stable intermediate representation. Each upgrade means rebuilding the exporter and rerunning its golden tests.

## Sources checked

- Universal Credit Regulations 2013 (S.I. 2013/376), regulations [6](https://www.legislation.gov.uk/uksi/2013/376/regulation/6), [22](https://www.legislation.gov.uk/uksi/2013/376/regulation/22), [27](https://www.legislation.gov.uk/uksi/2013/376/regulation/27) and [36](https://www.legislation.gov.uk/uksi/2013/376/regulation/36), on legislation.gov.uk, latest revised versions, checked 29 October 2026.
- Catala 1.3.0, released 1 October 2026 ([release notes](https://github.com/CatalaLang/catala/releases/tag/1.3.0)). Money and rounding behaviour comes from `runtimes/ocaml/catala_runtime.ml` at tag 1.3.0, lines 107 and 1102, checked 29 October 2026. The plugin mechanism is described in `compiler/plugins/plugins.mld` at the same tag.
