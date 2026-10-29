# Milestone 2: first strategic query, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add input labels, a housing costs element and a label-driven `strategic` module whose two queries (timing gain across two assessment periods, and the value of the LCW finding) are optimised by Z3, confirmed by cvc5 and replayed through Catala.

**Architecture:** Four behaviour-preserving refactors come first (units, an input registry with labels, one SMT script builder, one optimise-and-confirm routine). The rules then gain the housing costs element. The strategic queries are built on the builder: one household instance per assessment period per judgement case, sharing household facts, in one solver.

**Tech Stack:** Catala 1.3.0 (local opam switch, `opam exec --`), OCaml exporter (unchanged), Python 3.14 with uv, `z3-solver` and `cvc5` from PyPI, `policyengine-uk` 2.164.2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-first-strategic-query-design.md`

## Global Constraints

- Run Catala, clerk and dune only through `opam exec --` (the Makefile does). Python only through `uv run`. `make test` is the full suite: export, `clerk test`, dune tests, pytest.
- Money is integer pence and dates are days since 1970-01-01 everywhere in Python and SMT. Pounds appear only at the edges (TOML, CLI arguments, Catala JSON, report text).
- Every public text (docs, docstrings, comments, commit messages) is neutral, in British English, with no em-dashes. Money and legal claims cite legislation.gov.uk or the tool's source, with the date checked.
- Readings of the law are recorded as the project's reading, with sources, pending specialist review. Never as confirmed by the project owner.
- Never use `git stash`. Concurrent implementers each get their own worktree.
- Commit messages follow the existing style (imperative, sentence case, no prefix) and end with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Failures are loud. *Unknown* is a result, never read as "nothing found" or "no gain".
- Refactor tasks (1 to 4) change no behaviour: the whole existing suite passes unchanged after each, apart from the mechanical renames each task names.

## Review Focus

1. `--fix` with an unknown input name, or money that is not pounds with two decimals (`500`, `£500`), exits 1 with a one-line `bm:` error, not a traceback. Test owned by Task 10.
2. A `--start` whose second period falls after 5 April 2027 (for example 2027-03-10) is refused before any solver runs. Test owned by Task 7.
3. A first period starting on the 31st (for example 2027-01-31) gives a second period on the last day of the next month (2027-02-28), and the query does not crash. Test owned by Task 7.
4. `has_lcw` fixed by the caller: the timing query runs with one case; the judgement query on `has_lcw` refuses. Tests owned by Tasks 8 and 9.
5. A fixed household and total for which no split keeps every award above nil (for example `housing_costs_element = 0`, `aged_25_or_over = true`, `has_lcw = false`, total £2,000.00) raises `NoHousehold`, not *unknown* and not a gain of 0. Test owned by Task 8.

---

### Task 1: Shared units module

**Files:**
- Create: `src/bm/units.py`, `tests/test_units.py`
- Modify: `src/bm/bounds.py`, `src/bm/catala_run.py`, `src/bm/households.py`, `src/bm/policyengine.py`, `src/bm/report.py`, `src/bm/translate.py`

**Interfaces:**
- Produces, in `bm.units`:
  - `EPOCH: date` (1970-01-01)
  - `days(d: date) -> int` and `to_date(n: int) -> date`
  - `pence(pounds: str | Decimal) -> int`: exact; a string must match `-?[0-9]+(\.[0-9]{1,2})?`, and a `Decimal` with a fraction of a penny raises `ValueError`
  - `to_pounds(p: int) -> Decimal`: exact, two decimal places
  - `pounds_text(p: int) -> str`: as `report.money` today, `£1,234.56` and `-£0.05`

- [ ] **Step 1: Write the failing tests** in `tests/test_units.py`:

```python
def test_days_round_trip():
    assert units.days(date(2026, 4, 6)) == 20549
    assert units.to_date(20549) == date(2026, 4, 6)

def test_pence_exact():
    assert units.pence("710.10") == 71010
    assert units.pence("0.5") == 50
    assert units.pence(Decimal("424.90")) == 42490
    for bad in ("500.001", "£500", "1e3", ""):
        with pytest.raises(ValueError):
            units.pence(bad)

