"""Currency conversion, computed in code (never by the model)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from ai_backend.bank.models import ExchangeRate

Side = Literal["mid", "buy", "sell"]
CENT = Decimal("0.01")


def convert(amount: Decimal, rate: ExchangeRate, side: Side = "mid") -> Decimal:
    """`amount` in the rate's source currency → target currency, rounded half-up to cents.

    `side` picks which published rate to use: `mid` (exchange_rate), `buy` or `sell`, exactly as
    the dataset publishes them.
    """
    value = {"mid": rate.exchange_rate, "buy": rate.buy_rate, "sell": rate.sell_rate}[side]
    if value is None:
        raise ValueError(f"no {side} rate for {rate.source_currency}->{rate.target_currency}")
    return (amount * value).quantize(CENT, rounding=ROUND_HALF_UP)
