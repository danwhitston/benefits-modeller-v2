# Milestone 3: nil assessment periods, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Model the end of an award after a nil assessment period, the reclaim and surplus earnings over a three-period window in Catala, and report the gain, loss, spread and extra payday figures for each case of what DWP decides, confirmed by cvc5 and replayed by Catala, with a scaling probe at 3 to 6 periods.

**Architecture:** A `WindowStep` Catala scope carries the award's state from one period to the next and calls `UniversalCredit` as a sub-scope; `ClaimWindow` chains three steps. The exporter inlines sub-scope calls into flat bm-ir (version 1), so the translator is almost unchanged. A new `bm.window` module builds several copies of the window per household on the existing builder and optimises with `optimise_and_confirm`.

**Tech Stack:** Catala 1.3.0 and OCaml (local opam switch, `opam exec --`), Python 3.14 with uv, `z3-solver` 5.3.2 and `cvc5` 1.4.2 from PyPI, `policyengine-uk` 2.164.2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-nil-assessment-periods-design.md`. Read its [readings](../specs/2026-10-29-nil-assessment-periods-design.md#readings-this-design-rests-on) before any task that touches rules or public text. The research notes behind it are in the controller's scratchpad and are turned into `docs/nil-months.md` by Task 11.

## Global Constraints

- Run Catala, clerk and dune only through `opam exec --` (the Makefile does). Python only through `uv run`. `make test` is the full suite; `make test-fast` skips tests marked `slow`.
- Money is integer pence and dates are days since 1970-01-01 everywhere in Python and SMT. Pounds appear only at the edges (TOML, CLI arguments, Catala JSON, report text).
- Mark a test `slow` when it is written if it calls PolicyEngine UK or takes more than a few seconds.
- Every public text (docs, docstrings, comments, commit messages) is neutral, in British English, with no em-dashes. Money and legal claims cite legislation.gov.uk, the ADM or the tool's source, with the date checked. Readings of the law are the project's own, with sources, for specialist review, never confirmed by the project owner.
- Findings describe rules and classes of claimant. Nothing in the repository works as guidance for a particular claim (see "Publishing findings" in the brief).
- Findings come only from the exact rules, at 3 periods. Probe runs (more periods, or `--relaxed`) are labelled as probes and never reported as findings.
- Every period in a finding begins on or before 31 March 2027.
- Never use `git stash`. Concurrent implementers each get their own worktree.
- Commit messages follow the existing style (imperative, sentence case, no prefix) and end with `Co-Authored-By: <the model that wrote the commit> <noreply@anthropic.com>`.
- Failures are loud. *Unknown* is a result, never read as "nothing found", "no gain" or "no loss".

## Rulings made while planning

Checked against the installed tools on 29 October 2026. Each changes or settles a point in the spec.

1. **No new encoding for rates such as 20/11.** Z3 5.3.2 and cvc5 1.4.2 both accept the translator's existing form, `bm_round` of `(* (to_real m) (/ 20.0 11.0))`, with the money fixed and free. The brief's statement that Z3's linearity check rejects it does not reproduce with plain checks (it may have come from Z3's `Optimize` engine, which milestone 2 replaced). Task 5 pins the form with tests, and Task 12 corrects the brief.
2. **PolicyEngine UK 2.164.2 does not model surplus earnings** and computes UC over a year, not per assessment period. There is no differential test of the window. Task 12 records this as a deliberate difference in `docs/mismatches.md`.
3. **How Catala 1.3.0 presents a sub-scope.** A declared sub-scope (`p1 scope Sub`, with no `internal` keyword, which 1.3.0 rejects there) reaches the exporter as an ordinary `ScopeVarDefinition` of the sub-scope's struct type, whose expression applies the sub-scope's function to its input struct (`catala scopelang` prints `let p1 : Sub = Sub of {"x" = error_empty ⟨...⟩}`). Later uses are `EStructAccess` on that variable. The current exporter stops at the `EApp`. Task 2 inlines this shape.
4. **Window length comes from the IR,** not from a `--periods` flag: it is the number of `earnings_<k>` inputs. A `--probe` flag marks a probe run. A window longer than 3 periods, and `--relaxed`, are refused without `--probe`.
5. **The extra payday figure in cases with no claim after the end.** Its maximum (the cost of the pattern) drops the last-period rule on the pattern copy and is a lower bound, like the loss. Its minimum (the most the pattern can gain) keeps the rule, like the gain.

## Order

Tasks 1 to 5 and 7 to 10 run in sequence, then Task 12. Task 6 (the reference) depends only on the spec, and Task 11 (the research note) on nothing in the code. Both can run alongside the sequence in their own worktrees, but Task 6 must be merged before Task 7's reference tests run.

## Review Focus

1. A `--total` that does not divide by 3, for example £1,000.00, gives the even split 33,334p, 33,333p, 33,333p, with the remainder in the earliest periods. Test owned by Task 7.
2. A fixed household and total whose even split ends the window at nil (for example `has_lcw = false`, `housing_costs_element = 0`, `aged_25_or_over = true`, total £9,000.00) raises `NoHousehold` naming the excluded even split, not *unknown* and not a figure of 0. Test owned by Task 7.
3. `--start 2027-02-01` (third period from 1 April 2027) is refused before any solver runs, with a message naming 31 March 2027. Test owned by Task 7.
4. `--fix has_lcw=false` drops `lcw_carries_over` from the cases, giving 3 cases, and `--fix claim_after_end=false` gives 1 or 2 cases whose loss, spread and extra payday maximum are labelled lower bounds. Tests owned by Tasks 4 and 8.
5. A first start on the 31st (2027-01-31) gives starts 2027-01-31, 2027-02-28 and 2027-03-31, all accepted. Test owned by Task 1.

---

### Task 1: Carried forward from milestone 2

**Files:**
- Modify: `src/bm/solvers.py`, `src/bm/strategic.py`, `src/bm/household.py`, `src/bm/report.py`, `src/bm/checks.py`, `src/bm/cli.py`, `docs/superpowers/specs/2026-10-29-first-strategic-query-design.md`
- Test: `tests/test_solvers.py`, `tests/test_strategic.py`, `tests/test_household.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `strategic.period_starts(first: date, bound: Bound, periods: int = 2) -> list[date]`. It takes the start input's `Bound` instead of the specs, so window scopes can pass the bound of `start_<k>`. Callers in `strategic` pass `specs[START].bound`.
  - `solvers.optimise_and_confirm(..., max_checks: int = 200)`. When the search has made `max_checks` Z3 checks without proving an optimum, the status is "unknown".
  - `Script.declare` raises `ValueError` for a name that is one of the module's functions. `Script.instance` raises `ValueError` when `fixed` and `equal` name the same input.
  - `report.differential` and `checks.run` take the rules file from `--rules`, as replay does.

