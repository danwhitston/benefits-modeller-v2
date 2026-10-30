# Spike: how does solver time grow with the length of the claim window?

Run on 30 October 2026, on one Apple Silicon Mac (M4 Pro, macOS 27.0.1). Z3 5.3.2 and cvc5 1.4.2, both through their Python APIs (`z3-solver` and `cvc5` from the repo lockfile), Catala 1.3.0, Python 3.14.10. Timings are wall-clock seconds for one call of `bm.window.window` per row, with a 60-second limit on each Z3 search and on cvc5's confirmation. The code is `scripts/probe_window.py`, run by `make probe`. The rows are in `build/probe-window.json`, which git ignores, so they are not published; the tables below are the summary.

These are measurements of solver time. They are not findings about Universal Credit, and no award or gain from the runs is reported here. A relaxed row is not the rules at all (see below).

## The question

The window query takes the rules over 3 consecutive assessment periods. Later milestones may want longer windows, and the Catala scopes `ClaimWindow4` to `ClaimWindow6` exist so that this can be measured. Two questions:

1. How does the time to optimise a figure grow as the window goes from 3 to 6 periods?
2. How much of that time goes with the exact translation, as against the relaxed one? The exact translation rounds money to the penny at the stages the regulations name, which may make the constraints harder. The relaxed translation (`translate(scope, relaxed=True)`) drops the rounding and treats money as `Real`, so it differs in the sort of money as well as in the rounding, and the probe cannot separate the two. If the exact translation costs a great deal more, a later milestone could search on the relaxed model and confirm on the exact one. Slicing the translation to the definitions an objective depends on is another lever, and the probe does not measure it. Neither is built here.

## The method

- **Household and case.** One household, H: aged 25 or over, with limited capability for work, and a housing costs element of 804 pounds. The realistic case is fixed (a claim after the end of an award, a claim each month, the limited capability finding carried over), so each row is one optimisation. The first period starts on 6 April 2026 and later periods follow one calendar month apart.
- **Figures.** Gain and loss. The payday figures are refused beyond 3 periods, and the spread repeats the same kind of search, so the probe uses neither.
- **Rows.** 80: periods 3, 4, 5 and 6, by exact and relaxed, by seeds 1 to 5, by gain and loss. The seed sets Z3's `smt.random_seed` and cvc5's `seed` for every check in the row. Four rows were run a second time at the same seed (exact gain at 6 periods, seed 2; exact gain at 5, seed 4; relaxed gain at 3, seed 3; relaxed gain at 4, seed 3): each made the same number of Z3 checks and found the same value, and wall time differed by 0.01 to 0.2 s. That is a spot check of four rows, not a test of every row.
- **What a row times.** The call to `window`, which builds the scripts, runs Z3's search and then cvc5's confirmation (see `bm.solvers.optimise_and_confirm`). Loading the module and translating it are not timed. The Z3 checks are the satisfiability checks of that search: one for a first model, then checks that gallop away from the best value found and bisect, until Z3 proves nothing better exists. Z3 starts from a new context for every check.
- **Relaxed rows.** A relaxed objective is a `Real`, so the value a row reports is the integer that the search proves reachable (the floor of the supremum), not the optimum itself. Values from the two modes are not compared and are not reported.
- **Order.** Rows ran one after another, in the order of the table. Other load on the machine was not controlled.

## Results

All 80 rows finished with status "optimal", cvc5 confirming each. No row reached the 60-second limit: the slowest was 13.5 s. There are therefore no *unknown* rows in this run, and the probe says nothing about where the limit would be reached.

Time by window length and mode, over 10 rows each (5 seeds, gain and loss):

| Periods | Mode | Median (s) | Maximum (s) | Median Z3 checks | Median Z3 time per check (s) |
|---|---|---|---|---|---|
| 3 | exact | 0.43 | 0.67 | 21.5 | 0.018 |
| 3 | relaxed | 0.42 | 0.43 | 29 | 0.012 |
| 4 | exact | 1.51 | 3.64 | 11 | 0.098 |
| 4 | relaxed | 0.76 | 1.36 | 21 | 0.031 |
| 5 | exact | 5.12 | 8.52 | 19.5 | 0.247 |
| 5 | relaxed | 4.10 | 4.60 | 30 | 0.119 |
| 6 | exact | 6.82 | 13.47 | 12.5 | 0.293 |
| 6 | relaxed | 5.88 | 7.15 | 33 | 0.138 |

The same by figure, over 5 rows each:

| Periods | Mode | Gain median (s) | Gain maximum (s) | Loss median (s) | Loss maximum (s) |
|---|---|---|---|---|---|
| 3 | exact | 0.27 | 0.32 | 0.59 | 0.67 |
| 3 | relaxed | 0.30 | 0.42 | 0.42 | 0.43 |
| 4 | exact | 0.97 | 1.83 | 1.78 | 3.64 |
| 4 | relaxed | 0.26 | 0.46 | 1.21 | 1.36 |
| 5 | exact | 4.16 | 8.52 | 7.28 | 8.52 |
| 5 | relaxed | 2.65 | 4.45 | 4.35 | 4.60 |
| 6 | exact | 6.21 | 13.47 | 8.76 | 11.84 |
| 6 | relaxed | 4.55 | 5.21 | 6.74 | 7.15 |