def test_to_pounds_and_text():
    assert units.to_pounds(42484) == Decimal("424.84")
    assert units.pounds_text(123456) == "£1,234.56"
    assert units.pounds_text(-5) == "-£0.05"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_units.py -v`. Expected: FAIL, no module `bm.units`.
- [ ] **Step 3: Implement `bm.units`,** then replace the six `EPOCH` definitions and the four pounds and pence conversions (`bounds._value`, `catala_run._to_json`/`_from_json`, `policyengine._pounds`, `report.money`) with calls into it. `report.money` becomes an alias of `units.pounds_text`, or its callers switch to it. Leave `policyengine._to_pence` alone: it converts PolicyEngine's float, which is a different job.
- [ ] **Step 4: Run** `make test`. Expected: all pass. Then `grep -rn "date(1970, 1, 1)" src/bm` finds only `units.py`.
- [ ] **Step 5: Commit:** `Add a shared units module`.

### Task 2: Input registry with labels

**Files:**
- Create: `src/bm/inputs.py`, `tests/test_inputs.py`
- Delete: `src/bm/bounds.py`, `tests/test_bounds.py` (its tests move to `tests/test_inputs.py`)
- Modify: `rules/uc.inputs.toml`, `src/bm/cli.py`, `src/bm/report.py`, `src/bm/coverage.py`, `src/bm/queries.py`, `src/bm/households.py`, `src/bm/checks.py`, `src/bm/policyengine.py`, `Makefile`, `README.md`, every test that imports `bm.bounds`

**Interfaces:**
- Consumes: `bm.units` (Task 1), `bm.ir.Scope`.
- Produces, in `bm.inputs`:
  - `Bound(type: str, min: int, max: int)`, frozen, moved unchanged from `bm.bounds`
  - `InputSpec(name: str, type: str, bound: Bound | None, controlled_by: tuple[str, ...], checked_by: str)`, frozen
  - `CONTROLLED_BY = ("claimant", "employer", "landlord", "decision_maker", "nobody")`
  - `CHECKED_BY = ("third_party_data", "documentary_evidence", "claimant_declaration", "assessment", "dwp_records")`
  - `InputsError(ValueError)`, replacing `BoundsError`
  - `load(path: Path, scope: Scope) -> dict[str, InputSpec]`, in the scope's input order
  - `bounds(specs: dict[str, InputSpec]) -> dict[str, Bound]`: only the inputs that have one
  - The CLI flag `--bounds` becomes `--inputs`, and `report.build(ir_path, inputs_path, ...)` follows.

- [ ] **Step 1: Write the failing tests.** Move every test from `tests/test_bounds.py`, renamed for `load`, and add:

```python
def test_real_file_has_labels():
    specs = inputs.load(UC_INPUTS, scope())
    assert list(specs) == ["assessment_period_start", "earned_income", "aged_25_or_over", "has_lcw"]
    assert specs["earned_income"].controlled_by == ("employer", "claimant")
    assert specs["earned_income"].checked_by == "third_party_data"
    assert specs["has_lcw"].controlled_by == ("decision_maker",)
    assert specs["has_lcw"].bound is None

@pytest.mark.parametrize("change, message", [
    (drop_table("has_lcw"), "no entry for inputs ['has_lcw']"),
    (set_key("has_lcw", "controlled_by", ["judge"]), "unknown controlled_by 'judge'"),
    (set_key("has_lcw", "checked_by", "vibes"), "unknown checked_by 'vibes'"),
    (del_key("earned_income", "checked_by"), "checked_by"),
    (set_key("earned_income", "controlled_by", []), "controlled_by"),
    (add_table("not_an_input"), "unknown inputs ['not_an_input']"),
])
def test_bad_files_refused(tmp_path, change, message): ...
```

  The helpers edit a copy of the real TOML, and the test asserts that `InputsError` is raised with `message` in its text.
- [ ] **Step 2: Run** `uv run pytest tests/test_inputs.py -v`. Expected: FAIL, no module `bm.inputs`.
- [ ] **Step 3: Implement `bm.inputs`.** Then add labels for the four current inputs to `rules/uc.inputs.toml`, with the values and comments from the spec's inputs table (section 2, "Inputs and labels"). Boolean inputs get a table with `type` and the two labels, and no `min` or `max`. Update the header comment. Switch every `bm.bounds` import to `bm.inputs` (`load(...)` then `bounds(...)` wherever a `dict[str, Bound]` is still expected). Rename `--bounds` to `--inputs` in the CLI, `Makefile` and `README.md`. In `checks.run`, build the PolicyEngine inputs as `{name: household[name] for name in policyengine.INPUT_NAMES}`, not a hand-written dict.
- [ ] **Step 4: Add the mapping test** to `tests/test_policyengine.py`: `assert policyengine.INPUT_NAMES == set(inputs.load(UC_INPUTS, scope()))`.
- [ ] **Step 5: Run** `make test`. Expected: all pass.
- [ ] **Step 6: Commit:** `Replace the bounds file reader with an input registry that holds labels`.

### Task 3: One SMT script builder

**Files:**
- Create: `src/bm/household.py`, `tests/test_household.py`
- Modify: `src/bm/coverage.py`, `src/bm/queries.py`, `src/bm/evaluate.py`, `src/bm/households.py`, `src/bm/translate.py` (docstrings only)

**Interfaces:**
- Consumes: `SmtModule`, `quote`, `apply`, `literal`, `SORTS` from `bm.translate`; `Bound` from `bm.inputs`.
- Produces, in `bm.household`:

```python
def smt_sum(terms: list[str]) -> str            # "0" for none, the term for one, "(+ ...)" otherwise

