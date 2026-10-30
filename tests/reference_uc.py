"""A reference model of the UC award, for tests only.

The per-period award is written from the rules in `rules/uc.catala_en` by
hand, in integer pence. The claim window is written from the regulation text
and the design's readings (see below). Neither shares anything with the
translator or the SMT encoding of a query, so a brute force over it can check
a solver's optimum independently. Every
assessment period is taken to start on or after 6 April 2026, where the rates
below apply.

The deduction is 55% of the earnings above the work allowance, rounded to the
nearest penny with halves rounded up
([regulation 6(1)](https://www.legislation.gov.uk/uksi/2013/376/regulation/6)
of the Universal Credit Regulations 2013, checked 29 October 2026). For x >= 0
pence that is `(55 * x + 50) // 100`, which is Catala's rounding, half away
from zero, on a non-negative amount.

The claim window at the end of the file chains the same award over several
assessment periods. It is written from the rules on the end of an award,
surplus earnings and the reclaim, each cited where it is used, and from the
readings in the milestone 3 design
(`docs/superpowers/specs/2026-10-29-nil-assessment-periods-design.md`).
"""

from dataclasses import dataclass
from datetime import date
from itertools import product

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


# The claim window.

DE_MINIMIS_END = date(2027, 3, 31)  # last start date taking the larger threshold
SURPLUS_THRESHOLD_UNTIL_END = 250_000  # 2,500 pounds
SURPLUS_THRESHOLD_AFTER = 30_000  # 300 pounds
MAX_CLAIMS_AFTER_END = 5


def maximum_amount(aged_25: bool, housing: int) -> int:
    """The standard allowance plus the housing costs element (no other element is modelled)."""
    return STANDARD_ALLOWANCE[aged_25] + housing


def nil_uc_threshold(aged_25: bool, lcw: bool, housing: int) -> int:
    """The earnings at which the award is nil, in pence.

    It is M x 100 / 55 plus the work allowance
    ([regulation 54A(6)](https://www.legislation.gov.uk/uksi/2013/376/regulation/54A)
    of the Universal Credit Regulations 2013, checked 29 October 2026), where
    M is the maximum amount and there is no unearned income. M x 100 / 55 is
    M x 20 / 11, rounded once to the nearest penny with halves rounded up,
    which for M >= 0 is `(40 * M + 11) // 22`.
    """
    scaled = (40 * maximum_amount(aged_25, housing) + 11) // 22
    return scaled + work_allowance(lcw, housing)


def relevant_threshold(start: date, aged_25: bool, lcw: bool, housing: int) -> int:
    """The nil UC threshold plus 2,500 pounds, or 300 pounds from 1 April 2027.

    The larger figure applies to a period beginning before the temporary de
    minimis period ends on 31 March 2027
    ([regulation 5 of S.I. 2015/345](https://www.legislation.gov.uk/uksi/2015/345/regulation/5),
    checked 29 October 2026). A period beginning on 31 March 2027 itself is
    taken to be within it, which is the project's inference.
    """
    extra = SURPLUS_THRESHOLD_UNTIL_END if start <= DE_MINIMIS_END else SURPLUS_THRESHOLD_AFTER
    return nil_uc_threshold(aged_25, lcw, housing) + extra


@dataclass(frozen=True)
class PeriodTrace:
    earnings_used: int
    award: int
    entitled: bool
    surplus_after: int


def window(
    earnings: list[int],
    starts: list[date],
    aged_25: bool,
    lcw: bool,
    housing: int,
    claim_after_end: bool,
    claim_each_month: bool,
    lcw_carries_over: bool,
) -> list[PeriodTrace]:
    """Chain the award over consecutive assessment periods, in pence.

    The first period is a live award with no surplus. One period with an award
    below 1p ends the award from its first day
    ([regulation 17](https://www.legislation.gov.uk/uksi/2013/376/regulation/17)).
    Later periods can be treated as claims, up to 5 months after the end
    ([regulation 32A of the Claims and Payments Regulations 2013](https://www.legislation.gov.uk/uksi/2013/380/regulation/32A)),
    and the surplus earnings of the nil period are added to the earnings of
    the first period of each claim
    ([regulation 54A](https://www.legislation.gov.uk/uksi/2013/376/regulation/54A)).
    All links checked 29 October 2026. A claim that fails carries on only the
    excess over the relevant threshold, if failed months count as claims
    (`claim_each_month`); otherwise the surplus is left as it was.

    The limited capability for work finding holds in the first award. After
    the end it is kept only if it carries over to a new award
    (`lcw_carries_over`), and once lost it stays lost for the rest of the new
    award, as the design reads it.
    """
    if len(earnings) != len(starts):
        raise ValueError("one start date is needed for each period's earnings")
    live, surplus, months, lcw_in_force = True, 0, 0, lcw
    trace = []
    for earned, start in zip(earnings, starts):
        claim = (not live) and claim_after_end and 1 <= months <= MAX_CLAIMS_AFTER_END
        if not live:  # after the end, the finding is kept only if it carries over
            lcw_in_force = lcw_in_force and lcw_carries_over
        lcw_used = lcw_in_force
        used = earned + surplus if claim else earned
        paid = award(used, aged_25, lcw_used, housing) if (live or claim) else 0
        entitled = paid >= 1
        threshold = relevant_threshold(start, aged_25, lcw_used, housing)
        if entitled:
            next_surplus, next_months = 0, 0
        elif live:  # this period ends a live award
            next_surplus, next_months = max(0, earned - threshold), 1
        else:
            next_months = months + 1
            if claim and claim_each_month:
                next_surplus = max(0, used - threshold)
            else:
                next_surplus = surplus
        trace.append(PeriodTrace(used, paid, entitled, next_surplus))
        live, surplus, months = entitled, next_surplus, next_months
    return trace


