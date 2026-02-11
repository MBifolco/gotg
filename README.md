# GOTG

GOTG is an AI product and engineering department. We've taken real-world experience working with high-performing engineering teams and distilled it into a development tool built for AI-assisted software development. Instead of treating AI as a tool inside your editor, GOTG treats AI agents as team members with roles, autonomy, and communication responsibilities. This isn't multiple agents working on isolated tasks — it's AI agents and humans collaborating like real engineering teams, following a structure that ensures higher quality and safer products.

## Prerequisites

- **Python 3.11+**
- **Git** (required — `gotg init` requires a git repository)
- One of:
  - **Anthropic API key** (recommended — Claude Sonnet)
  - **OpenAI API key**
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

## End-to-End Walkthrough

This walks through the complete lifecycle of a project — from blank repo to working code. You are the **Product Manager**. AI agents discuss, design, and implement. You steer the conversation, review their work, and control every transition.

### 1. Initialize

```bash
mkdir my-project && cd my-project
git init -b main

# Need at least one commit (worktrees branch from HEAD)
echo "# my-project" > README.md
git add README.md && git commit -m "init"

gotg init .
gotg model anthropic
```

Edit `.env` with your API key:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Configure the iteration

Edit `.team/iteration.json` — set your task `description`, set `status` to `"in-progress"`, and raise `max_turns`:

```json
{
  "iterations": [
    {
      "id": "iter-1",
      "title": "CLI todo app",
      "description": "Build a CLI todo list application in Python. Support add, list, complete, and delete operations. Store todos in a JSON file.",
      "status": "in-progress",
      "phase": "refinement",
      "max_turns": 30
    }
  ],
  "current": "iter-1"
}
```

> **max_turns is per-phase** — the turn counter resets each time you `gotg advance`. 30 is a reasonable starting point for most phases.

### 3. Enable worktrees

Edit `.team/team.json` — set `worktrees.enabled` to `true`:

```json
{
  "worktrees": {
    "enabled": true
  }
}
```

This gives each agent an isolated git branch and working directory during implementation. Without worktrees, agents can still discuss and plan but can't write code in isolation.

### 4. Phase 1: Refinement

Agents discuss *what* to build — requirements, scope, edge cases, acceptance criteria. No implementation details.

```bash
gotg run                                    # Agents start discussing
gotg show                                   # Read the conversation
gotg continue -m "Also handle error cases"  # Inject your feedback, agents respond
gotg continue                               # Let them keep going
```

The coach facilitates and eventually calls `signal_phase_complete` when scope is nailed down. You'll see:
```
Coach recommends advancing. Run `gotg advance` to proceed, or `gotg continue` to keep discussing.
```

When you're satisfied:
```bash
gotg advance                                # Coach writes refinement_summary.md, moves to planning
```

### 5. Phase 2: Planning

Agents break the agreed scope into concrete tasks with dependencies and done criteria.

```bash
gotg continue                               # Agents plan tasks
# Coach signals when the task list looks complete
gotg advance                                # Coach extracts tasks.json
```

The advance produces `.team/iterations/iter-1/tasks.json` with computed dependency layers:

```json
[
  {"id": "T1", "description": "Create storage layer", "depends_on": [], "assigned_to": "", "layer": 0, ...},
  {"id": "T2", "description": "Create CLI parser", "depends_on": [], "assigned_to": "", "layer": 0, ...},
  {"id": "T3", "description": "Wire CLI to storage", "depends_on": ["T1", "T2"], "assigned_to": "", "layer": 1, ...}
]
```

**You must assign agents before continuing.** Edit `tasks.json` and fill in `assigned_to` for each task:

```json
{"id": "T1", "assigned_to": "agent-1", ...},
{"id": "T2", "assigned_to": "agent-2", ...},
{"id": "T3", "assigned_to": "agent-1", ...}
```

### 6. Phase 3: Pre-code-review

Agents propose implementation approaches — file structure, interfaces, test strategy. One task at a time, layer by layer. No actual code yet.

```bash
gotg continue                               # Agents discuss approaches
# Coach signals when all tasks have been discussed
gotg advance                                # Moves to implementation, sets current_layer=0
```

### 7. Phase 4: Implementation (layer 0)

Agents write code using file tools (`file_read`, `file_write`, `file_list`) in their own git worktrees. Each agent works on an isolated branch.