@dataclass(frozen=True)
class Instance:
    prefix: str
    inputs: dict[str, str]                       # input name -> quoted constant, e.g. "|p1.earned_income|"
    def output(self, name: str) -> str           # SMT application of the module function to this instance's inputs
    def household(self, model: dict[str, int | bool]) -> dict[str, int | bool]   # input name -> value

class Script:
    def __init__(self, module: SmtModule, bounds: dict[str, Bound] | None = None): ...
    def instance(self, prefix: str = "", fixed: dict[str, int | bool] | None = None,
                 equal: dict[str, str] | None = None, defined: bool = True) -> Instance: ...
    def declare(self, name: str, sort: str, term: str | None = None) -> str   # quoted constant
    def bound(self, term: str, bound: Bound) -> None
    def add(self, line: str) -> None
    def text(self, *extra: str) -> str           # every line, then extra, then "(check-sat)"
```

- Semantics:
  - `Script.__init__` emits `module.text`, then one `(define-fun |bm.obligation.i| (<inputs>) Bool <formula>)` per obligation.
  - `instance` declares one constant per scope input, named `|<prefix>.<input>|`, or `|<input>|` when `prefix == ""`. It asserts each `fixed` value and each `equal` term. It asserts the bound of every bounded input, when the script has bounds. When `defined` is true, it asserts that no obligation holds at the instance.
  - A repeated prefix raises `ValueError`.

- [ ] **Step 1: Write the failing tests** in `tests/test_household.py`, on the real UC module:
  - `test_smt_sum_shapes`: `smt_sum([]) == "0"`, `smt_sum(["|a|"]) == "|a|"`, `smt_sum(["|a|", "|b|"]) == "(+ |a| |b|)"`.
  - `test_one_term_sum_parses_in_cvc5`: a script declaring `|a|`, asserting `(= {smt_sum(["|a|"])} 3)`, gives `sat` with `a == 3` from both `solvers.run("cvc5", ...)` and `solvers.run("z3", ...)`.
  - `test_two_instances_share_no_constants`: instances `"p1"` and `"p2"`, with `earned_income` fixed to 0 and 100000 respectively, are `sat` together, and `p1.household(model)["earned_income"] != p2.household(model)["earned_income"]`.
  - `test_equal_ties_instances`: `p2` with `equal={"earned_income": "(+ |p1.earned_income| 100)"}` gives a model where the two differ by exactly 100.
  - `test_defined_excludes_error_households`: an instance with `assessment_period_start` fixed to `units.days(date(2026, 4, 5))` and `defined=True` is `unsat`, and with `defined=False` it is `sat`. That date is outside the rules, so an obligation holds there. Use a script without bounds, so the date bound does not decide it.
  - `test_repeated_prefix_refused`.
- [ ] **Step 2: Run** `uv run pytest tests/test_household.py -v`. Expected: FAIL, no module `bm.household`.
- [ ] **Step 3: Implement `bm.household`.**
- [ ] **Step 4: Move the callers onto `Script`:**
  - `coverage.check` uses `instance(defined=False)` and asserts each obligation.
  - `queries.emr` uses instances `""` and `"plus"`, with `equal={"earned_income": "(+ |earned_income| <delta>)"}` and the other inputs equal to the plain constants.
  - `evaluate.outputs` uses a `Script` without bounds and `instance(fixed=inputs, defined=False)`. It keeps its own obligation readout.
  - `households.last_penny_earnings` uses `instance(fixed=...)`.
  - Delete `coverage.declarations`. Model keys stay the plain input names wherever the prefix is `""`, so `CoverageFinding.example` and `EmrResult.household` are unchanged.
- [ ] **Step 5: Document `.defined`** in the docstrings of `Obligation` and `SmtModule` in `translate.py`: it is true at `error_on_empty` sites even where Catala raises an error, so every query must assert that no obligation holds, which `Script.instance(defined=True)` does.
- [ ] **Step 6: Run** `make test`. Expected: all pass.
- [ ] **Step 7: Commit:** `Build every solver script with one household builder`.

### Task 4: One optimise-and-confirm routine

**Files:**
- Modify: `src/bm/solvers.py`, `src/bm/queries.py`, `src/bm/households.py`, `tests/test_solvers.py`

**Interfaces:**
- Consumes: `solvers.run`, `SolverDisagreement`.
- Produces, in `bm.solvers`:

```python
@dataclass(frozen=True)
class Optimum:
    status: Literal["optimal", "unknown", "infeasible"]
    value: int | None                 # Z3's optimum; kept when only cvc5 is unknown
    model: Model | None
    versions: dict[str, str]          # {"z3": ..., "cvc5": ...}
    confirmed: bool                   # cvc5 answered unsat to "anything better"

