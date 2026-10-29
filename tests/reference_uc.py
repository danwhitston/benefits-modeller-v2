"""A reference model of the UC award, for tests only.

It is written from the rules in `rules/uc.catala_en` by hand, in integer pence,
and shares nothing with the translator or the SMT encoding of a query, so a
brute force over it can check a solver's optimum independently. Every
assessment period is taken to start on or after 6 April 2026, where the rates
below apply.

The deduction is 55% of the earnings above the work allowance, rounded to the
nearest penny with halves rounded up
([regulation 6(1)](https://www.legislation.gov.uk/uksi/2013/376/regulation/6)
of the Universal Credit Regulations 2013, checked 29 October 2026). For x >= 0
pence that is `(55 * x + 50) // 100`, which is Catala's rounding, half away
from zero, on a non-negative amount.
"""

STANDARD_ALLOWANCE = {True: 42_490, False: 33_858}  # 25 or over; under 25
HIGHER_WORK_ALLOWANCE = 71_000  # LCW, no housing costs element
LOWER_WORK_ALLOWANCE = 42_700  # LCW, a housing costs element above 0


def work_allowance(lcw: bool, housing: int) -> int:
    if not lcw:
        return 0
    return LOWER_WORK_ALLOWANCE if housing > 0 else HIGHER_WORK_ALLOWANCE


def award(earned: int, aged_25: bool, lcw: bool, housing: int) -> int:
    """The monthly award in pence, floored at nil."""
    above = max(0, earned - work_allowance(lcw, housing))
    deduction = (55 * above + 50) // 100
    return max(0, STANDARD_ALLOWANCE[aged_25] + housing - deduction)
