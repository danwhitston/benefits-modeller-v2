# Spike: are alternating-quantifier queries tractable?

Run on 29 October 2026, on an Apple Silicon Mac. Z3 5.3.2 and cvc5 1.4.2, both through their Python APIs (`z3-solver` and `cvc5` from the repo lockfile, Python 3.14.10). Timings are wall-clock seconds for one run each, measured inside the solver process (parse plus solve), with a 60-second limit per run. The code is on the unmerged branch `spike-quantifiers` (`spike/`).

## The question

Milestone 2 will ask strategic questions of the form "whatever the decision maker finds, is there a choice the claimant can make that gains more than X?". That is an existential choice followed by a universal one over a judgement point. The spike asks two things:

1. At the size of the first version, can Z3 and cvc5 answer such a query using `forall`?
2. If they can, is expanding the judgement point into its finite cases (form B) any better or worse?

It also asks, as a probe beyond that size, where each form stops being practical.

## The model

Hand-written SMT-LIB, using the same encoding as the translator: money is `Int` pence, decimals are exact `Real`, and money times a rate is `bm_round(to_real(m) * r)` rounded to the nearest penny, with halves rounded away from zero.

- Two monthly assessment periods. Total earnings across both periods is a parameter, and the claimant chooses how it is split (whole pounds in the first period). The even split is the baseline.
- One judgement point, "is the claimant part of a couple?", as a Boolean.
- Award per period: `max(0, standard allowance - deduction)`, where the deduction is 55% of earnings above the work allowance of 710.00 (reg. 22). The work allowance is assumed to apply.
- Standard allowance (reg. 36): 424.90 for a single claimant aged 25 or over, 666.97 for joint claimants where either is aged 25 or over. For a couple, earnings are combined and one work allowance applies, so the couple case differs from the single case only in the allowance.
- Query: is there a split such that, for every value of the judgement point, the two-period award exceeds the even-split award by more than X?
- Form A asserts `(forall ((couple Bool)) (> gain X))`. Form B asserts the same body twice, once with `true` and once with `false`, joined by `and`. The claimant's choice is a free constant in both, so the alternation is exists-forall.