Ratios of medians:

| Periods | Exact over relaxed, all rows | Gain | Loss | Share of an exact row spent in cvc5 (median) |
|---|---|---|---|---|
| 3 | 1.03 | 0.88 | 1.40 | 23% |
| 4 | 1.98 | 3.75 | 1.47 | 17% |
| 5 | 1.25 | 1.57 | 1.67 | 25% |
| 6 | 1.16 | 1.37 | 1.30 | 42% |

Growth from 3 to 6 periods, by medians: exact 0.43 s to 6.82 s (about 16 times), relaxed 0.42 s to 5.88 s (about 14 times). Step by step, exact: 3.5, 3.4 and 1.3 times; relaxed: 1.8, 5.4 and 1.4 times.

## Observations

1. **Time grows about 14 to 16 times from 3 to 6 periods, and most of that growth is already there at 5.** This is the median for either mode. The step from 5 to 6 periods is smaller (about 1.3 to 1.4 times), but one smaller step is too few data to say that growth flattens. It may not. The relaxed gain median at 4 periods (0.26 s) is below its value at 3 periods (0.30 s); with five rows a cell, that is noise.
2. **Exact over relaxed translation, by medians, ranged from about 1 to 2 in the rows measured, not an order of magnitude.** The relaxed translation drops the rounding and changes money from `Int` to `Real`, so this is the cost of both together. Exact over relaxed, by medians, is 1.03 at 3 periods, 1.98 at 4, 1.25 at 5 and 1.16 at 6. The ratio is not steady and is noisy at five seeds a cell: the 3.75 for gain at 4 periods comes from one cell of five rows. What does not vary is that the length of the window explains far more of the time than the difference between the translations does.
3. **Each exact Z3 check is more expensive than its relaxed counterpart, but the exact search often makes fewer checks.** The median time per Z3 check is 1.5 to 3.2 times higher exact than relaxed, while the exact search makes fewer checks at every length (for example 11 against 21 at 4 periods, and 12.5 against 33 at 6). The number of checks depends on how far Z3's first model is from the optimum, because the search gallops from it, so it varies with the seed (2 to 38 checks across rows). Time per row is therefore a product of two quantities that move independently. Time per check is the steadier of the two.
4. **The seed matters more than the mode in some cells.** For exact gain at 6 periods the five seeds took 4.3, 5.0, 6.2, 6.4 and 13.5 s. The 13.5 s row made 33 checks, the 4.3 s row made 6. A single run at a length would have told a reader little; the medians over five seeds still carry the spread of that one outlier in their maximum.
5. **cvc5's confirmation is a minority of the time at every length, though a larger share at 6 periods.** It is one run per row. Its median share of an exact row is 23%, 17% and 25% at 3, 4 and 5 periods, and 42% at 6, where it took a median of 2.9 s.
6. **Loss is slower than gain in most cells.** Both optimise a difference of two awards. This probe did not test why they differ.

## What this suggests for later window lengths

These are readings of one household on one machine, not forecasts.

- **Relax-then-confirm** could save something of the order of the difference between the exact and relaxed translations, on this household: a factor of about 1 to 2 on a whole row in these medians. The search would still need a confirmation on the exact rules, and cvc5's single run is itself 17 to 42% of an exact row. A gap of that size is modest, but the probe does not rank this against slicing.
- **Slicing**, which cuts the translation to the definitions an objective depends on, was not measured. Gain and loss are differences between whole-window awards, so every period may be needed, and how much slicing would remove is not known. The probe does not rank slicing against relax-then-confirm.
- **The 60-second limit left room at 6 periods** (slowest row 13.5 s). Windows beyond 6 periods are outside the existing scopes and were not measured, and the data give no basis for extrapolating to them.
- A later probe should take more seeds, more than one household (in particular one nearer the thresholds, where the taper and the surplus earnings carry more of the work), the other figures, and the cases other than the realistic one.

## Limits

- One household, one case, two figures, five seeds, one run per row, one machine, one day. Medians over ten rows and ratios of medians are indications, not estimates with an error bar.
- Wall time includes building the scripts in Python, which is a negligible part of a row: the Z3 and cvc5 times add up to within 0.01 s of the row time in every row.
- Time per check is Z3's time divided by the number of Z3 checks in the row; early checks (a first model) and late ones (a proof that nothing is better) differ in cost, and the division hides that.
- The relaxed translation is not the rules: a relaxed award can differ from Catala's by the pennies that the rounding moves, and a relaxed row is never replayed. Nothing here says the relaxed answers match the exact ones, and the probe does not check that.
- Solver versions change timings. Z3 5.3.2 and cvc5 1.4.2 are the lockfile's, as of 30 October 2026.
