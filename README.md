# benefits-modeller v2

A second version of [benefits-modeller](https://github.com/danwhitston/benefits-modeller): UK benefit rules written in [Catala](https://catala-lang.org/), with an SMT solver for questions such as where the cliff edges are and how high effective marginal rates can go.

Early stage. The first three milestones run end to end for a thin slice of Universal Credit (a standard allowance, a housing costs element taken as one input, a work allowance and an earnings deduction): Catala rules, an export to JSON, a translation to SMT-LIB, queries to Z3 and cvc5, and a differential check against PolicyEngine UK. Milestone 2 added two strategic queries: how much moving pay between two assessment periods can gain, and what the limited capability for work finding is worth, both while every award stays above nil. Milestone 3 modelled what happens when earnings take an assessment period to a nil award (the end of the award, the claims that follow, and surplus earnings) over a window of three periods, and added a query for the gain and loss from the timing of pay across it. The findings, and the conditions on each, are in [docs/model-gaps.md](docs/model-gaps.md#strategic-findings-and-their-conditions), and the research on nil periods is in [docs/nil-months.md](docs/nil-months.md). The direction and open questions are in [docs/v2-brief.md](docs/v2-brief.md).

## Running it

The versions used and tested on macOS on 29 October 2026 are Catala 1.3.0 on OCaml 5.3.0, and Python 3.14. The steps have not yet been run on Linux. Timings below were measured on an Apple Silicon Mac with warm caches, on 29 October 2026 unless they give another date; a first build with cold opam caches takes longer.

1. Install opam and the libraries Catala needs.
   - Mac: `brew install opam gmp pkgconf ninja`. The Xcode command-line tools are also needed (`xcode-select --install`).
   - Ubuntu, including WSL2: `sudo apt install opam libgmp-dev pkg-config ninja-build`
2. Set up opam and a switch inside the repository (about 2 minutes). Skip `opam init` if opam is already set up.
   ```
   opam init --bare --no-setup
   opam switch create . ocaml-base-compiler.5.3.0 -y
   opam install catala.1.3.0 -y
   ```
   If opam's sandbox (bubblewrap) fails on Linux, for example under AppArmor limits on user namespaces on native Ubuntu, use `opam init --bare --no-setup --disable-sandboxing`, as CI does.
3. Install the Python dependencies with [uv](https://docs.astral.sh/uv/): `uv sync`
4. Build the rules and run the tests (about 8 minutes, measured on 30 October 2026): `make build test`. For a quicker run while developing, `make test-fast` skips the tests marked slow, those that call PolicyEngine UK and others that take more than a few seconds (about 1 minute 20 seconds, measured on 30 October 2026); `make test` and CI run everything.
5. Print the report: `uv run bm report build/uc.bm-ir.json --inputs rules/uc.inputs.toml`. This needs `build/uc.bm-ir.json`, which `make export` writes and `make test` runs first. It checks 98 households: the default 50 random ones plus 48 fixed ones (the fourteen worked rows in the rules tests of the `UniversalCredit` scope; earnings at the work allowance and 1p either side, and the last-penny earnings and 1p less, for each age band and limited-capability-for-work combination, with a housing costs element of nil and of £500.00; and a 1p element at nil earnings with limited capability for work), and takes about 3.5 minutes.

The report gives the peak marginal rate with an example household, the two strategic findings described below, whether Catala can stop with an error for any household in the bounds, the number of mismatches between Catala, Z3 and PolicyEngine UK, and the tool versions, code commit and rules commit that produced it. Add `--json` for the same content as data. `bm --help` lists the other commands, and `make check` runs the differential check alone.

Two commands ask the strategic questions that the report also runs with their defaults. They print, for every household they find, who controls each input and how it is checked, using the labels in `rules/uc.inputs.toml`:

- `uv run bm query timing build/uc.bm-ir.json --inputs rules/uc.inputs.toml` asks how much a claimant can gain by choosing how a total of `earned_income` falls between two consecutive assessment periods, compared with an even split, over splits where every award stays above nil. Where a decision maker's finding such as `has_lcw` is open, it gives the gain that holds whichever way the finding goes. Options: `--start YYYY-MM-DD` (default 2026-04-06), `--total POUNDS`, `--fix NAME=VALUE` (repeatable) and `--cap` for the most judgement cases.
- `uv run bm query judgement build/uc.bm-ir.json has_lcw --inputs rules/uc.inputs.toml` gives the largest and the smallest amount that the decision maker's finding on a Boolean input changes the award by, in one assessment period, where both awards (with and without the finding) stay above nil. It takes `--start` and `--fix` too.

A third command asks about a longer run of assessment periods, where one period can end at nil:

- `uv run bm query window build/claim_window.bm-ir.json --inputs rules/claim_window.inputs.toml` takes a fixed or free total of earnings over three consecutive monthly assessment periods and gives, for each case of the decision maker's findings, the gain and the loss from timing alone against the even split of the same total, the spread between two splits, and the two figures for a claimant paid every four weeks (the award with the four payments spread evenly, less the award with them falling as P, 2P, P). Splits whose last period has an award below 1p are left out, and the report says so. In a case with no claim after the award ends, the split that the loss, the spread and the largest extra payday figure subtract may end at nil, so those figures are lower bounds, marked "at least". After the per-case figures the report gives the largest and the smallest of each figure across the cases, with the case that gives each (`across_cases` in the JSON). Options: `--start`, `--total POUNDS`, `--fix NAME=VALUE`, `--cap` (default 12), `--timeout-ms` and `--json`. The text shows the households at the optimum for the realistic cases only (every case, if none is realistic); `--json` shows them all. The window's length is that of the IR file. `--probe` marks a run for measuring solver time, and `--relaxed` (a translation that does not round, which is not the rules) and any window longer than three periods are refused without it. A probe's text begins "PROBE: not a finding", its figures are never findings, and a longer window leaves out the extra payday figures. A relaxed run is not replayed through Catala, and its JSON gives amounts that are not whole pence as exact fractions in strings. A figure that is not available says why, and is never shown as nil. The text ends with three caveat lines and the pointer to [docs/model-gaps.md](docs/model-gaps.md).

`--fix` gives an input a value: money in pounds with two decimal places (`housing_costs_element=500.00`), a date as `YYYY-MM-DD`, and a Boolean as `true` or `false`. All three commands take `--json`, whose output has a top-level `"unknown"` flag, and all exit with 2 when a result is unknown, which never means that there is no gain. Text output ends by pointing to [docs/model-gaps.md](docs/model-gaps.md).

The earnings input, `earned_income`, is employed earnings as regulation 55 of the Universal Credit Regulations 2013 defines them, not gross pay: earnings after deducting income tax, primary Class 1 National Insurance contributions, relievable pension contributions and payroll giving ([regulation 55(5)](https://www.legislation.gov.uk/uksi/2013/376/regulation/55), checked 29 October 2026).

Every command except `bm translate` refuses to run (exit 1) if the exported file was made by a different Catala version, or if a rules file has changed since the export; run `make export` again. The report exits with 0 when all is well, 1 on a failure or an unexplained mismatch, and 2 when a solver result is unknown, for example after a timeout. A failure (1) outranks unknown (2). Mismatches that fit a known class of 1p differences are counted and listed, and do not fail the run. A GitHub Actions workflow for the build, tests and check on pull requests is configured in `.github/workflows/ci.yml`. It has run on GitHub since 29 October 2026.

## Use of AI

This project is built with substantial help from AI coding tools. [AI-DECLARATION.md](AI-DECLARATION.md) says which tools are used and how.

## Licence

MIT. See [LICENSE](LICENSE).
