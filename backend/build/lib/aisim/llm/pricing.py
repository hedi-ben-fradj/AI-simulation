"""Cost estimates (USD per million tokens) for real API spend.

Configured prices in ``llm.input_price_per_mtok``/``output_price_per_mtok``
override this table. Cache reads are billed at 10% and cache writes at 125% of
the input price.
"""

from __future__ import annotations

MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}


def prices_for(model: str, input_override: float | None, output_override: float | None) -> tuple[float, float]:
    default_in, default_out = MODEL_PRICES.get(model, (4.0, 20.0))
    return (input_override if input_override is not None else default_in,
            output_override if output_override is not None else default_out)


def estimate_cost(input_price: float, output_price: float, input_tokens: int, output_tokens: int,
                  cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    return (
        input_tokens * input_price
        + cache_read_tokens * input_price * 0.1
        + cache_write_tokens * input_price * 1.25
        + output_tokens * output_price
    ) / 1_000_000
