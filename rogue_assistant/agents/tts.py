"""TTS — text-to-speech via MiniMax or ElevenLabs. Converts text to audio and plays it."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import requests

from .. import config as cfg
from .. import cost as cost_tracker
from ..ui import console, print_error, print_warn

# MiniMax
MINIMAX_API_URL = "https://api.minimax.io/v1/t2a_v2"
MINIMAX_VOICE_LIST_URL = "https://api.minimax.io/v1/get_voice"
MINIMAX_DEFAULT_MODEL = "speech-2.8-hd"
MINIMAX_DEFAULT_VOICE = "English_radiant_girl"

# ElevenLabs
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
ELEVENLABS_VOICES_URL = "https://api.elevenlabs.io/v1/voices"
ELEVENLABS_DEFAULT_MODEL = "eleven_multilingual_v2"
ELEVENLABS_DEFAULT_VOICE = "zSiMZcCo0oBh047sunsX"  # Andrew - Friendly and Energetic

# Friendly name aliases for ElevenLabs voices (lowercase → voice ID)
ELEVENLABS_ALIASES: dict[str, str] = {
    "andrew": "zSiMZcCo0oBh047sunsX",
    "finn":   "vBKc2FfBKJfcZNyEt1n6",
}


def _resolve_voice(voice_id: str) -> str:
    """Resolve a friendly name alias to a voice ID if one exists."""
    return ELEVENLABS_ALIASES.get(voice_id.lower(), voice_id)


def _detect_provider(voice_id: str) -> str:
    """Infer TTS provider from voice ID format.

    MiniMax IDs use underscores (e.g. 'Wise_Scholar', 'English_radiant_girl').
    ElevenLabs IDs are alphanumeric with mixed case and no underscores.
    """
    return "minimax" if "_" in voice_id else "elevenlabs"


def _active_voice() -> str:
    return cfg.load().get("tts_voice", MINIMAX_DEFAULT_VOICE)


def _active_provider() -> str:
    voice = _active_voice()
    return _detect_provider(voice)


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
    """Convert text to speech and play it via the active TTS provider."""
    voice_id = _resolve_voice(voice_id or _active_voice())
    provider = _detect_provider(voice_id)
    text = _clean_for_tts(text)

    if not text:
        return

    if provider == "elevenlabs":
        _speak_elevenlabs(text, voice_id)
    else:
        _speak_minimax(text, voice_id)


def _speak_minimax(text: str, voice_id: str) -> None:
    """Speak via MiniMax TTS API."""
    api_key = cfg.get_minimax_key()
    if not api_key:
        print_error("No MiniMax API key — run `wayland config` to add one.")
        return

    payload = {
        "model": MINIMAX_DEFAULT_MODEL,
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
            MINIMAX_API_URL,
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

    cost_tracker.session.record_tts(MINIMAX_DEFAULT_MODEL, len(text))
    _play(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)


def _speak_elevenlabs(text: str, voice_id: str) -> None:
    """Speak via ElevenLabs TTS API."""
    api_key = cfg.get_elevenlabs_key()
    if not api_key:
        print_error("No ElevenLabs API key — run `wayland config` to add one.")
        return

    payload = {
        "text": text[:5_000],
        "model_id": ELEVENLABS_DEFAULT_MODEL,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        },
    }

    try:
        resp = requests.post(
            f"{ELEVENLABS_API_URL}/{voice_id}",
            json=payload,
            headers={
                "xi-api-key": api_key,
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        resp.raise_for_status()
        audio_bytes = resp.content
    except requests.RequestException as e:
        print_error(f"ElevenLabs TTS request failed: {e}")
        return

    if not audio_bytes:
        print_error("ElevenLabs TTS returned no audio data.")
        return

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    cost_tracker.session.record_tts(ELEVENLABS_DEFAULT_MODEL, len(text))
    _play(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)


def set_voice(voice_id: str) -> None:
    """Save the chosen voice to config."""
    resolved = _resolve_voice(voice_id)
    conf = cfg.load()
    conf["tts_voice"] = resolved
    cfg.save(conf)
    provider = _detect_provider(resolved)
    label = f"{voice_id} → {resolved}" if resolved != voice_id else resolved
    console.print(f"[dim]Voice set to [cyan]{label}[/cyan] ([cyan]{provider}[/cyan])[/dim]")


def list_voices(language_filter: str | None = "English") -> None:
    """Fetch and print voices from the active TTS provider."""
    provider = _active_provider()
    if provider == "elevenlabs":
        _list_voices_elevenlabs()
    else:
        _list_voices_minimax(language_filter)


def _list_voices_minimax(language_filter: str | None = "English") -> None:
    """Fetch and print system voices from the MiniMax API."""
    api_key = cfg.get_minimax_key()
    if not api_key:
        print_error("No MiniMax API key — run `wayland config` to add one.")
        return

    try:
        resp = requests.post(
            MINIMAX_VOICE_LIST_URL,
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

    label = f"[bold cyan]MiniMax voices[/bold cyan]" + (f"  [dim]({language_filter})[/dim]" if language_filter else "")
    console.print(f"\n{label}\n")
    for v in voices:
        vid = v.get("voice_id", "")
        marker = "  [green]✓[/green] " if vid == active else "    "
        console.print(f"{marker}[cyan]{vid}[/cyan]")
    console.print(f"\n[dim]Use /voice <id> or `wayland voices --set <id>` to switch.[/dim]\n")


def _list_voices_elevenlabs() -> None:
    """Fetch and print voices from the ElevenLabs API."""
    api_key = cfg.get_elevenlabs_key()
    if not api_key:
        print_error("No ElevenLabs API key — run `wayland config` to add one.")
        return

    try:
        resp = requests.get(
            ELEVENLABS_VOICES_URL,
            headers={"xi-api-key": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        print_error(f"ElevenLabs voice list request failed: {e}")
        return

    voices = result.get("voices", [])
    active = _active_voice()

    if not voices:
        print_warn("No ElevenLabs voices found.")
        return

    console.print(f"\n[bold cyan]ElevenLabs voices[/bold cyan]\n")
    for v in voices:
        vid = v.get("voice_id", "")
        name = v.get("name", vid)
        marker = "  [green]✓[/green] " if vid == active else "    "
        console.print(f"{marker}[cyan]{vid}[/cyan]  [dim]{name}[/dim]")
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
            subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError:
            return
    print_warn("No audio player found. Install mpv:  sudo apt install mpv")