- [ ] **Step 1: Write the failing tests:**

```python
def test_period_starts_three_periods_over_new_year():
    assert period_starts(date(2026, 12, 15), BOUND, periods=3) == [
        date(2026, 12, 15), date(2027, 1, 15), date(2027, 2, 15)]

def test_period_starts_from_the_31st():
    assert period_starts(date(2027, 1, 31), BOUND, periods=3) == [
        date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)]

def test_unbounded_objective_is_unknown_within_the_check_cap():
    # An objective with no upper bound: the search gallops until the cap.
    result = optimise_and_confirm(["(declare-const x Int)", "(assert (>= x 0))"],
                                  "x", "max", timeout_ms=60_000, max_checks=20)
    assert result.status == "unknown" and result.value is None

def test_disagreement_message_with_equal_statuses():
    text = str(SolverDisagreement(SolverResult("sat", {}, "z"), SolverResult("sat", {}, "c"), "ctx"))
    assert "says sat but cvc5 says sat" not in text and "ctx" in text

def test_declare_refuses_a_module_function_name(module):
    with pytest.raises(ValueError):
        Script(module).declare("award", "Int")

def test_instance_refuses_fixed_and_equal_overlap(module):
    with pytest.raises(ValueError):
        Script(module).instance(fixed={"has_lcw": True}, equal={"has_lcw": "true"})
```

Plus a CLI test that `bm report` with `--rules` pointing at a copy of the rules runs the differential check on that copy (spy on `catala_run.outputs` and assert the path it receives).