def even_split(total: int, periods: int) -> list[int]:
    """Split a total as evenly as possible to the penny, the remainder going to the earliest periods."""
    base, extra = divmod(total, periods)
    return [base + 1 if i < extra else base for i in range(periods)]


# The copy that a figure subtracts, which drops the last-period rule where no
# claim is made after the end (the loss then runs on past the window). Only the
# loss, the spread and the larger extra payday figure drop it. The gain and the
# smaller extra payday figure keep it on both copies in every case.
_SUBTRACTED = {
    "gain": None,
    "loss": "split",
    "spread": "b",
    "extra_payday_max": "payday",
    "extra_payday_min": None,
}
_COPIES = {
    "gain": ("split", "even"),
    "loss": ("even", "split"),
    "spread": ("a", "b"),
    "extra_payday_max": ("even", "payday"),
    "extra_payday_min": ("even", "payday"),
}


def figure_value(
    figure: str,
    copies: dict[str, list[int]],
    starts: list[date],
    aged_25: bool,
    lcw: bool,
    housing: int,
    case: dict[str, bool],
) -> int | None:
    """A figure's value, in pence, for the given copies' earnings.

    The value is the total award of the first copy named for the figure less
    that of the second: gain is split less even, loss is even less split,
    spread is a less b, and both extra payday figures are even less payday.
    Every copy's last period must have an award of at least 1p, except that
    where `case["claim_after_end"]` is false the subtracted copy of the loss
    (split), the spread (b) and the larger extra payday figure (payday) need
    not. Returns None where a copy that must keep the rule breaks it.
    """
    added, subtracted = _COPIES[figure]
    totals = {}
    for name in (added, subtracted):
        trace = window(
            copies[name],
            starts,
            aged_25,
            lcw,
            housing,
            case["claim_after_end"],
            case["claim_each_month"],
            case["lcw_carries_over"],
        )
        exempt = (not case["claim_after_end"]) and name == _SUBTRACTED[figure]
        if not exempt and not trace[-1].entitled:
            return None
        totals[name] = sum(p.award for p in trace)
    return totals[added] - totals[subtracted]


def _splits(total: int, step: int, periods: int):
    """Every split of `total` into `periods` multiples of `step`."""
    units = total // step
    for head in product(range(units + 1), repeat=periods - 1):
        rest = units - sum(head)
        if rest >= 0:
            yield [h * step for h in head] + [rest * step]


def brute_force(
    figure: str,
    total: int,
    step: int,
    starts: list[date],
    aged_25: bool,
    lcw: bool,
    housing: int,
    case: dict[str, bool],
) -> int:
    """The best `figure_value` over a grid of earnings, in pence.

    Split figures range over every split of `total` into multiples of `step`
    (for spread, over every pair of splits), with the even copy exact. Extra
    payday figures range over P in multiples of `step` with 4P <= `total`,
    comparing the even split of 4P with the pattern (P, 2P, P). The least
    value is returned for `extra_payday_min` and the greatest for the others.
    Raises ValueError if the total is not a multiple of the step, or if no
    point on the grid is allowed.
    """
    if figure not in _COPIES:
        raise ValueError(f"unknown figure {figure!r}")
    if total % step:
        raise ValueError("the total must be a multiple of the step")
    periods = len(starts)

    def value(copies):
        return figure_value(figure, copies, starts, aged_25, lcw, housing, case)

    if figure.startswith("extra_payday"):
        candidates = (
            value({"even": even_split(4 * p, periods), "payday": [p, 2 * p, p]})
            for p in range(0, total // 4 + 1, step)
            if 4 * p <= total
        )
    elif figure == "spread":
        candidates = (
            value({"a": a, "b": b})
            for a in _splits(total, step, periods)
            for b in _splits(total, step, periods)
        )
    else:
        even = even_split(total, periods)
        candidates = (value({"even": even, "split": s}) for s in _splits(total, step, periods))
    found = [v for v in candidates if v is not None]
    if not found:
        raise ValueError("no point on the grid satisfies the last-period rule")
    return min(found) if figure == "extra_payday_min" else max(found)
