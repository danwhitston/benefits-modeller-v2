import json
import re
from datetime import date
from pathlib import Path

import pytest

from bm import inputs, ir

ROOT = Path(__file__).resolve().parent.parent
UC_IR = ROOT / "build" / "uc.bm-ir.json"
UC_INPUTS = ROOT / "rules" / "uc.inputs.toml"
WINDOW_INPUTS = ROOT / "rules" / "claim_window.inputs.toml"


def days(d: date) -> int:
    return (d - date(1970, 1, 1)).days


def scope() -> ir.Scope:
    return ir.load(UC_IR)


def window_scope(periods: int = 3) -> ir.Scope:
    name = "claim_window" if periods == 3 else f"claim_window{periods}"
    return ir.load(ROOT / "build" / f"{name}.bm-ir.json")


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
    assert result["housing_costs_element"] == inputs.Bound("money", 0, 80_400)
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


# The window inputs file: per-period expansion and conditional judgement points.


@pytest.mark.parametrize("periods", [3, 4, 5, 6])
def test_window_inputs_expand_per_period(periods):
    specs = inputs.load(WINDOW_INPUTS, window_scope(periods))
    ks = range(1, periods + 1)
    assert [n for n in specs if n.startswith("earnings_")] == [f"earnings_{k}" for k in ks]
    assert [n for n in specs if n.startswith("start_")] == [f"start_{k}" for k in ks]
    assert list(specs) == [s.name for s in window_scope(periods).inputs]
    for k in ks:
        assert specs[f"start_{k}"].bound == inputs.Bound(
            "date", days(date(2026, 4, 6)), days(date(2027, 3, 31))
        )
        assert specs[f"start_{k}"].controlled_by == ("claimant",)
        assert specs[f"start_{k}"].checked_by == "dwp_records"
        assert specs[f"earnings_{k}"].bound == inputs.Bound("money", 0, 1_000_000)


def test_window_judgement_point_labels():
    specs = inputs.load(WINDOW_INPUTS, window_scope())
    assert specs["claim_after_end"].controlled_by == ("decision_maker", "claimant")
    assert specs["claim_after_end"].checked_by == "dwp_records"
    assert specs["claim_each_month"].controlled_by == ("decision_maker",)
    assert specs["claim_each_month"].checked_by == "dwp_records"
    assert specs["lcw_carries_over"].controlled_by == ("decision_maker",)
    assert specs["lcw_carries_over"].checked_by == "assessment"
    assert specs["claim_each_month"].applies_when == "claim_after_end"
    assert specs["lcw_carries_over"].applies_when == "has_lcw"
    assert specs["claim_after_end"].applies_when is None
    assert specs["has_lcw"].applies_when is None


def test_shared_inputs_carry_the_same_labels():
    window, uc = inputs.load(WINDOW_INPUTS, window_scope()), inputs.load(UC_INPUTS, scope())
    pairs = {n: n for n in ("aged_25_or_over", "housing_costs_element", "has_lcw")}
    pairs |= {f"earnings_{k}": "earned_income" for k in (1, 2, 3)}
    pairs |= {f"start_{k}": "assessment_period_start" for k in (1, 2, 3)}
    for w, u in pairs.items():
        assert (window[w].controlled_by, window[w].checked_by) == (
            uc[u].controlled_by,
            uc[u].checked_by,
        )
    for n in ("aged_25_or_over", "housing_costs_element", "has_lcw"):
        assert window[n].bound == uc[n].bound
    assert window["earnings_1"].bound == uc["earned_income"].bound


def test_milestone_2_specs_have_no_condition():
    assert all(s.applies_when is None for s in inputs.load(UC_INPUTS, scope()).values())


def _window_refusal(tmp_path, change, message, periods=3):
    path = tmp_path / "window.toml"
    path.write_text(change(WINDOW_INPUTS.read_text()))
    with pytest.raises(inputs.InputsError) as raised:
        inputs.load(path, window_scope(periods))
    assert message in str(raised.value)


def test_per_period_on_a_boolean_refused(tmp_path):
    _window_refusal(
        tmp_path,
        lambda t: t + '\n[inputs.flag]\ntype = "bool"\nper_period = true\n'
        'controlled_by = ["nobody"]\nchecked_by = "dwp_records"\n',
        "per_period",
    )
    _window_refusal(tmp_path, set_key("has_lcw", "per_period", True), "per_period")


def test_per_period_entry_matching_nothing_refused(tmp_path):
    _window_refusal(
        tmp_path,
        lambda t: t
        + '\n[inputs.bonus]\ntype = "money"\nper_period = true\nmin = "0.00"\n'
        'max = "1.00"\ncontrolled_by = ["nobody"]\nchecked_by = "dwp_records"\n',
        "matches no input",
    )


def test_per_period_must_be_true(tmp_path):
    _window_refusal(tmp_path, set_key("earnings", "per_period", "yes"), "per_period")


def test_per_period_entry_clashing_with_an_explicit_one_refused(tmp_path):
    _window_refusal(
        tmp_path,
        lambda t: t
        + '\n[inputs.earnings_1]\ntype = "money"\nmin = "0.00"\nmax = "1.00"\n'
        'controlled_by = ["nobody"]\nchecked_by = "dwp_records"\n',
        "earnings_1",
    )


def test_per_period_file_refused_for_a_scope_without_periods(tmp_path):
    with pytest.raises(inputs.InputsError, match="matches no input"):
        inputs.load(WINDOW_INPUTS, scope())


@pytest.mark.parametrize(
    "parent, message",
    [
        ("nope", "unknown input"),
        ("aged_25_or_over", "judgement point"),  # a Boolean, but nobody decides it
        ("earnings_1", "Boolean"),
        ("lcw_carries_over", "applies_when"),  # itself conditional: no chains
        ("claim_each_month", "applies_when"),  # a child of claim_after_end
    ],
)
def test_bad_applies_when_refused(tmp_path, parent, message):
    _window_refusal(tmp_path, set_key("lcw_carries_over", "applies_when", parent), message)


def test_applies_when_on_a_non_judgement_point_refused(tmp_path):
    _window_refusal(
        tmp_path, set_key("aged_25_or_over", "applies_when", "has_lcw"), "judgement point"
    )


def test_applies_when_on_a_bounded_input_refused(tmp_path):
    _window_refusal(tmp_path, set_key("earnings", "applies_when", "has_lcw"), "applies_when")


def test_applies_when_on_itself_refused(tmp_path):
    _window_refusal(
        tmp_path, set_key("lcw_carries_over", "applies_when", "lcw_carries_over"), "itself"
    )
