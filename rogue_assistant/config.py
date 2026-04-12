"""Config layer — reads/writes ~/.{name}/config.json.

The assistant name is chosen during first-run setup. A pointer file at
~/.config/rogue-assistant/assistant_name records it so the base command
(rogue-assistant) can locate the config even after setup is complete.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Fixed pointer — survives renames, tells us where the real config lives
POINTER_DIR = Path.home() / ".config" / "rogue-assistant"
POINTER_FILE = POINTER_DIR / "assistant_name"

DEFAULTS = {
    "name": "assistant",
    "personality": "You are a helpful AI assistant.",
    "anthropic_api_key": "",
    "google_api_key": "",
    "google_project_id": "",
    "google_location": "us-central1",
    "minimax_api_key": "",
    "minimax_model": "MiniMax-M2.7",
    "tts_voice": "English_radiant_girl",
    "default_model": "claude-sonnet-4-6",
    "design_model": "claude-sonnet-4-6",
    "paper_enabled": False,
    "paper_mcp_url": "http://127.0.0.1:29979/mcp",
    "images_dir": "",  # filled in at setup time using chosen name
    "design_output_dir": "",  # filled in at setup time using chosen name
}


def get_name() -> str:
    """Return the configured assistant name, or 'assistant' if not yet set up."""
    if POINTER_FILE.exists():
        name = POINTER_FILE.read_text().strip()
        if name:
            return name
    return "assistant"


def get_config_dir() -> Path:
    return Path.home() / f".{get_name()}"


def get_config_file() -> Path:
    return get_config_dir() / "config.json"


# These are re-evaluated each call so they always reflect the current name
@property
def CONFIG_DIR() -> Path:  # type: ignore[misc]
    return get_config_dir()


# Module-level convenience aliases (evaluated at import time for the current name)
CONFIG_DIR: Path = get_config_dir()
CONFIG_FILE: Path = get_config_file()


def load() -> dict:
    cfg_file = get_config_file()
    if cfg_file.exists():
        with open(cfg_file) as f:
            data = json.load(f)
        for k, v in DEFAULTS.items():
            data.setdefault(k, v)
        return data
    return dict(DEFAULTS)


def save(cfg: dict) -> None:
    name = cfg.get("name", get_name())
    cfg_dir = Path.home() / f".{name}"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = cfg_dir / "config.json"
    with open(cfg_file, "w") as f:
        json.dump(cfg, f, indent=2)

    # Write pointer so rogue-assistant can always find this config
    POINTER_DIR.mkdir(parents=True, exist_ok=True)
    POINTER_FILE.write_text(name)

    # Refresh module-level aliases
    global CONFIG_DIR, CONFIG_FILE
    CONFIG_DIR = cfg_dir
    CONFIG_FILE = cfg_file


def exists() -> bool:
    cfg_file = get_config_file()
    return cfg_file.exists() and bool(load().get("anthropic_api_key"))


def ensure_dirs() -> None:
    get_config_dir().mkdir(parents=True, exist_ok=True)


def get_anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        key = load().get("anthropic_api_key", "")
    return key


def get_google_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        key = load().get("google_api_key", "")
    return key


def get_minimax_key() -> str:
    key = os.environ.get("MINIMAX_API_KEY", "")
    if not key:
        key = load().get("minimax_api_key", "")
    return key
