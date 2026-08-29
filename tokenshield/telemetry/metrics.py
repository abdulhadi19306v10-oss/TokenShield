"""Tokenomics and cost calculation engine for LLM token usage and savings."""

from typing import Dict, Tuple
from pydantic import BaseModel


class ModelPrice(BaseModel):
    input_per_million: float
    output_per_million: float


# ponytail: concise static pricing matrix covering standard LLM models
MODEL_PRICING: Dict[str, ModelPrice] = {
    "gpt-4o": ModelPrice(input_per_million=2.50, output_per_million=10.00),
    "gpt-4o-mini": ModelPrice(input_per_million=0.15, output_per_million=0.60),
    "gpt-4-turbo": ModelPrice(input_per_million=10.00, output_per_million=30.00),
    "gpt-4": ModelPrice(input_per_million=30.00, output_per_million=60.00),
    "gpt-3.5-turbo": ModelPrice(input_per_million=0.50, output_per_million=1.50),
    "claude-3-5-sonnet": ModelPrice(input_per_million=3.00, output_per_million=15.00),
    "claude-3-opus": ModelPrice(input_per_million=15.00, output_per_million=75.00),
    "claude-3-haiku": ModelPrice(input_per_million=0.25, output_per_million=1.25),
    "default": ModelPrice(input_per_million=2.50, output_per_million=10.00),
}


class SavingsResult(BaseModel):
    tokens_saved: int
    cost_saved_usd: float
    reduction_percentage: float
    model: str


class TokenomicsCalculator:
    """Calculates real-time tokenomics, pricing, and dollar savings from intercepted loops."""

    @staticmethod
    def get_model_pricing(model: str) -> ModelPrice:
        """Resolve model pricing with fallback to default tier."""
        # ponytail: longest-prefix match ensures specific tiers (e.g. gpt-4o-mini) match before base tiers (gpt-4o)
        model_lower = model.lower()
        for key in sorted(MODEL_PRICING.keys(), key=len, reverse=True):
            if key != "default" and key in model_lower:
                return MODEL_PRICING[key]
        return MODEL_PRICING["default"]

    @classmethod
    def calculate_cost(
        cls,
        prompt_tokens: int,
        completion_tokens: int,
        model: str = "gpt-4o-mini",
    ) -> float:
        """Calculate total USD cost for consumed prompt and completion tokens."""
        pricing = cls.get_model_pricing(model)
        input_cost = (prompt_tokens / 1_000_000.0) * pricing.input_per_million
        output_cost = (completion_tokens / 1_000_000.0) * pricing.output_per_million
        return round(input_cost + output_cost, 6)

    @classmethod
    def calculate_savings(
        cls,
        tokens_at_trip: int,
        max_context_limit: int = 4096,
        model: str = "gpt-4o-mini",
        pre_exec_tokens_saved: int = 0,
    ) -> SavingsResult:
        """Calculate net tokens and USD cost saved from early termination and pre-exec pruning."""
        stream_tokens_saved = max(0, max_context_limit - tokens_at_trip)
        total_tokens_saved = stream_tokens_saved + pre_exec_tokens_saved

        pricing = cls.get_model_pricing(model)
        # Savings are calculated primarily against avoided generation (output tokens) + avoided context
        cost_saved = (total_tokens_saved / 1_000_000.0) * pricing.output_per_million

        baseline_total = max(1, max_context_limit + pre_exec_tokens_saved)
        reduction_pct = round((total_tokens_saved / baseline_total) * 100.0, 2)

        return SavingsResult(
            tokens_saved=total_tokens_saved,
            cost_saved_usd=round(cost_saved, 6),
            reduction_percentage=min(100.0, reduction_pct),
            model=model,
        )
