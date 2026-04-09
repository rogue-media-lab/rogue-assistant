"""ChatAgent — general purpose chat with configurable personality and memory."""

from __future__ import annotations

from .. import config as cfg
from .base import BaseAgent


class ChatAgent(BaseAgent):
    name = "chat"
    model_config_key = "default_model"

    def __init__(
        self,
        model: str | None = None,
        user_memory: str = "",
        project_docs: str = "",
        project_name: str = "",
        mode: str = "",
    ):
        super().__init__(model=model)
        conf = cfg.load()
        assistant_name = conf.get("name", "Assistant")
        personality = conf.get("personality", "You are a helpful AI assistant.")
        self.name = assistant_name.lower()

        system = f"You are {assistant_name}. {personality}"

        if user_memory:
            system += f"\n\n## About the user\n{user_memory}"

        if project_docs and project_name:
            label = f"Project context: {project_name}"
            if mode:
                label += f" ({mode} mode)"
            system += f"\n\n## {label}\n{project_docs}"

        self.system_prompt = system
