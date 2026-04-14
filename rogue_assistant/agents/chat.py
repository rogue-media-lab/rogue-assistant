"""ChatAgent — general purpose chat with configurable personality."""

from __future__ import annotations

from .. import config as cfg
from ..weather import fetch_weather_context
from .base import BaseAgent


class ChatAgent(BaseAgent):
    name = "chat"
    model_config_key = "default_model"

    def __init__(self, model: str | None = None):
        super().__init__(model=model)
        conf = cfg.load()
        assistant_name = conf.get("name", "Assistant")
        personality = conf.get("personality", "You are a helpful AI assistant.")
        self.name = assistant_name.lower()
        self.system_prompt = f"You are {assistant_name}. {personality}"

        weather = fetch_weather_context(conf.get("weather_location", ""))
        if weather:
            self.system_prompt += f"\n\nCurrent weather: {weather}"

        from .tones import load_index
        index = load_index()
        if index:
            vocab = "\n".join(f"- {desc}" for desc in sorted(index.keys()))
            self.system_prompt += f"\n\nTone vocabulary (choose from these descriptions):\n{vocab}"
