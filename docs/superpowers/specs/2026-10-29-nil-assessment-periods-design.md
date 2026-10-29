# Milestone 3: nil assessment periods

Design for the third milestone of benefits-modeller v2. It builds on [the brief](../../v2-brief.md), the [milestone 2 design](2026-10-29-first-strategic-query-design.md), the [quantifier spike](../../spike-quantifier-tractability.md), the [mismatch log](../../mismatches.md) and the register of [model gaps](../../model-gaps.md).

Written 29 October 2026. Claims about legislation, guidance and external tools give the date they were checked. Every reading of the law below is the project's own, made from the cited sources by AI research agents and checked at source by a second agent. No welfare rights adviser or social security specialist has reviewed it.

## Goal

Model what happens when earnings push an assessment period to a nil award, and ask how the timing of a fixed total of earnings changes the award over a short window of periods:

labelled inputs → a Catala step scope that carries the award's state from one period to the next → a window scope that chains the steps → an exporter that inlines sub-scopes → Z3 searches, cvc5 confirms → Catala's interpreter replays the witness → a report of the gain, the loss and the spread across timings, for each case of what DWP decides.

Milestone 2 found that, while the award stays above nil, moving pay between two periods gains at most 1p, because the award is concave in earnings. Its lessons put any exposure from timing at nil periods, where the end of an award, the reclaim and surplus earnings apply. Milestone 3 models those rules for a short window. The query runs in two directions:

- **Gain:** how much more the award over the window can be, through timing alone, than with an even split.
- **Loss:** how much less it can be. This is the cost of irregular pay, a finding about the rules rather than about gaming them.

The milestone also measures how solver time grows with the window's length and with rounding, so that later milestones choose a window from evidence.

## Decisions

| Question | Decision |
|---|---|
| What milestone 3 is for | Rules that cross assessment periods at a nil award: the end of the award, the reclaim under regulation 32A, and surplus earnings under regulation 54A |
| What the query measures | Gain, loss and spread over splits of a fixed total of earnings, each against an even split; and the effect of an extra payday for a claimant paid every four weeks |
| Order of work | Legal readings first, checked at source, before the design. Evidence on practice gathered during the design, because it sets which case of each judgement point is realistic. |
| Where the cross-period rules live | In Catala, as a step scope written once and chained by a window scope. The exporter inlines sub-scope calls, so bm-ir keeps its node types. |
| Window length | 3 periods for findings. 4 to 6 periods for a scaling probe only. |
| The end of the window | The award in the window's last period must be at least 1p, so that the effects of a nil period end inside the window (see [the window and its limits](#the-window-and-its-limits)) |
| The surplus earnings threshold | £2,500 above the nil UC threshold. Every period in a finding begins on or before 31 March 2027. The rules hold the £300 figure for later periods, but no finding uses it. |
| DWP's discretions | Judgement points, expanded into cases: whether a claim is made after the award ends, whether a month in which that claim fails still counts as a claim, and whether the LCW finding carries over |
| Rounding | Unchanged. The rules round as reading (a) of the mismatch log. A relaxed translation without rounding exists only for the probe and is never reported as a finding. |

## Scope

### Household

A single claimant with employed earnings reported through Real Time Information (RTI), across 3 consecutive monthly assessment periods. Inputs:

