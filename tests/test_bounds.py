import re
from datetime import date
from pathlib import Path

import pytest

from bm import bounds, ir

ROOT = Path(__file__).resolve().parent.parent
UC_IR = ROOT / "build" / "uc.bm-ir.json"
UC_INPUTS = ROOT / "rules" / "uc.inputs.toml"


def days(d: date) -> int:
    return (d - date(1970, 1, 1)).days


def test_bounds_missing_input(tmp_path):
    text = UC_INPUTS.read_text()
    # Drop the [inputs.earned_income] table, up to the next table or the end.
    text = re.sub(r"\[inputs\.earned_income\][^\[]*", "", text)
    assert "earned_income" not in text
    path = tmp_path / "inputs.toml"
    path.write_text(text)
    with pytest.raises(bounds.BoundsError):
        bounds.load(path, ir.load(UC_IR))


def test_bounds_values():
    result = bounds.load(UC_INPUTS, ir.load(UC_IR))
    assert result["earned_income"] == bounds.Bound("money", 0, 1_000_000)
    assert result["assessment_period_start"] == bounds.Bound(
        "date", days(date(2026, 4, 6)), days(date(2027, 4, 5))
    )
    assert set(result) == {"earned_income", "assessment_period_start"}
