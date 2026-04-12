"""Tones — Eridian tone cache and playback for Rocky-style personalities.

Extracts *🎵 description 🎵* markers from responses, generates music via
MiniMax, caches locally, and plays in the background alongside TTS.
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import threading
from pathlib import Path

import requests

from .. import config as cfg
from .. import cost as cost_tracker

API_URL = "https://api.minimax.io/v1/music_generation"
PLAY_DURATION = 8  # seconds of tone to play


def _tones_dir() -> Path:
    d = Path.home() / f".{cfg.get_name()}" / "tones"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("rocky.tones")
    if not logger.handlers:
        log_path = Path.home() / f".{cfg.get_name()}" / "tones.log"
        handler = logging.FileHandler(str(log_path))
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False  # don't bleed into root logger or other libs
    return logger


def _log(msg: str) -> None:
    _get_logger().info(msg)


def _cache_path(description: str) -> Path:
    key = hashlib.md5(description.lower().strip().encode()).hexdigest()[:12]
    return _tones_dir() / f"{key}.mp3"


def extract(text: str) -> list[str]:
    """Return all 🎵 tone descriptions found in the response text."""
    return re.findall(r'\*🎵\s*(.+?)\s*🎵\*', text)


def _generate(description: str) -> Path | None:
    """Generate a tone clip for the description and save to cache."""
    api_key = cfg.get_minimax_key()
    if not api_key:
        return None

    prompt = (
        f"alien harmonic tones, {description}, "
        "ethereal atmospheric science fiction, Eridian alien communication, "
        "mathematical chord-based harmonics, non-vocal, no lyrics, "
        "otherworldly resonance, short ambient texture"
    )

    payload = {
        "model": "music-2.6",
        "prompt": prompt[:2000],
        "is_instrumental": True,
        "output_format": "hex",
        "audio_setting": {
            "sample_rate": 44100,
            "bitrate": 128000,
            "format": "mp3",
        },
    }

    for attempt in range(2):
        try:
            resp = requests.post(
                API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=240,
            )
            resp.raise_for_status()
            result = resp.json()
            break
        except requests.RequestException as e:
            if attempt == 1:
                _log(f"FAILED generation for '{description}': {e}")
                return None
            _log(f"Timeout for '{description}', retrying…")
    else:
        return None

    if result.get("base_resp", {}).get("status_code") != 0:
        msg = result.get("base_resp", {}).get("status_msg", "unknown")
        _log(f"API error for '{description}': {msg}")
        return None

    hex_audio = result.get("data", {}).get("audio", "")
    if not hex_audio:
        return None

    path = _cache_path(description)
    path.write_bytes(bytes.fromhex(hex_audio))
    cost_tracker.session.record_music("music-2.6")
    _log(f"CACHED '{description}' → {path.name}")
    return path


def _play_file(path: Path) -> None:
    """Play a tone file for PLAY_DURATION seconds in the background."""
    for player in (
        ["mpv", "--no-video", "--really-quiet", f"--length={PLAY_DURATION}", str(path)],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-t", str(PLAY_DURATION), str(path)],
    ):
        try:
            subprocess.Popen(player)
            return
        except FileNotFoundError:
            continue


def _play_tone(description: str) -> None:
    """Play if cached. If not cached, generate and save for next time. Runs in a thread."""
    path = _cache_path(description)
    if path.exists():
        _play_file(path)
    else:
        _generate(description)  # cache silently — will play next time


def play_all(descriptions: list[str]) -> None:
    """Play tones sequentially in a single background thread.

    Cached tones play for PLAY_DURATION seconds each, one after the other.
    Uncached tones generate silently for next time.
    """
    import time

    def _sequence():
        for desc in descriptions:
            path = _cache_path(desc)
            if path.exists():
                _play_file(path)
                time.sleep(PLAY_DURATION + 0.5)
            else:
                _generate(desc)

    threading.Thread(target=_sequence, daemon=True).start()
