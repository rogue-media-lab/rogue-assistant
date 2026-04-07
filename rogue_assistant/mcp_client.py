"""HTTP MCP client — communicates with local MCP servers via JSON-RPC over HTTP."""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any


class MCPClient:
    """Minimal synchronous HTTP MCP client."""

    _SLOW_TOOLS = {"write_html", "update_styles"}

    def __init__(self, url: str = "http://127.0.0.1:29979/mcp"):
        self.url = url
        self.session_id: str | None = None
        self._req_id = 0
        self._initialized = False

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _post(self, payload: dict) -> dict | None:
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        method = payload.get("params", {}).get("name", "")
        timeout = 120 if method in self._SLOW_TOOLS else 30
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid

                if resp.status == 204:
                    return None

                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read().decode()

                if "text/event-stream" in content_type:
                    return self._parse_sse(raw)
                else:
                    return json.loads(raw) if raw.strip() else None

        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot reach Paper MCP at {self.url}. Is Paper running?\n  {e}"
            ) from e

    def _parse_sse(self, text: str) -> dict | None:
        result = None
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    result = json.loads(line[6:])
                except json.JSONDecodeError:
                    pass
        return result

    def initialize(self) -> None:
        if self._initialized:
            return
        self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"roots": {"listChanged": False}},
                "clientInfo": {"name": "rogue-assistant", "version": "0.1.0"},
            },
        })
        self._post({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        self._initialized = True

    def list_tools(self) -> list[dict]:
        self.initialize()
        result = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        })
        if result and "result" in result:
            return result["result"].get("tools", [])
        return []

    def call_tool(self, name: str, arguments: dict) -> Any:
        result = self._post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        if result and "result" in result:
            return result["result"]
        if result and "error" in result:
            return {"error": result["error"]}
        return {}

    def is_available(self) -> bool:
        try:
            self.initialize()
            return True
        except (ConnectionError, Exception):
            return False

    @staticmethod
    def to_anthropic_tools(mcp_tools: list[dict]) -> list[dict]:
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
            }
            for t in mcp_tools
        ]
