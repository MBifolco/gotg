# GOTG - Guardians of the Groupchat

An AI SCRUM team tool that runs structured conversations between AI agents. Instead of treating AI as a tool inside your editor, GOTG treats AI agents as **team members** with roles, autonomy, and communication responsibilities.

The core idea: the conversation is the product, not the code. Code is a byproduct of good team process.

## Quick Start

```bash
# Clone and install (requires Python 3.10+)
git clone https://github.com/biff-ai/gotg.git
cd gotg
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Initialize a project somewhere
mkdir /tmp/my-project && cd /tmp/my-project
gotg init .

# Configure your model
gotg model anthropic          # uses Claude Sonnet (recommended)
# or: gotg model ollama       # uses local Ollama

# Edit your API key into .team/.env (for Anthropic/OpenAI)
# ANTHROPIC_API_KEY=sk-ant-...

# Set up your first task — edit .team/iteration.json:
#   "description": "Design a CLI todo list application..."
#   "status": "in-progress"

# Run the conversation
gotg run

# Replay it later
gotg show
```

## Prerequisites

- **Python 3.10+** (3.11+ recommended)
- One of:
  - **Anthropic API key** (recommended — Claude Sonnet)
  - **OpenAI API key**
  - **Ollama** running locally (free, no API key needed)

## How to Collaborate

GOTG puts you in the role of **Product Manager**. Two AI agents discuss and design based on your task description, and you steer the conversation with feedback.

### 1. Set up a project

```bash
mkdir /tmp/my-project && cd /tmp/my-project
gotg init .
```

This creates a `.team/` directory (like `git init` creates `.git/`):

```
.team/
  model.json           # Model provider config
  .env                 # API keys (gitignored)
  iteration.json       # Current task definition
  conversation.jsonl   # The conversation log (append-only)
  agents/
    agent-1.json       # Agent config + system prompt
    agent-2.json       # Agent config + system prompt
```

### 2. Configure the model

```bash
gotg model anthropic                    # Claude Sonnet (recommended)
gotg model openai                       # GPT-4o
gotg model ollama                       # Local Ollama (qwen2.5-coder:7b)
gotg model anthropic claude-sonnet-4-5-20250929  # Specific model name
```

For Anthropic or OpenAI, add your API key to `.team/.env`:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

`gotg model` will show current config and whether your key is set.

### 3. Define a task

Edit `.team/iteration.json`:

```json
{
  "id": "iter-1",
  "description": "Design a CLI todo list application. Discuss the command interface, data storage format, and core features.",
  "status": "in-progress",
  "max_turns": 10
}
```

### 4. Let the agents talk

```bash
gotg run                  # Run the full conversation (default: 10 turns)
gotg run --max-turns 4    # Or just 4 turns to start
```

### 5. Jump in with feedback

Read what the agents discussed, then inject your PM perspective:

```bash
gotg continue -m "Good ideas, but we need to account for authentication later. Also use TOML for config."
```

This appends your message (as `"from": "human"`) and resumes the agent conversation. By default it runs until the iteration's `max_turns` is reached, or you can specify how many more agent turns:

```bash
gotg continue --max-turns 4 -m "Focus on the data model next."
gotg continue --max-turns 2       # No message, just let them keep going
```

Human messages don't count toward `max_turns` — only agent messages do.

### 6. Review the conversation

```bash
gotg show                 # Replay with color-coded names
```

Agent messages are color-coded (cyan/yellow), human messages show in green.

### Typical workflow

```bash
gotg run --max-turns 4                          # Agents discuss initial thoughts
gotg show                                        # Read what they said
gotg continue --max-turns 4 -m "I like the SQLite idea but skip the ORM"
gotg show                                        # See how they responded
gotg continue --max-turns 4 -m "Let's finalize the schema"
```

You're steering the design conversation, not writing code. The agents treat you as a teammate — they'll reference your input, push back if they disagree, and incorporate your direction.

## Commands

### `gotg init [path]`

Initialize a `.team/` directory. Defaults to current directory.

### `gotg run [--max-turns N]`

Run the agent conversation. Validates that `.team/` exists, iteration is `in-progress`, and at least 2 agents are configured. Supports **resuming** — if `conversation.jsonl` already has messages, picks up where it left off.

