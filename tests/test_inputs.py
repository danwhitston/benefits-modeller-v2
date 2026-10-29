import json
import re
from datetime import date
from pathlib import Path

import pytest

from bm import inputs, ir

ROOT = Path(__file__).resolve().parent.parent
UC_IR = ROOT / "build" / "uc.bm-ir.json"
UC_INPUTS = ROOT / "rules" / "uc.inputs.toml"


def days(d: date) -> int:
    return (d - date(1970, 1, 1)).days


def scope() -> ir.Scope:
    return ir.load(UC_IR)


def _table(text: str, name: str) -> re.Match:
    """The `[inputs.<name>]` table: its header, and its body up to the next table."""
    found = re.search(rf"^(\[inputs\.{name}\]\n)(.*?)(?=^\[|\Z)", text, re.M | re.S)
    assert found, f"no table for {name}"
    return found


def drop_table(name: str):
    return lambda text: text[: (m := _table(text, name)).start()] + text[m.end() :]


def set_key(name: str, key: str, value: object):
    """Set `key` in a table to `value` (written as JSON, which is valid TOML for these)."""

    def change(text: str) -> str:
        m = _table(text, name)
        body = re.sub(rf"^{key} = .*\n", "", m.group(2), flags=re.M)
        return text[: m.start(2)] + f"{key} = {json.dumps(value)}\n" + body + text[m.end(2) :]

    return change


def del_key(name: str, key: str):
    def change(text: str) -> str:
        m = _table(text, name)
        body = re.sub(rf"^{key} = .*\n", "", m.group(2), flags=re.M)
        assert body != m.group(2), f"{name} has no key {key}"
        return text[: m.start(2)] + body + text[m.end(2) :]

    return change


def add_table(name: str):
    return lambda text: (
        text + f'\n[inputs.{name}]\ntype = "bool"\ncontrolled_by = ["nobody"]\n'
        'checked_by = "dwp_records"\n'
    )


def test_missing_input(tmp_path):
    text = drop_table("earned_income")(UC_INPUTS.read_text())
    assert "earned_income" not in text
    path = tmp_path / "inputs.toml"
    path.write_text(text)
    with pytest.raises(inputs.InputsError):
        inputs.load(path, scope())


def test_bounds_values():
    result = inputs.bounds(inputs.load(UC_INPUTS, scope()))
    assert result["earned_income"] == inputs.Bound("money", 0, 1_000_000)
    assert result["assessment_period_start"] == inputs.Bound(
        "date", days(date(2026, 4, 6)), days(date(2027, 4, 5))
    )
    assert result["housing_costs_element"] == inputs.Bound("money", 0, 300_000)
    assert set(result) == {"earned_income", "assessment_period_start", "housing_costs_element"}


def test_real_file_has_labels():
    specs = inputs.load(UC_INPUTS, scope())
    assert list(specs) == [
        "assessment_period_start",
        "earned_income",
        "aged_25_or_over",
        "has_lcw",
        "housing_costs_element",
    ]
    assert specs["earned_income"].controlled_by == ("employer", "claimant")
    assert specs["earned_income"].checked_by == "third_party_data"
    assert specs["has_lcw"].controlled_by == ("decision_maker",)
    assert specs["has_lcw"].bound is None
    assert specs["housing_costs_element"].controlled_by == ("landlord",)
    assert specs["housing_costs_element"].checked_by == "documentary_evidence"


@pytest.mark.parametrize(
    "change, message",
    [
        (drop_table("has_lcw"), "no entry for inputs ['has_lcw']"),
        (set_key("has_lcw", "controlled_by", ["judge"]), "unknown controlled_by 'judge'"),
        (set_key("has_lcw", "checked_by", "vibes"), "unknown checked_by 'vibes'"),
        (del_key("earned_income", "checked_by"), "checked_by"),
        (set_key("earned_income", "controlled_by", []), "controlled_by"),
        (add_table("not_an_input"), "unknown inputs ['not_an_input']"),
    ],
)
def test_bad_files_refused(tmp_path, change, message):
    path = tmp_path / "inputs.toml"
    path.write_text(change(UC_INPUTS.read_text()))
    with pytest.raises(inputs.InputsError) as raised:
        inputs.load(path, scope())
    assert message in str(raised.value)


def test_bad_money_bound_names_the_cause(tmp_path):
    path = tmp_path / "inputs.toml"
    path.write_text(set_key("earned_income", "max", "£500")(UC_INPUTS.read_text()))
    with pytest.raises(inputs.InputsError) as raised:
        inputs.load(path, scope())
    assert "not a valid money bound" in str(raised.value)
    assert isinstance(raised.value.__cause__, ValueError)
