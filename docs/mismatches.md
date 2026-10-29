# Mismatch log

Each entry is a class of household where PolicyEngine UK's award differs from
our rules. `bm.checks.run` returns every such household. None is filtered out.
An entry gives the household, the three figures (Catala, Z3, PolicyEngine),
the regulation, the classification and the date.

Classifications: our error (fixed, not logged here), PolicyEngine's error,
deliberate difference, or interpretation difference.

## 1. Rounding stage of the earnings deduction

- **Classification:** interpretation difference: rounding stage (open question).
- **Date:** 29 October 2026. policyengine-uk 2.164.2, Catala 1.3.0.
- **Which households:** those where earnings above the work allowance, in
  pence, are 10 (mod 20). 55% of such an amount ends in exactly half a penny.
  The check is the predicate `bm.checks.rounding_stage_difference`, which also
  requires PolicyEngine's award to be exactly 1p above ours.
- **Worked household:** assessment period from 1 May 2026, aged 25 or over,
  limited capability for work, earned income £710.10 a month.

| | Catala | Z3 | PolicyEngine UK |
|---|---|---|---|
| Award | £424.84 | £424.84 | £424.85 |

Arithmetic. Earnings above the £710.00 work allowance are £0.10, and 55% of
that is 5.5p.

- Our rules round the deduction: 5.5p becomes 6p, and £424.90 - £0.06 = £424.84.
- PolicyEngine UK rounds only the award: £424.90 - £0.055 = £424.845, which
  becomes £424.85.

Regulations, checked 29 October 2026:

- [Regulation 6(1)](https://www.legislation.gov.uk/uksi/2013/376/regulation/6)
  of the Universal Credit Regulations 2013 rounds a fraction of a penny arising
  in "the calculation of an amount" for the purposes of the Regulations. It
  does not say at which stage.
- [Regulation 22(1)(b)](https://www.legislation.gov.uk/uksi/2013/376/regulation/22)
  deducts 55% of the earned income above the work allowance. Our rules read
  that deduction as a calculation of an amount, so they round it, and the award
  follows from the rounded figure.

Other sources. DWP staff guidance deposited in Parliament in May 2024
(DEP2024-0673, "Work Allowance and Earnings Taper rate") describes the taper
result as an amount to be taken into account, without stating a rounding
stage. How DWP's own system rounds cannot be observed from outside.

Decision: the project keeps rounding the deduction. The question stays open.
If it is settled the other way, `rounding_stage_difference` and this entry are
the only things to change.

Count: in `test_checks_exact_match` (73 households, `n_random=50, seed=1`),
1 mismatch, and it is this one (the table row above).
