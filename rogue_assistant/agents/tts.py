"""TTS — Minimax text-to-speech. Converts text to audio and plays it."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import requests

from .. import config as cfg
from .. import cost as cost_tracker
from ..ui import console, print_error, print_warn

API_URL = "https://api.minimax.io/v1/t2a_v2"
VOICE_LIST_URL = "https://api.minimax.io/v1/get_voice"
DEFAULT_MODEL = "speech-2.8-hd"
DEFAULT_VOICE = "English_radiant_girl"


def _active_voice() -> str:
    return cfg.load().get("tts_voice", DEFAULT_VOICE)


def _clean_for_tts(text: str) -> str:
    """Strip stage directions and embellishments that TTS should not read.

    Stage directions: *Loud, ecstatic chords!* (has comma or 3+ words) → strip entirely
    Inline emphasis:  *exactly* or *Hail Mary* (1-2 words, no comma) → keep the word
    """
    def _handle_asterisk(m: re.Match) -> str:
        content = m.group(1)
        if ',' in content or len(content.split()) >= 3:
            return ''   # stage direction — drop it
        return content  # inline emphasis — keep the word(s)

    text = re.sub(r'\*([^*\n]+)\*', _handle_asterisk, text)
    # Remove any stray 🎵 emoji
    text = text.replace('🎵', '')
    # Collapse excess blank lines left behind
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def speak(text: str, voice_id: str | None = None) -> None:
    """Convert text to speech and play it via the Minimax TTS API."""
    api_key = cfg.get_minimax_key()
    if not api_key:
        print_error("No MiniMax API key — run `wayland config` to add one.")
        return

    voice_id = voice_id or _active_voice()
    text = _clean_for_tts(text)

    if not text:
        return  # nothing left to speak after cleaning

    payload = {
        "model": DEFAULT_MODEL,
        "text": text[:10_000],
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0,
        },
        "audio_setting": {
            "format": "mp3",
            "sample_rate": 32000,
            "bitrate": 128000,
            "channel": 1,
        },
        "output_format": "hex",
    }

    try:
        resp = requests.post(
            API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        print_error(f"TTS request failed: {e}")
        return

    status = result.get("base_resp", {})
    if status.get("status_code") != 0:
        print_error(f"TTS error: {status.get('status_msg', 'unknown error')}")
        return

    hex_audio = result.get("data", {}).get("audio", "")
    if not hex_audio:
        print_error("TTS returned no audio data.")
        return

    audio_bytes = bytes.fromhex(hex_audio)

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    cost_tracker.session.record_tts(DEFAULT_MODEL, len(text))
    _play(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)


def set_voice(voice_id: str) -> None:
    """Save the chosen voice to config."""
    conf = cfg.load()
    conf["tts_voice"] = voice_id
    cfg.save(conf)


def list_voices(language_filter: str | None = "English") -> None:
    """Fetch and print system voices from the Minimax API."""
    api_key = cfg.get_minimax_key()
    if not api_key:
        print_error("No MiniMax API key — run `wayland config` to add one.")
        return

    try:
        resp = requests.post(
            VOICE_LIST_URL,
            json={"voice_type": "system"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        print_error(f"Voice list request failed: {e}")
        return

    voices = result.get("system_voice", [])
    active = _active_voice()

    if language_filter:
        voices = [v for v in voices if language_filter.lower() in v.get("voice_id", "").lower()]

    if not voices:
        print_warn("No voices found." + (f" Try wayland voices --all to see all languages." if language_filter else ""))
        return

    label = f"[bold cyan]System voices[/bold cyan]" + (f"  [dim]({language_filter})[/dim]" if language_filter else "")
    console.print(f"\n{label}\n")
    for v in voices:
        vid = v.get("voice_id", "")
        marker = "  [green]✓[/green] " if vid == active else "    "
        console.print(f"{marker}[cyan]{vid}[/cyan]")
    console.print(f"\n[dim]Use /voice <id> or `wayland voices --set <id>` to switch.[/dim]\n")


def _play(path: str) -> None:
    """Play an audio file using the first available system player."""
    players = [
        ["mpv", "--no-video", "--really-quiet", path],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
        ["paplay", path],
    ]
    for cmd in players:
        try:
            subprocess.run(cmd, check=True)
            return
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError:
            return
    print_warn("No audio player found. Install mpv:  sudo apt install mpv")
