"""PolicyEngine UK as the independent oracle for the Universal Credit award.

`award` maps one household of our inputs onto a PolicyEngine UK situation and
returns the monthly award in pence. Checked on 29 October 2026 against
policyengine-uk 2.164.2 (the version in uv.lock), reading its installed source
under `policyengine_uk/`, not from memory.

Variables, one per input. "Variables" means files under `variables/gov/dwp/universal_credit/`
unless a path is given; "parameters" are under `parameters/gov/dwp/universal_credit/`.

* `earned_income`: person variable `uc_individual_earned_income_before_mif`
  (`income/uc_individual_earned_income_before_mif.py`), given as an input
  although it has a formula. Our `earned_income` is the Universal Credit
  earned income of regulation 22(1)(b), which is already net of income tax,
  National Insurance and pension contributions (regulation 55(5)). The
  variable above is PolicyEngine's equivalent. Giving the gross
  `employment_income` instead makes PolicyEngine deduct tax and National
  Insurance itself, which is a different quantity and shifts every award
  once annual earnings pass about 12,570 pounds (about 1,047 a month). At
  500, 1,000 and 710.10 pounds a month the two routes agree.
  PolicyEngine then applies the minimum income floor only where
  `uc_mif_applies` (`income/income_floor/uc_mif_applies.py`) holds, which it
  does not for a household with no self-employment.
* `aged_25_or_over`: person variable `age` (core variable, whole years).
  25 when true and 24 when false. The threshold is the parameter
  `standard_allowance/claimant_type/age_threshold.yaml` (25 from 2017-04-01),
  read in `standard_allowance/uc_standard_allowance_claimant_type.py`.
* `has_lcw`: person variable `uc_limited_capability_for_work`
  (`disability_element/limited_work_ability/uc_limited_capability_for_work.py`).
  `work_allowance/is_uc_work_allowance_eligible.py` reads it for the work
  allowance. The disability elements stay at zero, as they should: this
  variable is not the work-related-activity one.
* `housing_costs_element`: benefit unit variable `uc_housing_costs_element`
  (`housing_costs_element/uc_housing_costs_element.py`), given as an input
  although it has a formula (from tenure, rent, the Local Housing Allowance
  cap and non-dependant deductions), as `uc_individual_earned_income_before_mif`
  is. Our input is the element already worked out, so it is set directly, to
  12 times the monthly element in pounds. `work_allowance/uc_work_allowance.py`
  takes the `with_housing` amount when that element is above 0 and the
  `without_housing` one otherwise, which is the reading in our rules. The
  element is also a term of `uc_maximum_amount` (`uc_maximum_amount.py`), as in
  our rules. Files read on 29 October 2026 from policyengine-uk 2.164.2.
* Single adult, no children: one person, in one benefit unit, in one
  household, with no child. `is_uc_single_or_joint_claimant` therefore
  gives a single claimant.
* No other income: no other income variable is set, so unearned income is 0.
  Capital is 0, below `means_test/capital/limit.yaml` (16,000 pounds).
* Take-up: `would_claim_uc` (benefit unit) is set to true. Its default is also
  true for a situation, but it is the one variable that gates the award
  (`claims_universal_credit`) and is stochastic for data-built simulations,
  so it is stated.
* Deductions for debt: `uc_deduction_random_draw` is 1.0 in a household
  situation (`deductions/uc_deduction_random_draw.py`), so no deduction is
  made. No input is needed.

Period. `universal_credit` and everything it uses have `definition_period =
YEAR` (`universal_credit.py`), so PolicyEngine UK cannot compute the award for
a month. Its parameters are converted to UK fiscal years in
`utils/parameters.py` (`convert_to_fiscal_year_parameters`): the bare year
2026 means the tax year from April 2026 and every ordinary parameter takes its
30 April 2026 value. So the period is the year number of the tax year that
contains the assessment period start (the year before when the start is before
6 April). The day within the year does not matter, which is pinned by
`test_pe_period_pinned`.

Monthly figure. PolicyEngine annualises its monthly parameters by multiplying by
12 (`MONTHS_IN_YEAR`) in `standard_allowance/uc_standard_allowance.py` and
`work_allowance/uc_work_allowance.py`. We therefore give it 12 times the monthly
earned income and divide the annual award it returns by 12. The reduction rate
is a rate, so it is not scaled.

Parameters for 2026/27, as PolicyEngine holds them:

* Standard allowance, single: 338.58 pounds a month under 25 (`SINGLE_YOUNG`)
  and 424.90 pounds a month at 25 or over (`SINGLE_OLD`), both from 2026-04-01.
  File: `standard_allowance/amount.yaml`. These match our rules (regulation 36).
* Work allowance without housing: 710 pounds a month from 2026-04-01; with
  housing 427. File: `means_test/work_allowance.yaml`. Matches our rules
  (regulation 22).
* Taper (reduction rate): 0.55 since 2021-11-24. File:
  `means_test/reduction_rate.yaml`. Matches our rules (regulation 22(1)(b)).
* PolicyEngine's rates change on 1 April 2026; ours on 6 April 2026. The two
  differ only for starts from 1 to 5 April 2026, which our rules reject.

Exact pence. PolicyEngine returns a float32 array and does no rounding. The
conversion is in `_to_pence`: the float is read through `Decimal(repr(x))`,
never compared as a float, turned into monthly pence, snapped to the nearest
twentieth of a penny (every amount is a whole number of pence at 55%, a
multiple of 1/20 penny), and then rounded half up to a whole penny as
regulation 6(1) of S.I. 2013/376 does. This rounds the award once, at the end.
The snap raises if the value is more than 0.02 of a penny from the grid. That
is a guard against gross corruption only: the grid spacing is 0.05, so values
up to 0.02 off it pass, and float32 noise reached 0.0072 in a 3,000-household
sweep, so a tighter limit would leave little margin.
Our Catala rules round the earnings deduction instead. The two orders can
differ by a penny when the deduction ends in a half penny, for example earnings
of 710.10 pounds with limited capability for work. Such a household is logged
in `docs/mismatches.md` when the differential check finds it.
"""