- [ ] **Step 2: Run** `uv run pytest tests/test_solvers.py tests/test_strategic.py tests/test_household.py tests/test_cli.py -m "not slow" -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Also remove the unused `Optimize` path (`_run_z3`'s handling of `maximize` and `minimize`, and `_proved_optimal`), and rewrite the maximisation tests in `tests/test_solvers.py` as tests of `optimise_and_confirm`. In the `optimise_and_confirm` docstring, say that its timing figures were measured by a milestone 2 reviewer. For equal statuses, the disagreement text is `z3 and cvc5 disagree: <context>`.
- [ ] **Step 4: Fix the milestone 2 design's assumption 3 outcome** so that it states regulation 60's employer limb and paragraph (2) in the same terms as the regulation 60 entry in `docs/model-gaps.md`.
- [ ] **Step 5: Run** `make test`. Expected: all pass.
- [ ] **Step 6: Commit:** `Fix items carried forward from the milestone 2 reviews`.

### Task 2: Exporter inlines sub-scopes; bm-ir version 1

**Files:**
- Modify: `exporter/bm_export.ml`, `exporter/test/dune`, `src/bm/ir.py`, `docs/bm-ir.md`, any test that asserts version 0
- Create: `exporter/test/subscope.catala_en`, `exporter/test/subscope.expected.json`, `exporter/test/subscope_direct.catala_en`, `exporter/test/subscope_direct.expected.txt`
- Test: `tests/test_ir.py`

**Interfaces:**
- Produces bm-ir version 1 (`bm_ir_version: 1`). The node types are unchanged. Names of sub-scope variables are prefixed with the path of sub-scope names and a dot: `p1.x`, `p1.y`, `step_1.uc.award`. `inputs` holds only the top scope's inputs. Each sub-scope input becomes a definition `<prefix>.<input>` whose expression is the caller's argument. `outputs` names only the top scope's outputs. Definitions stay in dependency order.
- `bm.ir.IR_VERSION = 1`. Loading a version-0 file raises `UnsupportedIrVersion`.

- [ ] **Step 1: Write the fixtures.** `subscope.catala_en`: a scope `Inner` (input `x` money, output `y = x * 2.0`); a scope `Middle` that declares `i scope Inner` and outputs `z = i.y + $1`; and a scope `Top` (input `a` money) that declares `m1 scope Middle` and `m2 scope Middle`, with outputs `total = m1.z + m2.z`. Write `subscope.expected.json` by hand for `-s Top`. It defines `m1.a`, `m1.i.x`, `m1.i.y`, `m1.z`, the same under `m2.`, and `total`, in dependency order. `subscope_direct.catala_en` uses `(output of Inner with { -- x: a }).y`. Its expected text is the "Unsupported construct" error at that line.
- [ ] **Step 2: Add the dune rules** for both fixtures, following the existing pattern. Run `opam exec -- dune test --root exporter`. Expected: `subscope` FAILS on `EApp`.
- [ ] **Step 3: Implement inlining in `bm_export.ml`.** A `ScopeVarDefinition` whose type is a scope's output struct and whose expression is the application of that scope's function to an `EStruct` of its input struct: look up the called scope's body in `prg.code_items`, and walk it with the existing walker under the prefix. Its `DestructuringInputStruct` lets become definitions whose expressions are the matching argument fields. `EStructAccess` on a bound sub-scope variable becomes a reference to the prefixed definition. The walker's `bound` set becomes a map from variable to exported name. Any other `EApp`, an application inside an expression, a scope from another module, and recursion stay unsupported. Bump `bm_ir_version` to 1, and update the plugin's doc string.
- [ ] **Step 4: Run** `opam exec -- dune test --root exporter`. Expected: all fixtures PASS.
- [ ] **Step 5: Python side.** `ir.IR_VERSION = 1`, with a test that version 0 is refused. Update `docs/bm-ir.md`: version 1, the naming rule, and that `definitions` may hold sub-scope definitions. Run `make test`. Expected: all pass (the `UniversalCredit` export is the same apart from its version).
- [ ] **Step 6: Commit:** `Inline sub-scope calls in the exporter`.

### Task 3: Window rules in Catala

**Files:**
- Modify: `rules/uc.catala_en`, `rules/uc_tests.catala_en`, `Makefile`

**Interfaces:**
- Consumes: Task 2's exporter.
- Produces scopes in module `Uc`:
  - `WindowStep`, with inputs `live` (boolean), `surplus` (money), `months_since_end` (integer), `start` (date), `earnings` (money), `aged_25_or_over`, `housing_costs_element`, `has_lcw`, `claim_after_end`, `claim_each_month`, `lcw_carries_over`; a sub-scope `uc scope UniversalCredit`; internals `claim_made` and `lcw_used`; and outputs `earnings_used`, `award`, `entitled`, `nil_uc_threshold`, `relevant_threshold`, `live_next`, `surplus_next` and `months_since_end_next`.
  - `ClaimWindow`, with inputs `start_1`..`start_3`, `earnings_1`..`earnings_3`, `aged_25_or_over`, `housing_costs_element`, `has_lcw`, `claim_after_end`, `claim_each_month`, `lcw_carries_over`; sub-scopes `step_1`..`step_3 scope WindowStep`; and outputs, for each k, `award_<k>`, `earnings_used_<k>`, `entitled_<k>`, `surplus_after_<k>` (step k's `surplus_next`), `nil_uc_threshold_<k>` and `relevant_threshold_<k>`, plus `total_award`.
  - `ClaimWindow4`, `ClaimWindow5` and `ClaimWindow6`: the same pattern with 4, 5 and 6 steps.
  - `make export` writes `build/claim_window.bm-ir.json` (`-s ClaimWindow`) and `build/claim_window4.bm-ir.json` to `build/claim_window6.bm-ir.json`, as well as `build/uc.bm-ir.json`.

The rules are the spec's [Rules component](../specs/2026-10-29-nil-assessment-periods-design.md#1-rules-rulesuccatala_en), each next to the regulation text it implements, quoted briefly with links and the date checked. Two points the spec fixes:
- The nil UC threshold is `uc.maximum_amount * (100.0 / 55.0)`, one product and one rounding, plus `uc.work_allowance`.
- The £2,500 applies when `start <= |2027-03-31|`, and £300 otherwise.

The first step of each window is live, with a surplus of $0 and `months_since_end` of 0.

- [ ] **Step 1: Write the failing `clerk` tests** in `rules/uc_tests.catala_en`. Use starts 2026-04-06, 2026-05-06 and 2026-06-06 unless stated otherwise. Household H: aged 25 or over, `has_lcw` true, housing $804. Its nil UC threshold is $2,661.36 and its relevant threshold $5,161.36.

| Test | Inputs | Expected |
|---|---|---|
| H, even | earnings 2,600 each; all judgement points true | each award $33.75; `total_award` $101.25 |
| H, nil last | earnings 0, 0, 7,800; all true | awards $1,228.90, $1,228.90, $0; `entitled_3` false; `surplus_after_3` $2,638.64; `total_award` $2,457.80 |
| H, reclaim | earnings 7,800, 2,000, 2,000; all true | award_1 $0, `surplus_after_1` $2,638.64; `earnings_used_2` $4,638.64, award_2 $0, `surplus_after_2` $0; award_3 $363.75 |
| H, failed month not a claim | as the reclaim case, `claim_each_month` false | `surplus_after_2` $2,638.64; award_3 $0 |
| H, no claim | as the reclaim case, `claim_after_end` false | award_2 and award_3 $0; `surplus_after_3` $2,638.64 |
| H, LCW lost | as the reclaim case, `lcw_carries_over` false | award_3 $128.90 |
| Ends twice | aged 25 or over, no LCW, housing $0; earnings 3,000, 0, 3,000; all true | award_1 $0, `surplus_after_1` $0; award_2 $424.90; award_3 $0 |
| Step, £300 | `WindowStep`: start 2027-04-01, live, earnings $3,000, aged 25 or over, no LCW, housing $0 | `nil_uc_threshold` $772.55; `relevant_threshold` $1,072.55; `surplus_next` $1,927.45 |
| Step, £2,500 | as above, start 2027-03-31 | `relevant_threshold` $3,272.55; `surplus_next` $0 |
| Step, sixth month | `WindowStep`: not live, `months_since_end` 6, surplus $100, earnings $0, `claim_after_end` true | `award` $0; `surplus_next` $100; `months_since_end_next` 7 |

- [ ] **Step 2: Run** `make build`, then `opam exec -- clerk test`. Expected: the new tests FAIL (the scopes do not exist yet).
- [ ] **Step 3: Write the scopes,** then extend `make export`.
- [ ] **Step 4: Run** `make test`. Expected: all pass, and the four new IR files exist.
- [ ] **Step 5: Commit:** `Add the window rules for nil assessment periods`.

### Task 4: Window inputs and labels

**Files:**
- Create: `rules/claim_window.inputs.toml`
- Modify: `src/bm/inputs.py`, `src/bm/strategic.py` (`cases`)
- Test: `tests/test_inputs.py`, `tests/test_strategic.py`

**Interfaces:**
- Consumes: Task 3's IR files.
- Produces:
  - `InputSpec.applies_when: str | None` (default None).
  - `inputs.load(path, scope)` accepts `per_period = true` on a money, date or integer input named `<base>`, and matches it to the scope's inputs `<base>_1`, `<base>_2` and so on, each with the same bounds and labels. A per-period entry that matches no scope input is refused.
  - `strategic.cases(specs, points, cap)` skips combinations in which a point's `applies_when` is false, fixing that point to False. `bm.window.DEFAULT_CASE_CAP = 12`.

The TOML gives `start` (per period; min 2026-04-06, max 2027-03-31; `controlled_by = ["claimant"]`, `checked_by = "dwp_records"`), `earnings` (per period; as `earned_income` in `uc.inputs.toml`), the three household facts as in `uc.inputs.toml`, and the three judgement points with the labels in the spec's table. `lcw_carries_over` has `applies_when = "has_lcw"`, and `claim_each_month` has `applies_when = "claim_after_end"`. The comments say why each is labelled as it is, citing the spec's readings.

- [ ] **Step 1: Write the failing tests:**

```python
def test_window_inputs_expand_per_period():
    specs = load(WINDOW_TOML, window_scope)
    assert [n for n in specs if n.startswith("earnings_")] == ["earnings_1", "earnings_2", "earnings_3"]
    assert specs["start_3"].bound.max == units.days(date(2027, 3, 31))

