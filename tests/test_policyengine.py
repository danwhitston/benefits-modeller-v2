from datetime import date

from bm import policyengine

EPOCH = date(1970, 1, 1)


def days(d: date) -> int:
    return (d - EPOCH).days


def household(start: date, earned_income: int, aged_25_or_over: bool, has_lcw: bool) -> dict:
    return {
        "assessment_period_start": days(start),
        "earned_income": earned_income,
        "aged_25_or_over": aged_25_or_over,
        "has_lcw": has_lcw,
    }


def test_pe_mapping_known_household():
    # 424.90 standard allowance, no work allowance, 55% of 500.00 = 275.00.
    h = household(date(2026, 5, 1), 50_000, True, False)
    assert policyengine.award(h) == 14_990


def test_pe_period_pinned():
    # PolicyEngine UK works in whole years, so two dates in the same tax year
    # must give the same award. This pins how the start date becomes a period.
    may = household(date(2026, 5, 1), 50_000, True, False)
    nov = household(date(2026, 11, 1), 50_000, True, False)
    assert policyengine.award(may) == policyengine.award(nov) == 14_990
    # The tax year begins on 6 April, and the 2025/26 rates are lower:
    # 400.14 - 275.00 = 125.14. This pins the boundary.
    before = household(date(2026, 4, 5), 50_000, True, False)
    after = household(date(2026, 4, 6), 50_000, True, False)
    assert policyengine.award(before) == 12_514
    assert policyengine.award(after) == 14_990

