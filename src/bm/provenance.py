"""Where a result came from: the rules' git state and the tool versions.

`collect(rules)` records the commit that last changed the rules, whether the
rules have uncommitted or untracked changes (so the commit alone would not
reproduce the result), and the versions of Catala, Z3 and cvc5.

Results come from the exported IR (`build/uc.bm-ir.json`), not from the rules
directly, so `collect(rules, ir_path)` also checks that the IR describes these
rules and this Catala. It raises `ProvenanceError` if

- the IR's `catala_version` differs from the running `catala --version`, or
- any file under `rules` has a modification time later than the IR file, which
  means the rules were edited after `make export` wrote it.

The second check compares mtimes, which is simple and conservative: touching a
rules file without changing it also fails, and the fix is the same, `make export`.

`rules` is the rules directory or one rules file. Git is run from there, so
the rules may sit in a repository of their own.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from bm import ir, solvers


class ProvenanceError(RuntimeError):
    """The IR does not match the rules or the Catala that is running."""


@dataclass(frozen=True)
class Provenance:
    # Last commit that changed the rules; "none" if the rules were never committed.
    rules_commit: str
    # True if the rules differ from that commit, or hold untracked files.
    rules_dirty: bool
    catala_version: str
    # The Catala version recorded in the IR; equals `catala_version` once checked.
    ir_catala_version: str
    z3_version: str
    cvc5_version: str


def _run(args: list[str], cwd: Path, default: str | None = None) -> str:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode != 0 and default is not None:
        return default
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def _check_ir(rules: Path, ir_path: Path, catala_version: str) -> str:
    ir_version = ir.load(ir_path).catala_version
    if ir_version != catala_version:
        raise ProvenanceError(
            f"{ir_path} was exported with Catala {ir_version} but Catala {catala_version}"
            " is running; run `make export`"
        )
    written = ir_path.stat().st_mtime
    files = [rules] if rules.is_file() else [f for f in rules.rglob("*") if f.is_file()]
    if newer := sorted(f for f in files if f.stat().st_mtime > written):
        raise ProvenanceError(
            f"{newer[0]} was changed after {ir_path} was written"
            f" ({len(newer)} rules file(s) newer); run `make export`"
        )
    return ir_version


def collect(rules: Path, ir_path: Path | None = None) -> Provenance:
    rules = Path(rules).resolve()
    where = rules if rules.is_dir() else rules.parent
    target = "." if rules.is_dir() else rules.name
    # A repository with no commits yet has no rules commit; that is not an error.
    commit = _run(["git", "log", "-1", "--format=%H", "--", target], where, default="") or "none"
    dirty = bool(_run(["git", "status", "--porcelain", "--", target], where))
    repo = Path(__file__).resolve().parents[2]
    catala = _run(["opam", "exec", "--", "catala", "--version"], repo)
    ir_version = _check_ir(rules, Path(ir_path), catala) if ir_path else catala
    versions = solvers.versions()
    return Provenance(commit, dirty, catala, ir_version, versions["z3"], versions["cvc5"])
