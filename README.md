# benefits-modeller v2

A second version of [benefits-modeller](https://github.com/danwhitston/benefits-modeller): UK benefit rules written in [Catala](https://catala-lang.org/), with an SMT solver for questions such as where the cliff edges are and how high effective marginal rates can go.

Early stage. The first milestone runs end to end for a thin slice of Universal Credit (a standard allowance, a work allowance and an earnings deduction): Catala rules, an export to JSON, a translation to SMT-LIB, queries to Z3 and cvc5, and a differential check against PolicyEngine UK. The direction and open questions are in [docs/v2-brief.md](docs/v2-brief.md).

## Running it

The versions used and tested on 29 October 2026 are Catala 1.3.0 on OCaml 5.3.0, and Python 3.14.

1. Install opam and the libraries Catala needs.
   - Mac: `brew install opam gmp pkgconf ninja`
   - Ubuntu, including WSL2: `sudo apt install opam libgmp-dev pkg-config ninja-build`
2. Set up opam and a switch inside the repository (the first build takes a while):
   ```
   opam init --bare --no-setup
   opam switch create . ocaml-base-compiler.5.3.0
   opam install catala.1.3.0
   ```
3. Install the Python dependencies with [uv](https://docs.astral.sh/uv/): `uv sync`
4. Build the rules and run the tests: `make build test`
5. Print the report: `uv run bm report build/uc.bm-ir.json --bounds rules/uc.inputs.toml`. This needs `build/uc.bm-ir.json`, which `make export` writes and `make test` runs first. At the default 50 random households it takes about 3 minutes.

The report gives the peak marginal rate with an example household, whether Catala can stop with an error for any household in the bounds, the number of mismatches between Catala, Z3 and PolicyEngine UK, and the versions and rules commit that produced it. Add `--json` for the same content as data. `bm --help` lists the other commands, and `make check` runs the differential check alone.

The report refuses to run (exit 1) if the exported file was made by a different Catala version, or if a rules file has changed since the export; run `make export` again. It exits with 0 when all is well, 1 on a failure or an unexplained mismatch, and 2 when a solver result is unknown, for example after a timeout. A failure (1) outranks unknown (2). Mismatches that fit a known class of 1p differences are counted and listed, and do not fail the run. A GitHub Actions workflow for the build, tests and check on pull requests is configured in `.github/workflows/ci.yml`. As of 29 October 2026 it has not yet run on GitHub.

## Use of AI

This project is built with substantial help from AI coding tools. [AI-DECLARATION.md](AI-DECLARATION.md) says which tools are used and how.

## Licence

MIT. See [LICENSE](LICENSE).