```bash
gotg continue                               # Agents write code
```

The header confirms the setup:
```
Phase: implementation (layer 0)
File tools: enabled (writable: src/**, tests/**, docs/**)
Worktrees: 2 active
```

Run `gotg continue` as many times as needed until agents finish their layer 0 tasks. The coach periodically checks progress and signals when all agents confirm completion.

When ready:
```bash
gotg advance                                # Auto-commits dirty worktrees, moves to code-review
```

You'll see output like:
```
Auto-committed agent-1/layer-0: abc1234
Auto-committed agent-2/layer-0: def5678
Phase advanced: implementation → code-review
```

### 8. Phase 5: Code-review (layer 0)

Agents review each other's diffs. The coach tracks open concerns and signals when all are resolved.

```bash
gotg continue                               # Agents review each other's code
```

When the coach signals completion:
```
Coach signals code review complete.
Next: `gotg review` to inspect diffs, `gotg merge all` to merge, then `gotg next-layer`.
```

Now you review and merge:

```bash
gotg review                                 # See all diffs for the current layer
gotg review --stat-only                     # Just file stats
gotg review agent-1/layer-0                 # Review a specific branch

gotg merge all                              # Merge all branches into main
```

> If `merge` reports "uncommitted changes on main", commit any local changes first (`git add -A && git commit -m "..."`) before merging.

### 9. Next layer

After merging, advance to the next dependency layer:

```bash
gotg next-layer
```

This command:
- Verifies all branches for the current layer are merged
- Checks for uncommitted changes in worktrees (blocks if dirty)
- Removes current-layer worktrees
- Sets phase to `implementation` with the next layer number

If there are more layers, repeat from step 7. If all layers are complete:
```
All layers complete (through layer 1). Iteration is done.
Edit .team/iteration.json to set status to 'done' when ready.
```

### 10. Done

Edit `.team/iteration.json` and set `status` to `"done"` when you're satisfied.

Your code is on `main` with a clean git history:
```
$ git log --oneline
abc1234 Merge agent-1/layer-1 into main
def5678 Implementation complete
111aaaa Merge agent-2/layer-0 into main
222bbbb Merge agent-1/layer-0 into main
333cccc init
```

## How It Works

GOTG puts you in the role of **Product Manager**. AI agents discuss and design based on your task description, guided through structured phases by an AI coach. You steer the conversation with feedback and control when to advance.

### Phases

Every iteration progresses through five phases:

1. **Refinement** — Agents discuss *what* to build. Requirements, scope, edge cases, acceptance criteria.
2. **Planning** — Agents break the agreed scope into concrete, assignable tasks with dependencies and done criteria. The coach extracts a structured `tasks.json`.
3. **Pre-code-review** — Agents propose implementation approaches for their assigned tasks. File structure, interfaces, test strategy.
4. **Implementation** — Agents write code for their assigned tasks using file tools in isolated worktrees. The coach tracks progress and signals when all agents confirm completion.
5. **Code-review** — Agents review each other's implementation diffs. The coach tracks open review concerns and signals completion when all are resolved.

The coach facilitates each phase — summarizing progress, flagging gaps, and signaling when the team is ready to advance. You control transitions with `gotg advance`.

### Layer cycle

Tasks are organized into dependency layers. Layer 0 tasks have no dependencies. Layer 1 tasks depend on layer 0, and so on.

Each layer cycles through: **implementation → code-review → merge → next-layer**

After merging a layer into main, the next layer's worktrees branch from the updated main and automatically see all previous work.

### How conversations work

- The conversation log (`conversation.jsonl`) is append-only, but **agents only see messages from the current phase** — a history boundary is written on each `gotg advance`.
- `max_turns` in `iteration.json` is **per-phase** — the turn counter resets on each advance. If you run out, increase it in `iteration.json` and `gotg continue`.
- `gotg continue --max-turns N` adds N turns from the current point (relative), regardless of the total.
- The coach speaks after every full rotation of agents. It has a `signal_phase_complete` tool to recommend advancing, and an `ask_pm` tool to pause the conversation and request your input.
- Human messages (`gotg continue -m "..."`) are injected before the next agent turn. This is also how you respond to `ask_pm` questions from the coach.
- Agents have a `pass_turn` tool — when they have nothing new to add, they pass instead of restating agreement. This keeps conversations focused and reduces noise.