def test_window_cases_are_nine():
    specs = load(WINDOW_TOML, window_scope)
    assert len(cases(specs, judgement_points(specs, {}), cap=12)) == 9

def test_fixing_has_lcw_false_leaves_three_cases():
    specs = load(WINDOW_TOML, window_scope)
    points = judgement_points(specs, {"has_lcw": False})
    assert len(cases(specs, points, cap=12)) == 3

def test_shared_inputs_carry_the_same_labels():
    window, uc = load(WINDOW_TOML, window_scope), load(UC_TOML, uc_scope)
    pairs = {n: n for n in ("aged_25_or_over", "housing_costs_element", "has_lcw")}
    pairs |= {f"earnings_{k}": "earned_income" for k in (1, 2, 3)}
    pairs |= {f"start_{k}": "assessment_period_start" for k in (1, 2, 3)}
    for w, u in pairs.items():
        assert (window[w].controlled_by, window[w].checked_by) == (uc[u].controlled_by, uc[u].checked_by)
```

Plus refusals: `per_period` on a Boolean, a per-period entry with no matching inputs, an `applies_when` naming an unknown input or one that is not a Boolean judgement point.

- [ ] **Step 2: Run** `uv run pytest tests/test_inputs.py tests/test_strategic.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement,** and write the TOML.
- [ ] **Step 4: Run** `make test-fast`. Expected: all pass. Milestone 2's cases are unchanged, since `uc.inputs.toml` has no `applies_when`.
- [ ] **Step 5: Commit:** `Add window inputs with per-period and conditional judgement points`.