- **Assessment period starts.** One per period. Python computes them from the first, one calendar month apart, as in milestone 2, because a calendar month cannot be written in linear arithmetic.
- **Earnings in each period.** The only input that varies between periods.
- **Age band, housing costs element and limited capability for work (LCW),** as in milestone 2, the same in every period.
- **Three new judgement points,** described under [the rules](#1-rules-rulesuccatala_en).

### The window and its limits

- **The window starts in a live award,** with no surplus carried in.
- **The last period's award must be at least 1p.** Without this rule the solver can put the nil period last, where the end of the award and any surplus fall outside the window, and the gain is overstated. The checking agent found this with the project's rates: for a claimant aged 25 or over, with LCW and a housing costs element of £804, earning £2,600 a period, the split (£0, £0, £7,800) shows a gain of £2,356.55 inside the window. Its true gain is £2,289.05, because the surplus takes the next two periods to nil, and the true maximum over all splits is £2,322.80. With the rule, any surplus is used up inside the window, because a surplus stops once an award is made (see [readings](#readings-this-design-rests-on)). The window's exit state is then the same as the even split's: a live award with no surplus.
- **The exception: no claim after the award ends.** Where no claim is made, the loss continues past the window until a fresh claim, so no window bounds it. In those cases the loss, the spread and the extra payday figure are computed without the last-period rule and reported as lower bounds ("at least"). The gain keeps the rule in every case.
- **Every period begins on or before 31 March 2027,** so the £2,500 threshold applies throughout. This avoids an unresolved question: a chain of claims that crosses that date might, on a literal reading, measure its original surplus again against £300.
- **Excluded splits are reported.** Splits that end the window at nil, and households whose even split does so, are outside the finding, and the report says so.

### Readings this design rests on

Checked on 29 October 2026 against legislation.gov.uk (latest revised versions) and the chapters of DWP's [*Advice for Decision Making*](https://www.gov.uk/government/publications/advice-for-decision-making-staff-guide) (ADM, page last updated 22 October 2026). A research agent made the readings and a second agent checked each at its source. Each is the project's reading, for specialist review.

1. **One nil period ends the award, from its first day.** Entitlement needs an award of at least one penny ([regulation 17](https://www.legislation.gov.uk/uksi/2013/376/regulation/17) of the Universal Credit Regulations 2013; Welfare Reform Act 2012, sections [5](https://www.legislation.gov.uk/ukpga/2012/5/section/5) and [7](https://www.legislation.gov.uk/ukpga/2012/5/section/7)). The supersession takes effect "from the first day of the assessment period in which that change occurred" ([Decisions and Appeals Regulations 2013, Schedule 1](https://www.legislation.gov.uk/uksi/2013/381/schedule/1), paragraph 20). ADM A2050, Example 3, applies this. Clear from the text.
2. **The reclaim is a discretion.** Under [regulation 32A](https://www.legislation.gov.uk/uksi/2013/380/regulation/32A) of the Claims and Payments Regulations 2013, the Secretary of State "may", subject to conditions, treat the claimant as claiming on the first day of each later month that would have been an assessment period, "up to a maximum of 5". The old assessment period dates are kept. The 5 months run from the original nil period (ADM A2050, Examples 2 and 3). A fresh claim within 6 months also keeps the old dates (regulation [21(3C)](https://www.legislation.gov.uk/uksi/2013/376/regulation/21) of the Universal Credit Regulations; Claims and Payments [regulation 26(5)](https://www.legislation.gov.uk/uksi/2013/380/regulation/26)).
3. **Whether a failed month counts as a claim is also part of the discretion.** ADM A2050 Example 3 treats a claim only in the month in which entitlement arises, while Example 4 treats one in each month. This changes how far a surplus is worn down (reading 4), so it is a judgement point.
4. **Surplus earnings** ([regulation 54A](https://www.legislation.gov.uk/uksi/2013/376/regulation/54A); ADM H3300 to H3314 and H3 Appendix 2):
   - The original surplus is the nil period's earnings above the relevant threshold.
   - On each later claim, the surplus is added to that claim's first period's earnings. If no award results, only the excess over the relevant threshold carries on to the next claim.
   - It stops at the fifth claim, or once an award is made. Nothing carries into later periods of a new award.
   - Intervening months that are not claims do not wear it down.
   - The rule does not apply to a claimant who has recently been a victim of domestic violence (paragraph (5)). The model does not represent that condition.
5. **The nil UC threshold** is (M − U) / 55 × 100 + WA, where M is the maximum amount, U is unearned income and WA is the work allowance (regulation 54A(6); ADM H3308). The work allowance is not scaled. With no unearned income it is M × 20/11 + WA. The rules compute it as one amount, rounded once to the penny, as the ADM's worked example does (H3 Appendix 2, Example 1). Which period's M and WA apply is not stated. The rules use the values for the period of the claim being decided. Unresolved.
6. **The relevant threshold** is the nil UC threshold plus £2,500 for a claim in respect of a period beginning before the end of the temporary de minimis period, which ends on 31 March 2027 (S.I. 2015/345, [regulation 5](https://www.legislation.gov.uk/uksi/2015/345/regulation/5); the Secretary of State's [determination](https://www.gov.uk/government/publications/secretary-of-state-determination-under-regulation-5-of-the-universal-credit-surpluses-and-self-employed-losses-digital-service-amendment-regulatio--2/secretary-of-state-determination-under-regulation-5-of-the-universal-credit-surpluses-and-self-employed-losses-digital-service-amendment-regulatio), made 20 January 2026; ADM H3310, "ending on 31.03.27"). Otherwise it is the nil UC threshold plus £300. That a period beginning on 31 March 2027 itself takes £2,500 is the project's inference, as already recorded in [model gaps](../../model-gaps.md).
7. **The LCW finding carrying over** to a new award within 6 months rests on DWP's "Re-claims" staff guide (V11.0, deposited in Parliament as [DEP2024-0442](https://data.parliament.uk/DepositedPapers/Files/DEP2024-0442/138._Reclaims_V11.0.pdf); V8.0 of 2022 has the same wording), which says a determination "remains valid" if the condition has not changed and the review date has not passed. Neither [regulation 39](https://www.legislation.gov.uk/uksi/2013/376/regulation/39) nor the ADM says so. It is a judgement point.
8. **Regulation [61(6)](https://www.legislation.gov.uk/uksi/2013/376/regulation/61),** substituted from 16 November 2020 by S.I. 2020/1138 after *SSWP v Johnson* [2020] EWCA Civ 778, lets the Secretary of State treat one of two payments reported in one assessment period as earnings of another period, for a person "paid on a regular monthly basis". For such claimants, a timing finding that puts two monthly payments in one period holds only if the discretion is not used. It does not cover weekly, fortnightly or four-weekly pay. Not modelled; recorded in model gaps.
9. **The open account.** DWP keeps the account open through nil periods and closes it after 6 consecutive nil periods (see [what practice says](#what-practice-says)). The project reads the open account as how DWP administers regulation 32A, not as an award that continues at nil.

### What practice says

Gathered on 29 October 2026 by a research agent from official, research and advocacy sources. Two load-bearing sources were checked at source the same day: written answer 74834 and the explanatory memorandum to S.I. 2026/946. The rest is checked at source when `docs/nil-months.md` is written (see [Documentation](#documentation)). Each source is tagged by kind there.

- **The reclaim is automatic in practice.** DWP checks income each month for the 5 assessment periods after the nil period and pays again once the award is above nil. The claimant does not reclaim. The [explanatory memorandum](https://www.legislation.gov.uk/uksi/2026/946/pdfs/uksiem_20260946_en_001.pdf) to S.I. 2026/946 (DWP, September 2026) calls this the "automatic reclaim period", and says that afterwards a new claim is needed. DWP's "Claim closure" guide V35.0 ([DEP2025-0769](https://data.parliament.uk/DepositedPapers/Files/DEP2025-0769/032_Claim_closure_Guidance_V35.pdf), deposited 24 November 2025) closes the account after 6 consecutive nil periods. Before May 2020 a nil period closed the claim. University of Bath research describes earlier closures that forced a full new claim, but does not date them (Griffiths and Wood, [*Coping and hoping*](https://www.bath.ac.uk/publications/coping-and-hoping-navigating-the-ups-and-downs-of-monthly-assessment-in-universal-credit/), April 2024). No figures on failed reclaims were found.
- **The LCW finding carries over in practice** if entitlement returns within 6 months, the health condition has not changed and the review date has not passed. After 6 months a new Work Capability Assessment is needed (DWP "Re-claims" guide V11.0, [DEP2024-0442](https://data.parliament.uk/DepositedPapers/Files/DEP2024-0442/138._Reclaims_V11.0.pdf), 2024).
- **Nil periods are common.** 464,000 households had their award reduced to £0 by earnings in assessment periods ending 26 April to 25 May 2022, about 1 in 10 UC households then (written answer 74834, 8 November 2022). No figures on repeated nil periods were found. DWP put the share of claimants with earnings hit by surplus earnings at the £2,500 level at "less than one per cent" (letter to SSAC, May 2020). Both figures are from before 2023 and may be stale.
- **The realistic class is pay that is not monthly.** Four-weekly pay gives one assessment period a year with two paydays, fortnightly pay two, and weekly pay four. Regulation 61(6) does not reallocate these. 10% of in-work claimants who are not self-employed are paid four-weekly (written answer 66811, 17 July 2025). For these claimants a nil period can arise with no change in pay at all. *R (Pantellerisco) v SSWP* upheld the rules for four-weekly pay in the Court of Appeal (2021), and the Supreme Court refused permission to appeal (2022).
- **Regulation 61(6) is partly automated** for calendar-monthly pay, with a small number of cases handled by hand (written answers, November 2025 and April 2026). No count of cases was found.
- **What the award does not show.** A nil period can also cost passported help (free prescriptions, Healthy Start, Council Tax Support), which depends on receiving UC in a single assessment period (Citizens Advice, [*A better fit*](https://www.citizensadvice.org.uk/policy/publications/a-better-fit-how-universal-credit-can-improve-income-stability-for-employees/), August 2025). The model counts the UC award only.
- **Policy direction.** The £2,500 level has been extended one year at a time and ends on 31 March 2027, with nothing announced for later. Regulation 32A was extended in September 2026 for funded employment schemes. DWP has said it has no plans to change assessment periods.

**What this sets in the design:**

- **The realistic case** is `claim_after_end` true, `claim_each_month` true and, where the claimant has an LCW finding, `lcw_carries_over` true. The report names it and gives its figures first. The other cases are stress cases: the account closed early, failed months not counted as claims, or the LCW finding lost.
- **An extra payday figure** for the realistic class (see [Window query](#5-window-query-bmwindow)).
- **Caveats** on every finding: passported help is not modelled; reported earnings are taken as exact, although RTI reports can be late or wrong; and findings that depend on the £2,500 level or on the 6-period closure practice are dated.

## Components

### 1. Rules: `rules/uc.catala_en`

New sections after the per-period rules, each with the regulation text it implements, as now. They stay in the module `Uc`, because a call across modules would reach the exporter as an external reference, a second new construct.

**`WindowStep`**, written once. It works out one period, given the state the previous period left.

- **Inputs:**
  - the incoming state: `live` (the award continues into this period), `surplus` (money carried in) and `months_since_end` (0 in a live award; otherwise this period's number of months after the nil period);
  - this period's start date and earnings;
  - the household facts: `aged_25_or_over`, `housing_costs_element` and `has_lcw`;
  - the judgement points: `claim_after_end`, `claim_each_month` and `lcw_carries_over`.
- **A claim** is made in a period after the end when `claim_after_end` holds and `months_since_end` is between 1 and 5.
- **The LCW finding used** is `has_lcw` in a live award, and `has_lcw and lcw_carries_over` after the end.
- **Earnings used** are the period's earnings, plus the incoming surplus when a claim is made after the end.
- **The period's figures** come from a sub-scope `period scope UniversalCredit`, called with the earnings used and the LCW finding used.
- **The award** is the sub-scope's award in a live award or when a claim is made, and £0 otherwise. **Entitled** means an award of at least 1p, tested on the award itself rather than on the threshold, since the boundary lies about a penny below the threshold.
- **The thresholds.** The nil UC threshold is the sub-scope's `maximum_amount` × (100 / 55), rounded once, plus its `work_allowance`. The relevant threshold adds £2,500 for a period beginning on or before 31 March 2027 and £300 for a later one.
- **The outgoing state:**
  - `live` next is `entitled`.
  - `months_since_end` next is 0 if entitled, 1 if this period ended a live award, and one more than now otherwise.
  - `surplus` next is:
    - £0 if entitled;
    - max(£0, earnings − relevant threshold) if this period ended a live award (the original surplus);
    - after the end, when a claim was made and failed: max(£0, earnings used − relevant threshold) if `claim_each_month` holds, and the incoming surplus unchanged if it does not;
    - after the end with no claim: the incoming surplus unchanged.
- **Outputs:** `award`, `entitled`, `earnings_used`, `nil_uc_threshold`, `relevant_threshold`, and the outgoing state.

A second nil period after a new award starts both chains again, because entitlement resets the state. The 5-month limit is a rule in the step, so a window longer than 3 periods needs no new rules.

**`ClaimWindow`** chains `step_1` to `step_3`. The first step's state is live, with no surplus and `months_since_end` of 0. Each later step takes the previous step's outgoing state. Its outputs are each step's figures and `total_award`, the sum of the three awards.

**`ClaimWindow4`, `ClaimWindow5` and `ClaimWindow6`** chain 4, 5 and 6 steps over the same `WindowStep`. They exist for the scaling probe only.

**Tests (`rules/uc_tests.catala_en`, run by `clerk test`):**

- `WindowStep`, one test per state transition: a live award that continues, a live award that ends, a claim that succeeds with a surplus, a claim that fails with `claim_each_month` true and with it false, no claim, the sixth month after the end (no claim possible), and the £300 threshold for a period beginning after 31 March 2027.
- `ClaimWindow`: households built on the structure of ADM H3 Appendix 2 and A2050 Example 4, with figures recomputed by hand at 2026/27 rates; the £7,800 household above, whose window gives £2,356.55 more than the even split before the last-period rule excludes it; and a window in which the award ends twice.

### 2. Inputs and labels: `rules/claim_window.inputs.toml`

One file for every window scope, read by the existing loader with two additions:

- **`per_period = true`** marks an input with one value per period, such as earnings and the start date. The loader expands it to `earnings_1`, `earnings_2` and so on, for the scope's length, with the same bounds and labels.
- **`applies_when = "<name>"`** marks a judgement point that matters only when another Boolean judgement point is true. Case expansion skips combinations in which it does not apply. `lcw_carries_over` applies when `has_lcw`, and `claim_each_month` applies when `claim_after_end`. That gives 9 cases, not 16.

The new judgement points:

| Input | `controlled_by` | `checked_by` |
|---|---|---|
| `claim_after_end` | `decision_maker`, `claimant` | `dwp_records` |
| `claim_each_month` | `decision_maker` | `dwp_records` |
| `lcw_carries_over` | `decision_maker` | `assessment` |

`claim_after_end` names both parties because a treated claim is DWP's discretion and a fresh claim is the claimant's act. It counts as a judgement point, because `decision_maker` is among its controllers.

A test checks that every input shared with `uc.inputs.toml` (age, housing, LCW, and each period's earnings and start against `earned_income` and `assessment_period_start`) has the same labels. The first start date's upper bound is set so that the third period begins on or before 31 March 2027.

### 3. Exporter and bm-ir version 1

In Catala 1.3.0's default calculus a declared sub-scope appears as a scope variable definition of the sub-scope's struct type, whose expression applies the sub-scope's function to its input struct. Later uses are struct accesses on that variable. The exporter refuses this today, at the application. Checked on 29 October 2026 with throwaway probes (the plan, ruling 3).

- **Inlining.** On such a definition, the exporter finds the called scope's body in the same program and walks it with the existing walker, prefixing every name with the sub-scope's name (`step_1.period.award`). Each of the sub-scope's inputs becomes a definition whose expression is the caller's argument. Field accesses such as `step_1.award` become references to the prefixed definitions. Inlining nests, so a window, its steps and their `UniversalCredit` periods export as one flat list.
- **Still refused,** with the existing "Unsupported construct" error: the direct form `output of <Scope> with { ... }`, calls across modules, and recursion.
- **bm-ir version 1.** The node types do not change. `inputs` holds the top scope's inputs only. `definitions` includes the prefixed definitions of sub-scopes, still in dependency order. The version changes because a name no longer has to be a variable of the top scope. `docs/bm-ir.md` documents the naming rule.
- **`make export`** also writes `build/claim_window.bm-ir.json` and the three probe scopes. The `UniversalCredit` export is unchanged, for the milestone 1 and 2 queries and the differential check.
- **Tests (dune):** a sub-scope nested in a sub-scope, two instances of one sub-scope in one scope, and a refusal of the direct form.

### 4. Translator

- **Prefixed names** are valid SMT-LIB symbols as they stand.
- **Rates with no terminating decimal form.** Money times p/q is written as `bm_round` of an exact product with the constant `(/ p.0 q.0)`. The brief records that Z3's linearity check rejects that form for such rates, which the nil UC threshold (× 20/11) needs. Checked at plan time on 29 October 2026, Z3 5.3.2 and cvc5 1.4.2 both accept it with plain checks, so the encoding stays, pinned by tests, and the brief is corrected (the plan, ruling 1).
- **`--relaxed`** (probe only) replaces `bm_round` with exact rational arithmetic, so money is real-valued. The provenance records "relaxed, not the rules". No query reports a relaxed result as a finding.
- **Tests:** `bm_round` with 20/11 and 11/20, against Catala's interpreter, across signs and half-penny ties. The agreement test between Catala and Z3 covers `ClaimWindow`.

### 5. Window query: `bm.window`

A new module, because `bm.strategic` is already 568 lines. It reuses the household builder in `bm.household`, `optimise_and_confirm` in `bm.solvers`, and case expansion. Milestone 2's `timing` query stays as it is: it is the special case of two periods above nil.

**What the caller gives:** an optional total of earnings, an optional first start date (6 April 2026 by default, as in milestone 2), optional fixed household facts, and the window scope's IR (3 periods, or 4 to 6 for the probe).

**Copies.** One script holds several copies of the window for the same household and total. "Even" is the split as even as possible to the penny, with the remainder in the earliest periods.

| Figure | Objective, maximised over households, totals and splits |
|---|---|
| Gain | total award(split) − total award(even) |
| Loss | total award(even) − total award(split) |
| Spread | total award(split A) − total award(split B) |
| Extra payday | total award(even) − total award(P, 2P, P), maximised and minimised over households and the payday amount P |

The extra payday figure is not a free split. It is the pattern a claimant paid every four weeks has when two paydays fall in one assessment period, compared with the same four payments spread evenly. It answers what that pattern costs, or gains, for a class of claimant whose pay does not change.

Every copy, the even split included, has an award of at least 1p in its last period, except as set out under [the window and its limits](#the-window-and-its-limits) for cases with no claim after the end. Every copy asserts that no obligation holds, as every query does.

**Cases.** Each of the 9 cases is optimised in its own script, so the cost grows linearly with the number of cases. The cap for this query is 12. The report gives each case's gain, loss, spread and extra payday figure, the realistic case first (see [what practice says](#what-practice-says)), and the largest and smallest of each across cases.

**Checks:**

1. `optimise_and_confirm`: Z3 searches with plain checks, and cvc5 confirms that no larger value exists.
2. **Replay.** The witness for each figure is run through Catala's interpreter on the window scope. Every period's award and surplus must match Z3's to the penny. Any difference stops the run as a translator bug.
3. **Tests only: an independent reference.** `tests/reference_uc.py` gains the window chain, written from the regulation text and not from the Catala. A brute-force search over a coarse grid of splits and households must agree with the solver's optima, and with every figure in the witness trace.

### 6. Report and CLI

- `bm query window IR [--total £] [--start DATE] [--fix NAME=VALUE ...] [--probe] [--relaxed]`. The window's length is read from the IR (the plan, ruling 4).
- **The result** records the query, the cases, the fixed facts, the start dates, the figures for each case, and a witness trace for each figure: each period's earnings, earnings used, award, entitlement, surplus and thresholds, with every input's labels. It records the excluded splits and households, which figures are lower bounds, and which checks ran.
- **Probe runs** (`--probe`) are labelled as probes in the JSON and text output. They are never presented as findings. A window longer than 3 periods, and `--relaxed`, are refused without `--probe`.
- **Exit status** as now: 0 for definite answers, 1 for a disagreement between solvers or between replay and Z3, and 2 for *unknown*. The top-level `"unknown"` flag applies.
- The text report ends with a pointer to `docs/model-gaps.md`.

### 7. Scaling probe

- `make probe` runs a script in `scripts/` that times the window query at 3, 4, 5 and 6 periods, exact and relaxed, over several seeds for each, with a fixed early start date so that 6 periods fit before 31 March 2027.
- It records solver time for each figure and case, and the number of checks the search made.
- The results and their interpretation go in a new `docs/spike-window-scaling.md`: how time grows with the number of periods, and how much of it rounding accounts for. If rounding dominates, a later milestone can build a search that uses the relaxed model and confirms with the exact one. Slicing the translation to the definitions an objective depends on is the other lever. Neither is built here.
- A `slow` test runs the probe at 4 periods once, so that the probe scopes stay working.

### 8. Carried forward from milestone 2

These come from the milestone 2 reviews and touch the code this milestone works in. They are done first, with behaviour unchanged:

- `strategic.period_starts`, generalised to N periods, with a test of the December rollover.
- `solvers.optimise_and_confirm`: a cap on the number of checks for an unbounded objective, and a note in the docstring saying whose measurement its timing figures are.
- Removal of the unused `Optimize` path in `solvers._run_z3` and `_proved_optimal`, with the maximisation tests in `tests/test_solvers.py` rewritten as tests of `optimise_and_confirm`.
- The message for a disagreement between solvers, which can read "z3 says sat but cvc5 says sat".
- The differential check (`checks.run` through `report.differential`) following `--rules`, as replay already does.
- `Script._declared` seeded with the module's function names, and a refusal when `fixed` and `equal` overlap.
- In the milestone 2 design, a check that the outcome for assumption 3 states regulation 60's employer limb and paragraph (2), as model gaps does.

Lines over 100 columns stay on the brief's tidy-up list, because no linter is configured.

## Error handling

Failures are loud, as before. None is read as "nothing found", "no gain" or "no loss".

- The loader refuses a `per_period` input that is not a money, date or integer input, an `applies_when` that names something other than a Boolean judgement point, and the existing bad cases.
- The query refuses a window length outside 3 to 6, a start date whose last period lies outside the bounds or after 31 March 2027, more cases than the cap, and `--relaxed` outside a probe.
- The exporter refuses unsupported constructs by name and position, as now.
- A solver timeout or *unknown* is reported as *unknown*. A disagreement between Z3 and cvc5, or between replay and Z3, stops the run and shows both answers.

## Testing

Test-first, with one layer of tests per kind of risk. Tests that call PolicyEngine UK or take more than a few seconds are marked `slow` when they are written.

- **Rules:** `clerk test`, as listed under [Rules](#1-rules-rulesuccatala_en).
- **Exporter:** the dune tests under [Exporter](#3-exporter-and-bm-ir-version-1).
- **Translator:** the rounding tests, and the agreement test between Catala and Z3 on `ClaimWindow`. Its households are generated near the nil UC threshold and the relevant threshold, not at random, because a random sample rarely reaches them: in milestone 1 a random sample reached the taper in only 3 of 50 households.
- **Inputs:** the loader accepts the real file, expands `per_period` inputs, skips cases by `applies_when`, and refuses each bad case under [Error handling](#error-handling). Shared inputs carry the same labels in both files.
- **Window query, known answers:** gain, loss and spread are never negative; with `claim_after_end` false and the last-period rule in force, the gain equals that of a three-period split above nil; the £7,800 household is excluded by the last-period rule; and with no LCW (so no work allowance) and every period above nil, the award is linear in earnings, so the extra payday figure is no more than the rounding in three periods (3p).
- **Window query, cross-check:** the independent reference under [Window query](#5-window-query-bmwindow).
- **Differential:** the per-period check against PolicyEngine UK is unchanged. Whether PolicyEngine UK models surplus earnings across periods is checked at plan time. If it does, a differential test of the window is added. If not, the difference is recorded as deliberate, not as a mismatch.
- **CLI:** exit statuses 0, 1 and 2 for `query window`, the probe labels, and the refusal of `--relaxed` outside a probe.

## Assumptions for review

These readings drive the milestone's findings. All are questions for an outside reviewer before any finding is published.

1. One nil period ends the award from its first day (reading 1). The text supports this firmly.
2. Treated claims under regulation 32A follow the old assessment period dates, for up to 5 months counted from the nil period (reading 2). The count from the nil period rests on ADM examples.
3. Regulation 54A's surplus is added to the first period of each claim, carries on only on a claim that fails, and stops at an award (reading 4). The first-period point is inferred from paragraph (3) and the ADM's examples.
4. The relevant threshold uses the M and WA of the period of the claim being decided (reading 5). Unresolved in the text.
5. The nil UC threshold is rounded once (reading 5). Inferred from regulation 6 and the ADM's worked figures.
6. The £2,500 figure applies to a period beginning on or before 31 March 2027 (reading 6), and the window avoids chains that cross that date.
7. Whether a failed month counts as a claim, whether a claim is made at all, and whether the LCW finding carries over are DWP decisions, and are judgement points rather than rules (readings 2, 3 and 7).

## Out of scope for this milestone

- Periods beginning after 31 March 2027, and chains of claims that cross that date.
- Windows longer than 3 periods for findings.
- Regulation 61(6) reallocation, regulation 60 notional earnings, the domestic violence exception in regulation 54A(5), transitional protection, and the claimant commitment on a reclaim.
- A search that uses the relaxed model, and slicing the translation.
- The other candidates under [Milestones](../../v2-brief.md#milestones) in the brief: the rounding-stage query, other strategic queries, tax and National Insurance, the benefit cap, children, couples and the rest of the housing calculation.
- A population layer. PolicyEngine UK already does microsimulation on survey data, so the project does not build its own. Scale is taken from cited official statistics and, where a later finding needs it, from a bridge that hands a finding's region to PolicyEngine UK. The brief records this direction (see [Documentation](#documentation)).

## Documentation

- **`docs/nil-months.md`** (new): the legal readings, the checker's corrections and the evidence on practice, edited into one note with sources, dates and confidence, each reading marked for specialist review. It describes rules and classes of claimant, not any particular claim.
- **`docs/model-gaps.md`:** the surplus earnings entry becomes "modelled within the window's limits", with those limits. New entries: regulation 61(6); the window's limits; a chain crossing 31 March 2027; the reading of which M and WA apply; and the three new judgement points, with the realistic case for each from the evidence on practice. The milestone 3 findings and their conditions are added to the strategic findings.
- **`docs/v2-brief.md`:** a milestone 3 entry linking this design; the items carried forward from the milestone 2 reviews, as listed above; the research question on nil months marked as answered by `docs/nil-months.md`; and the direction on population questions: no population layer of the project's own, scale from cited official statistics, and a bridge to PolicyEngine UK as a candidate for a later milestone. The "Estimating impact" and architecture sections are updated to match.
- **`docs/bm-ir.md`** for version 1, and **`docs/spike-window-scaling.md`** for the probe.
- **`AI-DECLARATION.md`**, if the way of working changes, and the project `CLAUDE.md` with what worked and what got in the way in this milestone.

## Known limitations

- The earlier milestones' limitations still hold, including that DWP's own software cannot be tested from outside and that the exporter is tied to Catala 1.3.0.
- Findings hold for 3 periods, for splits that end the window in an award, and for periods beginning on or before 31 March 2027.
- Where no claim is made after the end of an award, the loss is a lower bound.
- For claimants paid regularly each month, a finding that relies on two payments in one period holds only if regulation 61(6) is not used.
- The housing costs element is an input, so findings hold for a given element, not for a given rent.

## Sources checked

Legislation is on legislation.gov.uk, latest revised versions, read through the XML data feed, which lists outstanding effects. None of the outstanding effects touches the provisions below. All checked 29 October 2026:

- Welfare Reform Act 2012, sections [3](https://www.legislation.gov.uk/ukpga/2012/5/section/3), [5](https://www.legislation.gov.uk/ukpga/2012/5/section/5), [7](https://www.legislation.gov.uk/ukpga/2012/5/section/7) and [8](https://www.legislation.gov.uk/ukpga/2012/5/section/8).
- Universal Credit Regulations 2013 (S.I. 2013/376), regulations [6](https://www.legislation.gov.uk/uksi/2013/376/regulation/6), [17](https://www.legislation.gov.uk/uksi/2013/376/regulation/17), [21](https://www.legislation.gov.uk/uksi/2013/376/regulation/21), [22](https://www.legislation.gov.uk/uksi/2013/376/regulation/22), [22A](https://www.legislation.gov.uk/uksi/2013/376/regulation/22A), [28](https://www.legislation.gov.uk/uksi/2013/376/regulation/28), [39](https://www.legislation.gov.uk/uksi/2013/376/regulation/39), [54](https://www.legislation.gov.uk/uksi/2013/376/regulation/54), [54A](https://www.legislation.gov.uk/uksi/2013/376/regulation/54A) and [61](https://www.legislation.gov.uk/uksi/2013/376/regulation/61).
- Universal Credit etc. (Claims and Payments) Regulations 2013 (S.I. 2013/380), regulations [26](https://www.legislation.gov.uk/uksi/2013/380/regulation/26) and [32A](https://www.legislation.gov.uk/uksi/2013/380/regulation/32A). Paragraphs (3) and (4) of regulation 32A, inserted from 22 September 2026 by S.I. 2026/946, concern funded employment schemes and are outside scope.
- Universal Credit, Personal Independence Payment, Jobseeker's Allowance and Employment and Support Allowance (Decisions and Appeals) Regulations 2013 (S.I. 2013/381), [regulation 23](https://www.legislation.gov.uk/uksi/2013/381/regulation/23) and [Schedule 1](https://www.legislation.gov.uk/uksi/2013/381/schedule/1).
- S.I. 2015/345, [regulation 5](https://www.legislation.gov.uk/uksi/2015/345/regulation/5), and the Secretary of State's determination under it, made 20 January 2026 and published on gov.uk on 31 March 2026.
- The [explanatory memorandum](https://www.legislation.gov.uk/uksi/2020/1138/pdfs/uksiem_20201138_en.pdf) to S.I. 2020/1138, and ADM memos 10/20 and 27/20.
- DWP, *Advice for Decision Making*, chapters A2, A4, E1, E2, F5, G1, G2 and H3 (gov.uk page last updated 22 October 2026).
- DWP staff guides deposited in Parliament: "Claim closure" V35.0 (DEP2025-0769, 24 November 2025) and V32.0, and "Surplus, fluctuating and irregular earnings plus payment cycles" (DEP2024-0673); "Re-claims" V11.0 (DEP2024-0442) and V8.0 (DEP2022-0452). These are process documents, not law, and later versions may differ.
- The explanatory memorandum to S.I. 2026/946, and written answers 74834 (8 November 2022) and 66811 (17 July 2025), read through the Parliament written questions API.
- University of Bath, *Coping and hoping* (April 2024), and Citizens Advice, *A better fit* (August 2025), for practice. These are research and advocacy sources.
- gov.uk, ["Universal Credit and earnings"](https://www.gov.uk/guidance/universal-credit-and-earnings) (last updated 1 April 2026).
- CPAG, ["UC, SEISS payments and automatic reclaims"](https://cpag.org.uk/welfare-rights/bulletins-articles/welfare-rights-bulletin/articles/uc-seiss-payments-automatic-reclaims), *Welfare Rights Bulletin* 277 (August 2020).