def optimise_and_confirm(lines: list[str], objective: str, direction: Literal["max", "min"],
                         timeout_ms: int, context: str = "") -> Optimum
```

- Semantics:
  - Z3 runs `lines + [(maximize|minimize objective), (check-sat)]`.
    - Z3 unsat gives `infeasible`.
    - Z3 unknown gives `unknown`, with no value and no model.
  - cvc5 then runs `lines + [(assert (> objective v))]`, or `<` for a minimum, then `(check-sat)`.
    - cvc5 sat raises `SolverDisagreement(z3, cvc5, context)`.
    - cvc5 unsat gives `optimal` and `confirmed=True`.
    - cvc5 unknown gives `unknown`, with Z3's value and model kept and `confirmed=False`.
  - The objective is evaluated by declaring `|bm.objective|` equal to it, so its value is read from the model.

- [ ] **Step 1: Write the failing tests** in `tests/test_solvers.py`:
  - `test_optimise_max`: `x` in [0, 7] gives `optimal`, value 7, `confirmed`.
  - `test_optimise_min`: the same, minimised, gives 0.
  - `test_optimise_infeasible`: `x > 3 and x < 2` gives `infeasible`.
  - `test_optimise_disagreement`: monkeypatch `solvers.run` so cvc5 returns sat, and assert that `SolverDisagreement` is raised.
  - `test_optimise_cvc5_unknown_keeps_z3`: monkeypatch cvc5 to return unknown, and assert status `unknown`, value 7, `confirmed is False`.
- [ ] **Step 2: Run** `uv run pytest tests/test_solvers.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement it,** then make `queries.emr` and `households.last_penny_earnings` call it. Each keeps its own outward behaviour:
  - `emr` raises `NoHousehold` on `infeasible`, and returns status `unknown` with `None` fields when Z3 is unknown.
  - `last_penny_earnings` raises `NoLastPenny` on anything but `optimal`.
- [ ] **Step 4: Run** `make test`. Expected: all pass.
- [ ] **Step 5: Commit:** `Share one routine for Z3 optimisation confirmed by cvc5`.

### Task 5: Housing costs element in the rules

**Files:**
- Modify: `rules/uc.catala_en`, `rules/uc_tests.catala_en`, `rules/uc.inputs.toml`, `src/bm/policyengine.py`, `src/bm/households.py`, `tests/test_policyengine.py`, and any test that builds a household dict by hand

**Interfaces:**
- Produces:
  - scope input `housing_costs_element` (money)
  - scope output `maximum_amount` (money)
  - `policyengine.INPUT_NAMES` gains `housing_costs_element`
  - generated households carry `housing_costs_element` (0 for every existing row)

- [ ] **Step 1: Write the failing Catala tests** in `rules/uc_tests.catala_en`. Add `-- housing_costs_element: $0.00` to every existing case, then add these, each with its arithmetic in a comment and an assessment period starting on 1 May 2026, aged 25 or over:

| Case | Earnings | LCW | Housing | Work allowance | Deduction | Maximum | Award |
|---|---|---|---|---|---|---|---|
| `TestHousingNoEarnings` | £0.00 | yes | £500.00 | £427.00 | £0.00 | £924.90 | £924.90 |
| `TestHousingAboveLower` | £1,000.00 | yes | £500.00 | £427.00 | £315.15 | £924.90 | £609.75 |
| `TestHousingHalfPenny` | £427.10 | yes | £500.00 | £427.00 | £0.06 | £924.90 | £924.84 |
| `TestHousingNoLcw` | £1,000.00 | no | £500.00 | £0.00 | £550.00 | £924.90 | £374.90 |
| `TestHousingOnePenny` | £1,000.00 | yes | £0.01 | £427.00 | £315.15 | £424.91 | £109.76 |

  Assert `work_allowance`, `earnings_deduction`, `maximum_amount` and `award` in each.
