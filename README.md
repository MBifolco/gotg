# GOTG - Guardians of the Groupchat

An AI SCRUM team tool that runs structured conversations between AI agents. Instead of treating AI as a tool inside your editor, GOTG treats AI agents as **team members** with roles, autonomy, and communication responsibilities.

The core idea: the conversation is the product, not the code. Code is a byproduct of good team process.

## Quick Start

```bash
# Install (requires Python 3.10+)
pip install -e .

# Start Ollama with a model
ollama pull qwen2.5-coder:7b
ollama serve

# Initialize a project
mkdir my-project && cd my-project
gotg init .

# Set up your first task
# Edit .team/iteration.json:
#   "description": "Design a CLI todo list application..."
#   "status": "in-progress"

# Run the conversation
gotg run

# Replay it later
gotg show
```

## Prerequisites

- **Python 3.10+**
- **Ollama** running locally (or any OpenAI-compatible API)
- A pulled model (default: `qwen2.5-coder:7b`)

### Installing Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Then pull a model and start the server:

```bash
ollama pull qwen2.5-coder:7b
ollama serve
```

For AMD GPUs (RX 6000/7000 series), you may need:
```bash
HSA_OVERRIDE_GFX_VERSION=10.3.0 ollama serve
```

## Commands

### `gotg init [path]`

Creates a `.team/` directory in your project (like `git init` creates `.git/`). Defaults to the current directory.

```
.team/
  model.json           # Model provider config
  iteration.json       # Current task definition
  conversation.jsonl   # The conversation log (append-only)
  agents/
    agent-1.json       # Agent config + system prompt
    agent-2.json       # Agent config + system prompt
```

### `gotg run`

Runs the agent conversation. Agents alternate turns, each message printed to the terminal and appended to the JSONL log. Stops when `max_turns` is reached.

Validates before starting:
- `.team/` directory exists
- `iteration.json` has a non-empty description
- `iteration.json` status is `"in-progress"`
- At least 2 agent configs exist

Supports **resuming** — if `conversation.jsonl` already has messages, the conversation picks up where it left off.

### `gotg show`

Replays the conversation log to the terminal with color-coded agent names.

## Configuration

All configuration lives in `.team/` and is plain JSON — edit with any text editor.

### `.team/model.json`

```json
{
  "provider": "ollama",
  "base_url": "http://localhost:11434",
  "model": "qwen2.5-coder:7b"
}
```

To use a different provider (OpenAI, etc.), change `base_url` and `model`, and add `"api_key": "sk-..."`. Any OpenAI-compatible API works.

### `.team/iteration.json`

```json
{
  "id": "iter-1",
  "description": "Design a CLI todo list application. Discuss the command interface, data storage format, and core features.",
  "status": "in-progress",
  "max_turns": 10
}
```

- `status` must be `"in-progress"` to run
- `max_turns` is the total number of messages (e.g., 10 = 5 per agent)

### `.team/agents/*.json`

```json
{
  "name": "agent-1",
  "system_prompt": "You are a software engineer..."
}
```

Agents are loaded alphabetically by filename. The first agent speaks first.

## Conversation Log Format

Messages are stored as newline-delimited JSON (JSONL):

```json
{"from":"agent-1","iteration":"iter-1","content":"I think we should store todos as JSON..."}
{"from":"agent-2","iteration":"iter-1","content":"What about collisions though?"}
```

The log is append-only. You can read it directly with `cat`, `tail -f`, `jq`, or any tool that handles JSONL.

## Development

```bash
# Set up
pyenv local 3.11.10       # or any 3.10+
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest

# Run tests
pytest -v
```

## Project Background

See [narrative.md](narrative.md) for the full design conversation and architectural decisions behind GOTG. See [docs/](docs/) for technical documentation.