### Task 5: Translator: rates, relaxed mode and agreement on the window

**Files:**
- Modify: `src/bm/translate.py`, `src/bm/solvers.py`
- Test: `tests/test_translate.py`, `tests/test_agreement.py`

**Interfaces:**
- Consumes: Task 3's IR.
- Produces:
  - `translate.translate(scope, relaxed: bool = False) -> SmtModule`. When `relaxed`, money is sort `Real`, `bm_round` is the identity, and `SmtModule.relaxed` is True.
  - `optimise_and_confirm(..., sort: Literal["Int", "Real"] = "Int")`. With `Real` the objective is declared `Real`, targets stay integers, and the value is the largest integer the search proves reachable. Model values may be `Fraction`.

- [ ] **Step 1: Write the failing tests:**
  - `test_mult_by_20_over_11_matches_catala_rounding`: translate a one-definition IR, `m * 20/11`. For m in {0, 1, 5, 6, 122890, 10**6} and their negatives, both Z3 and cvc5 give round-half-away-from-zero of m × 20/11. Compare with `Fraction` arithmetic in the test.
  - `test_mult_by_11_over_20_ties`: as above for 11/20, with m = 10, 30 and -10 (exact half pennies).
  - `test_relaxed_has_no_rounding`: the relaxed module of `m * 11/20` at m = 10 gives exactly 11/2.
  - `test_claim_window_agrees_with_catala` (marked `slow`): Catala and Z3 agree on every output of `ClaimWindow` for households generated near the thresholds. Generate them in Python: earnings in each period of the nil UC threshold ± 1p and the relevant threshold ± 1p (read from Catala's `nil_uc_threshold_1` and `relevant_threshold_1` outputs for the household, through `catala_run.outputs`), crossed with the age, LCW and housing values {0, 1p, 804} and every judgement case. At least 60 households. Every one with a nil period and a surplus is counted, and the test asserts at least 10 of each.
- [ ] **Step 2: Run** `uv run pytest tests/test_translate.py -v`. Expected: the relaxed test FAILS. The rate tests should pass already (ruling 1). If one fails, stop and report it, because it reverses the ruling.
- [ ] **Step 3: Implement** `relaxed` and the `Real` objective.
- [ ] **Step 4: Run** `make test`. Expected: all pass.
- [ ] **Step 5: Commit:** `Pin rate rounding, and add a relaxed translation for probes`.

### Task 6: Independent reference for the window

**Files:**
- Modify: `tests/reference_uc.py`
- Test: `tests/test_reference.py` (new)

Written from the regulation text and the spec's readings, not from the Catala. It shares nothing with the translator or `bm.window`.

**Interfaces:**
- Produces, in `tests/reference_uc.py`:
  - `nil_uc_threshold(aged_25: bool, lcw: bool, housing: int) -> int`: M × 20/11 rounded half up, which is `(40 * M + 11) // 22` for M ≥ 0, plus the work allowance.
  - `relevant_threshold(start: date, aged_25, lcw, housing) -> int`: plus 250,000 on or before 2027-03-31, and 30,000 after.
  - `PeriodTrace` (frozen dataclass): `earnings_used`, `award`, `entitled`, `surplus_after`.
  - `window(earnings: list[int], starts: list[date], aged_25: bool, lcw: bool, housing: int, claim_after_end: bool, claim_each_month: bool, lcw_carries_over: bool) -> list[PeriodTrace]`.
  - `even_split(total: int, periods: int) -> list[int]`: the remainder goes to the earliest periods.
  - `figure_value(figure: str, copies: dict[str, list[int]], starts, aged_25, lcw, housing, case: dict[str, bool]) -> int | None`: the figure for given copies' earnings (keys as Task 7's copy names), or None where a copy breaks the last-period rule as Task 8 applies it.
  - `brute_force(figure: str, total: int, step: int, starts, aged_25, lcw, housing, case: dict[str, bool]) -> int`: the best `figure_value` over every split of `total` into multiples of `step` pence (the even copy exact).

