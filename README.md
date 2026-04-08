# rogue-assistant

A personalizable, multi-LLM AI assistant CLI. Install it, name it whatever you want, and run it from your terminal.

## Features

- **Multi-LLM** — switch between Claude and Gemini models mid-session
- **Cost tracking** — real-time token usage and estimated cost per session
- **Image generation** — generate images with Google Imagen 4 (`/image`)
- **UI design** — design components with Claude (`/design`). Uses Paper design tool if installed, otherwise saves a self-contained HTML file
- **Plan review** — send your current conversation to Claude for a technical review (`/review`)
- **Fully renamed** — setup names the assistant and creates a matching terminal command

> **OpenAI support** is planned for a future release.

---

## Requirements

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/) (required)
- A [Google API key](https://aistudio.google.com/app/apikey) (optional — enables Gemini models and Imagen)
- A Google Cloud project with Vertex AI enabled (optional — required only for Imagen image generation)

---

## Installation

### Mac / Linux

```bash
git clone https://github.com/rogue-media-lab/rogue-assistant.git
cd rogue-assistant
pip install .
```

Then run the setup wizard:

```bash
rogue-assistant
```

The wizard will ask for your assistant's name, personality, and API keys. It will create a named command in `~/.local/bin/` (e.g. `aria`). After setup, use that command — not `rogue-assistant`.

**If `~/.local/bin` is not in your PATH**, add this to your `~/.bashrc` or `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then restart your terminal or run `source ~/.bashrc`.

### Windows

Windows users should install [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) and follow the Linux instructions above inside the WSL2 terminal.

---

## Getting API Keys

### Anthropic (Claude) — required

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create an account or sign in
3. Navigate to **API Keys** and create a new key
4. Copy the key — you'll paste it during setup

### Google (Gemini + Imagen) — optional

**For Gemini models:**

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with a Google account
3. Click **Create API key**
4. Copy the key — you'll paste it during setup

**For Imagen image generation** (additional setup required):

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use an existing one) and note the **Project ID**
3. Enable the **Vertex AI API** for that project
4. Make sure your Google API key has access to that project
5. Enter the Project ID during setup when prompted

---

## Usage

After setup, run your assistant by name:

```bash
aria
```

### Commands

| Command | Description |
|---|---|
| `/image <prompt>` | Generate an image with Imagen 4 |
| `/design` | Design a UI component |
| `/review` | Review the current plan for risks and gaps |
| `/model [name]` | Show or switch the active LLM |
| `/cost` | Show session token usage and estimated cost |
| `/clear` | Clear screen and conversation history |
| `/reset` | Clear conversation history only |
| `/help` | Show all commands |
| `/exit` | Exit |

Just type normally to chat.

### Switching models

```
aria > /model gemini-2.5-flash
aria > /model claude-opus-4-6
```

Any valid model ID works — not just the ones listed.

### Design command

```bash
# From inside the REPL
aria > /design a pricing page with three tiers

# Or as a standalone command
aria design "a pricing page with three tiers"

# With a reference image
aria design "match this style" --reference ./screenshot.png
```

If [Paper](https://paperhq.io) is running and configured, the design renders directly in Paper. Otherwise, a self-contained HTML file is saved to `~/designs/{name}/` and can be opened in any browser.

---

## Reconfigure

Run the setup wizard again at any time:

```bash
rogue-assistant config
```

---

## Optional dependencies

Gemini support is included by default. Imagen image generation requires an additional package:

```bash
pip install 'rogue-assistant[imagen]'
```

---

## Skills (design customization)

You can customize the design agent's behavior by creating skill files in `~/.{name}/skills/`. For example, `~/.aria/skills/design.md` will be used as the system prompt when running `/design`. If no skill file exists, a sensible default is used.
