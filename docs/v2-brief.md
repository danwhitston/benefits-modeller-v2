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

The solver finds the problem regions, and microdata estimates how many real households sit in them.

## Proposed architecture

| Layer | Choice | Role |
|---|---|---|
| Rules | [Catala](https://catala-lang.org/), English syntax | The benefit rules, written as literate code alongside the regulation text they implement |
| Input labels | Metadata on every input | Who controls the input, and how it is checked |
| Authoring | Claude Code drafting Catala from regulation text | Speeds up writing rules; the compiler, tests and a human review of each diff keep it honest |
| Analysis | Translator from Catala's intermediate representation to SMT-LIB, run with Z3 and cvc5 | Answers structural and strategic questions, with a concrete example household for each finding |
| Oracle and population | [PolicyEngine UK](https://policyengine.org/uk) | Differential testing of the rules, and weighting findings by Family Resources Survey households |
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

PolicyEngine UK's microdata says how many households sit near each weak point. How much AI raises take-up, optimisation or misrepresentation is not in any dataset. It is an assumption, so the model takes it as an explicit parameter and reports results across a range of values.

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

The repository is public. Methods, models and findings about classes of input and rule are published, for example "this class of input is self-declared and worth up to £X a month to N households". Material that would work as a how-to for a particular claim stays out of the repository: worked guides to presenting evidence, or ranked lists of specific declarations to falsify.

## Status of external tools (checked 28 October 2026)

- **Catala:** the compiler is at 1.x, maintained by the CatalaLang project. Updated 29 October 2026: the latest release is 1.3.0 (1 October 2026), not 1.2.0. No intermediate representation is documented as stable, and the supported way to read one is an OCaml compiler plugin. See the [milestone 1 design](superpowers/specs/2026-10-29-walking-skeleton-design.md).
- **PolicyEngine UK:** the Python model is actively maintained on PyPI. A Rust engine, [policyengine-uk-rust](https://policyengine.github.io/policyengine-uk-rust), with a Python wrapper (`policyengine-uk-compiled`), documents about 0.1 ms per household and covers Universal Credit, Child Benefit and other programmes. Decide which of the two to use as the oracle.
- **Research context:** a June 2026 preprint, [arXiv:2606.23913](https://arxiv.org/abs/2606.23913), proposes LLM translation into a language that extends Catala, checked by a verification kernel that uses an SMT solver. Useful background; not read in full.

## Open questions for design

Questions 1, 2, 3 and 7, and parts of 8 and 9, are answered for milestone 1 in the [walking skeleton design](superpowers/specs/2026-10-29-walking-skeleton-design.md) (29 October 2026). Question 6 gets a separate spike in that milestone. Questions 4 and 5 stay open until milestone 2.

1. Which artefacts come first: the Catala rules, or a minimal SMT translator for a handful of hand-written rules?
2. Translate from which Catala intermediate representation, and how stable is it between releases?
3. How to model money: integer pence throughout, or exact rationals with rounding modelled explicitly?
4. Where do input labels live: in the Catala source, or in a separate file keyed by input name?
5. How to represent a judgement point: a free choice, a bounded range, or a choice with a probability attached?
6. Do strategic questions that alternate quantifiers stay tractable at the scale of the first version?
7. Which PolicyEngine engine to test against, and how to map its variables onto ours?
8. How to generate test households: random, solver-generated near boundaries, or drawn from FRS records?
9. How should findings be presented: a command-line report, notebooks, or pages suitable for writing up?
