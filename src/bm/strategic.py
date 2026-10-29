"""Strategic queries: what the input labels decide.

A strategic query asks what a party can gain by timing or by a judgement, over
households the caller leaves free. The labels in `rules/uc.inputs.toml` decide
how each input is treated:

- **Judgement points.** An input whose `controlled_by` includes
  `decision_maker`, and which the caller has not fixed, is a judgement point.
  The query expands the judgement points into every combination of their
  values, one case per combination, and refuses above a cap (default 8).
- **The choice.** `Split(input, periods=2)` makes the input's values in the two
  periods free, subject to a fixed total. The input must be money and its
  `controlled_by` must include `claimant` or `employer`; otherwise the query
  refuses.
- **Household facts.** Every other input has one value, the same in every
  period and every case.

The periods are the first assessment period, starting on a date the caller
chooses, and the one after it, starting one calendar month later. A calendar
month cannot be written in linear arithmetic, so Python computes the dates.
The day within the month does not affect the 2026/27 rules, so fixing the
dates loses nothing. That is a modelling choice, not a reading of regulation
21 of the Universal Credit Regulations 2013.

This module holds the parts that need no solver. The queries themselves are
built on it.
"""

import calendar
import itertools
from dataclasses import dataclass
from datetime import date

from bm import units
from bm.inputs import InputSpec


class QueryRefused(ValueError):
    """The query's inputs are not ones it can answer for."""


class NoHousehold(ValueError):
    """No household satisfies the query's constraints."""


@dataclass(frozen=True)
class Split:
    """The input whose values in each period are free, given a fixed total."""

    input: str
    periods: int = 2


DEFAULT_START = date(2026, 4, 6)
DEFAULT_CASE_CAP = 8
_CHOOSERS = ("claimant", "employer")


def judgement_points(specs: dict[str, InputSpec], fixed: dict[str, int | bool]) -> list[str]:
    """The unfixed inputs the decision maker controls, in scope order."""
    return [
        name
        for name, spec in specs.items()
        if "decision_maker" in spec.controlled_by and name not in fixed
    ]


def cases(
    specs: dict[str, InputSpec], points: list[str], cap: int = DEFAULT_CASE_CAP
) -> list[dict[str, bool]]:
    """Every combination of the points' values, with True first.

    With no points there is one empty case. Refuses a point that is not a
    Boolean input, and more than `cap` cases.
    """
    for point in points:
        spec = specs.get(point)
        if spec is None or spec.type != "bool":
            kind = "not an input" if spec is None else f"a {spec.type} input"
            raise QueryRefused(f"judgement point {point} must be a Boolean input, but is {kind}")
    count = 2 ** len(points)
    if count > cap:
        raise QueryRefused(
            f"{len(points)} judgement points give {count} cases, above the cap of {cap}"
        )
    return [
        dict(zip(points, values, strict=True))
        for values in itertools.product((True, False), repeat=len(points))
    ]


def check_choice(specs: dict[str, InputSpec], choice: Split) -> None:
    """Refuses a choice the claimant or employer cannot make between two periods."""
    spec = specs.get(choice.input)
    if spec is None:
        raise QueryRefused(f"{choice.input} is not an input")
    if spec.type != "money":
        raise QueryRefused(f"{choice.input} is a {spec.type} input; only money can be split")
    if not any(who in spec.controlled_by for who in _CHOOSERS):
        raise QueryRefused(
            f"{choice.input} is controlled by {', '.join(spec.controlled_by)}, "
            f"not by the {' or '.join(_CHOOSERS)}"
        )
    if choice.periods != 2:
        raise QueryRefused(f"only two periods are supported, not {choice.periods}")


def period_starts(first: date, specs: dict[str, InputSpec], periods: int = 2) -> list[date]:
    """The start of each period: the same day of the next month, or its last day.

    Refuses if any start lies outside the bounds of `assessment_period_start`.
    """
    starts = [first]
    for _ in range(periods - 1):
        # Months counted from year 0, so December rolls into January.
        year, month_index = divmod(starts[-1].year * 12 + starts[-1].month, 12)
        month = month_index + 1
        day = min(first.day, calendar.monthrange(year, month)[1])
        starts.append(date(year, month, day))
    bound = specs["assessment_period_start"].bound
    for start in starts:
        if not bound.min <= units.days(start) <= bound.max:
            raise QueryRefused(
                f"the assessment period starting {start.isoformat()} is outside "
                f"{units.to_date(bound.min).isoformat()} to {units.to_date(bound.max).isoformat()}"
            )
    return starts