from datetime import date
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

from policyengine_uk import Simulation

from bm import units

MONTHS_IN_YEAR = 12
# Every amount at a 55% taper is a multiple of 1/20 of a penny.
GRID = 20
# How far the float32 result may sit from that grid, in pence, before we refuse it.
GRID_TOLERANCE = Decimal("0.02")

INPUT_NAMES = {
    "assessment_period_start",
    "earned_income",
    "aged_25_or_over",
    "has_lcw",
    "housing_costs_element",
}


def tax_year(start: date) -> int:
    """The PolicyEngine period: the year in which the UK tax year containing `start` begins."""
    return start.year if (start.month, start.day) >= (4, 6) else start.year - 1


def _to_pence(annual_pounds: float) -> int:
    """Monthly award in whole pence from PolicyEngine's annual award in pounds."""
    monthly_pence = Decimal(repr(float(annual_pounds))) * 100 / MONTHS_IN_YEAR
    snapped = (monthly_pence * GRID).quantize(Decimal(1), rounding=ROUND_HALF_EVEN) / GRID
    if abs(monthly_pence - snapped) > GRID_TOLERANCE:
        raise ValueError(
            f"PolicyEngine award {annual_pounds!r} a year is not a whole number of "
            f"twentieths of a penny a month, so the taper is not 55% of whole pence"
        )
    return int(snapped.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _pounds(pence: int) -> float:
    """Pounds from whole pence. PolicyEngine takes floats; the division is exact first."""
    return float(units.to_pounds(pence))


def award(inputs: dict[str, int | bool]) -> int:
    """The monthly Universal Credit award in pence, as PolicyEngine UK computes it."""
    if set(inputs) != INPUT_NAMES:
        raise ValueError(f"expected exactly {sorted(INPUT_NAMES)}, got {sorted(inputs)}")
    for name in ("assessment_period_start", "earned_income", "housing_costs_element"):
        if type(inputs[name]) is not int:
            raise TypeError(f"{name} must be an int, got {inputs[name]!r}")
    for name in ("aged_25_or_over", "has_lcw"):
        if type(inputs[name]) is not bool:
            raise TypeError(f"{name} must be a bool, got {inputs[name]!r}")
    start = units.to_date(inputs["assessment_period_start"])
    period = str(tax_year(start))
    annual_earned_income = _pounds(inputs["earned_income"] * MONTHS_IN_YEAR)
    annual_housing = _pounds(inputs["housing_costs_element"] * MONTHS_IN_YEAR)
    person = {
        "age": {period: 25 if inputs["aged_25_or_over"] else 24},
        "uc_limited_capability_for_work": {period: bool(inputs["has_lcw"])},
        "uc_individual_earned_income_before_mif": {period: annual_earned_income},
    }
    situation = {
        "people": {"claimant": person},
        "benunits": {
            "benunit": {
                "members": ["claimant"],
                "would_claim_uc": {period: True},
                "uc_housing_costs_element": {period: annual_housing},
            }
        },
        "households": {"household": {"members": ["claimant"]}},
    }
    annual = Simulation(situation=situation).calculate("universal_credit", period)
    return _to_pence(annual[0])