Sources: Universal Credit Regulations 2013, regulation 36 (<https://www.legislation.gov.uk/uksi/2013/376/regulation/36>), checked on legislation.gov.uk on 29 October 2026. The page shows the figures as substituted by S.I. 2026/113 from 6 April 2026. The single figure of 424.90 and the work allowance and taper from regulation 22 are as in the walking-skeleton design, checked the same day.

Files: `form_a.smt2`, `form_b.smt2`, `run.py`, with results in `results.json` and `results_scale.json`.

## Correctness checks

- Every grid point was also answered by an independent brute-force reference in plain Python (exact `Fraction` arithmetic, all splits tried).
- Every `sat` answer returned a split, which was re-checked against the reference for both values of the judgement point.
- `unsat` answers cannot be checked that way beyond the reference at two periods. At more periods they are only checked for agreement between solvers and forms.

## Timings: the first-version size (two periods)

Grid of 6 earnings totals by 8 values of X, 48 points. The grid straddles the boundary: 14 points are `sat` and 34 are `unsat`. Both solvers and both forms finished every point, well inside the limit.

| Solver and form | Min (s) | Median (s) | Max (s) |
|---|---|---|---|
| Z3, A (`forall`) | 0.003 | 0.004 | 0.015 |
| cvc5, A (`forall`) | 0.008 | 0.010 | 0.015 |
| Z3, B (expanded) | 0.003 | 0.004 | 0.004 |
| cvc5, B (expanded) | 0.005 | 0.006 | 0.006 |

Disagreements: none. All 192 runs returned `sat` or `unsat`; all four configurations agreed with each other and with the reference at all 48 points.

## Timings: scaling probe

The probe was added because the first-version size is too small to separate the two forms. It varies the number of periods N (2, 4 or 12, each with one free pay amount per period) and the number of Boolean judgement points k (1 to 8). Point 1 is the couple finding. Each further point adds a fixed amount to the standard allowance, as a stand-in for more findings. Form B has 2^k cases. Two values of X per size, with average earnings fixed per period. That is 30 points (3 values of N, 5 of k, 2 of X), each run on both solvers in both forms.

Summary by number of periods, each row covering 10 points (the full data is in `results_scale.json`):

| Periods | Form A, Z3 | Form A, cvc5 | Form B, Z3 | Form B, cvc5 |
|---|---|---|---|---|
| 2 | all done, at most 0.02 s | all done, at most 0.02 s | all done, at most 0.014 s | all done, at most 0.10 s |
| 4 | 9 of 10 done, nine of them within 0.4 s except one at 9.7 s; one timeout | all done, at most 0.25 s | all done, at most 0.16 s | all done, at most 0.70 s |
| 12 | 2 of 10 done (0.2 to 0.3 s), 8 timeouts | 0 of 10 done, 10 timeouts | 7 of 10 done, from 0.05 s to 3.3 s, 3 timeouts | 9 of 10 done, from 0.17 s to 58.8 s, one timeout |

Detail for 12 periods (the interesting row), times in seconds, T/O is a 60-second limit reached with status `unknown`:

| k | X | Z3, A | cvc5, A | Z3, B | cvc5, B |
|---|---|---|---|---|---|
| 1 | 100 | 0.22 | T/O | 0.30 | 0.17 |
| 1 | 300 | T/O | T/O | 0.23 | 0.68 |
| 2 | 100 | 0.26 | T/O | 0.05 | 0.37 |
| 2 | 300 | T/O | T/O | 0.26 | 0.92 |
| 4 | 100 | T/O | T/O | 0.70 | 0.65 |
| 4 | 300 | T/O | T/O | T/O | 2.8 |
| 6 | 100 | T/O | T/O | T/O | 58.8 |
| 6 | 300 | T/O | T/O | 3.3 | 17.8 |
| 8 | 100 | T/O | T/O | T/O | T/O |
| 8 | 300 | T/O | T/O | 1.8 | 22.7 |

Disagreements across all 30 scaling points: none among the answers that were returned, and every returned `sat` model passed the independent re-check. Timeouts came back as `unknown`, never as a wrong answer.

## Findings

1. **At two periods the question is trivial for both solvers and both forms.** Milliseconds, no disagreements, no need for care.
2. **The quantified form degrades first, and sharply, as the number of free choices grows.** With one judgement point, Form A is fine at 2 periods, mostly fine at 4, but fails to finish on most runs at 12 periods (Z3 finishes 2 of 10, cvc5 none), even with k = 1, where Form B finishes in under a second on both solvers. The quantifier itself is the cost, not the size of the arithmetic.
3. **Expansion holds up much further but is not free.** Its cost grows with 2^k as well as with the number of periods. At 12 periods and k of 4 or more, some runs time out and times spread from under a second to nearly a minute. The two solvers differ on which instances are hard (Z3 is often faster, cvc5 finished more of them within the limit). Neither is uniformly better.
4. **Run-to-run variation is large on a single instance.** One Z3 Form A run at 4 periods took 9.7 s where a neighbouring instance of the same size took 0.06 s, and another timed out. A single timing is not a benchmark. Treat the 12-period results as qualitative.
5. **Parsing differences matter to the translator.** cvc5 rejects a unary `(+ x)`, which Z3 accepts. A translator that emits n-ary sums must special-case n = 1. This was found by the spike, and is a reason to keep both solvers in the loop for emitted text.
6. **`unknown` must stay a first-class result.** Timeouts are frequent at the larger sizes. Reading one as "no such choice exists" would give a wrong answer. The design already says this; the spike confirms it matters.

## Limits of this spike

- One toy model, with all judgement points Boolean and independent, and a convex piecewise-linear award. Real rules will have more interacting conditions, which can make either form harder or easier.
- One run per instance, one machine, no tuning of solver options, and no use of incremental solving or quantifier-instantiation settings.
- Only the 2-period grid is a designed test of the first-version question; the 4- and 12-period results are a probe.
- Variables that range over larger domains than Booleans (an integer-valued finding, say) were not tried.

## Recommendation for milestone 2

Expand the judgement points into finite cases (Form B) as the default way to emit strategic queries, and do not rely on `forall` for answers.

- Judgement points are finite by construction (Booleans or small enumerations), so the translator can enumerate them. The cost is 2^k conjuncts, so keep the number of judgement points in a single query small (in the probe, k up to 8 was often workable with expansion, but timeouts began at k of 4 when the claimant had many free choices), and reject or warn above a configured limit.
- Keep the quantified form (Form A) only as a cross-check on small instances, since it is the cheaper way to confirm the expansion is written correctly, and it is fine at two periods.
- Report `unknown` as `unknown`. Run both Z3 and cvc5 on queries that are expensive, since neither dominates, and accept the first definite answer if the two never disagree on a definite one.
- Plan to limit the claimant's free choices per query (a few periods, or a coarse grid of choices) rather than leaving one free integer per period. Where more is needed, an untested alternative worth a short follow-up is a guess-and-check loop: propose a choice, check it against each case separately, and add the failed case as a constraint.
- If milestone 2 needs more than about 4 periods with free choices in a single query, run a larger benchmark first, with repeated runs, before committing to a design.
