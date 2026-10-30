# Milestone 2: the first strategic query

Design for the second milestone of benefits-modeller v2. It builds on [the brief](../../v2-brief.md), the [milestone 1 design](2026-10-29-walking-skeleton-design.md), the [quantifier spike](../../spike-quantifier-tractability.md) and the [mismatch log](../../mismatches.md). The scope summary and the items carried forward from milestone 1 are under [Milestones](../../v2-brief.md#milestones) in the brief. What the model leaves out is recorded in [model gaps](../../model-gaps.md).

Written 29 October 2026. Claims about legislation and external tools give the date they were checked.

## Goal

Build the first strategic query end to end, through every layer, on the thinnest slice that needs it:

labelled inputs → Catala rules with a housing costs element → one household instance per assessment period and per judgement case → Z3 optimises, cvc5 confirms → the example household is replayed through Catala's interpreter → a report that names who controls each input and how it is checked.

Milestone 1 tested the pipeline on an answer worked out by hand. Milestone 2 tests the strategic machinery: input labels, judgement points expanded into cases, several assessment periods in one query, and a worst case taken across what the decision maker might find. Its headline finding is modest, a bound on what moving pay between periods can gain while the award continues. It is a correct finding, and it is computed, not assumed. The larger gains from timing depend on rules that cross periods, which this milestone does not model (see [Scope](#scope)).

## Decisions

| Question | Decision |
|---|---|
| What milestone 2 is for | The first strategic query, end to end, rather than a wider rule set or a structural finding |
| Which strategic query | When earnings fall across two assessment periods, with limited capability for work (LCW) as the judgement point; and the value of the LCW finding on its own |
| Housing | A housing costs element, taken as one monthly input already worked out |
| Where input labels live (brief, open question 4) | In `rules/uc.inputs.toml`, next to each input's bounds |
| How to represent a judgement point (open question 5) | An input labelled as controlled by a decision maker. It is a Boolean or a small enumeration, expanded into cases by every query. No probabilities. |
| How to represent several periods | The Catala scope covers one assessment period. The query instantiates it once per period. |
| How to build the query | One `strategic` module driven by the labels, with one built-in kind of choice (a split of a fixed total across periods), not a query language |
| Timing and a nil award | Splits are limited to those where the award stays above nil in every period and every case, because the end of an award and surplus earnings are not modelled |
| Readings of the law | Each rests on cited sources and is recorded as the project's reading, pending specialist review. None rests on sign-off by the project owner. |

## Scope

### Household

A single claimant, in two consecutive monthly assessment periods. Inputs:

- **Assessment period start,** age band (under 25, or 25 or over), limited capability for work, and monthly earned income, as in milestone 1.
- **Housing costs element:** new. A monthly amount, taken as already worked out under regulation 26 and Schedule 4 of the Universal Credit Regulations 2013 ([regulation 26](https://www.legislation.gov.uk/uksi/2013/376/regulation/26), checked 29 October 2026). It stands for eligible rent after any Local Housing Allowance cap, under-occupancy deduction or housing cost contributions, none of which is modelled.

Every input except earned income is the same in both periods.

### Why timing gains are limited to awards above nil

While the award stays above nil, it is a concave function of earned income in each period: flat up to the work allowance, then falling at 55%. The sum over two periods of a concave function, for a fixed total, is largest at the even split. So moving pay between periods gains nothing beyond rounding, which happens separately in each period.

All the larger gains come from pushing one period to a nil award, so that the other period keeps the full maximum amount. That is where the law has rules that cross periods. A nil award because of earnings ends the award ([regulation 32A](https://www.legislation.gov.uk/uksi/2013/380/regulation/32A) of the Claims and Payments Regulations 2013, which deals with an award that "ceases because that condition is not met"). A new claim within 6 months then counts earnings above "the relevant threshold" as surplus earnings ([regulation 54A](https://www.legislation.gov.uk/uksi/2013/376/regulation/54A) of the Universal Credit Regulations 2013). Both checked 29 October 2026.

The relevant threshold is the nil UC threshold plus £300. For a claim in respect of a period that begins before the end of the "temporary de minimis period", it is the nil UC threshold plus £2,500 ([regulation 5](https://www.legislation.gov.uk/uksi/2015/345/regulation/5) of the Universal Credit (Surpluses and Self-employed Losses) (Digital Service) Amendment Regulations 2015, S.I. 2015/345, checked 29 October 2026; DWP's *Advice for Decision Making*, paragraphs H3309 and H3310). The regulation ends that period on 31 March 2019 and lets the Secretary of State extend it. The Secretary of State's [determination](https://www.gov.uk/government/publications/secretary-of-state-determination-under-regulation-5-of-the-universal-credit-surpluses-and-self-employed-losses-digital-service-amendment-regulatio--2/secretary-of-state-determination-under-regulation-5-of-the-universal-credit-surpluses-and-self-employed-losses-digital-service-amendment-regulatio), made on 20 January 2026 and published on gov.uk on 31 March 2026 (checked 29 October 2026), says the period "will end on 31st March 2027". The project reads the two together as: the threshold is the nil UC threshold plus £2,500 for a claim in respect of a period beginning on or before 31 March 2027 (the end of the temporary de minimis period as currently extended), and plus £300 for a claim in respect of a later period unless the period is extended again. That a period beginning on 31 March 2027 itself is covered is an inference from the determination's wording and regulation 5, for specialist review.

So regulation 54A does not block or reduce a gain through a nil period below the relevant threshold. It applies surplus earnings only for earnings above that threshold, and only if the claimant makes a new claim within 6 months. Regulation 60 on notional earnings is a separate possible limit (see assumption 3). Neither the end of the award nor the reclaim is modelled, and both cross periods. A query that ignored them could not say what a gain through a nil period is worth, and would report a large gain that the rules around it may reduce. So the timing query is limited to splits where every award, with the split and with the baseline, in every judgement case, is above nil. The reason is the modelling gap, not a finding that the law blocks or reduces such gains. The gap is recorded in [model gaps](../../model-gaps.md).

## Components

### 1. Rules: `rules/uc.catala_en`

- **New input** `housing_costs_element content money`, described in the file as above, with a pointer to the model gaps register.
- **New output** `maximum_amount`, equal to `standard_allowance + housing_costs_element`. Section 8(2) of the [Welfare Reform Act 2012](https://www.legislation.gov.uk/ukpga/2012/5/section/8) makes the maximum amount the total of the standard allowance, the child amounts, the housing costs amount and other particular needs (checked 29 October 2026). Only the first and third are modelled.
- **Work allowance.** Regulation 22(2) applies the higher work allowance "if the award contains no amount for the housing costs element" and the lower one if it does ([regulation 22](https://www.legislation.gov.uk/uksi/2013/376/regulation/22), checked 29 October 2026). Both amounts were substituted by S.I. 2026/148. Three flat definitions, whose conditions exclude each other, in the style of the existing rules:

  | LCW | Housing costs element | Work allowance |
  |---|---|---|
  | yes | £0 | £710.00, the higher work allowance |
  | yes | above £0 | £427.00, the lower work allowance |
  | no | any | £0, as in milestone 1 |

  They are flat definitions, not exceptions, because regulation 22(2)(a) and (b) are parallel cases. The rules read "contains an amount" as an element above zero, as PolicyEngine UK does. That reading is listed under [Assumptions for review](#assumptions-for-review).
- **Award** becomes `maximum_amount - earnings_deduction`, or zero if that is negative.
- **Assertion tests** in `rules/uc_tests.catala_en`, worked by hand: the housing costs element at £0 and above £0, with and without LCW, and a deduction that lands on exactly half a penny with the lower work allowance (earnings £427.10 with LCW and a housing costs element, where 55% of 10p is 5.5p).

### 2. Inputs and labels: `rules/uc.inputs.toml`

The file becomes the one list of the scope's inputs. Every input appears, Booleans included, with:

- `type`, and `min` and `max` where the type needs bounds;
- `controlled_by`: a list drawn from `claimant`, `employer`, `landlord`, `decision_maker` and `nobody`;
- `checked_by`: one of `third_party_data`, `documentary_evidence`, `claimant_declaration`, `assessment` and `dwp_records`.

| Input | Bounds | Controlled by | Checked by |
|---|---|---|---|
| `assessment_period_start` | 6 April 2026 to 5 April 2027 | claimant | dwp_records |
| `earned_income` | £0 to £10,000 | employer, claimant | third_party_data |
| `aged_25_or_over` | | nobody | documentary_evidence |
| `has_lcw` | | decision_maker | assessment |
| `housing_costs_element` | £0 to £804 | landlord | documentary_evidence |

Notes, written into the file as comments:

- The assessment period start follows from the date of claim, which the claimant chooses.
- Employed earnings arrive through HMRC's Real Time Information feed. Their timing and amount can be shaped by the employer or by the claimant. Self-employed earnings, when they are added, are a separate input with `checked_by = "claimant_declaration"`, because they are checked differently.
- The bound of £804 a month on the housing costs element keeps every modelled household below the benefit cap, which is not modelled (regulation 80A of the Universal Credit Regulations 2013: £14,753 a year outside Greater London, £1,229.42 a month, less the £424.90 standard allowance, rounded down; checked 29 October 2026).

### 3. Refactors, done first with behaviour unchanged

Each lands as its own task, and the existing test suite passes unchanged after each.

- **`bm.units`:** `EPOCH`, conversion between dates and day numbers, and exact conversion between pounds and pence through `Decimal`. It replaces the six definitions of `EPOCH` (in `bounds`, `catala_run`, `households`, `policyengine`, `report` and `translate`) and the four ways of converting money (in `bounds`, `catala_run`, `policyengine` and `report`).
- **`bm.inputs`:** loads `uc.inputs.toml` into one record per input (name, type, bounds, `controlled_by`, `checked_by`) and checks it against the scope's inputs in the IR. It absorbs `bounds.py`. `households`, `checks.run` and `cli` read the input names from it. `policyengine` keeps code per input for the mapping, and a test checks that the mapping covers exactly the inputs in the registry.
- **`bm.household`:** one builder, `instance(module, prefix, fixed={})`. It declares one copy of the scope's inputs under a name prefix, bounds them, fixes any values given, asserts that no obligation holds, and returns handles to the outputs. Several instances can share one solver. `coverage`, `queries.emr`, `households.last_penny_earnings` and `evaluate` use it.
- **`solvers.optimise_and_confirm`:** one implementation of "Z3 maximises, cvc5 confirms that nothing larger exists". It returns one of optimal, *unknown* or disagreement, with the value and the model. *Unknown* from either solver gives *unknown*. It replaces the two existing copies.
- **Documentation of `.defined`** on `SmtModule` and `Obligation`: it is true at `error_on_empty` sites even where Catala raises an error, so every query must assert that no obligation holds. The builder does this, which is one reason to have a single builder.
- **One-term sums:** a sum with one term is written as the term itself, because cvc5 rejects a unary `(+ x)`. The translator never writes a unary `+`: Catala's additions are binary, so the one-term special case lives in `bm.household.smt_sum`, where the query code builds sums. A test checks that cvc5 parses the output.

### 4. Strategic queries: `bm.strategic`

**What the caller gives:**

- **Fixed household facts** (optional). Any input that is not fixed ranges over its bounds, except as below.
- **The first assessment period's start,** defaulting to 6 April 2026. The second period starts one calendar month later. Python computes the second date, because a calendar month cannot be written in linear arithmetic. Both dates must lie within the bounds, or the query refuses. In 2026/27 the rules do not depend on the day within the year, so fixing the dates loses nothing.

**What the labels decide:**

- **Judgement points.** An input whose `controlled_by` includes `decision_maker`, and which the caller has not fixed, is a judgement point. The query expands the judgement points into every combination of their values, one case per combination. If the number of cases is above a cap (default 8), the query refuses. This follows the spike: expanded cases by default, and `forall` only as a cross-check.
- **The choice.** `Split(input, periods=2)`: the input's values in the two periods are free, subject to a fixed total. The input's `controlled_by` must include `claimant` or `employer`. Otherwise the query refuses.
- **Household facts.** Every other input. Each has one value, the same in every period and every case.

Each query builds one household instance per period per case with the builder, so the timing query has 2 × (number of cases) instances in one solver.

**Query 1: timing gain.**

- A total *T* of the chosen input is split into *e*₁ + *e*₂. The baseline is the even split, *b*₁ = ⌊*T*/2⌋ and *b*₂ = *T* − *b*₁, written with integer division by a constant, which stays linear.
- Every award, with the split and with the baseline, in every period and every case, must be above nil.
- For each case *c*: gain_c = award(*e*₁) + award(*e*₂) − award(*b*₁) − award(*b*₂), in pence.
- The query maximises *g* subject to *g* ≤ gain_c for every case. This is the gain the claimant can count on, whatever the decision maker finds.
- It also maximises each case's gain on its own, and reports it.
- The even split itself is allowed, so the gain is never negative.

**Query 2: value of a judgement point.**

- For a named judgement point with two values (for LCW, yes and no), in one period: the largest and the smallest value, over households, of award(yes) − award(no).
- The award in both cases must be above nil, so the value measures the finding, not the floor at zero.
- The named input must be a Boolean judgement point that the caller has not fixed. Otherwise the query refuses. Enumerated judgement points wait until one exists.

**How each answer is checked:**

1. `optimise_and_confirm`: Z3 maximises, and cvc5 confirms that no larger value exists.
2. **Replay.** The witness household for every period and case is run through Catala's interpreter. Each award must equal Z3's to the penny. Any difference stops the run, as a bug in the translator.
3. **Tests only: a brute-force reference.** A small Python model of the award, with exact fractions and the same rounding, tries every split for a few fixed households and must agree with the solver's optimum. It is independent of the translator and of the SMT encoding of the query.
4. **Tests only: a cross-check with `forall`.** On small instances, the form "a split exists such that, for every value of the judgement point, the gain is greater than the optimum" must be unsat, and the same with "at least the optimum" must be sat.

### 5. Differential checks: `bm check`

- Generated households include the housing costs element.
- The boundary generator adds households near the new kinks: the element at £0 and £0.01, which is where the work allowance switches, and earnings at £427 plus or minus 1p with LCW and an element above £0.
- Random households cover both a zero and a positive element.
- **PolicyEngine UK.** The mapping sets `uc_housing_costs_element` (a benefit unit variable) directly as an input, scaled by 12 for the year as earned income is. PolicyEngine's own `uc_work_allowance` takes the lower amount when that element is above zero. Checked on 29 October 2026 against policyengine-uk 2.164.2, in `variables/gov/dwp/universal_credit/housing_costs_element/uc_housing_costs_element.py` and `work_allowance/uc_work_allowance.py`. The mapping's docstring records this, as it does for the other inputs.
- Mismatches are triaged into `docs/mismatches.md` as before. The rounding-stage class is expected to grow to include households with the lower work allowance. That is the same class, not a new one, and its predicate is widened if needed.

### 6. Report and CLI

- `bm query timing [--start DATE] [--fix NAME=VALUE ...]` and `bm query judgement NAME [--fix NAME=VALUE ...]`.
- **Strategic results** record the query, the judgement cases expanded, the fixed facts, the start dates, the optimum (overall and per case), and the witness for every period and case. Every input in the witness carries its `controlled_by` and `checked_by` labels. They also record which verification steps ran and their outcome.
- **The JSON report** gains a top-level `"unknown"` flag, true when any result in it is *unknown*.
- **The text report** ends with a pointer to `docs/model-gaps.md`.
- **Exit status:** 0 for definite answers, 1 for a disagreement between solvers or between replay and Z3, 2 for *unknown*. These match the coverage command's existing codes.

## Error handling

Failures are loud, as in milestone 1. None is read as "nothing found" or "no gain".

- The loader refuses an input missing from `uc.inputs.toml`, an entry with no matching scope input, a missing label, or an unknown label value.
- A query refuses a choice whose input is not controlled by the claimant or the employer, more judgement cases than the cap, a period start whose second period falls outside the bounds, or a judgement query on an input that is not an unfixed Boolean judgement point.
- A solver timeout or *unknown* is reported as *unknown*, never as no gain.
- A disagreement between Z3 and cvc5, or between replay and Z3, stops the run and shows both answers.

## Testing

Test-first, with one layer of tests per kind of risk:

- **Rules:** `clerk test`, with households worked by hand, as listed under [Rules](#1-rules-rulesuccatala_en).
- **Inputs:** the loader accepts the real file, and refuses each of the bad cases under [Error handling](#error-handling).
- **Refactors:** the whole existing suite passes unchanged after each refactor task. New unit tests cover `bm.units` and the builder, including that two instances in one solver share no constants.
- **Translator:** a one-term sum parses in cvc5. The agreement test between Catala and Z3 covers the new input.
- **Strategic, known answers:**
  - The value of the LCW finding is at most £390.50 (55% of £710.00) with no housing costs element, and at most £234.85 (55% of £427.00) with an element above £0, where both awards stay above nil. Its smallest value is £0, with earnings of £0.
  - The timing gain is never negative.
- **Strategic, cross-checks:** the brute-force reference and the cross-check with `forall`, both described under [Strategic queries](#4-strategic-queries-bmstrategic).
- **Differential:** `bm check` against PolicyEngine UK, with an exact match required, the existing rounding-stage class apart.
- **CLI:** exit statuses 0, 1 and 2 for the new commands, plus the tests carried forward from milestone 1: exit status 1 when the solvers disagree, and exit statuses 1 and 2 from coverage.

## Assumptions for review

The project has no review by a welfare rights adviser or a social security policy specialist (see [model gaps](../../model-gaps.md)). These readings drive the milestone's findings. Each is to be checked against DWP's *Advice for Decision Making* during implementation, with the outcome recorded here or in the model gaps register. All of them are questions for an outside reviewer before any finding is published.

The outcomes below were recorded on 29 October 2026 from the chapters of [*Advice for Decision Making*](https://www.gov.uk/government/publications/advice-for-decision-making-staff-guide) (ADM) on gov.uk (page last updated 22 October 2026), and the regulations they cite, on legislation.gov.uk. The checking was done by an AI research agent, and the paragraph references were spot-checked at their source by a second agent. Neither is a specialist, so nothing below is a welfare rights adviser's opinion. Each ADM chapter is dated by its most recent entry in the page's update history, which is when DWP republished the chapter, not when the cited paragraph changed. The ADM is guidance to decision makers, not law. No outcome is a contradiction of an assumption. Assumption 1 is only partly supported, and the part not supported is that regulation 54A blocks or reduces a nil-period gain below the surplus earnings threshold (see its outcome).

1. A nil award because of earnings ends the award, so a two-period gain that relies on a nil period is blocked or reduced by regulation 54A. This reading is based on regulation 32A of the Claims and Payments Regulations 2013.
   - **Outcome (29 October 2026): partly supported.** That a nil award because of earnings ends the award is supported. ADM A2 (Claims, updated 26 May 2026), paragraph A2050, restates regulation 32A: entitlement can cease because the income condition is not met, and the Secretary of State "may" then treat the claimant as claiming again in each of up to 5 following months, so the reclaim is discretionary. ADM H3 (Earned income, employed earnings, updated 8 April 2026), paragraphs H3301 to H3304, apply surplus earnings to a new claim within 6 months of an award that ceased because of excess income. That regulation 54A blocks or reduces the gain is supported only where the nil period's earnings exceed the relevant threshold: paragraphs H3309 and H3310 give the nil UC threshold plus £2,500 for claims in the temporary de minimis period, which ends on 31 March 2027 (the threshold is set out in the section on why timing gains are limited to awards above nil). Below the threshold, regulation 54A applies no surplus earnings and neither blocks nor reduces the gain. The milestone's limit to awards above nil is unchanged, because it rests on the end of the award and the reclaim, which are not modelled. The ADM does not address the concavity argument for awards above nil, which is the project's own mathematics.
2. "Contains an amount for the housing costs element" (regulation 22(2)) means an element above zero.
   - **Outcome (29 October 2026): silent on the case that matters.** ADM E2 (Benefit unit, awards and maximum amount, updated 14 May 2026), paragraphs E2203 and E2204, repeat regulation 22(2) and do not define "contains an amount". ADM F3 (Housing costs element, support for renters, updated 21 April 2026), paragraph F3142, and Schedule 4, paragraph 14(3), say the element is nil where housing cost contributions exceed the rent calculated. So a claimant can meet the conditions for the element and have it calculated at nil, and the ADM does not say which work allowance applies then. E2203, Note 2, treats an element that cannot be paid because the claimant has earned income (owner-occupiers, ADM F4, paragraph F4020) as no amount, so the higher allowance applies. That is a different case. The model's input of £0 does not distinguish no element from an element reduced to nil. Recorded in [model gaps](../../model-gaps.md) as untested for the reduced-to-nil case.
3. Earned income is controlled by the employer or the claimant, and both can shape when it falls in an assessment period.
   - **Outcome (29 October 2026): supports for the employer; silent on the claimant, which has a limit.** ADM H3, paragraph H3191 and its examples, ties employed earnings in an assessment period to the PAYE information that HMRC reports to DWP in that period, so a late payment or report moves earnings into the next period. The ADM does not say a claimant can move pay between periods. Regulation 60 treats a person who has deprived themselves of earned income, or whose employer has arranged for them to be deprived, "for the purpose of securing entitlement to universal credit or to an increased amount" as possessing that income. Under paragraph (2) the purpose is treated as existing if higher entitlement resulted and, in the Secretary of State's opinion, this was a foreseeable and intended consequence. ADM H3, paragraphs H3201 to H3216, apply the rule, and H3216 tells decision makers to consider the timing of a disposal carefully. The claimant's control is therefore influence over the employer, not a legal power. Neither the regulation nor these paragraphs say that deferring pay to a later assessment period is a deprivation; whether deferring pay counts is the project's reading, for specialist review. Recorded in [model gaps](../../model-gaps.md).
4. The LCW finding is a judgement by a decision maker, made after a Work Capability Assessment, and not a fact the claimant controls.
   - **Outcome (29 October 2026): supports, with two qualifications.** ADM G2 (Limited capability for work, updated 21 April 2026), paragraphs G2002, G2003 and G2090, say the finding is determined on the basis of a Work Capability Assessment (WCA) or arises from being treated as having limited capability for work, and is conclusive for other UC decisions. The claimant supplies information but the finding is the decision maker's. The qualifications are (a) some claimants are treated as having limited capability for work without a WCA (G2010), and others after a WCA that found none (G2011), and (b) where monthly earnings reach the threshold in regulation 41(2) and (3), a WCA cannot be carried out unless the claimant receives a listed disability benefit or the WCA reviews an earlier finding, and otherwise the claimant is treated as not having limited capability for work (ADM G1, Work Capability Assessment, updated 25 August 2026, paragraphs G1030 to G1034; G1032 still says weekly earnings, whereas regulation 41(2) now says monthly). So `has_lcw` is not independent of earnings. Recorded in [model gaps](../../model-gaps.md).
5. The rounding stage follows reading (a) in the mismatch log, as in milestone 1.
   - **Outcome (29 October 2026): silent on the stage.** ADM B1 (Payment of UC, PIP, ESA and JSA, updated 26 October 2023), paragraph B1121, restates regulation 53 of the Claims and Payments Regulations, which rounds the amount payable "at the end of a calculation". ADM E2, paragraph E2195, and its note refer to regulation 6 for rounding to the nearest penny. Neither says at which stage the earnings deduction is rounded. The worked examples in ADM H3 show the deduction rounded as a step, which is consistent with reading (a), but none has a tie of exactly half a penny, so they do not choose between readings, and worked examples are not authority. The question stays open and the [mismatch log](../../mismatches.md) classification stands.

## Out of scope for this milestone

Listed under [Milestones](../../v2-brief.md#milestones) in the brief, with the reasons:

- the rounding-stage query, rules that cross periods (surplus earnings and the end of an award), and the other candidate strategic queries;
- income tax and National Insurance, the benefit cap, children, couples and the rest of the housing calculation;
- non-terminating decimal rates, and modelling division by zero;
- the tidy-up items, which go in a separate pull request.

## Documentation

- The brief's entry for milestone 2 links to this design.
- `docs/model-gaps.md` is updated with any gap the milestone finds, and with the outcome of checking the assumptions above.
- `docs/mismatches.md` is updated by the differential checks, as before.
- The project `CLAUDE.md` records what worked and what got in the way in the Superpowers trial for milestone 2.

## Known limitations

- Milestone 1's limitations still hold: DWP's own software cannot be tested from outside, the place where rounding happens depends on how the rules are written, and the exporter is tied to Catala 1.3.0.
- The timing finding holds only while the award stays above nil. It says nothing about gains that rely on a nil period.
- The housing costs element is an input, so findings hold for a given element, not for a given rent.

## Sources checked

Legislation is on legislation.gov.uk, latest revised versions. All checked 29 October 2026:

- Welfare Reform Act 2012, [section 8](https://www.legislation.gov.uk/ukpga/2012/5/section/8).
- Universal Credit Regulations 2013 (S.I. 2013/376), regulations [22](https://www.legislation.gov.uk/uksi/2013/376/regulation/22), [25](https://www.legislation.gov.uk/uksi/2013/376/regulation/25), [26](https://www.legislation.gov.uk/uksi/2013/376/regulation/26) and [54A](https://www.legislation.gov.uk/uksi/2013/376/regulation/54A). The work allowance amounts of £710.00 and £427.00 were substituted by S.I. 2026/148.
- The Universal Credit, Personal Independence Payment, Jobseeker's Allowance and Employment and Support Allowance (Claims and Payments) Regulations 2013 (S.I. 2013/380; title checked on legislation.gov.uk 30 October 2026), [regulation 32A](https://www.legislation.gov.uk/uksi/2013/380/regulation/32A). Regulation 53 was also read for the assumption on rounding.
- Universal Credit Regulations 2013, also [regulation 6](https://www.legislation.gov.uk/uksi/2013/376/regulation/6), [39](https://www.legislation.gov.uk/uksi/2013/376/regulation/39), [41](https://www.legislation.gov.uk/uksi/2013/376/regulation/41) and [60](https://www.legislation.gov.uk/uksi/2013/376/regulation/60), and [Schedule 4](https://www.legislation.gov.uk/uksi/2013/376/schedule/4), for the assumptions checks.
- Universal Credit (Surpluses and Self-employed Losses) (Digital Service) Amendment Regulations 2015 (S.I. 2015/345), [regulation 5](https://www.legislation.gov.uk/uksi/2015/345/regulation/5), and the Secretary of State's [determination under it](https://www.gov.uk/government/publications/secretary-of-state-determination-under-regulation-5-of-the-universal-credit-surpluses-and-self-employed-losses-digital-service-amendment-regulatio--2/secretary-of-state-determination-under-regulation-5-of-the-universal-credit-surpluses-and-self-employed-losses-digital-service-amendment-regulatio), made on 20 January 2026 and published on gov.uk on 31 March 2026 (read 29 October 2026).
- DWP, [*Advice for Decision Making*](https://www.gov.uk/government/publications/advice-for-decision-making-staff-guide) (gov.uk, page last updated 22 October 2026), chapters A2, B1, E1, E2, F2, F3, F4, G1, G2 and H3, read on 29 October 2026 for the assumptions checks.

PolicyEngine UK 2.164.2, the version in `uv.lock`, read from its installed source on 29 October 2026.