- [ ] **Step 1: Write the failing tests:** every row of Task 3's table that involves `ClaimWindow`, through `window`, with the same values. Also `even_split(100_000, 3) == [33_334, 33_333, 33_333]`.
- [ ] **Step 2: Run** `uv run pytest tests/test_reference.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit:** `Add an independent reference for the claim window`.

### Task 7: Window query: gain and loss

**Files:**
- Create: `src/bm/window.py`, `tests/test_window.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 4 and 5; `Script`, `Instance` and `smt_sum` from `bm.household`; `QueryRefused`, `NoHousehold`, `ReplayMismatch`, `cases`, `judgement_points` and `period_starts` from `bm.strategic`; `catala_run.outputs`.
- Produces, in `bm.window`:

```python
SCOPE = "ClaimWindow"
DEFAULT_CASE_CAP = 12
LAST_START = date(2027, 3, 31)
FIGURES = ("gain", "loss", "spread", "extra_payday_max", "extra_payday_min")
REALISTIC = {"claim_after_end": True, "claim_each_month": True, "lcw_carries_over": True}

@dataclass(frozen=True)
class PeriodTrace:
    earnings: int; earnings_used: int; award: int; entitled: bool
    surplus_after: int; nil_uc_threshold: int; relevant_threshold: int

@dataclass(frozen=True)
class CopyWitness:
    copy: str                       # "split", "even", "a", "b" or "payday"
    inputs: dict[str, int | bool]   # every ClaimWindow input, in SMT units
    trace: list[PeriodTrace]

@dataclass(frozen=True)
class Figure:
    value: int | None
    status: Literal["optimal", "unknown", "infeasible"]
    lower_bound: bool
    witnesses: list[CopyWitness]

@dataclass(frozen=True)
class CaseResult:
    case: dict[str, bool]
    realistic: bool
    figures: dict[str, Figure]

@dataclass(frozen=True)
class WindowResult:
    status: Literal["optimal", "unknown"]
    periods: int
    probe: bool
    relaxed: bool
    starts: list[int]
    total: int | None
    fixed: dict[str, int | bool]
    cases: list[CaseResult]        # realistic case first
    excluded: list[str]            # plain-text notes of what the last-period rule excluded
    verification: dict[str, str | list[str]]
    versions: dict[str, str]

def periods_of(module: SmtModule) -> int
def window(module: SmtModule, specs: dict[str, InputSpec], *, first_start: date = DEFAULT_START,
           total: int | None = None, fixed: dict[str, int | bool] | None = None,
           figures: tuple[str, ...] = FIGURES, probe: bool = False,
           cap: int = DEFAULT_CASE_CAP, timeout_ms: int = 60_000) -> WindowResult
def replay(rules: Path, result: WindowResult) -> None
```

This task implements `gain` and `loss`. Task 8 adds the rest. Requesting a figure that is not yet implemented raises `NotImplementedError`.

**The script for one figure in one case:**
- One `Script(module, bounds(specs))`.
- Shared facts, as `strategic._facts` declares them (move it to `bm.household` as a public `facts(...)` if both modules need it).
- The case's judgement values, and starts fixed to `period_starts(first_start, specs["start_1"].bound, n)`.
- `whole` = the total, fixed or free within n × the earnings bound.
- The copies, all with the same facts, case and starts:
  - **split:** free `earnings_<k>` that sum to `whole`;
  - **even:** `earnings_<k>` = `(div whole n)` plus 1 when k ≤ `(mod whole n)`.
- Each copy's award in the last period is declared as a constant and asserted ≥ 1, except where Task 8's lower-bound rule removes it.
- Objective: gain = `total_award`(split) − `total_award`(even); loss = the reverse. Run `optimise_and_confirm` with "max".

**Refusals, before any solver runs:**
- `periods_of(module) > 3` without `probe`;
- `relaxed` (from `module.relaxed`) without `probe`;
- a start after `LAST_START`, or outside the bounds;
- more cases than the cap.

If the even copy alone is infeasible for a fixed household and total, raise `NoHousehold`, saying that the even split ends the window at nil.

**Replay.** For each witness, `catala_run.outputs(rules, SCOPE or the probe scope, inputs)`. Every `award_<k>`, `surplus_after_<k>` and `earnings_used_<k>` must equal Z3's, or `ReplayMismatch`. Skipped, and recorded as skipped in `verification`, for relaxed runs.

- [ ] **Step 1: Write the failing tests** in `tests/test_window.py`:
  - `test_gain_and_loss_never_negative` (fixed household H from Task 3, `--total` free): both are `optimal` and ≥ 0.
  - `test_even_split_remainder` (Review Focus 1): with total 100,000 fixed, the even witness's earnings are [33_334, 33_333, 33_333].
  - `test_even_split_ending_at_nil_is_refused` (Review Focus 2): `NoHousehold`.
  - `test_start_after_31_march_2027_is_refused` (Review Focus 3): `first_start=date(2027, 2, 1)` raises `QueryRefused` naming 2027-03-31.
  - `test_no_claim_and_last_period_rule_reduce_to_above_nil`: with `claim_after_end` fixed false, the gain witness has every award ≥ 1p.
  - `test_more_than_three_periods_needs_probe`: the `ClaimWindow4` IR without `probe` raises `QueryRefused`.
  - `test_replay_agrees` (marked `slow`): the realistic case's gain, with H fixed and total free, replays without mismatch.
  - `test_gain_matches_reference` (marked `slow`), for H and total £7,800.00 in the realistic case: (a) the solver's gain is at least `reference_uc.brute_force("gain", 780_000, 1_000, ...)`, since the grid is a subset of the splits; and (b) `reference_uc.figure_value("gain", ...)` at the solver's witness earnings equals the solver's gain exactly. The same for loss.
