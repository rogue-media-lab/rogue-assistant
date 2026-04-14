"""Tones — Eridian tone cache and playback for Rocky-style personalities.

Extracts *🎵 description 🎵* markers from responses, plays from the tone
library, and optionally generates new tones via ElevenLabs.

Modes:
  off      — tones disabled
  library  — play from library only; fuzzy-match on cache miss, never generate
  generate — play from library; generate and cache new tones on miss
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import threading
from pathlib import Path

import requests

from .. import config as cfg
from .. import cost as cost_tracker

API_URL = "https://api.elevenlabs.io/v1/sound-generation"

MODE_OFF = "off"
MODE_LIBRARY = "library"
MODE_GENERATE = "generate"


def _tones_dir() -> Path:
    d = Path.home() / "Music" / cfg.get_name() / "tones"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return _tones_dir() / "tone_index.json"


def load_index() -> dict[str, str]:
    """Return the description → filename index."""
    p = _index_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _save_index(index: dict[str, str]) -> None:
    _index_path().write_text(json.dumps(index, indent=2, sort_keys=True))


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("rocky.tones")
    if not logger.handlers:
        log_path = Path.home() / f".{cfg.get_name()}" / "tones.log"
        handler = logging.FileHandler(str(log_path))
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def _log(msg: str) -> None:
    _get_logger().info(msg)


def _cache_path(description: str) -> Path:
    key = hashlib.md5(description.lower().strip().encode()).hexdigest()[:12]
    return _tones_dir() / f"{key}.mp3"


def _fuzzy_match(description: str, index: dict[str, str], threshold: float = 0.3) -> str | None:
    """Find the closest description in the index using word Jaccard similarity."""
    if not index:
        return None
    query = set(description.lower().replace(',', ' ').split())
    best_score, best_key = 0.0, None
    for key in index:
        candidate = set(key.lower().replace(',', ' ').split())
        intersection = len(query & candidate)
        union = len(query | candidate)
        score = intersection / union if union else 0.0
        if score > best_score:
            best_score, best_key = score, key
    return best_key if best_score >= threshold else None


def extract(text: str) -> list[str]:
    """Return all 🎵 tone descriptions found in the response text."""
    return re.findall(r'\*🎵\s*(.+?)\s*🎵\*', text)


def _generate(description: str) -> Path | None:
    """Generate a new tone clip and save to cache + index."""
    api_key = cfg.get_elevenlabs_key()
    if not api_key:
        return None

    text = (
        f"alien harmonic tones, {description}, "
        "ethereal atmospheric science fiction, Eridian alien communication, "
        "mathematical chord-based harmonics, non-vocal, "
        "otherworldly resonance, short ambient texture"
    )

    payload = {
        "text": text[:500],
        "duration_seconds": 5.0,
        "prompt_influence": 0.4,
    }

    for attempt in range(2):
        try:
            resp = requests.post(
                API_URL,
                json=payload,
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                timeout=60,
            )
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 1:
                _log(f"FAILED generation for '{description}': {e}")
                return None
            _log(f"Error for '{description}', retrying…")
    else:
        return None

    path = _cache_path(description)
    path.write_bytes(resp.content)
    cost_tracker.session.record_sound_effect()
    _log(f"CACHED '{description}' → {path.name}")

    # Add to index
    index = load_index()
    index[description] = path.name
    _save_index(index)

    return path


def _play_file(path: Path) -> None:
    """Play a tone file to completion (blocking)."""
    for player in (
        ["mpv", "--no-video", "--really-quiet", "--volume=40", str(path)],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", "40", str(path)],
    ):
        try:
            subprocess.run(player, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue


def _play_tone(description: str, mode: str) -> None:
    """Resolve and play a single tone according to the active mode."""
    path = _cache_path(description)

    if path.exists():
        _play_file(path)
        return

    # Cache miss — check index for exact match first
    index = load_index()
    if description in index:
        p = _tones_dir() / index[description]
        if p.exists():
            _play_file(p)
            return

    if mode == MODE_LIBRARY:
        # Fuzzy match against library — never generate
        match = _fuzzy_match(description, index)
        if match:
            p = _tones_dir() / index[match]
            if p.exists():
                _log(f"FUZZY '{description}' → '{match}'")
                _play_file(p)
                return
        # No match found — silent, will try again next time
        return

    if mode == MODE_GENERATE:
        # Try fuzzy first (instant), fall back to generation
        match = _fuzzy_match(description, index)
        if match:
            p = _tones_dir() / index[match]
            if p.exists():
                _log(f"FUZZY '{description}' → '{match}'")
                _play_file(p)
                # Generate the exact tone in background for next time
                threading.Thread(target=_generate, args=(description,), daemon=True).start()
                return
        # Nothing close — generate silently for next time
        _generate(description)


def play_all(descriptions: list[str], mode: str = MODE_GENERATE) -> None:
    """Play tones one after the other in a background thread."""
    def _sequence():
        for desc in descriptions:
            _play_tone(desc, mode)

    threading.Thread(target=_sequence, daemon=True).start()
