"""Session cost tracker — accumulates token usage across all API calls."""

from __future__ import annotations

from dataclasses import dataclass, field

# Per-image pricing (USD per image)
IMAGE_PRICING: dict[str, float] = {
    "imagen-4.0-generate-001": 0.04,
    "imagen-3.0-generate-001": 0.03,
}

_FALLBACK_IMAGE_PRICE = 0.04


def _image_price(model: str) -> float:
    for key, price in IMAGE_PRICING.items():
        if model.startswith(key):
            return price
    return _FALLBACK_IMAGE_PRICE


# Pricing per million tokens (MTok)
# Format: (input, output, cache_write, cache_read)
MODEL_PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-4-5":          (0.80,   4.00,  1.00,  0.08),
    "claude-haiku-4-5-20251001": (0.80,   4.00,  1.00,  0.08),
    "claude-sonnet-4-6":         (3.00,  15.00,  3.75,  0.30),
    "claude-opus-4-6":           (15.00, 75.00, 18.75,  1.50),
    "gemini-1.5-flash":          (0.075,  0.30,  0.0,   0.0),
    "gemini-2.0-flash":          (0.10,   0.40,  0.0,   0.0),
    "gemini-2.5-flash-lite":     (0.10,   0.40,  0.0,   0.0),
    "gemini-2.5-flash":          (0.30,   2.50,  0.0,   0.0),
    "gemini-2.5-pro":            (1.25,  10.00,  0.0,   0.0),
    "gemini-3.1-pro":            (2.00,  12.00,  0.0,   0.0),
    "gemini-3.1-flash-lite":     (0.25,   1.50,  0.0,   0.0),
    "gemini-3-flash-preview":    (0.30,   2.50,  0.0,   0.0),
}

_FALLBACK_PRICING = (3.00, 15.00, 3.75, 0.30)


def _price(model: str) -> tuple[float, float, float, float]:
    for key, pricing in MODEL_PRICING.items():
        if model.startswith(key):
            return pricing
    return _FALLBACK_PRICING


@dataclass
class SessionCost:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    calls: int = 0
    images_generated: int = 0
    _by_model: dict[str, dict] = field(default_factory=dict)
    _by_image_model: dict[str, int] = field(default_factory=dict)

    def record(self, model: str, usage) -> None:
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        cw  = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cr  = getattr(usage, "cache_read_input_tokens", 0) or 0

        self.input_tokens += inp
        self.output_tokens += out
        self.cache_write_tokens += cw
        self.cache_read_tokens += cr
        self.calls += 1

        if model not in self._by_model:
            self._by_model[model] = {"input": 0, "output": 0, "cw": 0, "cr": 0, "calls": 0}
        m = self._by_model[model]
        m["input"] += inp
        m["output"] += out
        m["cw"] += cw
        m["cr"] += cr
        m["calls"] += 1

    def record_gemini(self, model: str, usage_metadata) -> None:
        inp = getattr(usage_metadata, "prompt_token_count", 0) or 0
        out = getattr(usage_metadata, "candidates_token_count", 0) or 0

        self.input_tokens += inp
        self.output_tokens += out
        self.calls += 1

        if model not in self._by_model:
            self._by_model[model] = {"input": 0, "output": 0, "cw": 0, "cr": 0, "calls": 0}
        m = self._by_model[model]
        m["input"] += inp
        m["output"] += out
        m["calls"] += 1

    def record_image(self, model: str, count: int = 1) -> None:
        self.images_generated += count
        self._by_image_model[model] = self._by_image_model.get(model, 0) + count

    def total_cost(self) -> float:
        total = 0.0
        for model, m in self._by_model.items():
            p = _price(model)
            total += (m["input"]  / 1_000_000) * p[0]
            total += (m["output"] / 1_000_000) * p[1]
            total += (m["cw"]     / 1_000_000) * p[2]
            total += (m["cr"]     / 1_000_000) * p[3]
        for model, count in self._by_image_model.items():
            total += count * _image_price(model)
        return total

    def reset(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_write_tokens = 0
        self.cache_read_tokens = 0
        self.calls = 0
        self.images_generated = 0
        self._by_model.clear()
        self._by_image_model.clear()


# Module-level singleton shared across all agents in a session
session = SessionCost()
