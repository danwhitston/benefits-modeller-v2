"""The `bm` command line, the report and the provenance block."""

import json
import os
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from importlib import metadata
from pathlib import Path

import pytest

from bm import cli, inputs, ir, provenance, report, solvers, strategic
from bm.coverage import CoverageFinding
from bm.ir import Pos, Var
from bm.queries import EmrResult
from bm.strategic import JudgementResult, TimingResult, Witness

ROOT = Path(__file__).resolve().parent.parent
UC_IR = str(ROOT / "build" / "uc.bm-ir.json")
UC_BOUNDS = str(ROOT / "rules" / "uc.inputs.toml")
SPECS = inputs.load(Path(UC_BOUNDS), ir.load(Path(UC_IR)))


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
    assert p.policyengine_uk_version == metadata.version("policyengine-uk")
    assert p.code_commit == git(ROOT, "rev-parse", "HEAD")
    assert p.code_dirty is bool(git(ROOT, "status", "--porcelain"))


def test_provenance_code_dirty_flag(rules_repo: Path, monkeypatch):
    monkeypatch.setattr(provenance, "REPO", rules_repo)
    clean = provenance.collect(rules_repo)
    assert clean.code_commit == git(rules_repo, "rev-parse", "HEAD")
    assert clean.code_dirty is False
    (rules_repo / "code.py").write_text("untracked\n")
    assert provenance.collect(rules_repo).code_dirty is True


def write_ir(path: Path, catala_version: str) -> Path:
    data = json.loads(Path(UC_IR).read_text())
    data["catala_version"] = catala_version
    path.write_text(json.dumps(data))
    return path


def test_provenance_records_the_ir_version():
    p = provenance.collect(ROOT / "rules", Path(UC_IR))
    assert p.ir_catala_version == p.catala_version == "1.3.0"


def test_provenance_rejects_an_ir_from_another_catala(tmp_path: Path):
    old = write_ir(tmp_path / "old.bm-ir.json", "1.2.0")
    with pytest.raises(provenance.ProvenanceError, match="1.2.0.*1.3.0.*make export"):
        provenance.collect(ROOT / "rules", old)


def test_provenance_rejects_rules_newer_than_the_ir(tmp_path: Path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "uc.catala_en").write_text("rules\n")
    ir_file = write_ir(tmp_path / "uc.bm-ir.json", "1.3.0")
    os.utime(ir_file, (1_000_000, 1_000_000))
    os.utime(rules / "uc.catala_en", (2_000_000, 2_000_000))
    git(tmp_path, "init", "-q")
    with pytest.raises(provenance.ProvenanceError, match="changed after.*make export"):
        provenance.collect(rules, ir_file)
    os.utime(rules / "uc.catala_en", (500_000, 500_000))
    assert provenance.collect(rules, ir_file).rules_dirty is True  # untracked, but not stale


def test_provenance_staleness_ignores_files_other_than_the_rules(tmp_path: Path):
    rules = tmp_path / "rules"
    (rules / "sub").mkdir(parents=True)
    (rules / "uc.catala_en").write_text("rules\n")
    ir_file = write_ir(tmp_path / "uc.bm-ir.json", "1.3.0")
    os.utime(ir_file, (1_000_000, 1_000_000))
    os.utime(rules / "uc.catala_en", (500_000, 500_000))
    # Editors' backup, swap and lock files, and the bounds, which are not exported.
    for name in ("uc.catala_en~", ".uc.catala_en.swp", ".#uc.catala_en", "#uc.catala_en#",
                 "uc.inputs.toml"):
        (rules / name).write_text("stray\n")
        os.utime(rules / name, (2_000_000, 2_000_000))
    git(tmp_path, "init", "-q")
    provenance.collect(rules, ir_file)
    # A rules file in a subdirectory still counts.
    (rules / "sub" / "extra.catala_en").write_text("rules\n")
    os.utime(rules / "sub" / "extra.catala_en", (2_000_000, 2_000_000))
    with pytest.raises(provenance.ProvenanceError, match="extra.catala_en was changed after"):
        provenance.collect(rules, ir_file)


def test_report_with_a_mismatched_ir_fails_before_the_slow_checks(tmp_path: Path, capsys):
    old = write_ir(tmp_path / "old.bm-ir.json", "1.2.0")
    assert cli.main(["report", str(old), "--inputs", UC_BOUNDS, "--n-random", "1"]) == 1
    assert "make export" in capsys.readouterr().err


def test_translate_writes_smt2(tmp_path: Path, capsys):
    out = tmp_path / "uc.smt2"
    assert cli.main(["translate", UC_IR, "-o", str(out)]) == 0
    assert "(define-fun |award|" in out.read_text()


def test_coverage_uc_has_no_gaps(capsys):
    assert cli.main(["coverage", UC_IR, "--inputs", UC_BOUNDS]) == 0
    out = capsys.readouterr().out
    assert "no gaps" in out
    assert "Provenance" in out and "code commit" in out


def test_query_emr_text(capsys):
    assert cli.main(["query", "emr", UC_IR, "--inputs", UC_BOUNDS]) == 0
    out = capsys.readouterr().out
    assert "55%" in out
    assert "earned_income" in out


