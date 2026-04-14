"""Session cost tracker — accumulates token usage across all API calls."""

from __future__ import annotations

from dataclasses import dataclass, field

# Per-image pricing (USD per image) — sourced from https://ai.google.dev/gemini-api/docs/pricing
# Imagen 4: $0.02–$0.06 depending on quality/size; using $0.04 (standard)
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


# TTS pricing (USD per million characters)
# MiniMax: sourced from https://platform.minimax.io/docs/guides/pricing-paygo
# ElevenLabs: eleven_multilingual_v2 ~$300/million chars (Creator plan)
TTS_PRICING: dict[str, float] = {
    "speech-2.8-hd":           100.0,
    "speech-2.8-turbo":         60.0,
    "speech-2.6-hd":           100.0,
    "speech-2.6-turbo":         60.0,
    "speech-02-hd":            100.0,
    "speech-02-turbo":          60.0,
    "eleven_multilingual_v2":  300.0,
    "eleven_turbo_v2_5":       150.0,
    "eleven_flash_v2_5":        50.0,
}
_FALLBACK_TTS_PRICE = 100.0


def _tts_price(model: str) -> float:
    for key, price in TTS_PRICING.items():
        if model.startswith(key):
            return price
    return _FALLBACK_TTS_PRICE


# Video pricing (USD per video) keyed by (model_key, resolution, duration)
# sourced from https://platform.minimax.io/docs/guides/pricing-paygo
VIDEO_PRICING: dict[tuple, float] = {
    ("hailuo-2.3-fast", "768p",  6):  0.19,
    ("hailuo-2.3-fast", "768p", 10):  0.32,
    ("hailuo-2.3-fast", "1080p", 6):  0.33,
    ("hailuo-2.3",      "768p",  6):  0.28,
    ("hailuo-2.3",      "768p", 10):  0.56,
    ("hailuo-2.3",      "1080p", 6):  0.49,
    ("hailuo-02",       "512p",  6):  0.10,
    ("hailuo-02",       "512p", 10):  0.15,
    ("hailuo-02",       "768p",  6):  0.28,
    ("hailuo-02",       "768p", 10):  0.56,
    ("hailuo-02",       "1080p", 6):  0.49,
}
_FALLBACK_VIDEO_PRICE = 0.49


def _video_price(model: str, resolution: str, duration: int) -> float:
    model_key = model.lower().replace("minimax-", "")
    res_key = resolution.lower()
    return VIDEO_PRICING.get((model_key, res_key, duration), _FALLBACK_VIDEO_PRICE)


# Music pricing (USD per track)
MUSIC_PRICING: dict[str, float] = {
    "music-2.6":   0.15,
    "music-cover": 0.15,
    "music-2.0":   0.03,
}
_FALLBACK_MUSIC_PRICE = 0.15

# ElevenLabs sound effects — $0.008 per generation (8 credits at starter rate)
SOUND_EFFECT_PRICE = 0.008


def _music_price(model: str) -> float:
    for key, price in MUSIC_PRICING.items():
        if model.startswith(key):
            return price
    return _FALLBACK_MUSIC_PRICE


# Pricing per million tokens (MTok) as of 2026
# Format: (input, output, cache_write, cache_read)
MODEL_PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-4-5":          (0.80,   4.00,  1.00,  0.08),
    "claude-haiku-4-5-20251001": (0.80,   4.00,  1.00,  0.08),
    "claude-sonnet-4-6":         (3.00,  15.00,  3.75,  0.30),
    "claude-opus-4-6":           (15.00, 75.00, 18.75,  1.50),
    # Gemini models — sourced from https://ai.google.dev/gemini-api/docs/pricing
    # Pro models use ≤200k token tier (most sessions won't exceed this)
    # Format: (input, output, cache_write, cache_read) — no cache tiers for Gemini
    "gemini-1.5-flash":               (0.075,  0.30,   0.0,  0.0),
    "gemini-2.0-flash":               (0.10,   0.40,   0.0,  0.0),
    "gemini-2.5-flash-lite":          (0.10,   0.40,   0.0,  0.0),
    "gemini-2.5-flash":               (0.30,   2.50,   0.0,  0.0),
    "gemini-2.5-pro":                 (1.25,  10.00,   0.0,  0.0),
    # Gemini 3 series (from official pricing page)
    "gemini-3.1-pro":                 (2.00,  12.00,   0.0,  0.0),
    "gemini-3.1-flash-lite":          (0.25,   1.50,   0.0,  0.0),
    "gemini-3-flash-preview":         (0.30,   2.50,   0.0,  0.0),  # proxy: 2.5 Flash rates
    # MiniMax models — sourced from https://platform.minimax.io/docs/guides/pricing-paygo
    # Format: (input, output, cache_write, cache_read)
    "MiniMax-M2.7":                   (0.30,   1.20, 0.375, 0.06),
    "MiniMax-M2.7-highspeed":         (0.60,   2.40, 0.375, 0.06),
    "MiniMax-M2.5":                   (0.30,   1.20, 0.375, 0.03),
    "MiniMax-M2.5-highspeed":         (0.60,   2.40, 0.375, 0.03),
}

_FALLBACK_PRICING = (3.00, 15.00, 3.75, 0.30)  # assume Sonnet if unknown


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
    _tts_chars: dict[str, int] = field(default_factory=dict)
    _video_jobs: list[tuple] = field(default_factory=list)
    _music_tracks: dict[str, int] = field(default_factory=dict)
    _sound_effects: int = 0

    def record(self, model: str, usage) -> None:
        """Record usage from an Anthropic API response.usage object."""
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

    def record_tts(self, model: str, char_count: int) -> None:
        """Record TTS usage by character count."""
        self._tts_chars[model] = self._tts_chars.get(model, 0) + char_count

    def record_video(self, model: str, resolution: str, duration: int) -> None:
        """Record a video generation job."""
        self._video_jobs.append((model, resolution, duration))

    def record_music(self, model: str) -> None:
        """Record a music generation track."""
        self._music_tracks[model] = self._music_tracks.get(model, 0) + 1

    def record_sound_effect(self) -> None:
        """Record an ElevenLabs sound effect generation."""
        self._sound_effects += 1

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
        for model, chars in self._tts_chars.items():
            total += (chars / 1_000_000) * _tts_price(model)
        for model, resolution, duration in self._video_jobs:
            total += _video_price(model, resolution, duration)
        for model, count in self._music_tracks.items():
            total += count * _music_price(model)
        total += self._sound_effects * SOUND_EFFECT_PRICE
        return total

    def record_image(self, model: str, count: int = 1) -> None:
        """Record image generation usage."""
        self.images_generated += count
        self._by_image_model[model] = self._by_image_model.get(model, 0) + count

    def record_gemini(self, model: str, usage_metadata) -> None:
        """Record usage from a Gemini API response.usage_metadata object."""
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

    def reset(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_write_tokens = 0
        self.cache_read_tokens = 0
        self.calls = 0
        self.images_generated = 0
        self._by_model.clear()
        self._by_image_model.clear()
        self._tts_chars.clear()
        self._video_jobs.clear()
        self._music_tracks.clear()
        self._sound_effects = 0


# Module-level singleton shared across all agents in a session
session = SessionCost()
