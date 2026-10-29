# Mismatch log

Each entry is a class of household where PolicyEngine UK's award differs from
our rules, triaged against the regulation text. `bm.checks.run` returns every
such household. None is filtered out. An entry gives the household, the three
figures (Catala, Z3, PolicyEngine), the regulation, the classification and the
date.

Classifications: our error (logged, then fixed in the rules), PolicyEngine's
error, deliberate difference, or interpretation difference.

## 1. Rounding stage of the earnings deduction

- **Classification:** interpretation difference: rounding stage (open question).
- **Date:** 29 October 2026. policyengine-uk 2.164.2, Catala 1.3.0.
- **Which households:** those where earnings above the work allowance, in
  pence, are 10 (mod 20). 55% of such an amount ends in exactly half a penny.
  The check is the predicate `bm.checks.rounding_stage_difference`, which also
  requires PolicyEngine's award to be exactly 1p above ours.
- **Worked household:** assessment period from 1 May 2026, aged 25 or over,
  limited capability for work, earned income £710.10 a month.

| | Catala | Z3 | PolicyEngine UK, rounded once by bm |
|---|---|---|---|
| Award | £424.84 | £424.84 | £424.85 |

PolicyEngine UK does not round the award. It returns an annual float, here
£424.845 a month to within float precision. The check rounds that figure
once, to the nearest penny with halves rounded up (`bm.policyengine._to_pence`),
which is reading (b) below.

Arithmetic. Earnings above the £710.00 work allowance are £0.10, and 55% of
that is 5.5p. Three readings are on record:

- (a) Round each calculated amount (our rules). The deduction of 5.5p becomes
  6p, and £424.90 - £0.06 = £424.84.
- (b) Round only the final award (PolicyEngine UK's figure, as the check
  rounds it). £424.90 - £0.055 = £424.845, which becomes £424.85.
- (c) Resolve half-penny ties in the claimant's favour: a deduction with a
  fraction of exactly half a penny is rounded down, and an addition is rounded
  up. The deduction of 5.5p becomes 5p, and £424.90 - £0.05 = £424.85.

In this skeleton, (c) gives the same figures as (b), because there is a single
fractional step, so the skeleton cannot tell them apart. They diverge only when
several fractional amounts combine, which is expected in later milestones.

Regulations, checked 29 October 2026:

- [Regulation 6(1)](https://www.legislation.gov.uk/uksi/2013/376/regulation/6)
  of the Universal Credit Regulations 2013 rounds a fraction of a penny arising
  in "the calculation of an amount" for the purposes of the Regulations. It
  sets the direction of rounding (half a penny or more is "treated as a
  penny"), but not the stage at which it applies, so its wording fits (a) and
  (b) equally. No provision establishing (c) has been checked.
- [Regulation 22(1)(b)](https://www.legislation.gov.uk/uksi/2013/376/regulation/22)
  deducts 55% of the earned income above the work allowance. This project
  reads that deduction as an amount whose calculation regulation 6(1)
  rounds, a reading the project adopted on 29 October 2026, pending review by
  a benefits specialist (see "No specialist review" in `docs/model-gaps.md`),
  so the rules round it and the award follows from the rounded figure.

Other sources.
[DWP staff guidance deposited in Parliament](https://data.parliament.uk/DepositedPapers/Files/DEP2024-0673/196_Work_Allowance_and_Earnings_Taper_rate.pdf)
(DEP2024-0673, "Work Allowance and Earnings Taper rate", dated 8 May 2024,
checked 29 October 2026) says that earnings above the work allowance are
multiplied by 55% "to give an amount to be taken into account". It says
nothing about rounding. How DWP's own system rounds cannot be observed from
outside.

Decision: the project keeps rounding the deduction, reading (a). The question
stays open. If it is settled in favour of (b) or (c), the rules in
`rules/uc.catala_en` change (rounding moves to the award, or ties go to the
claimant). This class of mismatch then becomes our error, and
`bm.checks.rounding_stage_difference` is deleted.

Count, 29 October 2026: `test_checks_exact_match` (98 households,
`n_random=50, seed=1`) finds 3 mismatches, and all 3 are in this class. The
test also checks the count and the three households below, so a change to the
draw or the rules that changes them fails it until this entry is updated. All
three have limited capability for work, and earnings above the work allowance
that end in a half penny when taken at 55%. One is the table row above, with no
housing costs element and the £710.00 work allowance. Two have a housing costs
element, so the lower work allowance of £427.00 applies (regulation 22(2)):
the Catala test row with a £500.00 element, and one random household.

| Start | Earnings | Age 25 or over | LCW | Housing costs element | Work allowance | Catala | Z3 | PolicyEngine UK, rounded once by bm |
|---|---|---|---|---|---|---|---|---|
| 2026-05-01 | £710.10 | yes | yes | £0.00 | £710.00 | £424.84 | £424.84 | £424.85 |
| 2026-05-01 | £427.10 | yes | yes | £500.00 | £427.00 | £924.84 | £924.84 | £924.85 |
| 2026-12-12 | £1,920.90 | yes | yes | £485.65 | £427.00 | £88.90 | £88.90 | £88.91 |

The housing costs element is bounded at £804.00 a month in
`rules/uc.inputs.toml`, so that no modelled household reaches the benefit cap,
which the rules do not model. See the benefit cap in `docs/model-gaps.md`.