- [ ] **Step 2: Run** `make build`. Expected: FAIL, because `housing_costs_element` is not an input.
- [ ] **Step 3: Change the rules,** following the spec (section 1, "Rules"):
  - Add the input `housing_costs_element` and the output `maximum_amount`.
  - Replace the work allowance definitions with the three flat cases, citing regulation 22(2) and S.I. 2026/148, checked 29 October 2026. The lower allowance case's condition is `has_lcw and housing_costs_element > $0.00`.
  - Make the award `maximum_amount - earnings_deduction`, floored at zero.
  - Add the simplification to the file's header list: the element is taken as already worked out, with a pointer to `docs/model-gaps.md`.
  - Add `[inputs.housing_costs_element]` to `uc.inputs.toml`: `min = "0.00"`, `max = "3000.00"`, `controlled_by = ["landlord"]`, `checked_by = "documentary_evidence"`, with the comment that the bound is a modelling range, not a legal limit.
- [ ] **Step 4: Run** `make build && opam exec -- clerk test`. Expected: all Catala tests pass.
- [ ] **Step 5: Map the element in PolicyEngine UK.** Set the benefit unit variable `uc_housing_costs_element` to 12 times the monthly element in pounds. Extend the module docstring with the source files checked (`variables/gov/dwp/universal_credit/housing_costs_element/uc_housing_costs_element.py` and `work_allowance/uc_work_allowance.py`, policyengine-uk 2.164.2, with the date). Add `test_pe_housing_lowers_work_allowance`: with earnings £1,000.00, LCW, aged 25 or over and an element of £500.00, PolicyEngine's award is 60975 pence.
- [ ] **Step 6: Carry the input through the Python code.** `households` sets `housing_costs_element = 0` in every existing generated row. Hand-built households in tests gain the key. The agreement test between Catala and Z3 must draw the element from its bounds, so the new input is exercised.
- [ ] **Step 7: Run** `make test`. Expected: all pass. The known answers of `queries.emr` still hold (a peak of 55%).
- [ ] **Step 8: Commit:** `Add the housing costs element and the lower work allowance`.

### Task 6: Differential checks across the housing element

**Files:**
- Modify: `src/bm/households.py`, `src/bm/checks.py`, `docs/mismatches.md`, `tests/test_checks.py`

**Interfaces:**
- Consumes: Task 5's input. `households.generate(bounds: dict[str, Bound], n_random, seed, module)` keeps its signature.

- [ ] **Step 1: Write the failing test** `test_generate_covers_housing` in `tests/test_checks.py`. Generated households include:
  - `housing_costs_element` values 0 and 1;
  - with LCW and an element above 0, earnings of 42699, 42700 and 42701;
  - at least one random household with each of a zero and a positive element.
- [ ] **Step 2: Run** `uv run pytest tests/test_checks.py::test_generate_covers_housing -v`. Expected: FAIL.
- [ ] **Step 3: Extend `generate`.**
  - Boundary rows: repeat the work-allowance and last-penny rows for each combination of `(aged_25, lcw)` with element 0 and with element 50000 (£500.00), plus element 1 (1p) at earnings 0 with LCW.
  - Random households: draw the element after the Booleans. It is 0 with probability one half, and otherwise uniform over its bound.
  - Update the module docstring's numbered list to match.
- [ ] **Step 4: Run** `uv run pytest tests/test_checks.py -v` (PolicyEngine is slow; expect minutes). Triage every mismatch against the regulation text. Lower-work-allowance households where 55% of earnings above £427.00 ends in half a penny belong to the existing rounding-stage class. Confirm that `rounding_stage_difference` already accepts them; it reads the work allowance from Catala's outputs. Any other class is a new entry in `docs/mismatches.md`, in the existing format, and stops the task for a ruling if it is not plainly our error.
- [ ] **Step 5: Update the count paragraph** of entry 1 in `docs/mismatches.md` (the households, the seed, the number of mismatches and how they split) from the new run, dated.
- [ ] **Step 6: Run** `make test`. Expected: all pass.
- [ ] **Step 7: Commit:** `Check the housing costs element against PolicyEngine UK`.

### Task 7: Strategic foundations: judgement points, choice and periods

**Files:**
- Create: `src/bm/strategic.py`, `tests/test_strategic.py`

**Interfaces:**
- Consumes: `InputSpec` (Task 2), `bm.units`.
- Produces, in `bm.strategic`:

```python
class QueryRefused(ValueError): ...
class NoHousehold(ValueError): ...           # no household satisfies the query's constraints

@dataclass(frozen=True)
class Split:
    input: str
    periods: int = 2

DEFAULT_START = date(2026, 4, 6)
DEFAULT_CASE_CAP = 8

def judgement_points(specs: dict[str, InputSpec], fixed: dict[str, int | bool]) -> list[str]
def cases(specs: dict[str, InputSpec], points: list[str], cap: int = DEFAULT_CASE_CAP) -> list[dict[str, bool]]
def check_choice(specs: dict[str, InputSpec], choice: Split) -> None
def period_starts(first: date, specs: dict[str, InputSpec], periods: int = 2) -> list[date]
```