### `gotg continue [-m MESSAGE] [--max-turns N]`

Continue a conversation with optional human input. `-m` injects your message before agents resume. `--max-turns` controls how many more agent turns to run.

### `gotg show`

Replay the conversation log with color-coded agent names.

### `gotg model [provider] [model_name]`

View or change model config. Providers: `anthropic`, `openai`, `ollama`.

## Configuration

All configuration lives in `.team/` and is plain JSON — edit with any text editor.

### `.team/model.json`

```json
{
  "provider": "anthropic",
  "base_url": "https://api.anthropic.com",
  "model": "claude-sonnet-4-5-20250929",
  "api_key": "$ANTHROPIC_API_KEY"
}
```

The `api_key` field uses `$VARIABLE` syntax — the actual key is resolved from `.team/.env` first, then environment variables. Supported providers:

| Provider | base_url | Default model |
|----------|----------|---------------|
| `anthropic` | `https://api.anthropic.com` | `claude-sonnet-4-5-20250929` |
| `openai` | `https://api.openai.com` | `gpt-4o` |
| `ollama` | `http://localhost:11434` | `qwen2.5-coder:7b` |

Any OpenAI-compatible API works — just set `base_url` and `model` manually.

### `.team/.env`

API keys live here (not in model.json):

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

This file is created automatically by `gotg model` when you pick a provider that needs an API key. Keep it out of version control.

### `.team/iteration.json`

```json
{
  "id": "iter-1",
  "description": "Design a CLI todo list application...",
  "status": "in-progress",
  "max_turns": 10
}
```

- `status` must be `"in-progress"` to run
- `max_turns` counts agent messages only (human messages don't count)

### `.team/agents/*.json`

```json
{
  "name": "agent-1",
  "role": "Software Engineer",
  "system_prompt": "You are a software engineer working on a collaborative team..."
}
```

Agents are loaded alphabetically by filename. The first agent speaks first. Each agent sees their teammates' names and roles in the system prompt, but doesn't know who is human vs AI.

## Conversation Log Format

Messages are stored as newline-delimited JSON (JSONL):

```json
{"from":"agent-1","iteration":"iter-1","content":"I think we should store todos as JSON..."}
{"from":"agent-2","iteration":"iter-1","content":"What about collisions though?"}
{"from":"human","iteration":"iter-1","content":"Good points. Also consider auth later."}
```

The log is append-only. You can read it with `gotg show`, or directly with `cat`, `jq`, or any JSONL tool.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/biff-ai/gotg.git
cd gotg

# Create a virtualenv (Python 3.10+, 3.11+ recommended)
python3.11 -m venv .venv        # or: python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode — code changes take effect immediately
pip install -e .
pip install pytest

# Verify
gotg --help
pytest -v
```

The editable install (`pip install -e .`) means the `gotg` command in your venv points directly at the source files in `src/gotg/`. You can edit code and re-run `gotg` without reinstalling.

**Important**: The `gotg` command is only available inside the activated venv. Either activate it (`source .venv/bin/activate`) or use the full path (`.venv/bin/gotg`).

### Setting up a test project

```bash
# Create a scratch project (outside the gotg repo)
mkdir /tmp/my-test && cd /tmp/my-test
gotg init .

# Configure the model
gotg model anthropic
# Edit .team/.env to add your API key

# Edit .team/iteration.json with your task description, then:
gotg run --max-turns 4
gotg show
gotg continue --max-turns 2 -m "Your feedback here"
```

### Running tests

```bash
# From the gotg repo root, with venv activated
pytest -v
```

## Using Ollama (local, free)

If you don't want to use an API, you can run models locally with Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:7b
ollama serve
```

For AMD GPUs (RX 6000/7000 series), you may need:
```bash
HSA_OVERRIDE_GFX_VERSION=10.3.0 ollama serve
```

Then configure your project: `gotg model ollama`. No API key needed.

Note: Local models produce noticeably lower quality conversations than Anthropic/OpenAI. They work, but expect shorter responses and less nuanced discussion.

## Project Background

See [narrative.md](narrative.md) for the full design conversation and architectural decisions behind GOTG. See [docs/](docs/) for technical documentation.
