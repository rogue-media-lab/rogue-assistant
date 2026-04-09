"""Memory management — persistent context loaded into sessions."""

from __future__ import annotations

import json
from pathlib import Path

from . import config as cfg
from .ui import console, spinner, print_ok, print_info, print_warn


# ── Paths ─────────────────────────────────────────────────────────────────────

def memory_dir() -> Path:
    return cfg.get_config_dir() / "memory"


def user_memory_file() -> Path:
    return memory_dir() / "user.md"


def project_dir(project: str) -> Path:
    return memory_dir() / "projects" / project


def project_exists(project: str) -> bool:
    return project_dir(project).exists() and any(project_dir(project).glob("*.md"))


def list_projects() -> list[str]:
    pd = memory_dir() / "projects"
    if not pd.exists():
        return []
    return sorted(p.name for p in pd.iterdir() if p.is_dir())


# ── User memory ───────────────────────────────────────────────────────────────

def load_user_memory() -> str:
    f = user_memory_file()
    return f.read_text().strip() if f.exists() else ""


def append_user_memory(text: str) -> None:
    f = user_memory_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    existing = f.read_text() if f.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    f.write_text(existing + f"- {text}\n")
    print_ok(f"Saved to memory.")


# ── Project docs ──────────────────────────────────────────────────────────────

def load_project_docs(project: str) -> str:
    """Load all doc files for a project into a single formatted string."""
    pd = project_dir(project)
    if not pd.exists():
        return ""

    ORDER = ["overview", "features", "mvp", "sprint", "decisions"]
    parts = []
    for name in ORDER:
        f = pd / f"{name}.md"
        if f.exists():
            content = f.read_text().strip()
            if content:
                parts.append(content)

    return "\n\n---\n\n".join(parts)


def save_project_doc(project: str, name: str, content: str) -> Path:
    pd = project_dir(project)
    pd.mkdir(parents=True, exist_ok=True)
    f = pd / f"{name}.md"
    f.write_text(content)
    return f


def get_project_path(project: str) -> str | None:
    """Read the filesystem path from overview.md (line starting with Path:)."""
    f = project_dir(project) / "overview.md"
    if not f.exists():
        return None
    for line in f.read_text().splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped.lower().startswith("path:"):
            return stripped.split(":", 1)[1].strip()
    return None


def update_sprint(project: str, content: str) -> None:
    save_project_doc(project, "sprint", content)
    print_ok(f"Sprint updated for {project}.")


# ── Project interview ─────────────────────────────────────────────────────────

INTERVIEW_QUESTIONS = [
    ("description", "Describe the project in a few sentences."),
    ("stack",       "What's the tech stack? (e.g. Rails 8, PostgreSQL, React)"),
    ("user",        "Who is the target user?"),
    ("brand",       "Describe the brand: tone, visual style, any colors or references."),
    ("features",    "What are the main features you're planning? (list them)"),
    ("mvp",         "What's the MVP — the minimum version you'd ship?"),
    ("path",        "Where is the project on your filesystem? (full path, or leave blank)"),
]

DOC_GEN_SYSTEM = """\
You generate structured project documentation from interview answers.
Return ONLY a valid JSON object with exactly these keys:
overview, features, mvp

Each value is a markdown string.

overview.md should include:
# {project} — Overview
A description paragraph, then these sections:
## Stack
## Target User
## Brand
## Path
{path value on its own line}

features.md should include:
# {project} — Features
A bullet list of features with one-line descriptions.

mvp.md should include:
# {project} — MVP
What is in scope. What is explicitly out of scope.

Be concise and well-structured. No extra commentary outside the JSON.
"""

SPRINT_TEMPLATE = """\
# {project} — Active Sprint

## In Progress
- [ ] (nothing yet)

## Up Next
- [ ] (nothing yet)

## Done
(empty)
"""

DECISIONS_TEMPLATE = """\
# {project} — Decisions Log

| Date | Decision | Reason |
|------|----------|--------|
"""


def run_interview(project: str) -> bool:
    """Run the new-project interview. Returns True on success."""
    console.print(f"\n[bold cyan]New project: {project}[/bold cyan]")
    console.print("[dim]I'll ask a few questions to set up the project docs.[/dim]\n")

    answers: dict[str, str] = {}
    for key, question in INTERVIEW_QUESTIONS:
        try:
            answer = console.input(f"[cyan]{question}[/cyan]\n> ").strip()
        except (KeyboardInterrupt, EOFError):
            print_warn("Interview cancelled.")
            return False
        answers[key] = answer

    console.print()

    # Generate overview, features, mvp via Claude
    with spinner("generating project docs…"):
        try:
            docs = _generate_docs(project, answers)
        except Exception as e:
            print_warn(f"Doc generation failed ({e}) — saving raw answers instead.")
            docs = _fallback_docs(project, answers)

    # Save all files
    pd = project_dir(project)
    pd.mkdir(parents=True, exist_ok=True)

    files_created = []
    for doc_name, content in docs.items():
        path = save_project_doc(project, doc_name, content)
        files_created.append(path)

    # Show what was created
    console.print(f"[bold green]Project docs created:[/bold green]")
    for f in files_created:
        console.print(f"  [dim]{f}[/dim]")
    console.print()

    return True