- [ ] **Step 2: Run** `uv run pytest tests/test_window.py -m "not slow" -v`. Expected: FAIL (no module).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/test_window.py -v`. Expected: all PASS.
- [ ] **Step 5: Commit:** `Add the window query for gain and loss`.

### Task 8: Window query: spread, extra payday and lower bounds

**Files:**
- Modify: `src/bm/window.py`, `tests/test_window.py`

**Interfaces:**
- Consumes: Task 7's interfaces.
- Produces the remaining `FIGURES`:
  - **spread:** copies "a" and "b", both free splits of `whole`. The objective is `total_award`(a) − `total_award`(b).
  - **extra_payday_max** and **extra_payday_min:** a "payday" copy with earnings (P, 2P, P) for a free P within the earnings bound, and the even copy with `whole` = 4P. The objective is `total_award`(even) − `total_award`(payday), maximised and minimised. Only for 3 periods: refused for longer windows.
  - **The lower-bound rule** (spec, window limits; ruling 5). In a case with `claim_after_end` false, the copy whose award is subtracted drops the last-period rule: "split" in loss, "b" in spread, and "payday" in `extra_payday_max`. That `Figure` has `lower_bound=True`. The even copy keeps the rule in every case.

- [ ] **Step 1: Write the failing tests:**
  - `test_spread_at_least_gain_and_loss`: for H with a fixed total, spread ≥ max(gain, loss).
  - `test_extra_payday_linear_case`: for a household with no LCW and housing 0, with P limited so that every period stays above nil (fix the total, which fixes P = total / 4), |`extra_payday_max`| ≤ 3 and |`extra_payday_min`| ≤ 3.
  - `test_no_claim_figures_are_lower_bounds` (Review Focus 4): with `claim_after_end` fixed false, loss, spread and `extra_payday_max` have `lower_bound` True, and gain and `extra_payday_min` False.
  - `test_realistic_case_first`: `result.cases[0].realistic` is True when the realistic case is among the cases.
  - `test_spread_and_payday_match_reference` (marked `slow`): as Task 7's reference test, for spread and `extra_payday_max`. For the payday figure, `brute_force` ranges over P in steps of `step` instead of over splits. Also in a case with `claim_after_end` false, so the lower-bound rule is exercised.
- [ ] **Step 2: Run** `uv run pytest tests/test_window.py -m "not slow" -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/test_window.py -v`. Expected: all PASS.
- [ ] **Step 5: Commit:** `Add spread, extra payday and lower-bound figures to the window query`.

### Task 9: Report and CLI for the window query

**Files:**
- Modify: `src/bm/cli.py`, `src/bm/report.py`, `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `bm.window.window`, `bm.window.replay`, `WindowResult`.
- Produces:
  - `bm query window IR --inputs TOML [--rules FILE] [--total £] [--start DATE] [--fix NAME=VALUE ...] [--cap 12] [--probe] [--relaxed] [--timeout-ms 60000] [--json]`;
  - `report.window_json(result, provenance) -> dict` and `report.window_text(result) -> list[str]`.
