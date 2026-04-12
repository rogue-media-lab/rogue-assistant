"""CLI entry point."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.prompt import Prompt
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style as PTStyle

from . import config as cfg, cost as cost_tracker
from .ui import console, print_banner, print_info, print_error, print_ok, print_warn

SLASH_COMMANDS = [
    ("/image",   "Generate an image with Imagen 4"),
    ("/design",  "Design a UI component (uses Paper if available)"),
    ("/speak",   "Speak text aloud via MiniMax TTS"),
    ("/voice",   "Toggle auto-speak mode (reads every response aloud)"),
    ("/video",   "Generate a video from an image or prompt (MiniMax)"),
    ("/music",   "Generate a music track from a style/mood description (MiniMax)"),
    ("/review",  "Have Claude review the current plan for edge cases and gaps"),
    ("/model",   "Show or switch LLM (e.g. /model MiniMax-M2.7)"),
    ("/cost",    "Show session token usage and estimated cost"),
    ("/clear",   "Clear terminal screen and conversation history"),
    ("/reset",   "Clear conversation history (keep terminal)"),
    ("/help",    "Show all commands"),
    ("/exit",    "Exit"),
    ("/quit",    "Exit"),
]

PT_STYLE = PTStyle.from_dict({
    "completion-menu.completion":         "bg:#0d1117 #00d4ff",
    "completion-menu.completion.current": "bg:#00d4ff #000000 bold",
    "completion-menu.meta.completion":    "bg:#0d1117 #555555",
    "completion-menu.meta.completion.current": "bg:#00d4ff #333333",
    "prompt": "#00d4ff bold",
})

KNOWN_MODELS = {
    "Claude": [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-haiku-4-5-20251001",
    ],
    "Gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-3-flash-preview",
    ],
    "MiniMax": [
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
    ],
}

REVIEW_SYSTEM = """\
You are a senior technical architect reviewing a feature plan drafted with an AI assistant.
Find what's missing, what's risky, and what will cause problems later.
Be direct and specific. Structure your review as:

## Edge Cases & Error Conditions
What inputs, states, or sequences could break this?

## Technical Risks
What is being underestimated? What will be harder than it looks?

## Gaps in Requirements
What questions should be answered before writing any code?

## Verdict
One paragraph: is this plan ready to build from, or does it need more work?
"""


class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for cmd, meta in SLASH_COMMANDS:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text), display=cmd, display_meta=meta)


app = typer.Typer(
    name="rogue-assistant",
    help="A personalizable multi-LLM AI assistant.",
    add_completion=False,
    no_args_is_help=False,
)


def _provider_label(model: str) -> str:
    if model.startswith("gemini"):
        return "Gemini"
    if model.lower().startswith("minimax"):
        return "MiniMax"
    return "Claude"


def _help_text(name: str) -> str:
    return f"""\
[bold cyan]{name} — available commands[/bold cyan]

  [cyan]Tools[/cyan]
  /image <prompt>   Generate an image with Imagen 4
  /design           Design a UI component
  /review           Review the current plan for risks and gaps

  [cyan]Session[/cyan]
  /model [name]     Show active model or switch (e.g. /model gemini-2.5-flash)
  /cost             Show session token usage and estimated cost
  /clear            Clear terminal screen and conversation history
  /reset            Clear conversation history (keep terminal)
  /help  /          Show this message
  /exit  /quit      Exit