def test_query_emr_json(capsys):
    assert cli.main(["query", "emr", UC_IR, "--inputs", UC_BOUNDS, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "found"
    assert data["rate"] == "11/20"
    assert data["delta"] == 100
    assert data["provenance"]["ir_catala_version"] == "1.3.0"


def test_report_unknown_exit_code(capsys):
    code = cli.main(["query", "emr", UC_IR, "--inputs", UC_BOUNDS, "--timeout-ms", "1"])
    assert code == 2
    assert "unknown" in capsys.readouterr().out


def test_missing_file_exits_1(capsys):
    assert cli.main(["coverage", "no-such.json", "--inputs", UC_BOUNDS]) == 1
    assert "no-such.json" in capsys.readouterr().err


# The report. These build a Report by hand, so they do not need the differential check.

INPUTS = [
    Var("assessment_period_start", "date"),
    Var("earned_income", "money"),
    Var("flag", "bool"),
]
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


HOUSEHOLD_FACTS = {"aged_25_or_over": True, "housing_costs_element": 0}


def witness(period=1, kind="split", has_lcw=True, earnings=100_000, award=40_000) -> Witness:
    household = {
        "assessment_period_start": 20549,
        "earned_income": earnings,
        "has_lcw": has_lcw,
        **HOUSEHOLD_FACTS,
    }
    return Witness({"has_lcw": has_lcw}, period, kind, household, award)


VERIFIED = {"cvc5": "confirmed", "replay": "matched", "replayed": ["gain"]}
VERSIONS = {"z3": "1", "cvc5": "2"}


def make_timing(
    status="optimal", gain=12_345, per_case_gain=12_345, cvc5="confirmed", gain_status=None
) -> TimingResult:
    """A timing result whose values all have `status`, unless `gain_status` is given."""
    witnesses = [witness(p, k) for p in (1, 2) for k in ("split", "baseline")]
    replayed = ["gain"] if gain is not None else []
    return TimingResult(
        status,
        gain,
        gain_status or status,
        [({"has_lcw": True}, status, per_case_gain)],
        {},
        [20549, 20579],
        142_001 if gain is not None else None,
        witnesses if gain is not None else [],
        {"cvc5": cvc5, "replay": "matched" if replayed else "not run", "replayed": replayed},
        VERSIONS,
    )


def make_judgement(
    status="optimal", largest=39_050, smallest=0, cvc5="confirmed", largest_status=None
) -> JudgementResult:
    """A judgement result whose values all have `status`, unless `largest_status` is given."""
    yes, no = witness(has_lcw=True, kind="single"), witness(has_lcw=False, kind="single")
    replayed = [n for n, v in (("largest", largest), ("smallest", smallest)) if v is not None]
    return JudgementResult(
        "has_lcw",
        status,
        largest,
        largest_status or status,
        smallest,
        status,
        [yes, no] if largest is not None else [],
        [yes, no] if smallest is not None else [],
        {},
        20549,
        {
            "cvc5": cvc5,
            "replay": "matched" if len(replayed) == 2 else "matched in part",
            "replayed": replayed,
        },
        VERSIONS,
    )


def make_report(
    status="found",
    rate=Fraction(11, 20),
    coverage=(),
    explained=(),
    unexplained=(),
    timing=None,
    judgement=None,
) -> report.Report:
    emr = EmrResult(status, rate, 55, HOUSEHOLD, 57, 2, {"z3": "1", "cvc5": "2"})
    d = report.Differential(5, 1, list(explained), list(unexplained))
    p = provenance.Provenance("abc123", True, "def456", False, "1.3.0", "1.3.0", "1", "2", "2.164.2")
    return report.Report(
        "UC",
        INPUTS,
        "earned_income",
        100,
        emr,
        list(coverage),
        d,
        p,
        SPECS,
        timing or make_timing(),
        judgement or make_judgement(),
    )


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
    assert "def456 (clean)" in text
    assert "1.3.0 (the IR was exported with 1.3.0)" in text


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


@pytest.mark.slow
def test_report_json_shape(capsys):
    code = cli.main(["report", UC_IR, "--inputs", UC_BOUNDS, "--json", "--n-random", "5"])
    assert code == 0  # every mismatch must be explained by the rounding predicate
    data = json.loads(capsys.readouterr().out)
    assert {"emr", "timing", "judgement", "coverage", "mismatches", "provenance"} <= set(data)
    assert data["unknown"] is False
    assert data["emr"]["rate"] == "11/20"
    assert data["judgement"]["largest"] == 39_050
    assert data["timing"]["gain"] >= 0
    assert data["coverage"]["findings"] == []
    m = data["mismatches"]
    assert m["total"] == len(m["explained"]) + len(m["unexplained"])
    assert set(data["provenance"]) == {
        "rules_commit", "rules_dirty", "code_commit", "code_dirty", "catala_version",
        "ir_catala_version", "z3_version", "cvc5_version", "policyengine_uk_version",
    }


def test_check_exit_code_follows_unexplained_mismatches(capsys, monkeypatch):
    from bm import checks

    household = {
        "assessment_period_start": 20549, "earned_income": 148150,
        "aged_25_or_over": True, "has_lcw": True, "housing_costs_element": 0,
    }
    unexplained = checks.Mismatch(household, 57, 57, 60, {"award": 57, "work_allowance": 0})
    monkeypatch.setattr(checks, "run", lambda households, module=None, rules=None: [unexplained])
    assert cli.main(["check", UC_IR, "--inputs", UC_BOUNDS, "--n-random", "2"]) == 1
    assert "UNEXPLAINED" in capsys.readouterr().out
    monkeypatch.setattr(checks, "run", lambda households, module=None, rules=None: [])
    assert cli.main(["check", UC_IR, "--inputs", UC_BOUNDS, "--n-random", "2"]) == 0


def test_translator_disagreement_exits_1(capsys, monkeypatch):
    from bm import checks

    def disagree(households, module=None, rules=None):
        raise checks.TranslatorDisagreement({"earned_income": 1}, "award: Catala 1, Z3 2")

    monkeypatch.setattr(checks, "run", disagree)
    assert cli.main(["check", UC_IR, "--inputs", UC_BOUNDS, "--n-random", "2"]) == 1
    assert "Catala 1, Z3 2" in capsys.readouterr().err


def test_check_on_a_stale_ir_fails_with_the_provenance_error(tmp_path: Path, capsys, monkeypatch):
    # The rules under rules/ are all newer than this IR, as if edited after `make export`.
    stale = write_ir(tmp_path / "uc.bm-ir.json", "1.3.0")
    os.utime(stale, (1_000_000, 1_000_000))
    from bm import checks

    def must_not_run(households, module=None, rules=None):
        raise AssertionError("the differential check ran on a stale IR")

    monkeypatch.setattr(checks, "run", must_not_run)
    assert cli.main(["check", str(stale), "--inputs", UC_BOUNDS, "--n-random", "1"]) == 1
    err = capsys.readouterr().err
    assert "ProvenanceError" in err and "changed after" in err and "make export" in err
    assert "TranslatorBug" not in err


# The strategic queries.


def run_json(capsys, *argv: str) -> tuple[int, dict]:
    code = cli.main([*argv, "--inputs", UC_BOUNDS, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_query_timing_json(capsys):
    code, data = run_json(capsys, "query", "timing", UC_IR)
    assert code == 0
    assert data["unknown"] is False
    assert data["gain"] >= 0
    assert data["witnesses"]
    for w in data["witnesses"]:
        assert set(w["inputs"]) == set(SPECS)
        for name, entry in w["inputs"].items():
            assert entry["controlled_by"] == list(SPECS[name].controlled_by)
            assert entry["checked_by"] == SPECS[name].checked_by
    assert data["provenance"]["ir_catala_version"] == "1.3.0"


def test_query_judgement_text(capsys):
    assert cli.main(["query", "judgement", UC_IR, "has_lcw", "--inputs", UC_BOUNDS]) == 0
    out = capsys.readouterr().out
    assert "£390.50" in out
    assert out.rstrip().endswith("Model gaps that limit these findings: docs/model-gaps.md")


def test_query_judgement_with_fixed_facts(capsys):
    code, data = run_json(
        capsys, "query", "judgement", UC_IR, "has_lcw",
        "--fix", "housing_costs_element=500.00", "--fix", "aged_25_or_over=true",
    )
    assert code == 0
    assert data["largest"] == 23_485  # 55% of the 427.00 work allowance with housing costs
    assert data["fixed"]["housing_costs_element"] == 50_000
    assert data["fixed"]["aged_25_or_over"] is True


def test_query_timing_with_a_start_and_a_total(capsys):
    code, data = run_json(
        capsys, "query", "timing", UC_IR,
        "--start", "2026-07-31", "--total", "1420.01", "--fix", "has_lcw=true",
        "--fix", "aged_25_or_over=true", "--fix", "housing_costs_element=0.00",
    )
    assert code == 0
    assert data["total"] == 142_001
    assert data["starts"] == [20_665, 20_696]  # 2026-07-31 and 2026-08-31
    assert len(data["per_case"]) == 1


def unknown_everywhere(solver, script, timeout_ms):
    return solvers.SolverResult("unknown", None, "test")


@pytest.mark.parametrize("argv", [("timing",), ("judgement", "has_lcw")])
def test_query_unknown_exits_2(argv, capsys, monkeypatch):
    monkeypatch.setattr(solvers, "run", unknown_everywhere)
    code, data = run_json(capsys, "query", argv[0], UC_IR, *argv[1:])
    assert code == 2
    assert data["unknown"] is True
    assert data["status"] == "unknown"
    assert [data.get("gain"), data.get("largest"), data.get("smallest")].count(None) >= 1


def test_query_unknown_text_says_so_and_prints_no_amount(capsys, monkeypatch):
    monkeypatch.setattr(solvers, "run", unknown_everywhere)
    assert cli.main(["query", "timing", UC_IR, "--inputs", UC_BOUNDS]) == 2
    out = capsys.readouterr().out
    assert "UNKNOWN" in out
    assert "£0.00" not in out


@pytest.mark.parametrize("argv", [("timing",), ("judgement", "has_lcw")])
def test_query_disagreement_exits_1(argv, capsys, monkeypatch):
    real = solvers.run

    def cvc5_finds_better(solver, script, timeout_ms):
        if solver == "cvc5":
            return solvers.SolverResult("sat", {}, "test")
        return real(solver, script, timeout_ms)

    monkeypatch.setattr(solvers, "run", cvc5_finds_better)
    assert cli.main(["query", argv[0], UC_IR, *argv[1:], "--inputs", UC_BOUNDS]) == 1
    captured = capsys.readouterr()
    assert "SolverDisagreement" in captured.err
    assert "Traceback" not in captured.err


class Anything(dict):
    """A solver model that gives every constant the value 0 (or no)."""

    def __missing__(self, key):
        return 0


def test_coverage_exits_1_and_2(capsys, monkeypatch):
    monkeypatch.setattr(
        solvers, "run", lambda solver, script, timeout_ms: solvers.SolverResult("sat", Anything(), "t")
    )
    assert cli.main(["coverage", UC_IR, "--inputs", UC_BOUNDS]) == 1
    assert "found" in capsys.readouterr().out
    monkeypatch.setattr(solvers, "run", unknown_everywhere)
    assert cli.main(["coverage", UC_IR, "--inputs", UC_BOUNDS]) == 2
    assert "unknown" in capsys.readouterr().out


@pytest.mark.parametrize(
    "fix",
    ["nope=1", "housing_costs_element=500", "housing_costs_element=£500.00",
     "housing_costs_element=500.5", "has_lcw=maybe", "assessment_period_start=6/4/2026",
     "assessment_period_start=2026-04-06", "has_lcw", "has_lcw=true"],
)
def test_fix_errors(fix, capsys):
    argv = ["query", "judgement", UC_IR, "housing_costs_element", "--inputs", UC_BOUNDS]
    if fix == "has_lcw=true":
        # A bad combination, not a bad value: fixing the point being valued is refused.
        argv = ["query", "judgement", UC_IR, "has_lcw", "--inputs", UC_BOUNDS]
    assert cli.main([*argv, "--fix", fix]) == 1
    err = capsys.readouterr().err
    assert err.startswith("bm:") and err.count("\n") == 1
    assert "Traceback" not in err


def test_fix_errors_for_timing_too(capsys):
    argv = ["query", "timing", UC_IR, "--inputs", UC_BOUNDS]
    assert cli.main([*argv, "--fix", "housing_costs_element=500"]) == 1
    assert capsys.readouterr().err.startswith("bm:")
    assert cli.main([*argv, "--total", "1420"]) == 1
    assert capsys.readouterr().err.startswith("bm:")
    assert cli.main([*argv, "--start", "next week"]) == 1
    assert capsys.readouterr().err.startswith("bm:")


def test_fixed_values_are_parsed_by_type():
    parsed = cli.parse_fixed(
        SPECS,
        ["housing_costs_element=500.00", "has_lcw=false", "aged_25_or_over=true"],
    )
    assert parsed == {"housing_costs_element": 50_000, "has_lcw": False, "aged_25_or_over": True}
    with pytest.raises(ValueError, match="twice"):
        cli.parse_fixed(SPECS, ["has_lcw=true", "has_lcw=false"])


def test_report_json_has_unknown_flag():
    assert report.to_dict(make_report())["unknown"] is False
    for r in (
        make_report(status="unknown"),
        make_report(timing=make_timing("unknown", None, None, "unknown")),
        make_report(judgement=make_judgement("unknown", None, None, "unknown")),
        make_report(coverage=[CoverageFinding("empty", "award", Pos("u", 1), "unknown", None)]),
    ):
        assert report.to_dict(r)["unknown"] is True
        assert report.exit_code(r) == 2


def test_report_exit_code_for_unknown_strategic_results():
    unknown_timing = make_report(timing=make_timing("unknown", None, None, "unknown"))
    assert report.exit_code(unknown_timing) == 2
    assert report.exit_code(make_report(unexplained=[Mismatch()])) == 1
    unknown_and_failing = make_report(
        judgement=make_judgement("unknown", None, None, "unknown"), unexplained=[Mismatch()]
    )
    assert report.exit_code(unknown_and_failing) == 1


def test_timing_dict_carries_the_labels_and_the_known_pence():
    data = report.timing_dict(make_timing(), SPECS)
    assert data["unknown"] is False and data["gain"] == 12_345
    inputs_of_first = data["witnesses"][0]["inputs"]
    assert inputs_of_first["earned_income"] == {
        "value": 100_000,
        "type": "money",
        "controlled_by": ["employer", "claimant"],
        "checked_by": "third_party_data",
    }
    assert inputs_of_first["has_lcw"]["controlled_by"] == ["decision_maker"]
    assert data["verification"] == VERIFIED
    assert data["per_case"] == [{"case": {"has_lcw": True}, "status": "optimal", "gain": 12_345}]
    assert data["gain_status"] == "optimal"


def test_timing_text_words_each_value_from_its_own_status():
    # The worst-case gain is confirmed; the case's own optimisation found no
    # value in time. Only the case's line is UNKNOWN, and nothing says that
    # cvc5 could not confirm the gain.
    result = make_timing("unknown", 1, None, "unknown", gain_status="optimal")
    lines = report.timing_text(result, SPECS)
    (gain,) = [line for line in lines if "count on" in line]
    assert gain.endswith(": £0.01")
    (case,) = [line for line in lines if "Best gain with" in line]
    assert "UNKNOWN" in case and "Z3 did not prove a result" in case
    assert not any("cvc5 could not confirm" in line for line in lines)
    data = report.timing_dict(result, SPECS)
    assert data["unknown"] is True and data["status"] == "unknown"
    assert data["gain_status"] == "optimal" and data["per_case"][0]["status"] == "unknown"


def test_timing_text_shows_labels_gain_and_verification():
    text = "\n".join(report.timing_text(make_timing(), SPECS))
    assert "£123.45" in text
    assert "2026-04-06" in text and "2026-05-06" in text
    assert "controlled by employer, claimant; checked by third_party_data" in text
    assert "controlled by decision_maker; checked by assessment" in text
    assert "cvc5 confirmed" in text and "Catala" in text
    assert "UNKNOWN" not in text


def test_timing_text_unknown_without_a_value_never_prints_zero():
    text = "\n".join(report.timing_text(make_timing("unknown", None, None, "unknown"), SPECS))
    assert text.count("UNKNOWN") >= 1
    assert "£0.00" not in text and "None" not in text
    d = report.timing_dict(make_timing("unknown", None, None, "unknown"), SPECS)
    assert d["unknown"] is True and d["gain"] is None and d["total"] is None


def test_timing_text_unknown_with_a_kept_value_says_it_is_not_confirmed():
    text = "\n".join(report.timing_text(make_timing("unknown", 500, 500, "unknown"), SPECS))
    assert "UNKNOWN" in text and "£5.00" in text
    assert "cvc5 could not confirm" in text


def test_judgement_text_and_dict():
    result = make_judgement()
    text = "\n".join(report.judgement_text(result, SPECS))
    assert "£390.50" in text and "£0.00" in text
    assert "controlled by decision_maker; checked by assessment" in text
    assert "UNKNOWN" not in text
    data = report.judgement_dict(result, SPECS)
    assert data["point"] == "has_lcw" and data["unknown"] is False
    assert data["largest"] == 39_050 and data["smallest"] == 0
    assert data["largest_witnesses"][1]["inputs"]["has_lcw"]["value"] is False


def test_judgement_text_unknown_with_one_missing_value():
    result = make_judgement("unknown", 39_050, None, "unknown", largest_status="optimal")
    text = "\n".join(report.judgement_text(result, SPECS))
    assert "UNKNOWN" in text and "£390.50" in text
    assert "None" not in text
    (largest,) = [line for line in text.splitlines() if "Largest value" in line]
    assert largest.endswith(": £390.50")
    (smallest,) = [line for line in text.splitlines() if "Smallest value" in line]
    assert "UNKNOWN" in smallest and "£0.00" not in smallest
    assert "Catala's interpreter gave the same award as Z3 at the witnesses of largest" in text
    data = report.judgement_dict(result, SPECS)
    assert data["largest_status"] == "optimal" and data["smallest_status"] == "unknown"
    assert data["verification"]["replayed"] == ["largest"]


def test_text_report_ends_with_the_model_gaps_pointer_and_has_the_strategic_sections():
    text = report.to_text(make_report())
    assert text.rstrip().endswith("Model gaps that limit these findings: docs/model-gaps.md")
    assert "Timing gain" in text and "Value of the decision maker" in text
    unknown = report.to_text(make_report(timing=make_timing("unknown", None, None, "unknown")))
    assert unknown.splitlines()[1].startswith("UNKNOWN")  # near the top, before any section


def test_replay_runs_the_rules_that_the_provenance_describes(tmp_path: Path, capsys, monkeypatch):
    import shutil

    copy = tmp_path / "rules"
    shutil.copytree(ROOT / "rules", copy)  # keeps modification times, so the IR is not stale
    git(tmp_path, "init", "-q")
    seen = {}

    def stub(result):
        def query(*args, rules=None, **kwargs):
            seen["rules"] = rules
            return result

        return query

    monkeypatch.setattr(strategic, "timing", stub(make_timing()))
    monkeypatch.setattr(strategic, "judgement_value", stub(make_judgement()))
    for argv in (("timing",), ("judgement", "has_lcw")):
        seen.clear()
        code = cli.main(["query", argv[0], UC_IR, *argv[1:], "--inputs", UC_BOUNDS,
                         "--rules", str(copy)])
        assert code == 0, capsys.readouterr().err
        assert seen["rules"] == copy / "uc.catala_en"
        assert str(copy) not in capsys.readouterr().err


def test_a_rules_directory_without_the_rules_file_is_refused(tmp_path: Path, capsys, monkeypatch):
    def must_not_run(*args, **kwargs):
        raise AssertionError("the query ran")

    monkeypatch.setattr(strategic, "timing", must_not_run)
    monkeypatch.setattr(strategic, "judgement_value", must_not_run)
    for argv in (("timing",), ("judgement", "has_lcw")):
        code = cli.main(["query", argv[0], UC_IR, *argv[1:], "--inputs", UC_BOUNDS,
                         "--rules", str(tmp_path)])
        err = capsys.readouterr().err
        assert code == 1
        assert err.startswith("bm:") and "uc.catala_en" in err and err.count("\n") == 1


def _spy_on_the_differential_check(monkeypatch) -> list[Path]:
    """Make the differential check run one household, and return the rules files Catala is given.

    Catala runs for real. PolicyEngine UK is replaced by Catala's own award, so
    there is no mismatch and the test is fast.
    """
    from bm import catala_run, households, policyengine

    household = {
        "assessment_period_start": 20549, "earned_income": 148150,
        "aged_25_or_over": True, "has_lcw": True, "housing_costs_element": 0,
    }
    seen: list[Path] = []
    real = catala_run.outputs

    def outputs(rules, scope, inputs):
        seen.append(rules)
        return real(rules, scope, inputs)

    monkeypatch.setattr(households, "generate", lambda *args, **kwargs: [household])
    monkeypatch.setattr(catala_run, "outputs", outputs)
    monkeypatch.setattr(
        policyengine, "award", lambda h: int(real(ROOT / "rules" / "uc.catala_en",
                                                  "UniversalCredit", household)["award"])
    )
    return seen


def _copy_of_the_rules(tmp_path: Path) -> Path:
    import shutil

    copy = tmp_path / "rules"
    shutil.copytree(ROOT / "rules", copy)  # keeps modification times, so the IR is not stale
    git(tmp_path, "init", "-q")
    return copy


def test_report_runs_the_differential_check_on_the_rules_given(tmp_path: Path, capsys, monkeypatch):
    from bm import coverage, queries

    copy = _copy_of_the_rules(tmp_path)
    seen = _spy_on_the_differential_check(monkeypatch)
    monkeypatch.setattr(queries, "emr", lambda *args, **kwargs: EmrResult("unknown", None, None, None, None, None, {}))
    monkeypatch.setattr(coverage, "check", lambda *args, **kwargs: [])
    monkeypatch.setattr(strategic, "timing", lambda *args, **kwargs: make_timing())
    monkeypatch.setattr(strategic, "judgement_value", lambda *args, **kwargs: make_judgement())
    cli.main(["report", UC_IR, "--inputs", UC_BOUNDS, "--rules", str(copy), "--n-random", "1"])
    assert seen and set(seen) == {copy / "uc.catala_en"}, capsys.readouterr().err


def test_check_runs_the_differential_check_on_the_rules_given(tmp_path: Path, capsys, monkeypatch):
    copy = _copy_of_the_rules(tmp_path)
    seen = _spy_on_the_differential_check(monkeypatch)
    code = cli.main(["check", UC_IR, "--inputs", UC_BOUNDS, "--rules", str(copy), "--n-random", "1"])
    assert code == 0, capsys.readouterr().err
    assert seen and set(seen) == {copy / "uc.catala_en"}


# The window query.

WINDOW_IR = str(ROOT / "build" / "claim_window.bm-ir.json")
WINDOW4_IR = str(ROOT / "build" / "claim_window4.bm-ir.json")
WINDOW_INPUTS = str(ROOT / "rules" / "claim_window.inputs.toml")
WINDOW_SPECS = inputs.load(Path(WINDOW_INPUTS), ir.load(Path(WINDOW_IR)))
MODEL_GAPS = "Model gaps that limit these findings: docs/model-gaps.md"
# One household, in the realistic case, with a fixed total: one case, and fast.
FIXED_HOUSEHOLD = [
    "--fix", "aged_25_or_over=true", "--fix", "has_lcw=true",
    "--fix", "housing_costs_element=804.00", "--fix", "claim_after_end=true",
    "--fix", "claim_each_month=true", "--fix", "lcw_carries_over=true",
    "--total", "7800.00",
]  # fmt: skip


def run_window(*argv: str, ir_file: str = WINDOW_IR) -> tuple[int, str, str]:
    """The exit status, stdout and stderr of `bm query window`, with the window inputs."""
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["query", "window", ir_file, "--inputs", WINDOW_INPUTS, *argv])
    return code, out.getvalue(), err.getvalue()


@pytest.fixture(scope="module")
def fixed_window() -> tuple[int, dict, str]:
    """The fixed household's JSON and text, each run once."""
    code, out, err = run_window(*FIXED_HOUSEHOLD, "--json")
    assert err == ""
    text_code, text, err = run_window(*FIXED_HOUSEHOLD)
    assert err == "" and text_code == code
    return code, json.loads(out), text


def test_query_window_json_for_a_fixed_household(fixed_window):
    code, data, _ = fixed_window
    assert code == 0
    assert data["query"] == "window"
    assert data["unknown"] is False and data["status"] == "optimal"
    assert data["probe"] is False and data["relaxed"] is False
    assert data["periods"] == 3 and len(data["starts"]) == 3
    assert data["total"] == 780_000
    assert data["fixed"]["housing_costs_element"] == 80_400
    assert data["provenance"]["ir_catala_version"] == "1.3.0"
    assert data["provenance"]["translation"].startswith("exact")
    assert data["verification"]["cvc5"] == "confirmed"
    assert data["verification"]["replay"] == "matched"
    (case,) = data["cases"]
    assert case["realistic"] is True
    assert set(case["figures"]) == {
        "gain", "loss", "spread", "extra_payday_max", "extra_payday_min",
    }  # fmt: skip
    assert case["figures"]["gain"]["value"] >= 0
    assert case["figures"]["gain"]["status"] == "optimal"
    assert case["figures"]["gain"]["lower_bound"] is False
    assert data["excluded"]


def test_query_window_json_witnesses_carry_labels_and_traces(fixed_window):
    _, data, _ = fixed_window
    figure = data["cases"][0]["figures"]["gain"]
    assert [w["copy"] for w in figure["witnesses"]] == ["split", "even"]
    for w in figure["witnesses"]:
        assert set(w["inputs"]) == set(WINDOW_SPECS)
        for name, entry in w["inputs"].items():
            assert entry["controlled_by"] == list(WINDOW_SPECS[name].controlled_by)
            assert entry["checked_by"] == WINDOW_SPECS[name].checked_by
        assert [p["period"] for p in w["trace"]] == [1, 2, 3]
        for p in w["trace"]:
            assert {"start", "earnings", "earnings_used", "award", "entitled", "surplus_after"} <= set(p)


def test_query_window_text_for_a_fixed_household(fixed_window):
    _, data, text = fixed_window
    assert not text.startswith("PROBE")
    assert text.rstrip().endswith(MODEL_GAPS)
    gain = data["cases"][0]["figures"]["gain"]["value"]
    assert report.money(gain) in text
    assert "realistic" in text
    assert "earnings used" in text and "surplus" in text
    assert "controlled by employer, claimant; checked by third_party_data" in text
    assert "Passported help is not modelled" in text
    assert "Reported earnings are taken as exact" in text
    assert "£2,500" in text and "31 March 2027" in text and "29 October 2026" in text
    assert "last-period rule" in text  # the general excluded note
    assert "Provenance" in text
    assert "—" not in text


def test_query_window_relaxed_needs_probe(capsys):
    code, out, err = run_window(*FIXED_HOUSEHOLD, "--relaxed")
    assert code == 1 and out == ""
    assert err.startswith("bm: QueryRefused: ") and err.count("\n") == 1
    assert "relaxed" in err


def test_query_window_longer_window_needs_probe():
    code, out, err = run_window(*FIXED_HOUSEHOLD, ir_file=WINDOW4_IR)
    assert code == 1 and out == ""
    assert err.startswith("bm: QueryRefused: ") and err.count("\n") == 1
    assert "probe" in err


def test_query_window_probe_is_labelled_and_leaves_out_the_payday_figures():
    code, out, err = run_window(*FIXED_HOUSEHOLD, "--probe", ir_file=WINDOW4_IR)
    assert err == "" and code == 0
    assert out.startswith("PROBE: not a finding")
    assert "Extra payday" not in out
    assert out.rstrip().endswith(MODEL_GAPS)
    _, js, _ = run_window(*FIXED_HOUSEHOLD, "--probe", "--json", ir_file=WINDOW4_IR)
    data = json.loads(js)
    assert data["probe"] is True and data["periods"] == 4
    assert set(data["cases"][0]["figures"]) == {"gain", "loss", "spread"}


def test_query_window_relaxed_probe_skips_replay_and_says_so():
    code, out, err = run_window(*FIXED_HOUSEHOLD, "--probe", "--relaxed")
    assert err == "" and code == 0
    assert out.startswith("PROBE: not a finding")
    assert "relaxed" in out.lower() and "not the rules" in out
    _, js, _ = run_window(*FIXED_HOUSEHOLD, "--probe", "--relaxed", "--json")
    data = json.loads(js)
    assert data["relaxed"] is True and data["probe"] is True
    assert data["provenance"]["translation"].startswith("relaxed")
    assert data["verification"]["replay"].startswith("skipped")


def test_query_window_disagreement_exits_1(monkeypatch):
    real = solvers.run

    def cvc5_finds_better(solver, script, timeout_ms, **kwargs):
        if solver == "cvc5":
            return solvers.SolverResult("sat", {}, "test")
        return real(solver, script, timeout_ms, **kwargs)

    monkeypatch.setattr(solvers, "run", cvc5_finds_better)
    code, out, err = run_window(*FIXED_HOUSEHOLD)
    assert code == 1
    assert "SolverDisagreement" in err and "Traceback" not in err
    assert out == ""


def test_query_window_unknown_exits_2_and_prints_no_amount(monkeypatch):
    monkeypatch.setattr(solvers, "run", lambda solver, script, timeout_ms, **kw: solvers.SolverResult("unknown", None, "test"))
    code, out, err = run_window(*FIXED_HOUSEHOLD)
    assert code == 2 and err == ""
    assert "UNKNOWN" in out and "£0.00" not in out
    code, js, _ = run_window(*FIXED_HOUSEHOLD, "--json")
    data = json.loads(js)
    assert code == 2 and data["unknown"] is True and data["status"] == "unknown"
    figures = data["cases"][0]["figures"]
    assert all(f["value"] is None and f["status"] == "unknown" for f in figures.values())


def test_query_window_with_no_household_exits_1():
    code, out, err = run_window(
        "--fix", "aged_25_or_over=true", "--fix", "has_lcw=false",
        "--fix", "housing_costs_element=0.00", "--fix", "claim_after_end=true",
        "--fix", "claim_each_month=true", "--total", "9000.00",
    )  # fmt: skip
    assert code == 1 and out == ""
    assert err.startswith("bm: NoHousehold: ") and err.count("\n") == 1


@pytest.mark.parametrize(
    "bad", ["earnings_1=10.00", "start_2=2026-05-06", "nonsense=1", "has_lcw=maybe"]
)
def test_query_window_bad_fix_exits_1(bad):
    code, out, err = run_window("--fix", bad)
    assert code == 1 and out == ""
    assert err.startswith("bm: ") and err.count("\n") == 1


def test_query_window_bad_total_and_start_exit_1():
    for args in (["--total", "7800"], ["--start", "2027-03-31"], ["--start", "yesterday"]):
        code, out, err = run_window(*FIXED_HOUSEHOLD[:-2], *args)
        assert code == 1 and out == ""
        assert err.startswith("bm: ") and err.count("\n") == 1, args


# The window report, from hand-made results.


def make_window(figures: dict, *, excluded=None, **kwargs):
    from bm.window import CaseResult, WindowResult

    case = {"claim_after_end": False}
    base = dict(
        status="optimal", periods=3, probe=False, relaxed=False, starts=[20_549, 20_579, 20_610],
        total=None, fixed={}, cases=[CaseResult(case, False, figures)],
        excluded=["a general note"] + (excluded or []),
        verification={"cvc5": "confirmed", "replay": "not run", "replayed": []}, versions={},
    )  # fmt: skip
    return WindowResult(**{**base, **kwargs})


def window_figure(value, status="optimal", lower_bound=False):
    from bm.window import Figure

    return Figure(value, status, lower_bound, [])


def test_window_text_says_at_least_for_a_lower_bound():
    result = make_window({"loss": window_figure(12_345, lower_bound=True), "gain": window_figure(500)})
    text = "\n".join(report.window_text(result, WINDOW_SPECS))
    assert "at least £123.45" in text
    assert "at least £5.00" not in text and "£5.00" in text


def test_window_text_never_prints_an_infeasible_figure_as_nil():
    note = "In the case claim_after_end no, the even split ends the window at nil, so the case has no figures."
    result = make_window(
        {"gain": window_figure(None, "infeasible"), "loss": window_figure(None, "infeasible", True)},
        excluded=[note],
    )
    text = "\n".join(report.window_text(result, WINDOW_SPECS))
    assert "not available: the even split ends the window at nil, so the case has no figures." in text
    assert "£0.00" not in text


def test_window_text_unknown_is_not_an_amount():
    result = make_window(
        {"gain": window_figure(None, "unknown"), "loss": window_figure(700, "unknown", True)},
        status="unknown",
    )
    text = "\n".join(report.window_text(result, WINDOW_SPECS))
    assert "UNKNOWN" in text and "not the same as" in text
    assert "£0.00" not in text
    assert "Z3 found at least £7.00, but cvc5 could not confirm" in text
    assert report.window_json(result, WINDOW_SPECS, None)["unknown"] is True


def test_query_window_shows_every_realistic_case_first_and_an_unavailable_figure_in_words():
    # has_lcw free, so there are two realistic cases (with LCW carried over, and without LCW)
    # and one other. At this total the even split ends in nil without LCW.
    code, out, err = run_window(
        "--fix", "aged_25_or_over=true", "--fix", "housing_costs_element=804.00",
        "--fix", "claim_after_end=true", "--fix", "claim_each_month=true",
        "--total", "7800.00", "--json",
    )  # fmt: skip
    data = json.loads(out)
    assert code == 0 and err == ""
    assert [c["realistic"] for c in data["cases"]] == [True, True, False]
    nil = next(c for c in data["cases"] if c["case"].get("has_lcw") is False)
    assert {f["status"] for f in nil["figures"].values()} == {"infeasible"}
    assert all(f["value"] is None and "even split ends the window at nil" in f["reason"] for f in nil["figures"].values())
    code, text, _ = run_window(
        "--fix", "aged_25_or_over=true", "--fix", "housing_costs_element=804.00",
        "--fix", "claim_after_end=true", "--fix", "claim_each_month=true",
        "--total", "7800.00",
    )  # fmt: skip
    assert "not available: the even split ends the window at nil" in text
    assert "Households for the other cases are in the --json output." in text
    assert text.index("(realistic)") < text.index("(not the realistic case)")