- Semantics:
  - **`judgement_points`:** inputs whose `controlled_by` includes `decision_maker` and are not in `fixed`, in scope order.
  - **`cases`:** the product of the points' values, each `{point: value}`, with `True` first. With no points it gives `[{}]`. It raises `QueryRefused` above `cap`, or for a non-Boolean point.
  - **`check_choice`:** raises `QueryRefused` unless the input exists, is money, and is controlled by `claimant` or `employer`, and unless `periods == 2`.
  - **`period_starts`:** each start is the same day of the next month, or that month's last day when it has no such day. All starts must lie within `assessment_period_start`'s bound, or it raises `QueryRefused` naming the date. (The day within the month does not affect the 2026/27 rules. This is a modelling choice, not a reading of regulation 21.)

- [ ] **Step 1: Write the failing tests:**
  - `test_judgement_points_from_labels`: on the real specs, `== ["has_lcw"]`; with `fixed={"has_lcw": True}`, `== []`.
  - `test_cases`: `cases(specs, ["has_lcw"]) == [{"has_lcw": True}, {"has_lcw": False}]`; `cases(specs, []) == [{}]`; a cap of 1 with one point raises `QueryRefused`.
  - `test_check_choice`: `Split("earned_income")` passes; `Split("has_lcw")`, `Split("housing_costs_element")` (controlled by the landlord), `Split("nope")` and `Split("earned_income", periods=3)` raise `QueryRefused`.
  - `test_period_starts`: 2026-04-06 gives `[2026-04-06, 2026-05-06]`; 2027-01-31 gives `[2027-01-31, 2027-02-28]` (Review Focus 3); 2027-03-10 raises `QueryRefused` mentioning `2027-04-10` (Review Focus 2).
- [ ] **Step 2: Run** `uv run pytest tests/test_strategic.py -v`. Expected: FAIL, no module.
- [ ] **Step 3: Implement** the four functions and the types.
- [ ] **Step 4: Run** the tests again. Expected: PASS.
- [ ] **Step 5: Commit:** `Derive judgement cases, choices and periods from input labels`.

### Task 8: Timing gain query

**Files:**
- Modify: `src/bm/strategic.py`, `tests/test_strategic.py`
- Create: `tests/reference_uc.py` (a test-only reference model)

**Interfaces:**
- Consumes: `Script`, `Instance`, `smt_sum` (Task 3); `optimise_and_confirm`, `Optimum` (Task 4); Task 7's functions; `catala_run.outputs`.
- Produces:

```python
@dataclass(frozen=True)
class Witness:
    case: dict[str, bool]
    period: int                       # 1 or 2
    kind: Literal["split", "baseline", "single"]
    inputs: dict[str, int | bool]     # every scope input, SMT units
    award: int

@dataclass(frozen=True)
class TimingResult:
    status: Literal["optimal", "unknown"]
    gain: int | None                  # pence: worst case over judgement cases
    per_case: list[tuple[dict[str, bool], Literal["optimal", "unknown"], int | None]]
    fixed: dict[str, int | bool]
    starts: list[int]                 # days
    total: int | None                 # the chosen input's total over both periods
    witnesses: list[Witness]
    verification: dict[str, str]      # {"cvc5": "confirmed"|"unknown", "replay": "matched"|"not run"}
    versions: dict[str, str]

RULES = ROOT / "rules" / "uc.catala_en"   # as in bm.checks

class ReplayMismatch(RuntimeError): ...

def timing(module: SmtModule, specs: dict[str, InputSpec], choice: Split = Split("earned_income"),
           first_start: date = DEFAULT_START, fixed: dict[str, int | bool] | None = None,
           total: int | None = None, cap: int = DEFAULT_CASE_CAP, rules: Path | None = RULES,
           timeout_ms: int = 60_000) -> TimingResult
def replay(rules: Path, witnesses: list[Witness]) -> None    # raises ReplayMismatch
```

- **Encoding.** One `Script` with bounds:
  - Every household fact that is not the choice, a judgement point or the start is declared once as `|fact.<name>|` and bounded, or fixed when it is in `fixed`.
  - The split is `|choice.1|` (bounded) and `|choice.total|`. `total` fixes the latter.
  - For each case *c*, period *p* and kind *k* in (`split`, `baseline`), there is an instance `c<c>.p<p>.<k>` with `equal` set as follows:
    - facts: their `fact.` constant;
    - start: the period's start literal;
    - judgement points: the case literal;
    - choice: `split` p1 `|choice.1|`, `split` p2 `(- |choice.total| |choice.1|)`, `baseline` p1 `(div |choice.total| 2)`, `baseline` p2 `(- |choice.total| (div |choice.total| 2))`.
  - Each instance asserts `(> <award> 0)`.
  - gain_c = `(- smt_sum(split awards) smt_sum(baseline awards))`.
  - The robust query declares `|bm.gain|`, asserts `(<= |bm.gain| gain_c)` for every case, and maximises `|bm.gain|`.
  - Each case's own gain is a separate script containing only that case's instances.
