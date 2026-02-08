# GOTG

GOTG is an AI product and engineering department. We've taken real-world experience working with high-performing engineering teams and distilled it into a development tool built for AI-assisted software development. Instead of treating AI as a tool inside your editor, GOTG treats AI agents as team members with roles, autonomy, and communication responsibilities. This isn't multiple agents working on isolated tasks — it's AI agents and humans collaborating like real engineering teams, following a structure that ensures higher quality and safer products.

## Quick Start

```bash
# Clone and install (requires Python 3.10+)
git clone https://github.com/biff-ai/gotg.git
cd gotg
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Initialize a project (must be a git repo)
mkdir /tmp/my-project && cd /tmp/my-project
git init
gotg init .

# Configure your model
gotg model anthropic          # uses Claude Sonnet (recommended)
# or: gotg model ollama       # uses local Ollama
```

Edit your API key into `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```

Edit `.team/iteration.json` — set `description` and `status`:
```json
{
  "iterations": [
    {
      "id": "iter-1",
      "title": "",
      "description": "Design a CLI todo list application...",
      "status": "in-progress",
      "phase": "grooming",
      "max_turns": 10
    }
  ],
  "current": "iter-1"
}
```

```bash
gotg run                      # Agents discuss the task
gotg show                     # Replay the conversation
gotg continue -m "Feedback"   # Inject your input and resume
gotg advance                  # Move to the next phase
```

## Prerequisites

- **Python 3.10+** (3.11+ recommended)
- **Git** (required — `gotg init` requires a git repository)
- One of:
  - **Anthropic API key** (recommended — Claude Sonnet)
  - **OpenAI API key**
  - **Ollama** running locally (free, no API key needed)

## How It Works

GOTG puts you in the role of **Product Manager**. AI agents discuss and design based on your task description, guided through structured phases by an AI coach. You steer the conversation with feedback and control when to advance.

### Phases

Every iteration progresses through three phases:

1. **Grooming** — Agents discuss *what* to build. Requirements, scope, edge cases, acceptance criteria. No code, no implementation details.
2. **Planning** — Agents break the agreed scope into concrete, assignable tasks with dependencies and done criteria. The coach extracts a structured `tasks.json`.
3. **Pre-code-review** — Agents propose implementation approaches for their assigned tasks. File structure, interfaces, test strategy. Layer by layer, one task at a time.

The coach facilitates each phase — summarizing progress, flagging gaps, and signaling when the team is ready to advance. You control transitions with `gotg advance`.

### The PM Workflow

```bash
# Phase 1: Grooming
gotg run                                    # Agents discuss requirements
gotg show                                   # Read what they said
gotg continue -m "Also handle offline mode" # Steer the scope
gotg advance                                # Coach writes groomed.md, move to planning

# Phase 2: Planning
gotg continue                               # Agents break scope into tasks
gotg advance                                # Coach writes tasks.json
# Edit tasks.json to assign agents, then:

# Phase 3: Pre-code-review
gotg continue                               # Agents propose implementations
gotg advance                                # Ready for coding
```

## Commands

### Core

| Command | Description |
|---------|-------------|
| `gotg init [path]` | Initialize `.team/` in a git repo (defaults to current directory) |
| `gotg run [--max-turns N]` | Start the agent conversation |
| `gotg continue [-m MSG] [--max-turns N]` | Resume with optional human input |
| `gotg show` | Replay the conversation log |
| `gotg advance` | Advance to the next phase |
| `gotg model [provider] [model]` | View or change model config |

### Checkpoints

| Command | Description |
|---------|-------------|
| `gotg checkpoint [description]` | Create a manual checkpoint |
| `gotg checkpoints` | List all checkpoints |
| `gotg restore N` | Restore to checkpoint N |

### File Approvals

| Command | Description |
|---------|-------------|
| `gotg approvals` | Show pending file write requests |
| `gotg approve <id \| all>` | Approve a pending write |
| `gotg deny <id> [-m reason]` | Deny a pending write with reason |

### Worktrees & Merge

| Command | Description |
|---------|-------------|
| `gotg worktrees` | List active git worktrees |
| `gotg commit-worktrees [-m MSG]` | Commit all dirty worktrees |
| `gotg review [branch] [--layer N] [--stat-only]` | Review agent diffs against main |
| `gotg merge <branch \| all> [--layer N] [--abort] [--force]` | Merge agent branches into main |

## Project Structure

After `gotg init`, your project looks like this:

```
my-project/
  .git/
  .env                         # API keys (gitignored)
  .gitignore                   # Auto-configured: .team/, .env, .worktrees/
  .team/
    team.json                  # Model, agents, coach, file access, worktree config
    iteration.json             # Iteration list with current pointer
    iterations/
      iter-1/
        conversation.jsonl     # Append-only conversation log
        groomed.md             # Created on grooming → planning advance
        tasks.json             # Created on planning → pre-code-review advance
        debug.jsonl            # Diagnostic log (auto)
        approvals.json         # Approval requests (if enabled)
        checkpoints/           # Checkpoint snapshots
  .worktrees/                  # Git worktrees (if enabled, gitignored)
    agent-1-layer-0/
    agent-2-layer-0/
  src/                         # Your project code
```

