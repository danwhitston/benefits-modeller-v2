"""Where a result came from: the rules' git state and the tool versions.

`collect(rules)` records the commit that last changed the rules, whether the
rules have uncommitted or untracked changes (so the commit alone would not
reproduce the result), and the versions of Catala, Z3 and cvc5.

`rules` is the rules directory or one rules file. Git is run from there, so
the rules may sit in a repository of their own.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from bm import solvers


@dataclass(frozen=True)
class Provenance:
    # Last commit that changed the rules; "none" if the rules were never committed.
    rules_commit: str
    # True if the rules differ from that commit, or hold untracked files.
    rules_dirty: bool
    catala_version: str
    z3_version: str
    cvc5_version: str


def _run(args: list[str], cwd: Path) -> str:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def collect(rules: Path) -> Provenance:
    rules = Path(rules).resolve()
    where = rules if rules.is_dir() else rules.parent
    target = "." if rules.is_dir() else rules.name
    commit = _run(["git", "log", "-1", "--format=%H", "--", target], where) or "none"
    dirty = bool(_run(["git", "status", "--porcelain", "--", target], where))
    repo = Path(__file__).resolve().parents[2]
    catala = _run(["opam", "exec", "--", "catala", "--version"], repo)
    versions = solvers.versions()
    return Provenance(commit, dirty, catala, versions["z3"], versions["cvc5"])