- **Results.**
  - `infeasible` raises `NoHousehold`.
  - An optimum is replayed through Catala (`replay`) unless `rules is None`. A Catala award that differs from Z3's raises `ReplayMismatch`, naming the witness.
  - `status` is `optimal` only when every optimisation is `optimal`.

- [ ] **Step 1: Write the reference model** `tests/reference_uc.py`: `award(earned: int, aged_25: bool, lcw: bool, housing: int) -> int`, in pence, from the spec's rules, with exact integer arithmetic (the deduction is `(55 * x + 50) // 100` for x >= 0, which is half away from zero) so the brute force stays fast. Add `test_reference_matches_catala_table`: it reproduces every `award` assertion in `rules/uc_tests.catala_en`.
- [ ] **Step 2: Write the failing query tests:**
  - `test_timing_gain_never_negative`: the default query is `optimal`, with `gain >= 0`, and its witnesses replay.
  - `test_timing_matches_brute_force`: for each of the fixed households `(aged_25=True, housing=0)`, `(aged_25=True, housing=50000)` and `(aged_25=False, housing=50000)`, with `total` in `(142_001, 142_011, 85_421)`, the robust gain equals `min over lcw of max over e1 in 0..total` of the reference gain, restricted to splits and baselines whose four awards are above nil.
  - `test_timing_forall_cross_check`: for one of those households, a hand-built script in which `has_lcw` is a `forall`-bound variable is checked:

    ```
    (assert (forall ((j Bool)) (and above_nil(j) (> gain(j) <gain>))))   ; unsat
    (assert (forall ((j Bool)) (and above_nil(j) (>= gain(j) <gain>))))  ; sat
    ```

    Here `gain(j)` and `above_nil(j)` apply the module's functions to `j` in place of `has_lcw`. Both Z3 and cvc5 must agree.
  - `test_timing_with_lcw_fixed_has_one_case` (Review Focus 4).
  - `test_timing_no_household` (Review Focus 5): it raises `NoHousehold`.
  - `test_replay_mismatch_raises`: tamper one witness's award and assert `ReplayMismatch`.
- [ ] **Step 3: Run** `uv run pytest tests/test_strategic.py -v`. Expected: the new tests FAIL.
- [ ] **Step 4: Implement `timing` and `replay`.**
- [ ] **Step 5: Run** the tests again. Expected: PASS. Note the gain found, its witness and the solver times in the task report.
- [ ] **Step 6: Commit:** `Add the timing gain query, worst case over judgement points`.

### Task 9: Value of a judgement point

**Files:**
- Modify: `src/bm/strategic.py`, `tests/test_strategic.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class JudgementResult:
    point: str
    status: Literal["optimal", "unknown"]
    largest: int | None               # pence: award(True) - award(False)
    smallest: int | None
    largest_witnesses: list[Witness]  # kind "single", period 1, one per value
    smallest_witnesses: list[Witness]
    fixed: dict[str, int | bool]
    start: int
    verification: dict[str, str]
    versions: dict[str, str]

def judgement_value(module: SmtModule, specs: dict[str, InputSpec], point: str,
                    start: date = DEFAULT_START, fixed: dict[str, int | bool] | None = None,
                    rules: Path | None = RULES, timeout_ms: int = 60_000) -> JudgementResult
```

- **Encoding:** shared facts as in Task 8, and two instances, `yes` and `no`, with the point fixed `True` and `False`. Both awards are above nil. The query maximises and then minimises `(- award_yes award_no)`, and replays both optima.
- **Refusals:** `point` must be in `judgement_points(specs, fixed)` and Boolean, or `QueryRefused` is raised.

- [ ] **Step 1: Write the failing tests:**
  - `test_lcw_value_no_housing`: with `fixed={"housing_costs_element": 0}`, `largest == 39050`, `smallest == 0`.
  - `test_lcw_value_with_housing`: with `fixed={"housing_costs_element": 50000}`, `largest == 23485`, `smallest == 0`.
  - `test_lcw_value_overall`: unfixed, `largest == 39050`.
  - `test_judgement_refuses`: `point="earned_income"` raises, and `point="has_lcw"` with `fixed={"has_lcw": True}` raises (Review Focus 4).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement `judgement_value`.**
- [ ] **Step 4: Run** them again. Expected: PASS.
- [ ] **Step 5: Commit:** `Add the judgement point value query`.

### Task 10: Report and CLI

