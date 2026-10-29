"""Tests of the independent reference for the claim window.

The expected values are the hand-worked figures of the plan's table of window
tests, in pence. Household H is aged 25 or over, has LCW and a housing costs
element of 80,400p.
"""

from datetime import date

import pytest

import reference_uc as ref

STARTS = [date(2026, 4, 6), date(2026, 5, 6), date(2026, 6, 6)]
H = {"aged_25": True, "lcw": True, "housing": 80_400}
ALL_TRUE = {"claim_after_end": True, "claim_each_month": True, "lcw_carries_over": True}


def run(earnings, *, household=H, case=None, starts=STARTS):
    case = {**ALL_TRUE, **(case or {})}
    return ref.window(
        earnings,
        starts,
        household["aged_25"],
        household["lcw"],
        household["housing"],
        case["claim_after_end"],
        case["claim_each_month"],
        case["lcw_carries_over"],
    )


def awards(trace):
    return [p.award for p in trace]


def total(earnings, case=None):
    return sum(awards(run(earnings, case=case)))


def test_even_split_gives_the_remainder_to_the_earliest_periods():
    assert ref.even_split(100_000, 3) == [33_334, 33_333, 33_333]
    assert ref.even_split(100_001, 3) == [33_334, 33_334, 33_333]
    assert ref.even_split(0, 3) == [0, 0, 0]


def test_thresholds_of_household_h():
    assert ref.nil_uc_threshold(True, True, 80_400) == 266_136
    assert ref.relevant_threshold(date(2026, 4, 6), True, True, 80_400) == 516_136
    assert ref.relevant_threshold(date(2027, 3, 31), True, True, 80_400) == 516_136
    assert ref.relevant_threshold(date(2027, 4, 1), True, True, 80_400) == 296_136


def test_nil_uc_threshold_without_housing_or_lcw():
    # M x 20/11 = 42,490 x 20 / 11 = 77,254.54..., rounded to 77,255.
    assert ref.nil_uc_threshold(True, False, 0) == 77_255
    # LCW with no housing uses the higher work allowance of 71,000p.
    assert ref.nil_uc_threshold(True, True, 0) == 77_255 + 71_000


def test_even_earnings_give_a_small_award_each_period():
    trace = run([260_000] * 3)
    assert awards(trace) == [3_375, 3_375, 3_375]
    assert sum(awards(trace)) == 10_125
    assert [p.entitled for p in trace] == [True, True, True]
    assert [p.surplus_after for p in trace] == [0, 0, 0]


def test_nil_last_period_ends_the_award_and_leaves_a_surplus():
    trace = run([0, 0, 780_000])
    assert awards(trace) == [122_890, 122_890, 0]
    assert trace[2].entitled is False
    assert trace[2].surplus_after == 263_864
    assert sum(awards(trace)) == 245_780


def test_reclaim_after_a_nil_period_uses_the_surplus():
    trace = run([780_000, 200_000, 200_000])
    assert trace[0].award == 0
    assert trace[0].surplus_after == 263_864
    assert trace[1].earnings_used == 463_864
    assert trace[1].award == 0
    assert trace[1].surplus_after == 0
    assert trace[2].award == 36_375


def test_a_failed_month_that_is_not_a_claim_leaves_the_surplus():
    trace = run([780_000, 200_000, 200_000], case={"claim_each_month": False})
    assert trace[1].surplus_after == 263_864
    assert trace[2].award == 0


def test_no_claim_after_the_end_pays_nothing_and_keeps_the_surplus():
    trace = run([780_000, 200_000, 200_000], case={"claim_after_end": False})
    assert trace[1].award == 0
    assert trace[2].award == 0
    assert trace[2].surplus_after == 263_864


def test_losing_the_lcw_finding_lowers_the_award_after_the_end():
    trace = run([780_000, 200_000, 200_000], case={"lcw_carries_over": False})
    assert trace[2].award == 12_890


def test_an_award_that_ends_twice():
    household = {"aged_25": True, "lcw": False, "housing": 0}
    trace = run([300_000, 0, 300_000], household=household)
    assert trace[0].award == 0
    assert trace[0].surplus_after == 0
    assert trace[1].award == 42_490
    assert trace[2].award == 0


def test_a_period_after_31_march_2027_uses_the_300_pound_threshold():
    starts = [date(2027, 4, 6), date(2027, 5, 6), date(2027, 6, 6)]
    trace = run([780_000, 0, 0], starts=starts)
    assert trace[0].surplus_after == 780_000 - 296_136


