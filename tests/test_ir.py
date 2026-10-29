import json
from pathlib import Path

import pytest

from bm import ir

ROOT = Path(__file__).resolve().parent.parent
UC_IR = ROOT / "build" / "uc.bm-ir.json"


def test_load_rejects_unknown_version(tmp_path):
    data = json.loads(UC_IR.read_text())
    data["bm_ir_version"] = 1
    path = tmp_path / "v1.bm-ir.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ir.UnsupportedIrVersion):
        ir.load(path)


def test_load_uc_scope():
    scope = ir.load(UC_IR)
    assert scope.name == "UniversalCredit"
    assert [v.name for v in scope.inputs] == [
        "assessment_period_start",
        "earned_income",
        "aged_25_or_over",
        "has_lcw",
        "housing_costs_element",
    ]
    assert scope.outputs == [
        "standard_allowance",
        "work_allowance",
        "earnings_deduction",
        "maximum_amount",
        "award",
    ]
    assert [d.name for d in scope.definitions] == ["deduction_rate", *scope.outputs]