**Files:**
- Modify: `src/bm/cli.py`, `src/bm/report.py`, `tests/test_cli.py`, `README.md`

**Interfaces:**
- Consumes: `strategic.timing`, `strategic.judgement_value` and their results.
- Produces:
  - `bm query timing IR --inputs TOML [--rules DIR] [--start YYYY-MM-DD] [--total POUNDS] [--fix NAME=VALUE ...] [--cap 8] [--timeout-ms N] [--json]`
  - `bm query judgement IR NAME --inputs TOML [--rules DIR] [--start YYYY-MM-DD] [--fix NAME=VALUE ...] [--timeout-ms N] [--json]`
  - `report.timing_text(result, specs) -> list[str]`, `report.timing_dict(result, specs) -> dict`, `report.judgement_text(...)` and `report.judgement_dict(...)`
  - `Report` gains `timing: TimingResult` and `judgement: JudgementResult` (for `has_lcw`). `report.build` runs both with defaults. `exit_code` returns 2 when either is `unknown`.
  - `to_dict` and every `--json` output gain a top-level `"unknown": bool`.

- **Details:**
  - `--fix` values are parsed by the input's type: money with `units.pence`, dates as ISO dates, Booleans as `true` or `false`. An unknown name or a bad value raises `ValueError` with a one-line message, which `main` prints as `bm: ...` and exits 1.
  - In both text and JSON, each witness input shows its `controlled_by` and `checked_by`.
  - The text output ends with the line `Model gaps that limit these findings: docs/model-gaps.md`.
  - The `QueryRefused`, `NoHousehold` and `ReplayMismatch` exceptions are `ValueError` or `RuntimeError` subclasses, so `main` already maps them to exit 1.

- [ ] **Step 1: Write the failing tests** in `tests/test_cli.py`:
  - `test_query_timing_json`: exit 0; the JSON has `"unknown": false`, `gain >= 0`, and every witness input with `controlled_by` and `checked_by`.
  - `test_query_judgement_text`: exit 0; the text contains `£390.50` and `docs/model-gaps.md`.
  - `test_query_unknown_exits_2`: monkeypatch `solvers.run` to return `unknown`, and get exit 2 with `"unknown": true`.
  - `test_query_disagreement_exits_1`: monkeypatch cvc5 to return `sat` on confirmation, and get exit 1 with `SolverDisagreement` on stderr. This is the carried-forward test.
  - `test_coverage_exits_1_and_2`: monkeypatch so coverage finds a gap (exit 1), then so it returns unknown (exit 2). This is the carried-forward test.
  - `test_fix_errors` (Review Focus 1): `--fix nope=1`, `--fix housing_costs_element=500` and `--fix housing_costs_element=£500.00` each exit 1 with a one-line `bm:` message and no traceback.
  - `test_report_json_has_unknown_flag`.
- [ ] **Step 2: Run** `uv run pytest tests/test_cli.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the commands, the formatters and the report fields. Update the CLI module docstring and `README.md` with the new commands.
- [ ] **Step 4: Run** `make test`. Expected: all pass.
- [ ] **Step 5: Commit:** `Add timing and judgement queries to the CLI and the report`.

### Task 11: Documentation and assumptions

**Files:**
- Modify: `docs/model-gaps.md`, `docs/superpowers/specs/2026-10-29-first-strategic-query-design.md` (the "Assumptions for review" section and the "One-term sums" bullet only), `docs/v2-brief.md`, `README.md`

- [ ] **Step 1: Check each assumption** in the spec's "Assumptions for review" against DWP's *Advice for Decision Making* (gov.uk), and the regulations it cites. Record each outcome under its assumption: the chapter and paragraph consulted, the date, and whether it supports, contradicts or is silent. Contradiction stops the task for a ruling. Do not reword the assumptions into conclusions.
- [ ] **Step 2: Update `docs/model-gaps.md`** with anything Tasks 5 to 10 found, and with the timing finding's limit stated against the actual gain figure.
- [ ] **Step 3: Update the brief:** milestone 2's entry under Milestones records what was built and links the plan. Record, in the brief's milestone 2 entry and in the spec's "One-term sums" bullet, that the translator never writes a unary `+` (Catala's additions are binary), so the one-term special case lives in `bm.household.smt_sum`, where the query code builds sums.
- [ ] **Step 4: Run** `grep -rn $'\u2014' docs README.md` (the em-dash character). Expected: no new em-dashes. Then run `make test`. Expected: all pass.
- [ ] **Step 5: Commit:** `Record the milestone 2 assumptions checks and model gaps`.

After Task 11, the controller runs the whole-branch review and adds the milestone 2 notes to the Superpowers trial section of `CLAUDE.md`.
