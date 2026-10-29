from datetime import date
from decimal import Decimal

import pytest

from bm import units


def test_days_round_trip():
    assert units.days(date(2026, 4, 6)) == 20549
    assert units.to_date(20549) == date(2026, 4, 6)


def test_pence_exact():
    assert units.pence("710.10") == 71010
    assert units.pence("0.5") == 50
    assert units.pence(Decimal("424.90")) == 42490
    for bad in ("500.001", "£500", "1e3", ""):
        with pytest.raises(ValueError):
            units.pence(bad)


def test_pence_refuses_a_fraction_of_a_penny_in_a_decimal():
    with pytest.raises(ValueError):
        units.pence(Decimal("0.005"))
    with pytest.raises(ValueError):
        units.pence(Decimal("Infinity"))


def test_to_pounds_and_text():
    assert units.to_pounds(42484) == Decimal("424.84")
    assert str(units.to_pounds(50)) == "0.50"
    assert units.pounds_text(123456) == "£1,234.56"
    assert units.pounds_text(-5) == "-£0.05"
