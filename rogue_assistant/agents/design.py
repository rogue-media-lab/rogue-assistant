"""DesignAgent — designs UI components.

If Paper is configured and reachable, renders directly into Paper via MCP.
Otherwise generates a self-contained HTML file and saves it locally.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from datetime import datetime
from pathlib import Path

from .. import config as cfg
from .. import cost as cost_tracker
from ..ui import console, spinner, print_ok, print_error, print_warn, print_info

SKILLS_DIR = cfg.get_config_dir() / "skills"
DEFAULT_SKILL = "design"

PAPER_SYSTEM = """\
You are a senior UI designer working in Paper.
Design the component the user describes. Work iteratively, screenshot often,
call finish_working_on_nodes when done. Light mode, minimalist, strong typography.
Do NOT generate application code of any kind.
"""

FILE_SYSTEM = """\
You are a senior UI designer. Generate a complete, self-contained HTML file for the component \
the user describes. Use embedded CSS — no external dependencies. \
Light mode, minimalist, clean typography. Include realistic placeholder content. \
Output ONLY the raw HTML — no markdown fences, no explanation.
"""


def _encode_image(path: Path) -> dict:
    mime, _ = mimetypes.guess_type(str(path))
    if mime not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
        mime = "image/png"
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}


def _strip_images(content: list, tool_name: str) -> list:
    cleaned = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "image":
            cleaned.append({
                "type": "text",
                "text": f"[{tool_name} image captured — not retained in history to reduce cost]",
            })
        else:
            cleaned.append(item)
    return cleaned


def _load_skill(name: str) -> str:
    # Refresh skills dir in case name changed since module load
    skills_dir = cfg.get_config_dir() / "skills"
    path = skills_dir / f"{name}.md"
    if path.exists():
        return path.read_text()
    return PAPER_SYSTEM


class DesignAgent:
    name = "designer"

    def __init__(self, skill: str = DEFAULT_SKILL):
        api_key = cfg.get_anthropic_key()
        if not api_key:
            conf = cfg.load()
            n = conf.get("name", "assistant")
            raise RuntimeError(f"No Anthropic API key found. Run `{n} config` or set ANTHROPIC_API_KEY.")
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        conf = cfg.load()
        self.model = conf.get("design_model") or conf.get("default_model", "claude-sonnet-4-6")
        self.conf = conf
        self.skill_name = skill

    def _paper_available(self) -> bool:
        if not self.conf.get("paper_enabled", False):
            return False
        from ..mcp_client import MCPClient
        mcp = MCPClient(self.conf.get("paper_mcp_url", "http://127.0.0.1:29979/mcp"))
        return mcp.is_available()

    def run(self, brief: str, references: list[str] | None = None) -> None:
        if self._paper_available():
            self._run_paper(brief, references)
        else:
            self._run_file(brief, references)

    # ── Paper mode ───────────────────────────────────────────────────────────

    def _run_paper(self, brief: str, references: list[str] | None = None) -> None:
        from ..mcp_client import MCPClient

        mcp_url = self.conf.get("paper_mcp_url", "http://127.0.0.1:29979/mcp")
        mcp = MCPClient(mcp_url)

        print_ok("Paper detected — designing in Paper.")
        system = _load_skill(self.skill_name)

        with spinner("loading Paper tools…"):
            mcp_tools = mcp.list_tools()

        if not mcp_tools:
            print_warn("No tools returned from Paper. Falling back to file output.")
            self._run_file(brief, references)
            return

        tools = MCPClient.to_anthropic_tools(mcp_tools)
        console.print(f"\n[bold cyan]Designing:[/bold cyan] {brief}\n")

        ref_paths = [Path(r) for r in (references or [])]
        ref_paths = [p for p in ref_paths if p.exists()]

        if ref_paths:
            content: list = [_encode_image(p) for p in ref_paths]
            content.append({"type": "text", "text": brief})
        else:
            content = brief

        messages = [{"role": "user", "content": content}]

        _BASELINE = {"write_html", "update_styles", "get_screenshot", "finish_working_on_nodes"}
        tools_by_name = {t["name"]: t for t in tools}
        used_tools: set[str] = set()
        first_turn = True

        while True:
            active_tools = tools if first_turn else [
                tools_by_name[n] for n in (used_tools | _BASELINE) if n in tools_by_name
            ]

            with spinner("thinking…"):
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=8096,
                    system=system,
                    tools=active_tools,
                    messages=messages,
                )

            cost_tracker.session.record(self.model, response.usage)

            for block in response.content:
                if hasattr(block, "text") and block.text:
                    console.print(f"[dim cyan]designer:[/dim cyan] {block.text}")

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        used_tools.add(block.name)
                        console.print(f"[dim]  → {block.name}[/dim]")
                        raw = mcp.call_tool(block.name, block.input)

                        if isinstance(raw, dict) and "content" in raw:
                            content_val = raw["content"]
                            if isinstance(content_val, list):
                                result_str = json.dumps(_strip_images(content_val, block.name))
                            else:
                                result_str = str(content_val)
                        else:
                            result_str = json.dumps(raw)

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                first_turn = False
            else:
                break

        print_ok("Design complete. Review in Paper.")

    # ── File mode ────────────────────────────────────────────────────────────

    def _run_file(self, brief: str, references: list[str] | None = None) -> None:
        console.print(f"\n[bold cyan]Designing:[/bold cyan] {brief}\n")
        console.print("[dim]Paper not available — generating HTML file.[/dim]\n")

        ref_paths = [Path(r) for r in (references or [])]
        ref_paths = [p for p in ref_paths if p.exists()]

        if ref_paths:
            content: list = [_encode_image(p) for p in ref_paths]
            content.append({"type": "text", "text": brief})
            messages = [{"role": "user", "content": content}]
        else:
            messages = [{"role": "user", "content": brief}]

        with spinner("designing…"):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8096,
                system=FILE_SYSTEM,
                messages=messages,
            )

        cost_tracker.session.record(self.model, response.usage)
        html = response.content[0].text.strip()

        # Strip markdown fences if the model included them anyway
        if html.startswith("```"):
            lines = html.splitlines()
            html = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        out_dir_str = self.conf.get("design_output_dir") or str(
            Path.home() / "designs" / self.conf.get("name", "assistant")
        )
        out_dir = Path(out_dir_str)
        out_dir.mkdir(parents=True, exist_ok=True)

        slug = "-".join(brief.lower().split()[:5])
        slug = "".join(c if c.isalnum() or c == "-" else "" for c in slug)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = out_dir / f"{slug}-{timestamp}.html"
        out_path.write_text(html)

        print_ok(f"Design saved: {out_path}")
        console.print("[dim]Open the file in a browser to preview.[/dim]")
