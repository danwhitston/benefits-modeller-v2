# Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the end-to-end pipeline from Catala rules for a thin slice of Universal Credit to a solver-found peak marginal rate with an example household, checked against Catala's interpreter and PolicyEngine UK.

**Architecture:** Catala rules are compiled to typed default calculus and serialised to JSON (`bm-ir` v0) by a small OCaml plugin that holds no semantics. A Python package (`bm`) reads `bm-ir`, writes SMT-LIB, runs Z3 and cvc5 for coverage and marginal-rate queries, and compares results across Catala's interpreter, Z3 and PolicyEngine UK. A separate spike tests quantifier tractability with hand-written SMT.

**Tech Stack:** Catala 1.3.0 (opam, local switch), OCaml and dune, Python with uv, `z3-solver`, `cvc5`, `policyengine-uk`, pytest, hypothesis, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-29-walking-skeleton-design.md`

## Global Constraints

- Catala pinned to exactly 1.3.0. The exporter is built against that version only.
- `bm-ir` JSON carries `"bm_ir_version": 0`. The translator refuses any other version.
- Money is integer pence (SMT `Int`). Decimals are exact rationals (SMT `Real`), never floats, anywhere in the pipeline.
- Money multiplied or divided by a decimal is computed exactly, then rounded once, half away from zero: `sgn(q) * floor(|q| + 1/2)`.
- Parameters are 2026/27, valid for assessment periods starting on or after 6 April 2026: higher work allowance £710.00 (reg. 22(2), S.I. 2026/148); deduction 55% of earnings above the work allowance (reg. 22(1)(b)); standard allowance £338.58 under 25 and £424.90 aged 25 or over (reg. 36, S.I. 2026/113). Each is cited in the rules file with "checked 29 October 2026".
- Input bounds: earnings £0.00 to £10,000.00 a month; assessment period start 2026-04-06 to 2027-04-05 (the rules hold 2026/27 rates only, so the bound stops before the next uprating).
- The marginal-rate step Δ defaults to 100 pence.
- The regulation text is ground truth. Differential tests require an exact match to the penny.
- Failures are loud: an unsupported construct, an unknown `bm-ir` version, solver *unknown* or timeout, or Z3 and cvc5 disagreeing never produces "no finding".
- Every result records the rules' git commit, the Catala version, and the Z3 and cvc5 versions.
- Public repo: commit messages and docs are neutral, use British English and contain no em-dashes. Money or legal claims in docs cite a source and the date checked.
- Commit at the end of each task. Do not push unless asked.

## Review Focus

1. **Negative amounts in rounding.** Catala rounds half away from zero, so −0.5p becomes −1p. The rules never multiply a negative amount, but the translator must still match Catala on negative inputs. Test in Task 3.
2. **An assessment period outside the parameter dates.** Catala raises an empty-default error. The translator must surface this as a coverage gap with an example, not as a zero award. Test in Task 5.
3. **Earnings at the upper bound in the marginal-rate query.** *e* + Δ must also be within bounds, or the solver will report a fall that no valid household has. Test in Task 5.
4. **PolicyEngine's period handling.** PolicyEngine UK works mostly in years. A monthly award derived by dividing an annual one can differ by pennies for reasons unrelated to the rules. The mapping must state which period it uses, and a test must pin it. Test in Task 6.
5. **A solver timeout during a query.** It must come back as status `unknown` and show as *unknown* in the report, never as a missing finding. Test in Tasks 5 and 7.

---

### Task 1: Toolchain and rules

**Files:**
- Create: `.python-version`, `pyproject.toml`, `uv.lock`, `Makefile`, `src/bm/__init__.py`, `tests/test_smoke.py`
- Create: `rules/uc.catala_en`, `rules/uc_tests.catala_en`, `rules/uc.inputs.toml`
- Modify: `.gitignore` (add `_opam/`, `_build/`, `build/`, `.venv/`), `CLAUDE.md` (Project notes)

**Interfaces:**
- Produces: Catala scope `UniversalCredit` in `rules/uc.catala_en`, with
  - inputs: `assessment_period_start` (date), `earned_income` (money), `aged_25_or_over` (boolean), `has_lcw` (boolean)
  - outputs: `standard_allowance`, `work_allowance` (zero when none applies), `earnings_deduction`, `award` (all money)
- Produces: `rules/uc.inputs.toml`, with one table per non-boolean input under `[inputs.<name>]`, with keys `type`, `min` and `max`. Money is given as a decimal string in pounds; dates are TOML dates.
- Produces: `make build`, which runs `catala typecheck` over `rules/` (Task 2 adds the exporter build), and `make test`, which runs `clerk test` and then `uv run pytest`.

- [ ] **Step 1: Set up the toolchain.** Create a local opam switch (`opam switch create . --empty`), install OCaml and `catala.1.3.0` into it, and check that `opam exec -- catala --version` prints `1.3.0`. Initialise the uv project with `src/bm`. Choose the newest Python that the current `policyengine-uk` release supports (read its PyPI metadata) and write it to `.python-version`. Add `z3-solver`, `cvc5`, `policyengine-uk`, `pytest` and `hypothesis`, pinned in the lockfile. Add a one-line smoke test in `tests/test_smoke.py` that imports `z3` and `cvc5`. In `CLAUDE.md`, record that OCaml and Catala use a local opam switch, an exception to the workspace mise rule because opam is the supported way to build Catala plugins.

- [ ] **Step 2: Write the failing Catala tests.** In `rules/uc_tests.catala_en`, write one test scope per case below, using the test mechanism documented for Catala 1.3.0 in the Catala book. All cases have `assessment_period_start = 2026-05-01`.

| Case | 25+ | LCW | Earnings | `work_allowance` | `earnings_deduction` | `award` |
|---|---|---|---|---|---|---|
| no earnings | yes | yes | £0.00 | £710.00 | £0.00 | £424.90 |
| at work allowance | yes | yes | £710.00 | £710.00 | £0.00 | £424.90 |
| above work allowance | yes | yes | £1,000.00 | £710.00 | £159.50 | £265.40 |
| half penny rounds up | yes | yes | £710.10 | £710.00 | £0.06 | £424.84 |
| sub-penny rounds up | yes | yes | £710.01 | £710.00 | £0.01 | £424.89 |
| last penny of award | yes | yes | £1,482.53 | £710.00 | £424.89 | £0.01 |
| award reaches zero | yes | yes | £1,482.54 | £710.00 | £424.90 | £0.00 |
| no LCW | yes | no | £500.00 | £0.00 | £275.00 | £149.90 |
| under 25, floored at zero | no | no | £1,000.00 | £0.00 | £550.00 | £0.00 |

Write the arithmetic as a comment in each test. For example, for the half-penny case: 55% × 10p = 5.5p, which rounds to 6p, and 424.90 − 0.06 = 424.84.

- [ ] **Step 3: Run the tests and check they fail.** Run `make test`. Expected: `clerk test` fails because the scope `UniversalCredit` is not defined.

- [ ] **Step 4: Write the rules.** In `rules/uc.catala_en`, write the scope as literate Catala, with each block below the regulation text it implements (regs. 22 and 36, quoted under 15 words a block, linked and dated). Requirements:
  - Each parameter is defined only under the condition `assessment_period_start >= |2026-04-06|`, so an earlier date leaves it empty and Catala fails loudly.
  - `earnings_deduction` is `(earned_income - work_allowance) * 55%` when earnings exceed the work allowance, and £0.00 otherwise. That is one money-times-decimal step, so it is rounded once, as regulation 6 requires.
  - `award` is `standard_allowance - earnings_deduction`, or £0.00 if that is negative.

  Write `rules/uc.inputs.toml` with the bounds from Global Constraints.

- [ ] **Step 5: Run the tests and check they pass.** Run `make test`. Expected: all nine Catala tests pass, and pytest passes.

- [ ] **Step 6: Commit.** Commit with the message `Add toolchain and Universal Credit skeleton rules`.

### Task 2: OCaml exporter (`bm-ir` v0)

**Files:**
- Create: `exporter/dune-project`, `exporter/bm_export.ml`, `exporter/dune`, `exporter/test/dune`, `exporter/test/*.catala_en` (fixtures), `exporter/test/*.expected.json`, `docs/bm-ir.md`
- Modify: `Makefile` (add `export`, which writes `build/uc.bm-ir.json`, and add the dune tests to `test`)

**Interfaces:**
- Consumes: Catala 1.3.0 `Driver.Passes.dcalc` (`compiler/driver.mli`) and `Driver.Plugin.register` (`compiler/plugin.mli`). The typed AST constructors are in `compiler/shared_ast/definitions.ml` at tag 1.3.0.
- Produces: the `catala bm-export -s <Scope> <file> -o <out.json>` command, loaded through `--plugin-dir` or `CATALA_PLUGINS`.
- Produces: `bm-ir` v0, specified in `docs/bm-ir.md`:

```
Root  = {bm_ir_version: 0, catala_version: str, scope: str,
         inputs: [Var], outputs: [str],
         definitions: [{name: str, type: Type, expr: Expr}]}   // in dependency order
Var   = {name: str, type: Type}
Type  = "money" | "decimal" | "integer" | "bool" | "date"
Pos   = {file: str, line: int}
Expr  = {k: "lit", type: Type, value: str, pos}    // money: pence as an integer string; decimal: "num/den" in lowest terms;
                                                   // date: "YYYY-MM-DD"; bool: "true" | "false"; integer: decimal digits
      | {k: "var", name: str, pos}
      | {k: "op", op: str, args: [Expr], pos}      // op is Catala's resolved operator name, for example "Mult_mon_rat"
      | {k: "if", cond: Expr, then: Expr, else: Expr, pos}
      | {k: "default", exceptions: [Expr], just: Expr, cons: Expr, pos}
      | {k: "pure", arg: Expr, pos}
      | {k: "empty", pos}
      | {k: "error_on_empty", arg: Expr, pos}
```

- [ ] **Step 1: Write the golden fixtures and expected JSON by hand.** One fixture per construct:
  - `lit_money`, for example $1.50, which must give `"150"`
  - `lit_decimal` (55%, which must give `"11/20"`, never a float)
  - `lit_date`
  - `arith` (one each of `Add_mon_mon`, `Sub_mon_mon`, `Mult_mon_rat`, `Lt_mon_mon`)
  - `if_then_else`
  - `exception` (a base definition plus one labelled exception)
  - `date_condition`
  - `unsupported` (a list literal)

  The expected output of `unsupported` is a non-zero exit and an error message naming the construct and its source line.

- [ ] **Step 2: Run the tests and check they fail.** Run `opam exec -- dune test --root exporter`. Expected: FAIL, because the plugin does not exist.

- [ ] **Step 3: Implement the plugin in `exporter/bm_export.ml`.** It registers the `bm-export` command, takes the typed `dcalc` program, finds the named scope, and walks its body in order, emitting one definition per scope-level binding. Literals are written exactly, using the integer and rational values, never `string_of_float`. Operators are written under their resolved Catala constructor name. Any other AST node stops the export with `Unsupported construct <name> at <file>:<line>`. The plugin contains no arithmetic and no evaluation.

- [ ] **Step 4: Run the tests and check they pass.** Run `opam exec -- dune test --root exporter`. Expected: PASS for all eight fixtures. Then run `make export` and check that `build/uc.bm-ir.json` exists and has `"bm_ir_version": 0` and `"catala_version": "1.3.0"`.

- [ ] **Step 5: Commit.** Commit with the message `Add bm-ir exporter plugin for Catala 1.3.0`.

### Task 3: Translator to SMT-LIB

**Files:**
- Create: `src/bm/ir.py`, `src/bm/bounds.py`, `src/bm/translate.py`, `src/bm/evaluate.py`
- Test: `tests/test_ir.py`, `tests/test_bounds.py`, `tests/test_translate.py`. Fixtures are the exporter's `exporter/test/*.expected.json` plus `build/uc.bm-ir.json`.

**Interfaces:**
- Consumes: `bm-ir` v0 from Task 2, and `rules/uc.inputs.toml` from Task 1.
- Produces:
  - `bm.ir.load(path: Path) -> Scope`. `Scope` is a frozen dataclass with `name`, `catala_version`, `inputs: list[Var]`, `outputs: list[str]` and `definitions: list[Definition]`. It raises `UnsupportedIrVersion` unless the version is 0.
  - `bm.bounds.load(path: Path, scope: Scope) -> dict[str, Bound]`. `Bound(type, min: int, max: int)` holds pence for money and days since 1970-01-01 for dates. It raises `BoundsError` if a non-boolean input has no bound or a bound names an unknown input.
  - `bm.translate.translate(scope: Scope) -> SmtModule`. `SmtModule(text: str, inputs: list[Var], functions: dict[str, str], obligations: list[Obligation])`. `functions` maps each definition name to its SMT function name. Each definition becomes `(define-fun |<name>| (<all inputs in order>) <sort> ...)`, paired with `|<name>.defined|` returning `Bool`.
  - `Obligation(kind: Literal["empty", "conflict"], definition: str, pos: Pos, formula: str)`. `formula` is an SMT `Bool` term over the input names, true exactly when the gap or conflict happens.
  - `bm.evaluate.outputs(module: SmtModule, inputs: dict[str, int | bool]) -> dict[str, int | bool | Fraction]`. It evaluates every output at fixed inputs using the Z3 Python API (`z3.parse_smt2_string`).

**Encoding** (the implementer can't derive these from the tests alone):
- Sorts: money, integer and date are `Int`; decimal is `Real`; bool is `Bool`. Dates are days since 1970-01-01.
- Each expression translates to a pair (`value`, `defined`). `default` is defined if exactly one exception is defined (its value), or if there is none and `just` holds (the value of `cons`). Each pair of exceptions gives a `conflict` obligation whose formula is "both are defined". Each `error_on_empty` gives an `empty` obligation whose formula is "the argument is not defined"; the `error_on_empty` expression itself takes the argument's value.
- Rounding: `(define-fun bm_round ((q Real)) Int (ite (>= q 0.0) (to_int (+ q 0.5)) (- (to_int (+ (- q) 0.5)))))`.
- `Mult_mon_rat` becomes `bm_round(to_real(m) * r)`, and `Div_mon_rat` becomes `bm_round(to_real(m) / r)`. These are allowed only when the decimal operand is a literal. Otherwise the translator raises `NonlinearTerm`.
- Any operator the translator doesn't map raises `UnsupportedOperator(op, pos)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_load_rejects_unknown_version`: a `bm-ir` with `bm_ir_version: 1` raises `UnsupportedIrVersion`.
  - `test_bounds_missing_input`: dropping `earned_income` from the TOML raises `BoundsError`.
  - `test_bounds_values`: earnings give `Bound("money", 0, 1_000_000)`, and the start date gives `Bound("date", days(2026-04-06), days(2027-04-05))`, where `days(d) = (d - date(1970, 1, 1)).days` is computed in the test, not by hand.
  - `test_round_half_away_from_zero`, parametrised over (money pence, decimal) → expected pence: (10, 11/20) → 6; (1, 11/20) → 1; (−10, 11/20) → −6; (−1, 1/2) → −1; (3, 1/2) → 2.
  - `test_exception_conflict_obligation`: the `exception` fixture yields one `conflict` obligation.
  - `test_uc_outputs`: for each row of the Task 1 table, `evaluate.outputs` on `build/uc.bm-ir.json` gives the same `award` and `earnings_deduction` in pence.
  - `test_unsupported_operator`: an IR with `op: "Pow_int_int"` raises `UnsupportedOperator` naming the line.

- [ ] **Step 2: Run the tests and check they fail.** Run `uv run pytest tests/test_ir.py tests/test_bounds.py tests/test_translate.py -v`. Expected: FAIL with import errors.

- [ ] **Step 3: Implement `ir.py`, `bounds.py`, `translate.py` and `evaluate.py`** with the signatures above.

- [ ] **Step 4: Run the tests and check they pass.** Run the same command. Expected: PASS.

- [ ] **Step 5: Commit.** Commit with the message `Add bm-ir loader, input bounds and SMT-LIB translator`.

### Task 4: Interpreter agreement and solver runners

**Files:**
- Create: `src/bm/catala_run.py`, `src/bm/solvers.py`
- Test: `tests/test_agreement.py`, `tests/test_solvers.py`

**Interfaces:**
- Consumes: `SmtModule`, `evaluate.outputs` and `bounds.load` from Task 3.
- Produces:
  - `bm.catala_run.outputs(rules: Path, scope: str, inputs: dict[str, int | bool]) -> dict[str, int | bool]`. It runs Catala's interpreter, using the JSON input interface documented for 1.3.0 (check the flags with `catala interpret --help`), and converts money to pence. A Catala runtime error raises `CatalaRuntimeError(message)`.
  - `bm.solvers.run(solver: Literal["z3", "cvc5"], script: str, timeout_ms: int) -> SolverResult`. `SolverResult(status: Literal["sat", "unsat", "unknown"], model: dict[str, int | bool] | None, version: str)`. A timeout gives `"unknown"`, never an exception. Use each solver's Python API to parse SMT-LIB text. If the cvc5 PyPI package can't parse a script from text, use the cvc5 binary of the same version from its GitHub release, pinned by checksum in the `Makefile`, and record the choice in the module docstring.
  - `bm.solvers.versions() -> dict[str, str]`.
  - `bm.solvers.SolverDisagreement(Exception)`, carrying both solvers' results. Tasks 5 and 6 raise it.

- [ ] **Step 1: Write the failing tests.**
  - `test_interpreter_matches_z3` (hypothesis, 200 examples): draw inputs within `rules/uc.inputs.toml`. Assert that `catala_run.outputs` equals `evaluate.outputs` for every output.
  - `test_interpreter_matches_z3_edges`: the same check over every Task 1 table row, plus earnings at £0.00, £10,000.00 and work allowance ± 1p.
  - `test_interpreter_errors_before_parameter_dates`: a start date of 2026-04-05 raises `CatalaRuntimeError`.
  - `test_solver_sat_unsat`: a trivial script gives `sat` with a model, and its negation gives `unsat`, for both solvers.
  - `test_solver_timeout_is_unknown`: a nonlinear integer problem with `timeout_ms=1` gives `"unknown"`.

- [ ] **Step 2: Run the tests and check they fail.** Run `uv run pytest tests/test_agreement.py tests/test_solvers.py -v`. Expected: FAIL with import errors.

- [ ] **Step 3: Implement `catala_run.py` and `solvers.py`.**

- [ ] **Step 4: Run the tests and check they pass.** Run the same command. Expected: PASS. Any disagreement between the interpreter and Z3 is a translator bug. Fix it in Task 3's code, adding a unit test for the construct.

- [ ] **Step 5: Commit.** Commit with the message `Check translator against Catala interpreter; add solver runners`.

### Task 5: Coverage and marginal-rate queries

**Files:**
- Create: `src/bm/coverage.py`, `src/bm/queries.py`
- Test: `tests/test_coverage.py`, `tests/test_queries.py`, plus the fixture `tests/fixtures/uc_wide_dates.inputs.toml` (start dates from 2026-03-01)

**Interfaces:**
- Consumes: `SmtModule`, `Bound` and `solvers.run`.
- Produces:
  - `bm.coverage.check(module: SmtModule, bounds: dict[str, Bound], timeout_ms: int = 60_000) -> list[CoverageFinding]`. `CoverageFinding(kind, definition, pos, status: Literal["found", "unknown"], example: dict | None)`. For each obligation, Z3 checks its formula under the bounds. A `sat` result gives `found` with the model, and `unknown` gives `unknown`. If Z3 reports `unsat`, cvc5 is asked the same question, and if cvc5 disagrees, `SolverDisagreement` is raised.
  - `bm.queries.emr(module: SmtModule, bounds: dict[str, Bound], earnings_input: str = "earned_income", output: str = "award", delta: int = 100, fixed: dict[str, int | bool] | None = None, earnings_range: tuple[int, int] | None = None, timeout_ms: int = 60_000) -> EmrResult`. `EmrResult(status: Literal["found", "unknown"], rate: Fraction | None, drop: int | None, household: dict | None, award_at_e: int | None, award_at_e_plus_delta: int | None, solver_versions: dict[str, str])`.

**Algorithm:** maximise `output(e) − output(e + Δ)`, with the other inputs shared and both *e* and *e* + Δ inside the bounds (and inside `earnings_range` if one is given). Use Z3's `(maximize ...)`. Then ask cvc5 whether a fall larger than the maximum exists. If cvc5 says `sat`, raise `SolverDisagreement`. If it says `unknown`, return the result with `status="unknown"`. The rate is `Fraction(drop, delta)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_uc_coverage_clean`: `check` over the UC module and `rules/uc.inputs.toml` returns `[]`.
  - `test_uc_coverage_finds_date_gap`: with `uc_wide_dates.inputs.toml`, there is at least one `empty` finding, and its example has a start date before 2026-04-06.
  - `test_emr_peak_is_taper`: `emr(...)` gives `rate == Fraction(55, 100)` and `drop == 55`. The example household's award at *e* + Δ is at least 0, and its earnings plus Δ are at most 1,000,000.
  - `test_emr_zero_within_work_allowance`: with `fixed={"has_lcw": True}` and `earnings_range=(0, 71_000 - 100)`, the rate is `0`.
  - `test_emr_penny_step_noise`: with `delta=1`, the rate is `1` (100%). This pins the rounding artefact that the spec warns about.
  - `test_emr_upper_bound`: with `earnings_range=(999_800, 1_000_000)` and `delta=100`, the household's earnings are at most 999,900 (so *e* + Δ stays within bounds), and `rate == 0`, because the award is already zero there.
  - `test_emr_timeout_is_unknown`: with `timeout_ms=1`, the status is `"unknown"` and `rate is None`.

- [ ] **Step 2: Run the tests and check they fail.** Run `uv run pytest tests/test_coverage.py tests/test_queries.py -v`. Expected: FAIL with import errors.

- [ ] **Step 3: Implement `coverage.py` and `queries.py`.**

- [ ] **Step 4: Run the tests and check they pass.** Run the same command. Expected: PASS.

- [ ] **Step 5: Commit.** Commit with the message `Add coverage checks and marginal-rate query`.

### Task 6: PolicyEngine UK differential check

**Files:**
- Create: `src/bm/policyengine.py`, `src/bm/households.py`, `src/bm/checks.py`, `docs/mismatches.md`
- Test: `tests/test_policyengine.py`, `tests/test_checks.py`

**Interfaces:**
- Consumes: `catala_run.outputs`, `evaluate.outputs`, `bounds`, and `queries.emr` (for boundary households).
- Produces:
  - `bm.policyengine.award(inputs: dict[str, int | bool]) -> int`, giving the monthly award in pence. The module docstring states the PolicyEngine variable for each of our inputs (earnings, age, LCW, no housing costs, no children, single adult), the period used, and how a monthly figure is obtained.
  - `bm.households.generate(bounds: dict[str, Bound], n_random: int, seed: int) -> list[dict]`. It covers every Task 1 table row, the work allowance ± 1p, the last-penny earnings for each age band and LCW combination (found by asking Z3 for the smallest earnings with an award of 0), and `n_random` households drawn from the bounds.
  - `bm.checks.run(households: list[dict]) -> list[Mismatch]`. `Mismatch(household, catala: int, z3: int, policyengine: int)`. Catala and Z3 disagreeing raises `TranslatorDisagreement`, because that is a translator bug and not a mismatch.

- [ ] **Step 1: Write the failing tests.**
  - `test_pe_mapping_known_household`: aged 25 or over, no LCW, earnings £500.00, start date 2026-05-01. `policyengine.award` returns `14_990`.
  - `test_pe_period_pinned`: two households that differ only in start date (2026-05-01 and 2026-11-01) give the same PolicyEngine award. This pins the period handling.
  - `test_checks_exact_match`: `checks.run(households.generate(bounds, n_random=50, seed=1))` returns `[]`.

  Any test that fails because PolicyEngine differs is triaged against the regulation text before it is changed. Record each mismatch in `docs/mismatches.md` with the household, the three figures, the regulation reference, the classification (our error, PolicyEngine's error, or a deliberate difference) and the date. Only a mismatch classified as PolicyEngine's error or a deliberate difference may be marked `xfail`, with a reason that links to its entry. Our errors are fixed.

- [ ] **Step 2: Run the tests and check they fail.** Run `uv run pytest tests/test_policyengine.py tests/test_checks.py -v`. Expected: FAIL with import errors.

- [ ] **Step 3: Implement `policyengine.py`, `households.py` and `checks.py`.** Find PolicyEngine's variable names in the installed `policyengine-uk` source, not from memory.

- [ ] **Step 4: Run the tests and triage.** Run the same command. Expected: PASS, or every failure triaged and logged as above.

- [ ] **Step 5: Commit.** Commit with the message `Add PolicyEngine UK differential check and mismatch log`.

### Task 7: CLI, report, provenance and CI

**Files:**
- Create: `src/bm/provenance.py`, `src/bm/report.py`, `src/bm/cli.py`, `.github/workflows/ci.yml`
- Modify: `pyproject.toml` (add the console script `bm = "bm.cli:main"`), `Makefile` (add `check`, which runs `bm check`), `README.md` (update the status line and add a "Running it" section)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `bm.provenance.collect(rules: Path) -> Provenance`. `Provenance(rules_commit: str, rules_dirty: bool, catala_version: str, z3_version: str, cvc5_version: str)`.
  - CLI commands: `bm translate IR -o OUT.smt2`, `bm coverage IR --bounds TOML`, `bm query emr IR --bounds TOML [--delta 100] [--timeout-ms 60000] [--json]`, `bm check IR --bounds TOML [--n-random 50] [--seed 1]` and `bm report IR --bounds TOML [--json]`. The exit code is 0 when there are no errors, 1 on any failure or mismatch, and 2 when any result is *unknown*.
  - `report` text includes the peak rate as a percentage, the example household, the coverage outcome, the mismatch count and the provenance block. The `--json` output has the same content.

- [ ] **Step 1: Write the failing tests.**
  - `test_report_json_shape`: `bm report --json` on the UC files has the keys `emr`, `coverage`, `mismatches` and `provenance`, and `emr.rate == "11/20"`.
  - `test_report_unknown_exit_code`: `bm query emr --timeout-ms 1` exits with 2 and prints `unknown`.
  - `test_provenance_dirty_flag`: in a temporary git repository with an uncommitted change, `rules_dirty` is `True`.

- [ ] **Step 2: Run the tests and check they fail.** Run `uv run pytest tests/test_cli.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `provenance.py`, `report.py` and `cli.py`, and add the CI workflow.** CI runs on pull requests on `ubuntu-latest`. It caches `_opam` keyed on the Catala version, and the uv cache keyed on `uv.lock`. Steps: `make build`, `make export`, `make test`, `make check`. Record the job duration in the pull request description. If it is over 15 minutes, move `tests/test_policyengine.py` and `tests/test_checks.py` to a nightly scheduled job and say so in the README.

- [ ] **Step 4: Run the tests and check they pass.** Run `make test && make check`. Expected: PASS, and `bm report` prints a peak marginal rate of 55% with an example household.

- [ ] **Step 5: Commit.** Commit with the message `Add bm CLI, report with provenance, and CI`.

### Task 8: Quantifier tractability spike (independent, own branch)

This task has no dependency on Tasks 1 to 7. Run it on a branch called `spike-quantifiers` that is never merged. Only the write-up comes back, through a small pull request of its own.

**Files:**
- Create (on the spike branch): `spike/*.smt2`, `spike/run.py`
- Create (merged): `docs/spike-quantifier-tractability.md`

- [ ] **Step 1: Write the model.** Hand-write SMT-LIB for two monthly assessment periods. Use the 2026/27 figures and the Task 1 encoding, with Catala-style rounding, for a couple who may or may not be found to be living together (the judgement point). If they are a couple, use the joint standard allowance from reg. 36 (check its current figure on legislation.gov.uk and record the date). Earnings over the two periods total a fixed amount, which is a parameter. The claimant chooses how the total is split between the periods (the controlled input), in whole pounds.

- [ ] **Step 2: Write the query in two forms.** The question: is there a split such that, whatever the decision maker finds, the total award over both periods exceeds the even-split award by more than £X?
  - Form A uses `forall` over the judgement point.
  - Form B expands the judgement point into its two cases joined by `and`.

  Sweep £X and the earnings total over a grid of at least 20 points.

- [ ] **Step 3: Run and time.** Run both forms on Z3 and cvc5 with a 60-second timeout. Record the status and time for each grid point, and check that the forms agree wherever both finish.

- [ ] **Step 4: Write it up.** In `docs/spike-quantifier-tractability.md`, cover the question, the model, a timings table, any disagreements, and a recommendation for milestone 2 (quantifiers, or expansion into finite cases). Keep it to findings about the method. No worked guides to particular claims.

- [ ] **Step 5: Commit.** Commit the spike code on its branch, and the write-up on a branch called `spike-quantifiers-writeup`.
