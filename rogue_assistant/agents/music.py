"""MusicAgent — Minimax music generation."""

from __future__ import annotations

import time
from pathlib import Path

import requests

from .. import config as cfg
from .. import cost as cost_tracker
from ..ui import console, print_error, print_ok

API_URL = "https://api.minimax.io/v1/music_generation"
DEFAULT_MODEL = "music-2.6"


def _output_dir() -> Path:
    d = Path.home() / "Music" / cfg.get_name()
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate(
    prompt: str,
    lyrics: str = "",
    instrumental: bool = False,
    cover: str = "",
    model: str = DEFAULT_MODEL,
) -> None:
    """Generate or cover a music track via the Minimax music generation API.

    cover: a public URL or local file path to use as the reference audio.
    """
    api_key = cfg.get_minimax_key()
    if not api_key:
        print_error("No MiniMax API key — run `wayland config` to add one.")
        return

    is_cover = bool(cover)
    if is_cover:
        model = "music-cover"

    payload: dict = {
        "model": model,
        "prompt": prompt[:300] if is_cover else prompt[:2000],
        "output_format": "hex",
        "audio_setting": {
            "sample_rate": 44100,
            "bitrate": 256000,
            "format": "mp3",
        },
    }

    if is_cover:
        cover_path = Path(cover).expanduser()
        if cover_path.exists():
            import base64
            encoded = base64.b64encode(cover_path.read_bytes()).decode()
            payload["audio_base64"] = encoded
        else:
            # Assume it's a URL
            payload["audio_url"] = cover
        if lyrics:
            payload["lyrics"] = lyrics[:3500]
        # If no lyrics, ASR extracts them automatically
    else:
        payload["is_instrumental"] = instrumental
        if lyrics:
            payload["lyrics"] = lyrics[:3500]
        else:
            payload["lyrics_optimizer"] = True

    if is_cover:
        mode = "cover"
    elif instrumental:
        mode = "instrumental"
    elif lyrics:
        mode = "custom lyrics"
    else:
        mode = "auto lyrics"

    console.print(f"[dim]Generating music ({model}, {mode})…[/dim]")

    try:
        resp = requests.post(
            API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        print_error(f"Music request failed: {e}")
        return

    if result.get("base_resp", {}).get("status_code") != 0:
        print_error(f"Music error: {result.get('base_resp', {}).get('status_msg', 'unknown')}")
        return

    hex_audio = result.get("data", {}).get("audio", "")
    if not hex_audio:
        print_error("No audio data returned.")
        return

    audio_bytes = bytes.fromhex(hex_audio)
    filename = f"wayland_{int(time.time())}.mp3"
    out_path = _output_dir() / filename

    with open(out_path, "wb") as f:
        f.write(audio_bytes)

    cost_tracker.session.record_music(model)
    print_ok(f"Track saved: {out_path}")
    console.print(f"[dim]Play with: mpv \"{out_path}\"[/dim]")

    # Auto-play
    _play(str(out_path))


def _play(path: str) -> None:
    import subprocess
    players = [
        ["mpv", "--no-video", "--really-quiet", path],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
    ]
    for cmd in players:
        try:
            subprocess.run(cmd, check=True)
            return
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError:
            return