def _generate_docs(project: str, answers: dict[str, str]) -> dict[str, str]:
    """Use Claude to generate structured docs from interview answers."""
    import anthropic
    api_key = cfg.get_anthropic_key()
    if not api_key:
        raise RuntimeError("No Anthropic API key")

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""Project name: {project}

Interview answers:
- Description: {answers.get('description', '')}
- Stack: {answers.get('stack', '')}
- Target user: {answers.get('user', '')}
- Brand: {answers.get('brand', '')}
- Features: {answers.get('features', '')}
- MVP: {answers.get('mvp', '')}
- Path: {answers.get('path', '')}

Generate the three documentation files as a JSON object."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=DOC_GEN_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    from . import cost as cost_tracker
    cost_tracker.session.record("claude-sonnet-4-6", response.usage)

    text = response.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(text)
    result = {
        "overview":  data.get("overview", ""),
        "features":  data.get("features", ""),
        "mvp":       data.get("mvp", ""),
        "sprint":    SPRINT_TEMPLATE.format(project=project),
        "decisions": DECISIONS_TEMPLATE.format(project=project),
    }
    return result


def _fallback_docs(project: str, answers: dict[str, str]) -> dict[str, str]:
    """Plain text fallback if Claude is unavailable."""
    overview = f"# {project} — Overview\n\n"
    overview += f"{answers.get('description', '')}\n\n"
    overview += f"## Stack\n{answers.get('stack', '')}\n\n"
    overview += f"## Target User\n{answers.get('user', '')}\n\n"
    overview += f"## Brand\n{answers.get('brand', '')}\n\n"
    overview += f"## Path\n{answers.get('path', '')}\n"

    features = f"# {project} — Features\n\n{answers.get('features', '')}\n"
    mvp = f"# {project} — MVP\n\n{answers.get('mvp', '')}\n"

    return {
        "overview":  overview,
        "features":  features,
        "mvp":       mvp,
        "sprint":    SPRINT_TEMPLATE.format(project=project),
        "decisions": DECISIONS_TEMPLATE.format(project=project),
    }


# ── Sync ──────────────────────────────────────────────────────────────────────

SYNC_SYSTEM = """\
You are a technical architect doing a sync check between project documentation and actual code.
Compare what the docs say should exist with what you can see in the code.

Report in this format:

## In Sync
What matches between docs and code.

## Gaps — Docs ahead of code
Features or decisions documented but not yet implemented.

## Gaps — Code ahead of docs
Things in the code that aren't reflected in the docs.

## Recommendation
One or two sentences: safe to build, or update docs first?
"""


def run_sync(project: str) -> None:
    """Compare project docs to code and report gaps."""
    if not project_exists(project):
        print_warn(f"No docs found for '{project}'. Run /plan {project} first.")
        return

    docs = load_project_docs(project)
    project_path = get_project_path(project)

    code_context = ""
    if project_path and Path(project_path).exists():
        code_context = _read_project_structure(project_path)
    else:
        print_warn("No project path found in docs — syncing against docs only.")

    prompt = f"## Project docs\n\n{docs}"
    if code_context:
        prompt += f"\n\n## Code structure\n\n{code_context}"
    else:
        prompt += "\n\n(No code path available for comparison.)"

    console.print("\n[bold cyan]── Sync Check ───────────────────────────────────[/bold cyan]")
    try:
        import anthropic
        from . import cost as cost_tracker
        client = anthropic.Anthropic(api_key=cfg.get_anthropic_key())
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYNC_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        cost_tracker.session.record("claude-sonnet-4-6", response.usage)
        console.print(response.content[0].text)
    except Exception as e:
        print_warn(f"Sync failed: {e}")
    console.print("[bold cyan]────────────────────────────────────────────────[/bold cyan]\n")


def _read_project_structure(path: str, max_lines: int = 200) -> str:
    """Return a directory tree + key file snippets."""
    import subprocess
    try:
        result = subprocess.run(
            ["find", path, "-type", "f",
             "-not", "-path", "*/.*",
             "-not", "-path", "*/node_modules/*",
             "-not", "-path", "*/__pycache__/*",
             "-not", "-name", "*.log",
             ],
            capture_output=True, text=True, timeout=10
        )
        lines = sorted(result.stdout.strip().splitlines())[:max_lines]
        return "\n".join(lines)
    except Exception:
        return f"(Could not read project at {path})"
