"""Scaling probe for the claim window: how solver time grows with its length.

Times the window query (`bm.window.window`) at 3 to 6 assessment periods, on
the exact rules and on the relaxed translation (no rounding to the penny,
money as Real), for several solver seeds. Each row is one optimisation: one
figure (gain or loss) in the realistic case, for one fixed household. The
results are measurements of solver time. They are never findings about the
rules, and a relaxed row is not the rules at all (see `bm.translate`).

    uv run python scripts/probe_window.py [--seeds N] [--timeout SECONDS] [--out PATH]

writes `build/probe-window.json`, and rewrites it after every row so that a
long run leaves its partial results. The write-up is
`docs/spike-window-scaling.md`.

Household H is aged 25 or over, with limited capability for work (LCW) and a
housing costs element of 804 pounds. The realistic case (a claim after the end
of an award, a claim each month, the LCW finding carried over) is fixed, so
that a row has no case to loop over. The first period starts on 6 April 2026,
which is the earliest start the inputs allow, so that six periods end before
31 March 2027. Payday figures are not probed: they need exactly 3 periods.
"""

import argparse
import json
import platform
import sys
import time
from datetime import date
from pathlib import Path

from bm import inputs, ir, solvers, translate
from bm.window import REALISTIC, window

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
INPUTS = ROOT / "rules" / "claim_window.inputs.toml"
OUT = BUILD / "probe-window.json"

FIRST_START = date(2026, 4, 6)
HOUSEHOLD = {"aged_25_or_over": True, "has_lcw": True, "housing_costs_element": 80_400}
PERIODS = (3, 4, 5, 6)
MODES = ("exact", "relaxed")
FIGURES = ("gain", "loss")
TIMEOUT_S = 60
SEEDS = 5

_loaded: dict[tuple[int, str], tuple] = {}


def _load(periods: int, mode: str):
    """The module and input specs for a window length and mode, loaded once."""
    key = (periods, mode)
    if key not in _loaded:
        name = "claim_window" if periods == 3 else f"claim_window{periods}"
        scope = ir.load(BUILD / f"{name}.bm-ir.json")
        _loaded[key] = (
            translate.translate(scope, relaxed=mode == "relaxed"),
            inputs.load(INPUTS, scope),
        )
    return _loaded[key]


class _Timer:
    """Counts and times the solver calls made while it is installed."""

    def __init__(self):
        self.calls = {"z3": 0, "cvc5": 0}
        self.seconds = {"z3": 0.0, "cvc5": 0.0}

    def __enter__(self):
        self._run = solvers.run

        def timed(solver, script, timeout_ms, **kwargs):
            started = time.perf_counter()
            try:
                return self._run(solver, script, timeout_ms, **kwargs)
            finally:
                self.calls[solver] += 1
                self.seconds[solver] += time.perf_counter() - started

        solvers.run = timed
        return self

    def __exit__(self, *exc):
        solvers.run = self._run


def probe_row(
    periods: int, mode: str, seed: int, figure: str, *, timeout_s: float = TIMEOUT_S
) -> dict:
    """Time one optimisation: `figure` for household H in the realistic case.

    `mode` is "exact" (the rules) or "relaxed" (no rounding). `timeout_s` applies
    to each Z3 search and to cvc5's confirmation, so a row can take up to about
    twice as long. Loading and translating the module are not timed. The row
    has the wall time of the call, the number of Z3 checks and cvc5 runs, the
    time spent in each solver, the status and the value in pence. A relaxed
    value is the integer the search proves reachable (see
    `bm.solvers.optimise_and_confirm`), not the exact optimum.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
    module, specs = _load(periods, mode)
    with _Timer() as timer:
        started = time.perf_counter()
        result = window(
            module,
            specs,
            first_start=FIRST_START,
            fixed={**HOUSEHOLD, **REALISTIC},
            figures=(figure,),
            probe=True,
            timeout_ms=int(timeout_s * 1000),
            seed=seed,
        )
        seconds = time.perf_counter() - started
    (case,) = result.cases
    found = case.figures[figure]
    return {
        "periods": periods,
        "mode": mode,
        "seed": seed,
        "figure": figure,
        "case": "realistic",
        "status": found.status,
        "value": found.value,
        "seconds": round(seconds, 3),
        "z3_checks": timer.calls["z3"],
        "cvc5_runs": timer.calls["cvc5"],
        "z3_seconds": round(timer.seconds["z3"], 3),
        "cvc5_seconds": round(timer.seconds["cvc5"], 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seeds", type=int, default=SEEDS, help="seeds 1 to N (default 5)")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_S, help="seconds per search")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    meta = {
        "household": HOUSEHOLD,
        "case": REALISTIC,
        "first_start": FIRST_START.isoformat(),
        "timeout_s": args.timeout,
        "versions": solvers.versions(),
        "python": platform.python_version(),
        "machine": f"{platform.machine()} {platform.platform()}",
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    rows: list[dict] = []
    for periods in PERIODS:
        for mode in MODES:
            for seed in range(1, args.seeds + 1):
                for figure in FIGURES:
                    row = probe_row(periods, mode, seed, figure, timeout_s=args.timeout)
                    rows.append(row)
                    print(json.dumps(row), flush=True)
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(json.dumps({"meta": meta, "rows": rows}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
