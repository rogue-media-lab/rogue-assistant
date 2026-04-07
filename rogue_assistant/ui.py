"""Rich console helpers — panels, spinners, prompts."""

from __future__ import annotations

from contextlib import contextmanager

from rich.console import Console
from rich.theme import Theme

THEME = Theme({
    "agent": "bold cyan",
    "user":  "bold white",
    "dim":   "dim white",
    "ok":    "bold green",
    "warn":  "bold yellow",
    "err":   "bold red",
    "model": "dim cyan",
})

console = Console(theme=THEME)


def print_error(msg: str) -> None:
    console.print(f"[err]error:[/err] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")


def print_ok(msg: str) -> None:
    console.print(f"[ok]✓[/ok] {msg}")


def print_warn(msg: str) -> None:
    console.print(f"[warn]![/warn] {msg}")


@contextmanager
def spinner(msg: str = "thinking…"):
    with console.status(f"[dim]{msg}[/dim]", spinner="dots"):
        yield


def print_banner(name: str) -> None:
    """Print a clean, name-aware banner."""
    console.print(f"\n[bold cyan]{name.upper()}[/bold cyan]  [dim]your AI assistant — type /help for commands[/dim]\n")
