from datetime import date
from decimal import Decimal

import pytest

from ai_backend.bank.models import ExchangeRate
from ai_backend.fx.convert import convert

RATE = ExchangeRate(
    source_currency="USD", target_currency="COP", rate_date=date(2026, 6, 17),
    exchange_rate=Decimal("3954.982076"), buy_rate=Decimal("3915.220455"),
    sell_rate=Decimal("3994.743697"), source="Central Bank",
)


@pytest.mark.parametrize(
    ("side", "expected"),
    [("mid", "395498.21"), ("buy", "391522.05"), ("sell", "399474.37")],
)
def test_convert_sides_round_half_up_to_cents(side, expected):
    assert convert(Decimal("100"), RATE, side) == Decimal(expected)


def test_missing_side_is_an_error():
    rate = RATE.model_copy(update={"buy_rate": None})
    with pytest.raises(ValueError, match="no buy rate"):
        convert(Decimal("1"), rate, "buy")