def test_claims_are_made_in_months_one_to_five_only():
    # The award ends in period 1. Periods 2 to 6 are months 1 to 5 after the
    # end: claims that fail, each adding to the surplus. Period 7 is month 6,
    # which is not a claim, so the surplus stays as it was.
    starts = [date(2026, 4, 6)] + [date(2026, m, 6) for m in range(5, 11)]
    trace = run([900_000] * 7, starts=starts)
    assert awards(trace) == [0] * 7
    assert trace[5].surplus_after > trace[4].surplus_after
    assert trace[6].surplus_after == trace[5].surplus_after
    assert trace[6].earnings_used == 900_000


def test_window_refuses_mismatched_lengths():
    with pytest.raises(ValueError):
        run([0, 0], starts=STARTS)


# figure_value


def value(figure, copies, case=None):
    case = {**ALL_TRUE, **(case or {})}
    return ref.figure_value(figure, copies, STARTS, True, True, 80_400, case)


def test_figure_value_gain_and_loss_are_opposites():
    even = ref.even_split(780_000, 3)
    split = [780_000, 0, 0]
    loss = value("loss", {"even": even, "split": split})
    gain = value("gain", {"even": even, "split": split})
    assert loss == total(even) - total(split)
    assert gain == total(split) - total(even)
    assert loss == -gain


def test_figure_value_spread_and_payday():
    a, b = [780_000, 200_000, 200_000], [260_000] * 3
    assert value("spread", {"a": a, "b": b}) == total(a) - total(b)
    payday, even = [100_000, 200_000, 100_000], ref.even_split(400_000, 3)
    for figure in ("extra_payday_max", "extra_payday_min"):
        assert value(figure, {"even": even, "payday": payday}) == total(even) - total(payday)


def test_figure_value_is_none_where_a_copy_breaks_the_last_period_rule():
    even = ref.even_split(780_000, 3)
    nil_last = [0, 0, 780_000]
    assert value("gain", {"even": even, "split": nil_last}) is None
    assert value("loss", {"even": even, "split": nil_last}) is None
    assert value("spread", {"a": nil_last, "b": even}) is None
    assert value("spread", {"a": even, "b": nil_last}) is None
    # The even copy keeps the rule too.
    assert value("loss", {"even": nil_last, "split": even}) is None
    assert value("extra_payday_max", {"even": even, "payday": nil_last}) is None


def test_without_a_claim_the_subtracted_copy_drops_the_rule():
    case = {"claim_after_end": False}
    even = ref.even_split(780_000, 3)
    nil_last = [0, 0, 780_000]
    assert value("loss", {"even": even, "split": nil_last}, case) == total(even, case) - total(nil_last, case)
    assert value("spread", {"a": even, "b": nil_last}, case) == total(even, case) - total(nil_last, case)
    assert value("extra_payday_max", {"even": even, "payday": nil_last}, case) == total(even, case) - total(
        nil_last, case
    )
    assert value("extra_payday_min", {"even": even, "payday": nil_last}, case) is not None
    # The gain keeps the rule for the split, and the even copy always does.
    assert value("gain", {"even": even, "split": nil_last}, case) is None
    assert value("spread", {"a": nil_last, "b": even}, case) is None
    assert value("loss", {"even": nil_last, "split": even}, case) is None
    # The gain subtracts the even copy, which keeps the rule in every case.
    assert value("gain", {"even": nil_last, "split": even}, case) is None


# brute_force


def brute(figure, total_pence, step, case=None):
    case = {**ALL_TRUE, **(case or {})}
    return ref.brute_force(figure, total_pence, step, STARTS, True, True, 80_400, case)


def test_brute_force_figures_are_not_negative_when_the_baseline_is_on_the_grid():
    # The even split of 600,000 is 200,000 each, so it is on the grid.
    for figure in ("gain", "loss", "spread"):
        assert brute(figure, 600_000, 100_000) >= 0


def test_brute_force_gain_matches_an_explicit_search():
    even = ref.even_split(600_000, 3)
    best = max(
        v
        for e1 in range(0, 600_001, 100_000)
        for e2 in range(0, 600_001 - e1, 100_000)
        if (v := value("gain", {"even": even, "split": [e1, e2, 600_000 - e1 - e2]})) is not None
    )
    assert brute("gain", 600_000, 100_000) == best


def test_brute_force_payday_ranges_over_p_with_4p_within_the_total():
    # P is 0, 100,000 or 200,000 pence only, since 4P must not exceed 800,000.
    seen = [
        value("extra_payday_max", {"even": ref.even_split(4 * p, 3), "payday": [p, 2 * p, p]})
        for p in (0, 100_000, 200_000)
    ]
    seen = [v for v in seen if v is not None]
    assert brute("extra_payday_max", 800_000, 100_000) == max(seen)
    assert brute("extra_payday_min", 800_000, 100_000) == min(seen)


def test_brute_force_refuses_a_total_that_is_not_a_multiple_of_the_step():
    with pytest.raises(ValueError):
        brute("gain", 600_050, 100_000)
