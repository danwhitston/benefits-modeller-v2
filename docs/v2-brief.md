# benefits-modeller v2: brief

Starting input for design. It records the direction chosen so far and the questions still open. The detailed design and plan come later and build on it.

First written 28 October 2026. Claims about external tools are dated, because they will go stale.

## Background

[benefits-modeller](https://github.com/danwhitston/benefits-modeller) (v1) was an MSc project. It defined Ben, a small language for UK benefit rules, with an ANTLR4 grammar, a Python parser and a runner that translated rules into Z3 constraints. It showed that a solver can answer questions about a rule set, but it had a hand-built language, a small sample of rules and no link from each rule back to its legal source.

v2 keeps v1's two core ideas: a dedicated language for the rules, and an SMT solver for asking questions about them. It changes how each part is built, and it adds a purpose.

## Purpose

The administrative burden of claiming has long acted as an unofficial limit on demand for benefits. Claimants have to learn what exists, gather evidence, fill in forms, present their circumstances in the way the system expects, and work through reconsiderations and appeals. Herd and Moynihan call these learning, compliance and psychological costs (*Administrative Burden: Policymaking by Other Means*, 2018).

AI lowers those costs. Tom Loosemore has warned of an AI-generated increase in demand for public services, and of personal AI agents that will deal with services on people's behalf ([20 October 2026](https://www.linkedin.com/feed/update/urn:li:activity:7518300848641249280/), linking a Sky News explainer, *Why AI could overwhelm Britain's public services*; [26 October 2026](https://www.linkedin.com/feed/update/urn:li:activity:7520436586774364163/)).

v2 aims to:

1. estimate how exposed the benefits system is when that friction falls, and the likely scale of the effect
2. find the weak points: where outcomes depend on inputs that are unchecked, controlled by the claimant, or decided by judgement
3. test which changes to the rules or to verification would reduce that exposure

Lower friction has four different effects, and each needs a different policy response:

- **Take-up of genuine entitlement.** Not gaming, but it raises cost, because friction currently does unofficial rationing.
- **Lawful optimisation of facts the claimant controls.** Examples: when pay falls relative to assessment periods, how earnings are split within a couple, and when changes are reported.
- **Presentation where judgement applies.** Evidence for the Work Capability Assessment, or whether two people are living together as a couple.
- **Misrepresentation.** False declarations of inputs that are not independently checked.

## Rules and judgement

Legal codes leave room for judges to decide what is reasonable and what a rule really means. Benefits administration sits between law and purely technical rules. Most of Universal Credit is formula: allowances, elements, the work allowance, the taper and the cap. Judgement enters at points that can be named:

- **Findings of fact by a decision maker:** living together as a couple, whether self-employment is gainful (which decides whether the minimum income floor applies), habitual residence, deprivation of capital, and good reason in sanctions cases.
- **Assessments that weigh evidence:** chiefly the Work Capability Assessment descriptors.
- **Discretion:** budgeting advances; and, outside Universal Credit itself, councils' Discretionary Housing Payments.
- **Interpretation shaped by appeals:** Upper Tribunal decisions set binding precedent, and DWP's *Advice for Decision Making* guidance turns them into practice.

The model keeps the formula in Catala and makes every judgement point an explicit input, labelled as decided by a decision maker. Nothing that depends on judgement is hidden inside a rule.

## Three kinds of question

1. **Population questions.** What does a reform cost? Who gains and who loses? How many households are affected? These need survey microdata, not proofs.
2. **Structural questions.** Does any household face an effective marginal rate above 100%? Where are the cliff edges? Can two rules conflict? Is there an income range where earning more leaves a household worse off? These are "for all" and "there exists" questions, and they are what a solver is for.
3. **Strategic questions.** What is the most a household can gain through lawful choices about inputs it controls? What is each judgement point worth to a household? What is the value of an unchecked declaration? These are optimisation questions over the inputs a particular party controls.

The solver finds the problem regions. How many real households sit in them comes from elsewhere: from cited official statistics, and perhaps later from PolicyEngine UK's microsimulation (see [Estimating impact](#estimating-impact)).

## Proposed architecture

| Layer | Choice | Role |
|---|---|---|
| Rules | [Catala](https://catala-lang.org/), English syntax | The benefit rules, written as literate code alongside the regulation text they implement |
| Input labels | Metadata on every input | Who controls the input, and how it is checked |
| Authoring | Claude Code drafting Catala from regulation text | Speeds up writing rules; the compiler, tests and a human review of each diff keep it honest |
| Analysis | Translator from Catala's intermediate representation to SMT-LIB, run with Z3 and cvc5 | Answers structural and strategic questions, with a concrete example household for each finding |
| Oracle | [PolicyEngine UK](https://policyengine.org/uk) | Differential testing of the rules, one assessment period at a time |
| Scale | Cited official statistics; a bridge to PolicyEngine UK as a candidate | How many households a finding's class may cover. No population layer of the project's own (see [Estimating impact](#estimating-impact)) |
| Optional | Lean | One or two theorems that need parameters as variables, such as monotonicity of net income for any taper rate |

### Why Catala rather than a new grammar

Catala uses default logic: a base rule plus prioritised exceptions. UK regulations are drafted the same way. It is literate, so each block of code sits next to the legal text it implements, which gives the traceability v1 lacked. Its authors used it to formalise part of French family benefits and report finding a bug in the official implementation along the way ([Merigoux, Chataing and Protzenko, ICFP 2021](https://arxiv.org/abs/2103.03198)).

Source text: the Universal Credit Regulations 2013, from [legislation.gov.uk](https://www.legislation.gov.uk/uksi/2013/376/contents), which also publishes the legislation as structured XML.

### Labelling inputs

Every input carries two labels.

- **Controlled by:** the claimant, an employer, a decision maker, or nobody (for example, a child's age).
- **Checked by:** third-party data (employee earnings arrive from HMRC's Real Time Information feed), documentary evidence, or the claimant's own declaration.

Strategic questions use these labels to decide which variables the solver may choose, and on whose behalf. A candidate reform can change a label as well as a rule: verifying a declared input is a reform in the same sense as changing the taper.

### Why SMT remains the reasoning layer

Benefit rules are mostly piecewise-linear arithmetic over bounded values with many case splits. Questions about them are usually decidable, and an SMT solver answers them automatically. Z3's optimisation interface goes further than yes or no: it can find the household with the highest effective marginal rate, or the largest gain available from inputs the claimant controls. Running cvc5 alongside Z3 gives a cross-check.

Some strategic questions alternate quantifiers: "whatever the decision maker finds, is there a claimant choice that gains more than X?" These are harder for a solver than plain existence questions. Bounded input ranges should keep them workable, but this needs testing early.

Lean only becomes worthwhile when rates themselves become variables. The arithmetic then turns nonlinear, and penny rounding makes it nonlinear integer arithmetic, which is undecidable in general. Lean could also be used to prove that the Catala-to-SMT translation preserves meaning. Neither is needed for a first version.

### Where LLMs fit

LLMs are used to write rules, not to reason about them. LLM translations of legal text are known to introduce assumptions the source does not contain. So every drafted rule passes through independent checks:

- the Catala type checker and compiler
- assertions checked by the solver
- differential tests against PolicyEngine UK
- a human reading the diff against the regulation text

### Estimating impact

Decided by the project owner on 29 October 2026: the project does not build a population layer of its own. PolicyEngine UK already runs microsimulation on Family Resources Survey data, and a second one here would duplicate it.

- **Scale from cited official statistics.** Where a finding needs a sense of scale, it cites DWP's statistics, written answers and similar official sources, with their dates and limits, as [`docs/nil-months.md`](nil-months.md#35-scale) does for nil periods. A cited figure describes a population that the official source counted, which is rarely exactly a finding's class, so the docs say how the two differ.
- **A bridge to PolicyEngine UK, as a candidate.** A later milestone could hand a finding's region (the bounds on its inputs, as the solver states them) to PolicyEngine UK and ask how many weighted households fall inside. It is not built. PolicyEngine UK computes Universal Credit over a year (see the [mismatch log](mismatches.md), entry 2), so a region defined over assessment periods would need care to map.
- **Behaviour is an assumption.** How much AI raises take-up, optimisation or misrepresentation is not in any dataset. If a later milestone estimates it, it takes it as an explicit parameter and reports results across a range of values.

## First version scope

**In:**
- A meaningful slice of Universal Credit: standard allowance, child element, housing element, work allowance, taper, and the benefit cap.
- A small, fixed number of consecutive assessment periods (two or three), enough to show the effect of when pay falls.
- Labels on every input, and judgement points modelled as labelled inputs.
- A first set of structural queries: effective marginal rate peaks, cliff edges, and whether the rules cover every case.
- A first set of strategic queries: the gain available from claimant-controlled inputs, and the value of each judgement point.
- Differential tests against PolicyEngine UK for a set of generated households.

**Out, for now:**
- Longer time horizons, changes of circumstance beyond the fixed periods, and transitional protection. Bounded unrolling in SMT can handle these, but they could take over the whole project.
- Legacy benefits and Pension Credit.
- Lean.

## Publishing findings

The repository is public. Methods, models and findings about classes of input and rule are published, for example "this class of input is self-declared and worth up to £X a month to N households". Material that would work as a how-to for a particular claim stays out of the repository: worked guides to presenting evidence, or ranked lists of specific declarations to falsify. The tool is published as a method: a run for a fully fixed household prints the solver's example, which is what makes a figure checkable by replay, and the repository's documents give figures for classes and no per-household targets.

## Status of external tools (checked 28 October 2026)

- **Catala:** the compiler is at 1.x, maintained by the CatalaLang project. Updated 29 October 2026: the latest release is 1.3.0 (1 October 2026), not 1.2.0. No intermediate representation is documented as stable, and the supported way to read one is an OCaml compiler plugin. See the [milestone 1 design](superpowers/specs/2026-10-29-walking-skeleton-design.md).
- **PolicyEngine UK:** the Python model is actively maintained on PyPI. A Rust engine, [policyengine-uk-rust](https://policyengine.github.io/policyengine-uk-rust), with a Python wrapper (`policyengine-uk-compiled`), documents about 0.1 ms per household and covers Universal Credit, Child Benefit and other programmes. Decide which of the two to use as the oracle.
- **Research context:** a June 2026 preprint, [arXiv:2606.23913](https://arxiv.org/abs/2606.23913), proposes LLM translation into a language that extends Catala, checked by a verification kernel that uses an SMT solver. Useful background; not read in full.

## Open questions for design

Questions 1, 2, 3 and 7, and parts of 8 and 9, are answered for milestone 1 in the [walking skeleton design](superpowers/specs/2026-10-29-walking-skeleton-design.md) (29 October 2026). Question 6 is answered by the [quantifier tractability spike](spike-quantifier-tractability.md) (29 October 2026): at the first version's size (two periods) both forms are trivial for Z3 and cvc5, quantified queries degrade sharply with more free choices, and milestone 2 should expand judgement points into finite cases by default. Questions 4 and 5 are answered for milestone 2 under [Milestones](#milestones) (29 October 2026).

1. Which artefacts come first: the Catala rules, or a minimal SMT translator for a handful of hand-written rules?
2. Translate from which Catala intermediate representation, and how stable is it between releases?
3. How to model money: integer pence throughout, or exact rationals with rounding modelled explicitly?
4. Where do input labels live: in the Catala source, or in a separate file keyed by input name?
5. How to represent a judgement point: a free choice, a bounded range, or a choice with a probability attached?
6. Do strategic questions that alternate quantifiers stay tractable at the scale of the first version?
7. Which PolicyEngine engine to test against, and how to map its variables onto ours?
8. How to generate test households: random, solver-generated near boundaries, or drawn from FRS records?
9. How should findings be presented: a command-line report, notebooks, or pages suitable for writing up?

## Milestones

Each milestone is a thin slice through every layer, widened from the one before. Items that milestone 1's per-task and whole-branch reviews deferred are placed below under the milestone or pull request expected to deal with them, so that none is lost. Plans for later work are candidates, not commitments.

### Milestone 1: walking skeleton (done)

Merged on 29 October 2026. [Design](superpowers/specs/2026-10-29-walking-skeleton-design.md), [plan](superpowers/plans/2026-10-29-walking-skeleton.md).

### Milestone 2: the first strategic query (done)

Merged on 29 October 2026. Scope agreed the same day. [Design](superpowers/specs/2026-10-29-first-strategic-query-design.md), [plan](superpowers/plans/2026-10-29-first-strategic-query.md).

- **Built.** The refactors below, then input labels in `rules/uc.inputs.toml`, a housing costs element with the lower work allowance, judgement points expanded into cases, a timing query and a judgement value query in `bm.strategic` (Z3 optimises, cvc5 confirms, Catala's interpreter replays the example), their commands and report, and a differential check of the housing costs element against PolicyEngine UK. What the model leaves out, and the conditions on each finding, are in [model gaps](model-gaps.md).
- **Findings** (single claimant, rules as modelled, no specialist review; conditions in [model gaps](model-gaps.md#strategic-findings-and-their-conditions)):
  - Timing: while every award stays above nil, moving pay between two assessment periods gains at most 1p in the worst case over the limited capability for work (LCW) finding, and also 1p in each case. Z3 found it, cvc5 confirmed that no larger gain exists, and Catala's interpreter replayed the witness. One witness found was a claimant under 25 with a housing costs element; which household Z3 returns depends on its search, so another run may give a different one.
  - LCW value: up to 390.50 pounds a month with no housing costs element (55% of 710.00 pounds), and up to 234.85 pounds with an element above zero (55% of 427.00 pounds), where both awards stay above nil. Its smallest value is 0 pounds.
  - The housing costs element is bounded at 804.00 pounds a month so that no modelled household reaches the benefit cap (regulation 80A), which is not modelled.
- **Assumptions.** The five assumptions in the design were checked against DWP's *Advice for Decision Making* on 29 October 2026, and the outcomes are recorded under each in the design. None was contradicted, but assumption 1 is only partly supported: a nil award because of earnings ends the award, but regulation 54A blocks or reduces a nil-period gain only where earnings exceed the surplus earnings threshold. The guidance does not decide assumptions 2 (an element reduced to nil) or 5 (the rounding stage), and all five remain questions for an outside reviewer. The checks also corrected the surplus earnings threshold (below) and added two qualifications to [model gaps](model-gaps.md): the in-work gateway, which ties the LCW finding to earnings, and regulation 60 on notional earnings, which treats earnings the claimant has deprived themselves of for the purpose of securing or increasing universal credit as possessed. Whether deferring pay counts is the project's reading, for specialist review.
- **Lessons.** Recorded after the milestone was merged, 29 October 2026.
  - About the rules. Within a continuing award there is little to gain from the timing of pay: the award is concave in earnings, so an even split is already best and only rounding remains (1p). Any exposure from timing sits at nil months, where the end of the award, the reclaim and surplus earnings apply, and where the surplus earnings threshold is currently the higher 2,500 pound figure. How large a gain is possible there is not yet modelled.
  - About the rules. A housing costs element lowers the value of the LCW finding, because it brings in the lower work allowance. For a single claimant with no earnings outside Greater London, an element above about 804 pounds a month brings the award to the benefit cap, so the cap and its earnings exemption are another threshold for exposure queries.
  - About the method. A solver adds most where the rules have floors, thresholds or rules that cross periods. On the smooth parts of the rules the answer follows from the shape of the formula, as the timing result did.
  - About the method. A solver reports confidently from incomplete rules. Twice in this milestone an unmodelled rule would have produced a false gain: surplus earnings, caught in design, and the benefit cap, caught by the differential test against PolicyEngine UK. The guards are the [model gaps](model-gaps.md) register and bounding inputs so that unmodelled rules cannot apply. The differential test catches errors of scope as well as of arithmetic.
  - About the method. A judgement point can depend on other inputs: the in-work gateway ties the LCW finding to earnings. Later milestones may need constraints between inputs as well as labels on each.
  - About the method. Independent cross-checks earned their cost: a brute-force reference caught the plan's own test asking the wrong question, and solver timings varied enough that Z3's optimiser was replaced by a search of plain Z3 checks, still confirmed by cvc5. At two assessment periods, cvc5 could not settle one `forall` cross-check in 60 seconds (see the [quantifier spike](spike-quantifier-tractability.md#later-evidence)), which supports expanding judgement points into cases by default.

- **Query.** For a single claimant across two assessment periods: how much can the claimant gain by choosing when earnings fall between the two periods, whatever the decision maker finds on limited capability for work? And what is that finding worth on its own? The claimant's choice is how a fixed total of earnings is split between the periods. Splits are limited to those where the award stays above nil in both periods, because the end of an award after a nil period and the reclaim are not modelled (see [model gaps](model-gaps.md)). Regulation 54A does not block or reduce a gain through a nil period below the surplus earnings threshold, which is the nil UC threshold plus 2,500 pounds for a claim in respect of a period beginning on or before 31 March 2027 (the end of the temporary de minimis period as currently extended) and plus 300 pounds for a later period unless it is extended again (S.I. 2015/345 regulation 5, and the Secretary of State's [determination](https://www.gov.uk/government/publications/secretary-of-state-determination-under-regulation-5-of-the-universal-credit-surpluses-and-self-employed-losses-digital-service-amendment-regulatio--2/secretary-of-state-determination-under-regulation-5-of-the-universal-credit-surpluses-and-self-employed-losses-digital-service-amendment-regulatio), made 20 January 2026 and published on gov.uk 31 March 2026, checked 29 October 2026). That the 2,500 pounds covers a period beginning on 31 March 2027 itself is the project's reading of the determination's "will end on 31st March 2027" with regulation 5, which applies the higher threshold to a period beginning before the end of the temporary de minimis period; it is for specialist review. Regulation 60 on notional earnings is a separate possible limit. Within the limit, any gain comes from rounding.
- **Rules.** A housing costs element, taken as one monthly input, which adds to the maximum amount and brings in the lower work allowance. The Catala scope still covers one assessment period. The query calls it once for each period. A scope that covers several periods waits until a rule crosses periods.
- **Input labels (open question 4).** In `rules/uc.inputs.toml`, next to each input's bounds: who controls the input, and how it is checked.
- **Judgement points (open question 5).** An input labelled as controlled by a decision maker is a judgement point. It is a Boolean or a small enumeration, and queries expand it into its cases, as the [quantifier spike](spike-quantifier-tractability.md) recommends: `forall` is kept only as a cross-check on small instances, and the number of judgement points and free choices in a query is capped. Probabilities are left out for now.
- **Refactors first.** These are needed before adding inputs:
  - A shared units module. `EPOCH` is defined in six modules, and pounds and pence are converted in four different ways (`bounds`, `catala_run`, `policyengine`, `report`).
  - A single builder for a valid household. Declaring the input constants, bounding them and asserting that no obligation holds is written out four times (`coverage`, `queries.emr`, `households.last_penny_earnings`, `evaluate`). The "Z3 optimises, cvc5 confirms" pattern appears twice, with different handling of *unknown*.
  - Input names read from `uc.inputs.toml`. They are currently hard-coded in `households`, `checks.run`, `policyengine` and `cli`.
  - Document the `.defined` flag on `SmtModule` and `Obligation`. It is true at `error_on_empty` sites even where Catala raises an error, so every query must assert that no obligation holds.
- **Translator.** cvc5 rejects a unary `(+ x)`, so a sum with one term must be special-cased. The translator never writes a unary `+`, because Catala's additions are binary. The special case lives in `bm.household.smt_sum`, where the query code builds sums.
- **Report and CLI.** A top-level indicator in the JSON report that a result was *unknown*, and CLI tests for exit status 1 when the solvers disagree and for exit statuses 1 and 2 from coverage.
- **PolicyEngine UK.** Map the housing costs element, so that differential tests cover the new rules. PolicyEngine works out the element from rent and tenure. The mapping does not use those: it sets PolicyEngine's `uc_housing_costs_element` directly to our input, as it sets earned income (see `bm.policyengine`).

### Milestone 3: nil assessment periods (done)

Merged on 30 October 2026. [Design](superpowers/specs/2026-10-29-nil-assessment-periods-design.md), [plan](superpowers/plans/2026-10-29-nil-assessment-periods.md), and the research note on [nil assessment periods](nil-months.md).

- **Built.** The items carried forward from the milestone 2 reviews, done first with behaviour unchanged. Then, in `rules/uc.catala_en`, a step scope `WindowStep` that carries the award's state from one period to the next (the end of an award at a nil period, claims under regulation 32A for up to 5 months, and surplus earnings under regulation 54A), chained by `ClaimWindow` over 3 periods, with `ClaimWindow4` to `ClaimWindow6` for the probe only. The exporter inlines sub-scopes (bm-ir version 1, [`docs/bm-ir.md`](bm-ir.md)). The translator gained a relaxed mode for probes. A window query in `bm.window` reports the gain, loss, spread and extra payday figures for each case of DWP's three new judgement points, with replay through Catala and an independent reference in the tests. A [scaling probe](spike-window-scaling.md) measured solver time from 3 to 6 periods. What the model leaves out is in [model gaps](model-gaps.md), and why windows with a nil period are not compared with PolicyEngine UK is entry 2 of the [mismatch log](mismatches.md).
- **Findings** (30 October 2026; single claimant, exact rules over 3 periods starting 6 April 2026, every period on or before 31 March 2027, a housing costs element of up to 804.00 pounds, earnings of up to 10,000 pounds a period, the last-period rule (the last period's award at least 1p, applied as model gaps sets out), no specialist review; all conditions, the figures for every case and the caveats are in [model gaps](model-gaps.md#milestone-3-the-timing-of-pay-over-a-window-with-nil-periods)):
  - In the realistic cases (a claim after the award ends, each failed month counted, an LCW finding kept), the timing of a fixed total of earnings over 3 periods can raise the award by up to 1,375.02 pounds against an even split, with or without an LCW finding. That is 2p more than 55% of the 2,500 pounds added to the nil UC threshold to give the relevant threshold for surplus earnings, which on the project's reading is what bounds it; on the project's reading, the 2p comes from rounding: each period's earnings deduction is rounded to the penny (regulation 6, as the rules read it), and so is the nil UC threshold.
  - In the same cases it can lower the award by up to 469.71 pounds with an LCW finding (in the solver's example, two periods' unused work allowance) and 2p without. For a claimant paid every four weeks with an LCW finding, a period with two paydays (the pattern P, 2P, P) pays from 731.87 pounds more to 195.25 pounds less over the window than the same four payments spread evenly.
  - Where no claim is made after the award ends, the gain is 2p, with or without an LCW finding, and the loss is at least 2,927.49 pounds with an LCW finding and at least 2,457.81 pounds without, lower bounds because the loss carries on past the window. Two figures in stress cases are *unknown* after 600 seconds.
  - A figure says what the rules would pay for a pattern of reported earnings, not that the pattern is open to a claimant: regulation 60 on notional earnings and regulation 61(6) on two monthly payments in one period may limit it (see [model gaps](model-gaps.md)).
- **Assumptions for review.** The seven in the design, each the project's reading from the cited sources, made by AI research agents and checked at source by a second agent. Two rulings during execution settled points in them: each surplus is measured against the thresholds of the period whose earnings are measured (which matters only where an LCW finding is lost), and the nil UC threshold is the maximum amount divided by 0.55, rounded once, plus the work allowance.
- **Direction on population questions** (decided by the project owner on 29 October 2026): no population layer of the project's own; see [Estimating impact](#estimating-impact).

### Tidy-up between milestones

The items deferred from the milestone 1 and 2 reviews were fixed in one pull request after milestone 2, and the ones that touched the milestone 3 code were done at the start of milestone 3. Outstanding:

- Lines over 100 columns in the Python sources and tests. No linter is configured, so nothing enforces a limit; configure one and reflow, or drop the limit.

### Candidates for later milestones

Gaps in the model, and how each limits findings, are recorded in [model gaps](model-gaps.md). Remediation is planned from there.

- **The rounding stage.** The stage at which regulation 6 rounds is an open question with three readings on record ([mismatch log](mismatches.md), entry 1). A query could make the rounding stage a parameter and have the solver bound how far the readings can disagree.
- **Rules that cross assessment periods.** Modelled in milestone 3 for a window of 3 periods, within the limits in [model gaps](model-gaps.md#the-windows-limits). Still open: longer windows (the [scaling probe](spike-window-scaling.md) measured solver time up to 6 periods on one household), periods after 31 March 2027 and chains of claims that cross that date, and regulation 61(6) reallocation.
- **How nil months work in practice.** Answered by [`docs/nil-months.md`](nil-months.md) (29 October 2026): how an award ends after a nil period, how DWP handles the claims treated as made under [regulation 32A](https://www.legislation.gov.uk/uksi/2013/380/regulation/32A) of the Claims and Payments Regulations in the months that follow, the evidence on scale, and what claimants and advice agencies have reported. Its section 4 lists what remains unresolved, and its "Sources not reached" the sources it could not reach or did not find (among them two House of Commons Library briefings, and any Work and Pensions Committee report).
- **Other strategic queries considered for milestone 2:** when pay falls, with the couple finding as the judgement point (needs joint claims, and a comparison of one joint claim with two single claims); and when self-employed receipts fall, with the "gainful self-employment" finding as the judgement point (needs the minimum income floor and the rules on self-employed earnings).
- **The rest of the first version's rules:** income tax and National Insurance, the benefit cap and its earnings exemption, children, couples, and a fuller housing calculation (weekly rent, under-occupancy, the Local Housing Allowance).
- **Translator gaps that this later content will reach:**
  - Corrected 29 October 2026 (the [milestone 3 plan](superpowers/plans/2026-10-29-nil-assessment-periods.md), ruling 1). This entry said that decimal rates with no terminating decimal form, such as 52/12 for converting weekly amounts to monthly, are written in a form that Z3's linearity check rejects. That does not reproduce: Z3 5.3.2 and cvc5 1.4.2 accept the translator's form, `bm_round` of the exact product or quotient of the money and a rational constant (for example `(* (to_real m) (/ 20.0 11.0))`), with plain checks, and `tests/test_translate.py` pins it for 20/11 and 11/20. The nil UC threshold, which divides by 0.55, uses it. It is no longer a gap.
  - A zero divisor in an unreachable division is refused, and Catala's `DivisionByZero` is not modelled as an obligation.
