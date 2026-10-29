"""The `bm` command line, the report and the provenance block."""

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import pytest

from bm import cli, provenance, report
from bm.coverage import CoverageFinding
from bm.ir import Pos, Var
from bm.queries import EmrResult

ROOT = Path(__file__).resolve().parent.parent
UC_IR = str(ROOT / "build" / "uc.bm-ir.json")
UC_BOUNDS = str(ROOT / "rules" / "uc.inputs.toml")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def rules_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / "uc.catala_en").write_text("first\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "rules")
    return tmp_path


def test_provenance_clean_then_dirty(rules_repo: Path):
    clean = provenance.collect(rules_repo)
    assert clean.rules_dirty is False
    assert clean.rules_commit == git(rules_repo, "rev-parse", "HEAD")
    (rules_repo / "uc.catala_en").write_text("second\n")
    assert provenance.collect(rules_repo).rules_dirty is True


def test_provenance_dirty_flag(rules_repo: Path):
    (rules_repo / "uc.catala_en").write_text("uncommitted change\n")
    assert provenance.collect(rules_repo).rules_dirty is True


def test_provenance_untracked_file_is_dirty(rules_repo: Path):
    (rules_repo / "new.catala_en").write_text("new\n")
    assert provenance.collect(rules_repo).rules_dirty is True


def test_provenance_ignores_changes_outside_the_rules(rules_repo: Path):
    (rules_repo / "rules").mkdir()
    (rules_repo / "rules" / "a.catala_en").write_text("a\n")
    git(rules_repo, "add", ".")
    git(rules_repo, "commit", "-q", "-m", "rules dir")
    (rules_repo / "elsewhere.txt").write_text("not a rule\n")
    assert provenance.collect(rules_repo / "rules").rules_dirty is False


def test_provenance_tool_versions():
    p = provenance.collect(ROOT / "rules")
    assert p.catala_version == "1.3.0"
    assert p.z3_version and p.cvc5_version


def test_translate_writes_smt2(tmp_path: Path, capsys):
    out = tmp_path / "uc.smt2"
    assert cli.main(["translate", UC_IR, "-o", str(out)]) == 0
    assert "(define-fun |award|" in out.read_text()


def test_coverage_uc_has_no_gaps(capsys):
    assert cli.main(["coverage", UC_IR, "--bounds", UC_BOUNDS]) == 0
    assert "no gaps" in capsys.readouterr().out


def test_query_emr_text(capsys):
    assert cli.main(["query", "emr", UC_IR, "--bounds", UC_BOUNDS]) == 0
    out = capsys.readouterr().out
    assert "55%" in out
    assert "earned_income" in out


def test_query_emr_json(capsys):
    assert cli.main(["query", "emr", UC_IR, "--bounds", UC_BOUNDS, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "found"
    assert data["rate"] == "11/20"
    assert data["delta"] == 100


def test_report_unknown_exit_code(capsys):
    code = cli.main(["query", "emr", UC_IR, "--bounds", UC_BOUNDS, "--timeout-ms", "1"])
    assert code == 2
    assert "unknown" in capsys.readouterr().out


def test_missing_file_exits_1(capsys):
    assert cli.main(["coverage", "no-such.json", "--bounds", UC_BOUNDS]) == 1
    assert "no-such.json" in capsys.readouterr().err


# The report. These build a Report by hand, so they do not need the differential check.

INPUTS = [Var("assessment_period_start", "date"), Var("earned_income", "money"), Var("flag", "bool")]
HOUSEHOLD = {"assessment_period_start": 20549, "earned_income": 148150, "flag": True}


@dataclass
class Mismatch:
    """Stands in for bm.checks.Mismatch."""

    household: dict = None
    catala: int = 57
    z3: int = 57
    policyengine: int = 58

    def __post_init__(self):
        self.household = self.household or HOUSEHOLD


def make_report(
    status="found", rate=Fraction(11, 20), coverage=(), explained=(), unexplained=()
) -> report.Report:
    emr = EmrResult(status, rate, 55, HOUSEHOLD, 57, 2, {"z3": "1", "cvc5": "2"})
    d = report.Differential(5, 1, list(explained), list(unexplained))
    p = provenance.Provenance("abc123", True, "1.3.0", "1", "2")
    return report.Report("UC", INPUTS, "earned_income", 100, emr, list(coverage), d, p)


def test_exit_code_ok():
    assert report.exit_code(make_report()) == 0


def test_exit_code_explained_mismatch_is_not_a_failure():
    assert report.exit_code(make_report(explained=[Mismatch()])) == 0


def test_exit_code_unexplained_mismatch_fails():
    assert report.exit_code(make_report(explained=[Mismatch()], unexplained=[Mismatch()])) == 1


def test_exit_code_unknown_is_2_and_failure_wins():
    assert report.exit_code(make_report(status="unknown")) == 2
    assert report.exit_code(make_report(status="unknown", unexplained=[Mismatch()])) == 1


def test_exit_code_coverage_gap_fails():
    gap = CoverageFinding("empty", "award", Pos("uc.catala_en", 3), "found", HOUSEHOLD)
    assert report.exit_code(make_report(coverage=[gap])) == 1


def test_text_report_contents():
    text = report.to_text(make_report(explained=[Mismatch()]))
    assert "55%" in text
    assert "£1,481.50" in text and "2026-04-06" in text
    assert "no gaps" in text
    assert "mismatches: 1 (1 explained, 0 unexplained)" in text
    assert "docs/mismatches.md" in text
    assert "award catala £0.57, z3 £0.57, policyengine £0.58" in text
    assert "abc123 (uncommitted changes)" in text


def test_percent_is_exact_where_possible():
    assert report.percent(Fraction(11, 20)) == "55%"
    assert report.percent(Fraction(1, 3)).startswith("33.33%")
    assert "1/3" in report.percent(Fraction(1, 3))


def test_json_report_keys_and_exact_rate():
    data = json.loads(report.to_json(make_report(explained=[Mismatch()])))
    assert {"emr", "coverage", "mismatches", "provenance"} <= set(data)
    assert data["emr"]["rate"] == "11/20"
    assert data["mismatches"]["total"] == 1
    assert data["mismatches"]["explained"][0]["policyengine"] == 58
    assert data["provenance"]["rules_dirty"] is True


def test_report_json_shape(capsys):
    code = cli.main(["report", UC_IR, "--bounds", UC_BOUNDS, "--json", "--n-random", "5"])
    assert code in (0, 1)  # the exit code depends on the differential check's outcome
    data = json.loads(capsys.readouterr().out)
    assert {"emr", "coverage", "mismatches", "provenance"} <= set(data)
    assert data["emr"]["rate"] == "11/20"
    assert data["coverage"]["findings"] == []
    m = data["mismatches"]
    assert m["total"] == len(m["explained"]) + len(m["unexplained"])
    assert set(data["provenance"]) == {
        "rules_commit", "rules_dirty", "catala_version", "z3_version", "cvc5_version",
    }


def test_check_exit_code_follows_unexplained_mismatches(capsys, monkeypatch):
    from bm import checks

    household = {
        "assessment_period_start": 20549, "earned_income": 148150,
        "aged_25_or_over": True, "has_lcw": True,
    }
    unexplained = checks.Mismatch(household, 57, 57, 60, {"award": 57, "work_allowance": 0})
    monkeypatch.setattr(checks, "run", lambda households, module=None: [unexplained])
    assert cli.main(["check", UC_IR, "--bounds", UC_BOUNDS, "--n-random", "2"]) == 1
    assert "UNEXPLAINED" in capsys.readouterr().out
    monkeypatch.setattr(checks, "run", lambda households, module=None: [])
    assert cli.main(["check", UC_IR, "--bounds", UC_BOUNDS, "--n-random", "2"]) == 0


def test_translator_disagreement_exits_1(capsys, monkeypatch):
    from bm import checks

    def disagree(households, module=None):
        raise checks.TranslatorDisagreement({"earned_income": 1}, "award: Catala 1, Z3 2")

    monkeypatch.setattr(checks, "run", disagree)
    assert cli.main(["check", UC_IR, "--bounds", UC_BOUNDS, "--n-random", "2"]) == 1
    assert "Catala 1, Z3 2" in capsys.readouterr().err
