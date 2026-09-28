"""Tokens → USD, from `price_per_mtok` in models.yaml. Unknown price → None, never a guess."""

from __future__ import annotations

from decimal import Decimal

from ai_backend.config import ModelSpec

MILLION = Decimal(1_000_000)


def cost_usd(
    spec: ModelSpec, tokens_in: int, tokens_out: int, tokens_cached: int = 0
) -> Decimal | None:
    price = spec.price_per_mtok
    if price is None:
        return None
    cached_rate = price.cache_read if price.cache_read is not None else price.input
    uncached = max(tokens_in - tokens_cached, 0)
    total = uncached * price.input + tokens_cached * cached_rate + tokens_out * price.output
    return (total / MILLION).quantize(Decimal("0.000001"))
