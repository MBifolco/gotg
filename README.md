# GOTG

GOTG is an AI product and engineering department. We've taken real-world experience working with high-performing engineering teams and distilled it into a development tool built for AI-assisted software development. Instead of treating AI as a tool inside your editor, GOTG treats AI agents as team members with roles, autonomy, and communication responsibilities. This isn't multiple agents working on isolated tasks — it's AI agents and humans collaborating like real engineering teams, following a structure that ensures higher quality and safer products.

## Prerequisites

- **Python 3.11+**
- **Git** (required — `gotg init` requires a git repository)
- One of:
  - **Anthropic API key** (recommended, default — Claude Sonnet 4.6)
  - **OpenAI API key** (GPT-4.1 mini, GPT-4.1, o3, o4-mini)
  - **Ollama** running locally (free, no API key needed)

## Install

```bash
git clone https://github.com/biff-ai/gotg.git
cd gotg
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Optional: install the TUI
pip install -e ".[tui]"
```

## Quickstart

```bash
mkdir my-project && cd my-project
git init -b main && echo "# my-project" > README.md && git add . && git commit -m "init"
gotg init .
gotg model anthropic
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
gotg new "Build a CLI todo list app"
gotg run
```

Agents discuss your task through five phases: refinement, planning, pre-code-review, implementation, and code-review. The coach signals when each phase is ready to advance. You control transitions with `gotg advance`.

For the full walkthrough, see the [User Guide](docs/guide.md).

## How It Works

GOTG puts you in the role of **Product Manager**. AI agents discuss and design based on your task description, guided through structured phases by an AI coach. Tasks are organized into dependency layers. Each layer cycles through: **implementation → code-review → merge → next-layer**.

See the [User Guide](docs/guide.md#how-it-works) for phases, layers, and conversation mechanics.

## Commands

### Core

| Command | Description |
|---------|-------------|
| `gotg init [path]` | Initialize `.team/` in a git repo |
| `gotg new "description"` | Create a new iteration |
| `gotg run [--max-turns N] [--layer N]` | Start the agent conversation |
| `gotg continue [-m MSG] [--max-turns N]` | Resume with optional human input |
| `gotg show` | Replay the conversation log |
| `gotg advance` | Advance to the next phase |
| `gotg model [provider] [model]` | View or change model config |

### Worktrees & Merge

| Command | Description |
|---------|-------------|
| `gotg worktrees` | List active worktrees with status |
| `gotg commit-worktrees [-m MSG]` | Commit all dirty worktrees |
| `gotg review [branch] [--layer N] [--stat-only]` | Review agent diffs against main |
| `gotg merge <branch \| all> [--layer N] [--abort]` | Merge agent branches into main |
| `gotg next-layer` | Advance to the next task layer (after merging) |
| `gotg rework` | Send tasks back for rework after changes_requested review |

### File Approvals

| Command | Description |
|---------|-------------|
| `gotg approvals` | Show pending file write requests |
| `gotg approve <id \| all>` | Approve a pending write |
| `gotg deny <id> [-m reason]` | Deny a pending write with reason |

### Exploration

| Command | Description |
|---------|-------------|
| `gotg explore start "topic" [--coach] [--slug S]` | Start a new exploration |
| `gotg explore continue <slug> [-m MSG] [--max-turns N]` | Resume an exploration |
| `gotg explore list` | List all exploration sessions |
| `gotg explore show <slug>` | Replay an exploration conversation |
| `gotg explore summarize <slug>` | Generate summary from conversation |

See [User Guide — Exploration](docs/guide.md#exploration) for context injection, read-only file tools, and TUI usage.

## Terminal UI

```bash
gotg ui
```

Launches a Textual-based terminal interface for managing iterations, running sessions, and reviewing code. Requires `pip install gotg[tui]`.

See the [User Guide — TUI Walkthrough](docs/guide.md#tui-walkthrough) for screen descriptions and key bindings.

## Development Setup

```bash
git clone https://github.com/biff-ai/gotg.git
cd gotg
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest

gotg --help
pytest -q
```

The editable install (`pip install -e .`) means the `gotg` command points directly at source files. Edit code and re-run without reinstalling.

### Running tests

```bash
pytest -q                     # all tests
pytest tests/test_worktree.py # just worktree tests
pytest -k "merge"             # tests matching "merge"
```

## Supported Models

GOTG defaults to **Anthropic Claude Sonnet 4.6**. You can configure different providers per-team or per-agent using `gotg model` or the TUI settings screen.

| Provider | Default | Available Models |
|----------|---------|------------------|
| **Anthropic** | claude-sonnet-4-6 | claude-opus-4-6, claude-sonnet-4-5, claude-haiku-4-5, claude-opus-4-5, claude-sonnet-4, claude-opus-4, claude-3-7-sonnet, claude-3-5-haiku |
| **OpenAI** | gpt-4.1-mini | gpt-4.1, gpt-4.1-nano, gpt-5-mini, gpt-4o, gpt-4o-mini, o4-mini, o3 |
| **Ollama** | qwen2.5-coder:7b | qwen2.5-coder:14b/32b, llama3.2:8b, deepseek-coder-v2:16b, codellama:13b |

Per-agent model overrides let you mix providers — e.g. one agent on Claude, another on GPT-4.1. Configure in the TUI settings screen or directly in `.team/team.json`.

## Using Ollama (local, free)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:7b
ollama serve
```

For AMD GPUs (RX 6000/7000 series):
```bash
HSA_OVERRIDE_GFX_VERSION=10.3.0 ollama serve
```

Configure: `gotg model ollama`. No API key needed.

Note: Local models produce noticeably lower quality conversations than Anthropic/OpenAI.

## Project Background

See [narrative.md](narrative.md) for the full design conversation and architectural decisions behind GOTG. See [docs/](docs/) for the user guide and technical documentation.