## Configuration

All configuration lives in `.team/team.json`:

```json
{
  "model": {
    "provider": "anthropic",
    "base_url": "https://api.anthropic.com",
    "model": "claude-sonnet-4-5-20250929",
    "api_key": "$ANTHROPIC_API_KEY"
  },
  "agents": [
    {"name": "agent-1", "role": "Software Engineer"},
    {"name": "agent-2", "role": "Software Engineer"}
  ],
  "coach": {
    "name": "coach",
    "role": "Agile Coach"
  },
  "file_access": {
    "writable_paths": ["src/**", "tests/**", "docs/**"],
    "protected_paths": [],
    "max_file_size_bytes": 1048576,
    "max_files_per_turn": 10,
    "enable_approvals": false
  },
  "worktrees": {
    "enabled": false
  }
}
```

### Model Config

The `api_key` field uses `$VARIABLE` syntax — resolved from `.env` first, then environment variables.

| Provider | Default Model | API Key |
|----------|---------------|---------|
| `anthropic` | `claude-sonnet-4-5-20250929` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| `ollama` | `qwen2.5-coder:7b` | none |

Any OpenAI-compatible API works — set `base_url` and `model` manually in team.json.

### File Access

When `file_access` is configured, agents get `file_read`, `file_write`, and `file_list` tools during conversations.

- **`writable_paths`** — Glob patterns for files agents can write freely (e.g. `src/**`)
- **`protected_paths`** — Glob patterns that require approval even within writable paths
- **Hard-denied paths** — `.team/`, `.git/`, `.env*` are always blocked
- **`enable_approvals`** — When `true`, writes outside `writable_paths` go to a pending queue instead of failing. Review with `gotg approvals`.

### Worktrees

When `worktrees.enabled` is `true`, each agent gets an isolated git worktree (separate branch and working directory). Agents write to their own copy of the codebase without stepping on each other.

```bash
# Enable in team.json, then:
gotg run --layer 0             # Creates worktrees, agents work in isolation

# After conversation:
gotg worktrees                 # See worktree status
gotg commit-worktrees          # Commit all dirty worktrees

# PM reviews and merges:
gotg review                    # See diffs of all branches against main
gotg review --stat-only        # Just file stats, no full diff
gotg review agent-1/layer-0    # Review a specific branch

gotg merge agent-1/layer-0     # Merge one branch into main
gotg merge all                 # Merge all unmerged branches in layer 0
gotg merge all --layer 1       # Merge all in layer 1

# If there's a conflict:
gotg merge --abort             # Abort and restore clean state
```

**Merge safety:**
- Dirty worktrees block merging — run `gotg commit-worktrees` first, or use `--force` to override
- Merges use `--no-ff` to create visible merge commits
- `merge all` stops on the first conflict so you can resolve it before continuing
- Already-merged branches are skipped with an informative message

**Layer progression:**
Layers represent dependency tiers in the task graph. Layer 0 tasks have no dependencies. Layer 1 tasks depend on layer 0. After merging layer 0, create layer 1 worktrees — they branch from main and automatically see all layer 0 work.

```bash
gotg run --layer 0             # Agents work on layer 0 tasks
gotg commit-worktrees
gotg review
gotg merge all                 # Merge layer 0 into main

gotg run --layer 1             # Agents work on layer 1 tasks (see layer 0 work)
gotg commit-worktrees
gotg review --layer 1
gotg merge all --layer 1       # Merge layer 1 into main
```

## Checkpoints

GOTG automatically checkpoints after every `run`, `continue`, and `advance` command. You can also create manual checkpoints at any time.

Checkpoints are stored per-iteration under `.team/iterations/<id>/checkpoints/<N>/`. Each checkpoint contains a copy of all iteration files plus metadata.

```bash
gotg checkpoints
#    Phase              Turns   Trigger   Description                    Timestamp
# ----------------------------------------------------------------------------------------------------
# 1  grooming           8       auto                                     2026-02-07T20:15:33
# 2  planning           14      auto                                     2026-02-07T20:22:10
# 3  planning           14      manual    before prompt experiment       2026-02-07T20:25:00

gotg checkpoint "before prompt experiment"   # Manual snapshot
gotg restore 3                                # Roll back (prompts for safety checkpoint)
```

## Conversation Log Format

Messages are stored as newline-delimited JSON (JSONL):

```json
{"from":"agent-1","iteration":"iter-1","content":"I think we should store todos as JSON..."}
{"from":"agent-2","iteration":"iter-1","content":"What about collisions though?"}
{"from":"human","iteration":"iter-1","content":"Good points. Also consider auth later."}
{"from":"coach","iteration":"iter-1","content":"Let me summarize what we've agreed on..."}
{"from":"system","iteration":"iter-1","content":"--- Phase advanced: grooming → planning ---"}
```

The log is append-only. Read with `gotg show`, or directly with `cat`, `jq`, or any JSONL tool.

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
pytest -q                     # ~508 tests
pytest tests/test_worktree.py # Just worktree tests
pytest -k "merge"             # Tests matching "merge"
```

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

See [narrative.md](narrative.md) for the full design conversation and architectural decisions behind GOTG. See [docs/](docs/) for iteration specs and technical documentation.
