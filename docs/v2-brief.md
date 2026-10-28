# benefits-modeller v2: brief

Starting input for design. It records the direction chosen so far and the questions still open. The detailed design and plan come later and build on it.

Written 28 October 2026. Claims about external tools are dated, because they will go stale.

## Background

[benefits-modeller](https://github.com/danwhitston/benefits-modeller) (v1) was an MSc project. It defined Ben, a small language for UK benefit rules, with an ANTLR4 grammar, a Python parser and a runner that translated rules into Z3 constraints. It showed that a solver can answer questions about a rule set, but it had a hand-built language, a small sample of rules and no link from each rule back to its legal source.

v2 keeps v1's two core ideas: a dedicated language for the rules, and an SMT solver for asking questions about them. It changes how each part is built.

## Two kinds of question

1. **Population questions.** What does a reform cost? Who gains and who loses? How many households are affected? These need survey microdata, not proofs.
2. **Structural questions.** Does any household face an effective marginal rate above 100%? Where are the cliff edges? Can two rules conflict? Is there an income range where earning more leaves a household worse off? These are "for all" and "there exists" questions, and they are what a solver is for.

v2 aims at both. The solver finds the problem regions, and microdata estimates how many real households sit in them.

## Proposed architecture

| Layer | Choice | Role |
|---|---|---|
| Rules | [Catala](https://catala-lang.org/), English syntax | The benefit rules, written as literate code alongside the regulation text they implement |
| Authoring | Claude Code drafting Catala from regulation text | Speeds up writing rules; the compiler, tests and a human review of each diff keep it honest |
| Analysis | Translator from Catala's intermediate representation to SMT-LIB, run with Z3 and cvc5 | Answers structural questions, with a concrete example household for each finding |
| Oracle and population | [PolicyEngine UK](https://policyengine.org/uk) | Differential testing of the rules, and weighting findings by Family Resources Survey households |
| Optional | Lean | One or two theorems that need parameters as variables, such as monotonicity of net income for any taper rate |

### Why Catala rather than a new grammar

Catala uses default logic: a base rule plus prioritised exceptions. UK regulations are drafted the same way. It is literate, so each block of code sits next to the legal text it implements, which gives the traceability v1 lacked. Its authors used it to formalise part of French family benefits and report finding a bug in the official implementation along the way ([Merigoux, Chataing and Protzenko, ICFP 2021](https://arxiv.org/abs/2103.03198)).

Source text: the Universal Credit Regulations 2013, from [legislation.gov.uk](https://www.legislation.gov.uk/uksi/2013/376/contents), which also publishes the legislation as structured XML.

### Why SMT remains the reasoning layer

Benefit rules are mostly piecewise-linear arithmetic over bounded values with many case splits. Questions about them are usually decidable, and an SMT solver answers them automatically. Z3's optimisation interface goes further than yes or no: it can find the household with the highest effective marginal rate under given constraints. Running cvc5 alongside Z3 gives a cross-check.

Lean only becomes worthwhile when rates themselves become variables. The arithmetic then turns nonlinear, and penny rounding makes it nonlinear integer arithmetic, which is undecidable in general. Lean could also be used to prove that the Catala-to-SMT translation preserves meaning. Neither is needed for a first version.

### Where LLMs fit

LLMs are used to write rules, not to reason about them. LLM translations of legal text are known to introduce assumptions the source does not contain. So every drafted rule passes through independent checks:

- the Catala type checker and compiler
- assertions checked by the solver
- differential tests against PolicyEngine UK
- a human reading the diff against the regulation text

## First version scope

**In:**
- A meaningful slice of Universal Credit: standard allowance, child element, housing element, work allowance, taper, and the benefit cap.
- A single assessment period.
- A first set of structural queries: effective marginal rate peaks, cliff edges, and whether the rules cover every case.
- Differential tests against PolicyEngine UK for a set of generated households.

**Out, for now:**
- Time: multiple assessment periods, changes of circumstance, transitional protection. Bounded unrolling in SMT can handle these, but they could take over the whole project.
- Legacy benefits and Pension Credit.
- Lean.

## Status of external tools (checked 28 October 2026)

- **Catala:** the compiler is at 1.x (1.2.0 is the latest release found), maintained by the CatalaLang project. Check the state of the English syntax and of the intermediate representation's documentation before designing the translator.
- **PolicyEngine UK:** the Python model is actively maintained on PyPI. A Rust engine, [policyengine-uk-rust](https://policyengine.github.io/policyengine-uk-rust), with a Python wrapper (`policyengine-uk-compiled`), documents about 0.1 ms per household and covers Universal Credit, Child Benefit and other programmes. Decide which of the two to use as the oracle.
- **Research context:** a June 2026 preprint, [arXiv:2606.23913](https://arxiv.org/abs/2606.23913), proposes LLM translation into a language that extends Catala, checked by a verification kernel that uses an SMT solver. Useful background; not read in full.

## Open questions for design

1. Which artefacts come first: the Catala rules, or a minimal SMT translator for a handful of hand-written rules?
2. Translate from which Catala intermediate representation, and how stable is it between releases?
3. How to model money: integer pence throughout, or exact rationals with rounding modelled explicitly?
4. Which PolicyEngine engine to test against, and how to map its variables onto ours?
5. How to generate test households: random, solver-generated near boundaries, or drawn from FRS records?
6. How should findings be presented: a command-line report, notebooks, or pages suitable for writing up?
