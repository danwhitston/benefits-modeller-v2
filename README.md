# benefits-modeller v2

A second version of [benefits-modeller](https://github.com/danwhitston/benefits-modeller): UK benefit rules written in [Catala](https://catala-lang.org/), with an SMT solver for questions such as where the cliff edges are and how high effective marginal rates can go.

Early stage. The first milestone runs end to end for a thin slice of Universal Credit (a standard allowance, a work allowance and an earnings deduction): Catala rules, an export to JSON, a translation to SMT-LIB, queries to Z3 and cvc5, and a differential check against PolicyEngine UK. The direction and open questions are in [docs/v2-brief.md](docs/v2-brief.md).

## Running it

The versions used and tested on macOS on 29 October 2026 are Catala 1.3.0 on OCaml 5.3.0, and Python 3.14. The steps have not yet been run on Linux. Timings below were measured that day on an Apple Silicon Mac with warm caches; a first build with cold opam caches takes longer.

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
4. Build the rules and run the tests (about 4.5 minutes): `make build test`
5. Print the report: `uv run bm report build/uc.bm-ir.json --bounds rules/uc.inputs.toml`. This needs `build/uc.bm-ir.json`, which `make export` writes and `make test` runs first. It checks 73 households, the default 50 random ones plus 23 fixed ones (the worked rows in the rules tests, earnings at the work allowance and 1p either side, and the last-penny earnings), and takes about 3 minutes.

The report gives the peak marginal rate with an example household, whether Catala can stop with an error for any household in the bounds, the number of mismatches between Catala, Z3 and PolicyEngine UK, and the tool versions, code commit and rules commit that produced it. Add `--json` for the same content as data. `bm --help` lists the other commands, and `make check` runs the differential check alone.

The earnings input, `earned_income`, is Universal Credit earned income as regulation 55 of the Universal Credit Regulations 2013 defines it, not gross pay: employed earnings after deducting income tax, primary Class 1 National Insurance contributions, relievable pension contributions and payroll giving ([regulation 55(5)](https://www.legislation.gov.uk/uksi/2013/376/regulation/55), checked 29 October 2026).

Every command except `bm translate` refuses to run (exit 1) if the exported file was made by a different Catala version, or if a rules file has changed since the export; run `make export` again. The report exits with 0 when all is well, 1 on a failure or an unexplained mismatch, and 2 when a solver result is unknown, for example after a timeout. A failure (1) outranks unknown (2). Mismatches that fit a known class of 1p differences are counted and listed, and do not fail the run. A GitHub Actions workflow for the build, tests and check on pull requests is configured in `.github/workflows/ci.yml`. As of 29 October 2026 it has not yet run on GitHub.

## Use of AI

This project is built with substantial help from AI coding tools. [AI-DECLARATION.md](AI-DECLARATION.md) says which tools are used and how.

## Licence

MIT. See [LICENSE](LICENSE).
