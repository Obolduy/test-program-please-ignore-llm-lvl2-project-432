from decimal import Decimal

from app.core.config import settings

PER_TOKENS = Decimal(1_000_000)
CENT_FRACTION = Decimal("0.000001")


def prices_for(model: str) -> dict[str, float]:
    return settings.llm_prices.get(model, settings.llm_prices["default"])


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    prices = prices_for(model)
    total = Decimal(str(prompt_tokens)) * Decimal(str(prices["input"])) + Decimal(
        str(completion_tokens)
    ) * Decimal(str(prices["output"]))
    return (total / PER_TOKENS).quantize(CENT_FRACTION)
