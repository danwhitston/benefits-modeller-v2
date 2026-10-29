"""The project's units, and the only place that converts between them.

Money is whole pence and dates are days since 1970-01-01 everywhere in Python
and SMT. Pounds appear only at the edges: TOML files, command-line arguments,
Catala JSON and report text. All conversions here are exact; none goes through
`float`.
"""

import re
from datetime import date, timedelta
from decimal import Decimal

EPOCH = date(1970, 1, 1)
_POUNDS = re.compile(r"-?[0-9]+(\.[0-9]{1,2})?")


def days(d: date) -> int:
    """Days from 1970-01-01 to `d`."""
    return (d - EPOCH).days


def to_date(n: int) -> date:
    """The date `n` days after 1970-01-01."""
    return EPOCH + timedelta(days=n)


def pence(pounds: str | Decimal) -> int:
    """Whole pence from pounds, exactly.

    A string must be digits with at most two decimal places and an optional
    leading minus sign, such as "710.10". A `Decimal` must be a whole number
    of pence. Anything else raises `ValueError`.
    """
    match pounds:
        case str() if _POUNDS.fullmatch(pounds):
            return int(Decimal(pounds) * 100)
        case Decimal() if pounds.is_finite() and (p := pounds * 100) == p.to_integral_value():
            return int(p)
    raise ValueError(f"{pounds!r} is not a whole number of pence in pounds")


def to_pounds(p: int) -> Decimal:
    """Pounds from whole pence, exactly, with two decimal places."""
    return Decimal(p).scaleb(-2).quantize(Decimal("0.01"))


def pounds_text(p: int) -> str:
    """Pence as report text: `£1,234.56`, or `-£0.05` when negative."""
    sign = "-" if p < 0 else ""
    pounds, rest = divmod(abs(p), 100)
    return f"{sign}£{pounds:,}.{rest:02d}"