## Commands

### Core

| Command | Description |
|---------|-------------|
| `gotg ui` | Launch the terminal UI (requires the `tui` extra — see [Terminal UI](#terminal-ui)) |
| `gotg init [path]` | Initialize `.team/` in a git repo (defaults to current directory) |
| `gotg run [--max-turns N] [--layer N]` | Start the agent conversation |
| `gotg continue [-m MSG] [--max-turns N] [--layer N]` | Resume with optional human input |
| `gotg show` | Replay the conversation log |
| `gotg advance` | Advance to the next phase |
| `gotg next-layer` | Advance to the next task layer (after merging) |
| `gotg model [provider] [model]` | View or change model config |

### Worktrees & Merge

| Command | Description |
|---------|-------------|
| `gotg worktrees` | List active git worktrees with dirty/clean status |
| `gotg commit-worktrees [-m MSG]` | Commit all dirty worktrees |
| `gotg review [branch] [--layer N] [--stat-only]` | Review agent diffs against main |
| `gotg merge <branch \| all> [--layer N] [--abort] [--force]` | Merge agent branches into main |

### Checkpoints

| Command | Description |
|---------|-------------|
| `gotg checkpoint [description]` | Create a manual checkpoint |
| `gotg checkpoints` | List all checkpoints |
| `gotg restore N` | Restore to checkpoint N (prompts for safety checkpoint) |

### File Approvals

| Command | Description |
|---------|-------------|
| `gotg approvals` | Show pending file write requests |
| `gotg approve <id \| all>` | Approve a pending write |
| `gotg deny <id> [-m reason]` | Deny a pending write with reason |

### Grooming (Freeform Exploration)

| Command | Description |
|---------|-------------|
| `gotg groom start "topic" [--coach] [--slug S]` | Start a new grooming conversation |
| `gotg groom continue <slug> [-m MSG] [--max-turns N]` | Resume a grooming conversation |
| `gotg groom list` | List all grooming sessions |
| `gotg groom show <slug>` | Replay a grooming conversation |

Grooming conversations are freeform explorations that live outside the iteration lifecycle. No phases, no deliverables — just agents discussing a topic. Use `--coach` to add a facilitator who keeps the conversation broad. See [Grooming](#grooming) below.

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
        refinement_summary.md  # Created on refinement → planning advance
        tasks.json             # Created on planning → pre-code-review advance
        debug.jsonl            # Diagnostic log (auto)
        approvals.json         # Approval requests (if enabled)
        checkpoints/           # Checkpoint snapshots
    grooming/                  # Freeform grooming conversations
      file-conflicts/
        grooming.json          # Session metadata (topic, coach, max_turns)
        conversation.jsonl     # Conversation log
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
    "enabled": true
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

When `worktrees.enabled` is `true`, each agent gets an isolated git worktree during implementation and code-review phases. Each worktree is a separate branch and working directory — agents write to their own copy of the codebase without stepping on each other.

Worktrees are created automatically when entering implementation or code-review phases. They require:
- At least one commit on `main`
- HEAD on `main` (not a detached HEAD or other branch)
- `file_access` configured (worktrees use file tools)

**Merge safety:**
- Dirty worktrees block `gotg merge` — run `gotg commit-worktrees` first, or use `--force` to override
- Dirty worktrees block `gotg next-layer` — commit or discard changes first
- Merges use `--no-ff` to create visible merge commits
- `merge all` stops on the first conflict so you can resolve it before continuing
- Already-merged branches are skipped

**Manual worktree commands** (for when you need direct control):

```bash
gotg worktrees                 # See worktree status (dirty/clean)
gotg commit-worktrees          # Commit all dirty worktrees
gotg commit-worktrees -m "WIP" # With a custom commit message
gotg review agent-1/layer-0    # Review a specific branch
gotg merge agent-1/layer-0     # Merge one branch
gotg merge --abort             # Abort in-progress merge
```

## Checkpoints

GOTG automatically checkpoints after every `run`, `continue`, `advance`, and `next-layer` command. You can also create manual checkpoints at any time.

Checkpoints are stored per-iteration under `.team/iterations/<id>/checkpoints/<N>/`. Each checkpoint contains a copy of all iteration files plus metadata.

```bash
gotg checkpoints
#    Phase              Turns   Trigger   Description                    Timestamp
# ----------------------------------------------------------------------------------------------------
# 1  refinement         8       auto                                     2026-02-07T20:15:33
# 2  planning           14      auto                                     2026-02-07T20:22:10
# 3  planning           14      manual    before prompt experiment       2026-02-07T20:25:00

gotg checkpoint "before prompt experiment"   # Manual snapshot
gotg restore 3                                # Roll back (prompts for safety checkpoint)
```

## Grooming

Grooming conversations are freeform explorations that live outside the iteration lifecycle. Use them to brainstorm, poke holes in ideas, or explore topics before committing to an iteration.

```bash
gotg groom start "how should we handle file conflicts?"
gotg groom list
gotg groom show file-conflicts
gotg groom continue file-conflicts -m "what about concurrent writes?"
gotg groom continue file-conflicts --max-turns 5  # 5 more turns
```

Key properties:
- **No iteration lifecycle.** No phases, no planning, no tasks. Just conversation.
- **Lives outside iterations.** `.team/grooming/<slug>/` is a sibling of `.team/iterations/`.
- **No coach by default.** Add `--coach` to `groom start` for a facilitator who keeps the conversation broad (prevents premature convergence).
- **Multiple concurrent conversations.** Explore several ideas in parallel, each in its own slug.
- **Slugs are auto-generated** from the topic. Override with `--slug my-slug`.

When an idea crystallizes, create an iteration manually and start from refinement.

## Terminal UI

GOTG includes a full terminal UI for managing iterations, running sessions, and reviewing code — all without leaving the terminal.

```bash
pip install -e ".[tui]"   # One-time setup (installs Textual)
gotg ui
```

### Home Screen

The home screen shows all iterations and grooming sessions in tabbed tables. From here you can:

- **Enter** — Open a conversation to read it
- **R** — Run a session (starts the engine immediately)
- **C** — Continue a session
- **N** — Create a new iteration or grooming session
- **E** — Edit iteration properties (description, max turns, status)
- **S** — Open settings to configure model, agents, coach, file access, and worktrees

### Chat Screen

The chat screen displays conversations with full Markdown rendering — headings, bold, lists, and syntax-highlighted code blocks. Each agent gets a distinct border color. During a live session:

- Messages stream in real time with a loading spinner between arrivals
- Smart auto-scroll keeps you at the bottom, but won't yank you back if you scroll up to read earlier messages
- **R** — Start a new run
- **C** — Continue (or type a message and press Enter to reply to the coach)
- **P** — Advance to the next phase when the coach signals phase complete
- **A** — Open the approval screen when file writes need review
- **D** — Open the diff review screen when code review is complete
- **Home/End** — Jump to top/bottom of the conversation

### Approval Screen

When agents request file writes outside writable paths (with approvals enabled), the session pauses and you can review each request:

- Select a request to see the file content with syntax highlighting
- **A** — Approve the selected request
- **Y** — Approve all pending requests
- **D** — Deny with an optional reason

### Review Screen

After code review, inspect agent diffs and merge:

- Select a branch to see its diff with syntax highlighting
- **M** — Merge the selected branch
- **Y** — Merge all branches
- **N** — Advance to the next implementation layer (after all branches are merged)
- **F** — Mark iteration as done (when all layers are complete)

### Settings Screen

Edit `team.json` without leaving the UI:

- Model configuration with provider presets (Ollama, Anthropic, OpenAI)
- Agent CRUD — add, edit, and remove agents (minimum 2)
- Coach toggle — enable/disable with a switch
- File access and worktree configuration
- **Ctrl+S** — Save changes

Press **?** from any screen to see all available keybindings.

## Conversation Log Format

Messages are stored as newline-delimited JSON (JSONL):

```json
{"from":"agent-1","iteration":"iter-1","content":"I think we should store todos as JSON..."}
{"from":"agent-2","iteration":"iter-1","content":"What about collisions though?"}
{"from":"human","iteration":"iter-1","content":"Good points. Also consider auth later."}
{"from":"coach","iteration":"iter-1","content":"Let me summarize what we've agreed on..."}
{"from":"system","iteration":"iter-1","content":"--- Phase advanced: refinement → planning ---"}
{"from":"system","iteration":"iter-1","content":"(agent-1 passes: agree with proposal)","pass_turn":true}
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
pytest -q                     # ~977 tests
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
