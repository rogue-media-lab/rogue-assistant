"""BaseAgent — shared Claude/Gemini client, message history, streaming."""

from __future__ import annotations

import anthropic

from .. import config as cfg
from .. import cost as cost_tracker
from ..ui import spinner


class BaseAgent:
    """Foundation for all agents. Supports Claude and Gemini providers."""

    name: str = "base"
    system_prompt: str = "You are a helpful AI assistant."
    model_config_key: str | None = None

    def __init__(self, model: str | None = None):
        conf = cfg.load()
        if model:
            self.model = model
        elif self.model_config_key:
            self.model = conf.get(self.model_config_key) or conf.get("default_model", "claude-sonnet-4-6")
        else:
            self.model = conf.get("default_model", "claude-sonnet-4-6")

        self.history: list[dict] = []
        self._provider = "gemini" if self.model.startswith("gemini") else "claude"

        if self._provider == "claude":
            api_key = cfg.get_anthropic_key()
            if not api_key:
                name = conf.get("name", "assistant")
                raise RuntimeError(
                    f"No Anthropic API key found. Run `{name} config` or set ANTHROPIC_API_KEY."
                )
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            self._init_gemini()

    def _init_gemini(self) -> None:
        api_key = cfg.get_google_key()
        if not api_key:
            conf = cfg.load()
            name = conf.get("name", "assistant")
            raise RuntimeError(
                f"No Google API key found. Run `{name} config` or set GOOGLE_API_KEY."
            )
        try:
            from google import genai
            from google.genai import types as gentypes
            self._gemini_client = genai.Client(api_key=api_key)
            self._gentypes = gentypes
            self._gemini_chat = None
        except ImportError:
            raise RuntimeError(
                "google-genai not installed. Run: pip install 'rogue-assistant[gemini]'"
            )

    def _get_gemini_chat(self):
        if self._gemini_chat is None:
            self._gemini_chat = self._gemini_client.chats.create(
                model=self.model,
                config=self._gentypes.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                ),
            )
        return self._gemini_chat

    def reset(self) -> None:
        self.history = []
        if self._provider == "gemini":
            self._gemini_chat = None

    def ask(self, user_input: str, stream: bool = True) -> str:
        self.history.append({"role": "user", "content": user_input})
        if stream:
            return self._stream_response()
        else:
            return self._blocking_response()

    def _stream_response(self) -> str:
        if self._provider == "gemini":
            return self._stream_gemini()

        full_text = ""
        with self.client.messages.stream(
            model=self.model,
            max_tokens=8096,
            system=self.system_prompt,
            messages=self.history,
        ) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
                full_text += text
            cost_tracker.session.record(self.model, stream.get_final_message().usage)
        print()
        self.history.append({"role": "assistant", "content": full_text})
        return full_text

    def _stream_gemini(self) -> str:
        user_input = self.history[-1]["content"]
        chat = self._get_gemini_chat()
        full_text = ""
        last_chunk = None
        for chunk in chat.send_message_stream(user_input):
            text = chunk.text or ""
            print(text, end="", flush=True)
            full_text += text
            last_chunk = chunk
        print()
        if last_chunk and hasattr(last_chunk, "usage_metadata") and last_chunk.usage_metadata:
            cost_tracker.session.record_gemini(self.model, last_chunk.usage_metadata)
        self.history.append({"role": "assistant", "content": full_text})
        return full_text

    def _blocking_response(self) -> str:
        if self._provider == "gemini":
            return self._blocking_gemini()

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8096,
            system=self.system_prompt,
            messages=self.history,
        )
        cost_tracker.session.record(self.model, response.usage)
        text = response.content[0].text
        self.history.append({"role": "assistant", "content": text})
        return text

    def _blocking_gemini(self) -> str:
        user_input = self.history[-1]["content"]
        chat = self._get_gemini_chat()
        response = chat.send_message(user_input)
        text = response.text or ""
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            cost_tracker.session.record_gemini(self.model, response.usage_metadata)
        self.history.append({"role": "assistant", "content": text})
        return text