Just type normally to chat.
"""


def _repl(model: str | None = None) -> None:
    cfg.ensure_dirs()

    conf = cfg.load()
    name = conf.get("name", "assistant")

    try:
        from .agents.chat import ChatAgent
        agent = ChatAgent(model=model)
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)

    print_banner(name)
    print_info(f"Model: {agent.model}  ({_provider_label(agent.model)})")
    print_info("Type /help to see commands.\n")

    voice_mode: bool = False

    def _toolbar():
        cost = cost_tracker.session.total_cost()
        cost_str = f"${cost:.4f}" if cost_tracker.session.calls > 0 else "$0.0000"
        voice_str = " | voice:on" if voice_mode else ""
        return f" {name} | {agent.model} | {cost_str}{voice_str} "

    session = PromptSession(
        completer=SlashCompleter(),
        complete_while_typing=True,
        style=PT_STYLE,
        bottom_toolbar=_toolbar,
    )

    current_model: str | None = model

    while True:
        try:
            user_input = session.prompt(f"{name} > ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]bye.[/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            parts = user_input[1:].split(maxsplit=1)
            cmd = parts[0].lower() if parts else ""
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "":
                console.print(_help_text(name))

            elif cmd in ("exit", "quit", "q"):
                console.print("[dim]bye.[/dim]")
                break

            elif cmd == "help":
                console.print(_help_text(name))

            elif cmd == "cost":
                _show_cost()

            elif cmd == "reset":
                agent.reset()
                print_ok("Conversation history cleared.")

            elif cmd == "clear":
                os.system("clear")
                agent.reset()
                print_ok("Screen and conversation history cleared.")

            elif cmd == "model":
                if not arg or arg.lower() == "list":
                    print_info(f"Active model: [bold]{agent.model}[/bold]  ({_provider_label(agent.model)})\n")
                    console.print("[bold cyan]Available models[/bold cyan]")
                    for provider, models in KNOWN_MODELS.items():
                        console.print(f"  [dim]{provider}[/dim]")
                        for m in models:
                            marker = "  [green]✓[/green] " if m == agent.model else "    "
                            console.print(f"{marker}[cyan]{m}[/cyan]")
                    console.print("\n[dim]Use /model <name> to switch. Any valid API model name works.[/dim]")
                else:
                    try:
                        from .agents.chat import ChatAgent
                        agent = ChatAgent(model=arg)
                        current_model = arg
                        print_ok(f"Switched to [bold]{agent.model}[/bold]  ({_provider_label(agent.model)})")
                    except (ValueError, RuntimeError) as e:
                        print_error(str(e))

            elif cmd == "speak":
                if not arg:
                    arg = console.input("[dim]Text to speak:[/dim] ").strip()
                if arg:
                    from .agents.tts import speak
                    speak(arg)

            elif cmd == "voice":
                if arg:
                    from .agents.tts import set_voice
                    set_voice(arg)
                    print_ok(f"Voice set to [bold]{arg}[/bold].")
                else:
                    voice_mode = not voice_mode
                    state = "[green]on[/green]" if voice_mode else "[dim]off[/dim]"
                    print_ok(f"Voice mode {state}.")

            elif cmd == "video":
                from .agents.video import generate as gen_video
                image_path = None
                prompt = ""
                if arg:
                    p = Path(arg.split()[0]).expanduser()
                    if p.exists() and p.is_file():
                        image_path = str(p)
                        prompt = " ".join(arg.split()[1:])
                    else:
                        prompt = arg
                if not image_path and not prompt:
                    prompt = console.input("[dim]Prompt or image path:[/dim] ").strip()
                gen_video(image_path=image_path, prompt=prompt)

            elif cmd == "music":
                if not arg:
                    arg = console.input("[dim]Style/mood prompt:[/dim] ").strip()
                if arg:
                    from .agents.music import generate as gen_music
                    gen_music(prompt=arg)

            elif cmd == "review":
                _review_plan(agent.history, conf)

            elif cmd == "image":
                if not arg:
                    arg = console.input("[dim]Image prompt:[/dim] ").strip()
                if arg:
                    from .agents.image_gen import ImageAgent
                    ImageAgent().generate(arg)

            elif cmd == "design":
                brief = arg or console.input("[bold]What should I design?[/bold] ").strip()
                if brief:
                    from .agents.design import DesignAgent
                    DesignAgent().run(brief)

            else:
                print_warn(f"Unknown command: /{cmd}  — try /help")
            continue

        console.print("[dim cyan]─[/dim cyan]")
        try:
            response = agent.ask(user_input, stream=True)
            if voice_mode and response:
                from .agents.tts import speak
                speak(response)
        except Exception as e:
            print_error(str(e))
        console.print("[dim cyan]─[/dim cyan]\n")


def _review_plan(history: list[dict], conf: dict) -> None:
    if len(history) < 2:
        print_warn("Nothing to review yet — have a planning conversation first.")
        return

    convo = "\n\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}:\n{m['content']}"
        for m in history
    )
    review_prompt = f"Please review the following planning conversation:\n\n---\n{convo}\n---\n"

    console.print("\n[bold cyan]── Review ──────────────────────────────────────[/bold cyan]")
    try:
        from .agents.base import BaseAgent
        reviewer = BaseAgent(model="claude-sonnet-4-6")
        reviewer.system_prompt = REVIEW_SYSTEM
        reviewer.ask(review_prompt, stream=True)
    except Exception as e:
        print_error(f"Review failed: {e}")
        return
    console.print("[bold cyan]────────────────────────────────────────────────[/bold cyan]\n")


def _show_cost() -> None:
    s = cost_tracker.session
    if s.calls == 0 and s.images_generated == 0:
        print_info("No API calls made this session yet.")
        return
    console.print(f"\n[bold cyan]Session usage[/bold cyan]  ({s.calls} API call{'s' if s.calls != 1 else ''})")
    for model, m in s._by_model.items():
        p = cost_tracker._price(model)
        model_cost = (
            (m["input"]  / 1_000_000) * p[0]
            + (m["output"] / 1_000_000) * p[1]
            + (m["cw"]     / 1_000_000) * p[2]
            + (m["cr"]     / 1_000_000) * p[3]
        )
        console.print(
            f"  [dim]{model}[/dim]  "
            f"in:{m['input']:,} out:{m['output']:,} tokens  "
            f"[cyan]${model_cost:.4f}[/cyan]"
        )
    for model, count in s._by_image_model.items():
        img_cost = count * cost_tracker._image_price(model)
        console.print(f"  [dim]{model}[/dim]  {count} image{'s' if count != 1 else ''}  [cyan]${img_cost:.4f}[/cyan]")
    console.print(f"\n  [bold]Estimated total: ${s.total_cost():.4f}[/bold]\n")


def _create_command_link(name: str) -> bool:
    """Create a named CLI command via symlink (Mac/Linux) or .bat wrapper (Windows)."""
    exe = shutil.which("rogue-assistant")
    if not exe:
        print_warn("Could not locate rogue-assistant executable — skipping command link.")
        print_warn(f"You can create it manually: ln -s $(which rogue-assistant) ~/.local/bin/{name}")
        return False

    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        bat = local_bin / f"{name}.bat"
        bat.write_text(f"@echo off\nrogue-assistant %*\n")
        print_ok(f"Created {bat}")
        print_info(f"Make sure {local_bin} is in your PATH.")
    else:
        link = local_bin / name
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(exe, link)
        print_ok(f"Created symlink: {link} → {exe}")
        # Check if ~/.local/bin is on PATH
        if str(local_bin) not in os.environ.get("PATH", ""):
            print_warn(f"{local_bin} is not in your PATH.")
            print_info(f'Add this to your shell config:  export PATH="$HOME/.local/bin:$PATH"')

    return True


def _run_setup_wizard() -> None:
    console.print("\n[bold cyan]Welcome to rogue-assistant setup[/bold cyan]\n")
    console.print("Let's get your personal AI assistant configured.\n")

    current = cfg.load()

    # Name
    name = Prompt.ask(
        "What would you like to name your assistant?",
        default=current.get("name", "assistant"),
    ).strip().lower()
    # Sanitize: letters, digits, hyphens only
    name = "".join(c for c in name if c.isalnum() or c == "-") or "assistant"

    # Personality
    personality = Prompt.ask(
        "Describe your assistant's personality or role",
        default=current.get("personality", "You are a helpful AI assistant."),
    ).strip()

    # API keys
    anthropic_key = Prompt.ask(
        "\nAnthropic API key (required — powers Claude)",
        default=current.get("anthropic_api_key", ""),
        password=True,
    )
    google_key = Prompt.ask(
        "Google API key (optional — powers Gemini models and Imagen image generation)",
        default=current.get("google_api_key", ""),
        password=True,
    )
    minimax_key = Prompt.ask(
        "MiniMax API key (optional — powers MiniMax models, TTS, video, and music)",
        default=current.get("minimax_api_key", ""),
        password=True,
    )
    google_project = ""
    if google_key:
        google_project = Prompt.ask(
            "Google Cloud project ID (optional — required for Imagen image generation)",
            default=current.get("google_project_id", ""),
        )

    # Default model
    default_model = Prompt.ask(
        "\nDefault model",
        default=current.get("default_model", "claude-sonnet-4-6"),
    )

    # Paper
    paper_enabled = False
    paper_url = "http://127.0.0.1:29979/mcp"
    use_paper = Prompt.ask(
        "\nDo you use Paper design tool?",
        choices=["y", "n"],
        default="n",
    )
    if use_paper == "y":
        paper_enabled = True
        paper_url = Prompt.ask(
            "Paper MCP URL",
            default=current.get("paper_mcp_url", "http://127.0.0.1:29979/mcp"),
        )

    # Images directory
    default_images = str(Path.home() / "Pictures" / name)
    images_dir = Prompt.ask(
        "\nDirectory for saved images",
        default=current.get("images_dir") or default_images,
    )

    new_cfg = {
        **current,
        "name": name,
        "personality": personality,
        "anthropic_api_key": anthropic_key,
        "google_api_key": google_key,
        "minimax_api_key": minimax_key,
        "google_project_id": google_project,
        "default_model": default_model,
        "design_model": default_model,
        "paper_enabled": paper_enabled,
        "paper_mcp_url": paper_url,
        "images_dir": images_dir,
        "design_output_dir": str(Path.home() / "designs" / name),
    }
    cfg.save(new_cfg)
    cfg.ensure_dirs()

    console.print(f"\n[bold cyan]Config saved to {cfg.get_config_file()}[/bold cyan]\n")

    # Create the named command
    console.print(f"Setting up the [bold]{name}[/bold] command…")
    _create_command_link(name)

    console.print(f"\n[bold green]Setup complete![/bold green]")
    console.print(f"Run [bold cyan]{name}[/bold cyan] to start your assistant.\n")


def _check_stale_invocation() -> bool:
    """Return True if running as 'rogue-assistant' but already configured under another name."""
    configured_name = cfg.get_name()
    if configured_name == "assistant":
        return False  # not yet set up, or default

    # Only warn if the config actually exists — pointer without config means incomplete cleanup
    if not cfg.exists():
        return False

    invoked_as = Path(sys.argv[0]).stem if sys.argv else "rogue-assistant"
    base_names = {"rogue-assistant", "rogue_assistant"}
    if invoked_as in base_names and configured_name not in base_names:
        return True
    return False


# ── Commands ──────────────────────────────────────────────────────────────────

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    model: Optional[str] = typer.Option(None, "--model", "-m", help="LLM to use"),
) -> None:
    """Launch the assistant REPL (default)."""
    if ctx.invoked_subcommand is None:
        if _check_stale_invocation():
            name = cfg.get_name()
            console.print(
                f"\n[bold yellow]You've already set this up as [cyan]{name}[/cyan].[/bold yellow]"
            )
            console.print(f"Run [bold cyan]{name}[/bold cyan] instead of [dim]rogue-assistant[/dim].\n")
            console.print(f"[dim]To reconfigure, run: rogue-assistant config[/dim]\n")
            raise typer.Exit(0)

        if not cfg.exists():
            console.print("[warn]No config found.[/warn] Running setup wizard…\n")
            _run_setup_wizard()
        _repl(model=model)


@app.command()
def config() -> None:
    """Run the setup wizard (reconfigure at any time)."""
    _run_setup_wizard()


@app.command()
def image(
    prompt: str = typer.Argument(..., help="Image generation prompt"),
) -> None:
    """Generate an image with Vertex AI Imagen."""
    if not cfg.exists():
        console.print("[warn]No config found.[/warn] Running setup wizard…\n")
        _run_setup_wizard()
    from .agents.image_gen import ImageAgent
    ImageAgent().generate(prompt)


@app.command()
def voices(
    all: bool = typer.Option(False, "--all", help="Show all languages, not just English"),
    set_id: str = typer.Option(None, "--set", help="Set the active TTS voice by ID"),
) -> None:
    """List available MiniMax TTS voices."""
    from .agents.tts import list_voices, set_voice
    if set_id:
        set_voice(set_id)
        print_ok(f"Voice set to [bold]{set_id}[/bold].")
    else:
        list_voices(language_filter=None if all else "English")


@app.command()
def video(
    image: Optional[str] = typer.Argument(None, help="Path to image file (image-to-video). Omit for text-to-video."),
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Description / camera direction"),
    duration: int = typer.Option(6, "--duration", "-d", help="Duration in seconds (6 or 10)"),
    resolution: str = typer.Option("1080P", "--resolution", "-r", help="Resolution: 768P or 1080P"),
    model: str = typer.Option("MiniMax-Hailuo-2.3", "--model", "-m", help="MiniMax video model"),
) -> None:
    """Generate a video from an image (image-to-video) or a prompt (text-to-video)."""
    if not cfg.exists():
        console.print("[warn]No config found.[/warn] Running setup wizard…\n")
        _run_setup_wizard()
    from .agents.video import generate
    generate(image_path=image, prompt=prompt or "", duration=duration, resolution=resolution, model=model)


@app.command()
def music(
    prompt: str = typer.Argument(..., help="Style/mood for generation, or target style for a cover"),
    lyrics: Optional[str] = typer.Option(None, "--lyrics", "-l", help="Custom lyrics (supports [Verse]/[Chorus]/[Bridge] tags)"),
    instrumental: bool = typer.Option(False, "--instrumental", "-i", help="Generate without vocals"),
    cover: Optional[str] = typer.Option(None, "--cover", "-c", help="URL or local file path to restyle as a cover"),
    model: str = typer.Option("music-2.6", "--model", "-m", help="music-2.6 or music-cover"),
) -> None:
    """Generate a music track, or restyle an existing track as a cover."""
    if not cfg.exists():
        console.print("[warn]No config found.[/warn] Running setup wizard…\n")
        _run_setup_wizard()
    from .agents.music import generate as gen_music
    gen_music(prompt=prompt, lyrics=lyrics or "", instrumental=instrumental, cover=cover or "", model=model)


@app.command()
def design(
    brief: Optional[str] = typer.Argument(None, help="What to design"),
    reference: Optional[list[str]] = typer.Option(None, "--reference", "-r", help="Reference image path"),
) -> None:
    """Design a UI component (uses Paper if available, otherwise saves HTML file)."""
    if not cfg.exists():
        console.print("[warn]No config found.[/warn] Running setup wizard…\n")
        _run_setup_wizard()
    if not brief:
        brief = console.input("[bold]What should I design?[/bold] ").strip()
    if not brief:
        print_error("No design brief provided.")
        raise typer.Exit(1)
    from .agents.design import DesignAgent
    DesignAgent().run(brief, references=reference)
    _show_cost()