- **Text output:**
  - the realistic case first, with each figure in pounds and "at least" before a lower bound;
  - the excluded notes;
  - a witness trace table (each period's earnings, earnings used, award, entitlement and surplus), with labels for each input;
  - "PROBE: not a finding" at the top of a probe run;
  - three caveat lines: passported help is not modelled; reported earnings are taken as exact; figures depend on the £2,500 level, which ends on 31 March 2027, and on DWP's practice of checking income each month after a nil period, both as at 29 October 2026;
  - the pointer to `docs/model-gaps.md`.
- **JSON** as for `timing`, with `"probe"`, `"relaxed"` and the top-level `"unknown"` flag.
- **Exit status** 0, 1 or 2, as for the other queries.

- [ ] **Step 1: Write the failing CLI tests:** exit status 0 and JSON keys for a fixed, fast household; `--relaxed` without `--probe` exits 1 with a one-line `bm:` error; the `ClaimWindow4` IR without `--probe` exits 1; with `--probe` the text starts with "PROBE"; a solver disagreement (monkeypatched) exits 1; an unknown (monkeypatched) exits 2.
- [ ] **Step 2: Run** `uv run pytest tests/test_cli.py -m "not slow" -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement,** and add the command to the README's usage section.
- [ ] **Step 4: Run** `make test-fast`. Expected: all pass.
- [ ] **Step 5: Commit:** `Add the window command and report`.

### Task 10: Scaling probe

**Files:**
- Create: `scripts/probe_window.py`, `docs/spike-window-scaling.md`, `tests/test_probe.py`
- Modify: `Makefile` (`probe` target), `src/bm/solvers.py`

**Interfaces:**
- Consumes: `bm.window.window` with `probe=True`; `translate(scope, relaxed=True)`.
- Produces:
  - `solvers.run(..., seed: int | None = None)` and `optimise_and_confirm(..., seed: int | None = None)`, which set Z3's `smt.random_seed` and cvc5's `seed`;
  - `scripts/probe_window.py` writes `build/probe-window.json`: one row per (periods 3 to 6, exact or relaxed, seed 1 to 5, figure gain or loss, realistic case), with wall time, the number of Z3 checks, the status and the value. It uses first start 2026-04-06 and a fixed household H.

- [ ] **Step 1: Write the failing test** `test_probe_runs_at_four_periods` (marked `slow`): the script's function for one row, at 4 periods exact with seed 1, returns status "optimal".
- [ ] **Step 2: Implement** the seed parameter, the script and `make probe`.
- [ ] **Step 3: Run** `make probe` (in the background; it may take a long time). Expected: a JSON file with 80 rows, none failed. A row may be *unknown* within its timeout. Record that as data, not as a failure.
- [ ] **Step 4: Write `docs/spike-window-scaling.md`:** the question, the method, a table of median and maximum time by periods and mode, the observations, what they suggest for later window lengths (relax-then-confirm, slicing), and the limits (one household, one machine, named versions). Date it.
- [ ] **Step 5: Commit:** `Add a scaling probe for the claim window`.

### Task 11: Research note on nil assessment periods

Independent of Tasks 1 to 10. It can run in parallel from the start, in its own worktree.

**Files:**
- Create: `docs/nil-months.md`

**Inputs:** the controller passes three research notes (legal readings, the check of them, and practice and policy). They are in the controller's scratchpad, outside the repository.

- [ ] **Step 1: Check at source** every practice claim the note will make that the spec does not already cite as checked: guide versions and quotations, written answer figures, and the research and advocacy findings. Record any that cannot be reached, and leave them out or mark them.
- [ ] **Step 2: Write `docs/nil-months.md`.** Write it as one note, not three: what the law says (with confidence labels), what the check corrected, what practice shows, what remains unresolved, and where the model draws its lines. Every claim has a source, a date checked and its kind (law, official guidance, research, advocacy). It describes rules and classes of claimant only. No guidance on timing pay or presenting a claim. Neutral wording, British English, no em-dashes.
- [ ] **Step 3: Have a fresh reviewer read it** against the publishing rules in the brief and the Career hostile-check rule (every claim must survive a sceptical reader with a search engine). Fix what they find.
- [ ] **Step 4: Commit:** `Add a research note on nil assessment periods`.

### Task 12: Findings and documentation

**Files:**
- Modify: `docs/model-gaps.md`, `docs/v2-brief.md`, `docs/mismatches.md`, `AI-DECLARATION.md` (if the way of working changed), `README.md`

- [ ] **Step 1: Run the finding.** `uv run bm query window build/claim_window.bm-ir.json --inputs rules/claim_window.inputs.toml --json`, with the household free and the default start (in the background if slow). Keep the JSON in `build/`. Every figure must be `optimal`, or recorded as *unknown*.
- [ ] **Step 2: `docs/model-gaps.md`:**
  - the surplus entry becomes "modelled within the window's limits", with those limits;
  - new entries: regulation 61(6); the window's limits; a chain of claims crossing 31 March 2027; the reading of which M and WA apply; and the three judgement points with their realistic case;
  - the milestone 3 findings and their conditions under strategic findings, the realistic case first, each figure in pounds, lower bounds marked;
  - caveats as in Task 9.
- [ ] **Step 3: `docs/v2-brief.md`:**
  - a milestone 3 entry linking the design and plan, with the findings in brief;
  - the research question on nil months marked as answered by `docs/nil-months.md`;
  - the population direction (no population layer of the project's own; scale from cited official statistics; a bridge to PolicyEngine UK as a candidate), with "Estimating impact" and the architecture table updated to match;
  - the translator gap for rates corrected (ruling 1);
  - lines over 100 columns kept on the tidy-up list.
- [ ] **Step 4: `docs/mismatches.md`:** entry 2, a deliberate difference. PolicyEngine UK 2.164.2 computes UC over the year and does not model regulation 54A or the end of an award (ruling 2), so windows with a nil period are not compared.
- [ ] **Step 5: Run** `make test`. Expected: all pass.
- [ ] **Step 6: Commit:** `Record the milestone 3 findings and update the documentation`.

The project `CLAUDE.md` notes on the Superpowers trial are written by the controller after the whole-branch review, as before.
