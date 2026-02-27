# GOTG User Guide

## What GOTG Does

GOTG runs structured conversations between AI agents inside your project. You give it a task, and a team of AI engineers discusses it through a series of phases — refining requirements, planning tasks, reviewing approaches, implementing code, and reviewing diffs. An AI coach facilitates the conversation, tracking progress and surfacing unresolved issues.

Between iterations, grooming sessions let the team explore ideas with full awareness of what's already been built.

All conversations are logged as JSONL. You can use the CLI for everything, or launch the TUI (`gotg ui`) for an interactive interface.

## Installation

### Python

You need Python 3.11 or higher.

```bash
python --version  # check your version
```

If you're using pyenv:
```bash
pyenv install 3.11.10
pyenv local 3.11.10
```

### GOTG

From the repo:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .          # CLI only
pip install -e ".[tui]"   # CLI + TUI (adds textual)
```

### Model Provider

GOTG supports Anthropic (recommended), OpenAI-compatible APIs, and Ollama for local models.

**Anthropic (recommended):**
```bash
gotg model anthropic
# Then add your key to .env:
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

**Ollama (local):**
```bash
ollama pull qwen2.5-coder:7b
ollama serve
# GOTG defaults to Ollama, no extra config needed
```

**AMD GPU users**: You likely need `HSA_OVERRIDE_GFX_VERSION=10.3.0 ollama serve`.

## Quick Start

```bash
git init my-project && cd my-project
gotg init
gotg model anthropic
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

Edit `.team/iteration.json` — set `description` and `status`:
```json
{
  "iterations": [{
    "id": "iter-1",
    "description": "Build a CLI calculator with basic arithmetic",
    "status": "in-progress",
    "phase": "refinement",
    "max_turns": 30
  }],
  "current": "iter-1"
}
```

Then run:
```bash
gotg run          # agents discuss until coach signals phase complete
gotg advance      # move to next phase (produces artifacts)
gotg run          # run the next phase
```

## Project Structure

`gotg init` creates a `.team/` directory (like `.git/`):

```
.team/
  team.json              # Model config, agents, coach, file access, worktrees
  iteration.json         # All iterations with current pointer
  iterations/
    iter-1/
      conversation.jsonl # The conversation log
      debug.jsonl        # Debug traces (prompt dumps)
      refinement_summary.md  # (generated on advance from refinement)
      tasks.json             # (generated on advance from planning)
  grooming/
    some-topic/
      grooming.json      # Session metadata
      conversation.jsonl # Grooming conversation
```

## Iteration Lifecycle

Each iteration goes through five phases:

1. **Refinement** — Define scope, requirements, edge cases. No implementation talk.
2. **Planning** — Break scope into tasks with dependencies and done criteria.
3. **Pre-code-review** — Propose implementation approaches. Interface alignment.
4. **Implementation** — Agents write code using file tools in git worktrees.
5. **Code-review** — Agents review each other's diffs.

### Running a Phase

```bash
gotg run       # start or resume the current phase
```

The coach facilitates and calls `signal_phase_complete` when the team is ready. `max_turns` in iteration.json is per-phase — turns reset at each phase boundary.

### Advancing Phases

```bash
gotg advance   # move to the next phase
```

Each advance produces artifacts:
- Refinement to planning: generates `refinement_summary.md`
- Planning to pre-code-review: generates `tasks.json` (with dependency layers)
- Pre-code-review to implementation: extracts task notes, sets `current_layer`
- Implementation to code-review: auto-commits worktrees

### Continuing a Conversation

If a conversation is interrupted (Ctrl+C, max turns reached):
```bash
gotg continue              # resume from where it left off
gotg continue -m "message" # inject a PM message first
```

### Layer Progression (Implementation)

Tasks are organized into dependency layers. After code review:
```bash
gotg review    # see diffs for the current layer
gotg merge     # merge approved branches
gotg next-layer  # advance to the next layer's implementation
```

## Grooming

Grooming sessions are freeform exploration conversations outside the iteration lifecycle. No phases, no deliverables — just the team discussing a topic.

### Why Grooming Exists

Between iterations, you often want the team to explore ideas before committing to a formal iteration. Grooming sessions let agents brainstorm with full awareness of what's already been built — they can reference previous iteration artifacts and browse the codebase.

### Starting a Grooming Session (CLI)

```bash
gotg groom start "topic to explore"
gotg groom start "adding a TUI" --coach          # with coach facilitation
gotg groom start "new feature" --max-turns 20     # custom turn limit
gotg groom start "topic" --slug my-custom-slug    # override auto-slug
```

### Iteration Context Injection

By default, grooming sessions auto-detect the latest iteration with artifacts (refinement_summary.md or tasks.json) and inject them into agent system prompts. Agents start the conversation aware of existing decisions, requirements, and task structure.

```bash
# Default: auto-detect latest iteration with artifacts
gotg groom start "improving the calculator"

# Explicit: load context from a specific iteration
gotg groom start "rethinking auth" --context-from iter-2

# Skip: no iteration context (pure freeform)
gotg groom start "random brainstorm" --no-context
```

`--context-from` and `--no-context` are mutually exclusive.

The choice is persisted in `grooming.json` as `context_from`. On `groom continue`, the same context is reloaded automatically — no re-scanning or flags needed.

### Read-Only File Tools

When `file_access` is configured in `team.json` (it is by default), grooming agents get `file_read` and `file_list` tools. They can browse the codebase but cannot write files. This lets agents verify claims about existing code rather than speculating.

### Bootstrap Kickoff

The first turn of a grooming session orients the team based on what's available:

- **Context + file tools**: "Review the iteration context. Use file tools to inspect the codebase. Summarize what exists before proposing."
- **Context only**: "Review the iteration context in your system prompt. Summarize what's been built."
- **Generic** (no context): "This is an open exploration. What are your initial thoughts?"

### Continuing a Session

```bash
gotg groom continue <slug>                  # resume
gotg groom continue <slug> -m "consider X"  # inject a PM message first
gotg groom continue <slug> --max-turns 10   # 10 more turns from current point
```

### Listing and Viewing

```bash
gotg groom list              # list all grooming sessions
gotg groom show <slug>       # print the conversation
```

### Grooming in the TUI

Press **G** from the Home screen to create a new grooming session. The TUI prompts for a topic, auto-detects iteration context, and opens the conversation directly.

Existing grooming sessions appear in the **Grooming** tab on the Home screen. Select one and press Enter to view the conversation, **R** to run, or **C** to continue.

The TUI grooming path has the same context injection as the CLI — iteration artifacts are loaded based on the persisted `context_from` field.

Note: `--context-from` and `--no-context` options are CLI-only. The TUI always auto-detects. For explicit control, use the CLI.

## TUI (Interactive Interface)

```bash
gotg ui
```

Launches a Textual-based terminal interface. Requires `pip install gotg[tui]`.

### Home Screen

Two tabs: **Iterations** and **Grooming**. Plus an **Info** tab showing project configuration.

Key bindings:
- **Enter** — View conversation
- **R** — Run (start fresh)
- **C** — Continue
- **N** — New iteration (or grooming, depending on active tab)
- **G** — New grooming session (works from any tab)
- **E** — Edit iteration properties
- **S** — Settings

### Chat Screen

Two-column layout: messages on the left, info tile on the right. During a run, messages stream in real time.

Key bindings:
- **P** — Advance phase (when coach signals complete)
- **A** — Manage approvals (when pending)
- **D** — Open review screen (code-review phase)
- **Esc** — Stop running / go back

### Settings Screen

Configure model provider, agents, coach, file access, and worktrees. Changes are saved with **Ctrl+S**.

## Configuration Reference

### team.json

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
    "enable_approvals": false
  },
  "worktrees": {"enabled": false},
  "streaming": false
}
```

- **model.api_key**: Use `$VAR` syntax to reference `.env` or shell environment variables.
- **file_access**: Enables file tools for agents. `writable_paths` controls where agents can write during implementation. Grooming sessions get read-only access regardless.
- **worktrees**: When enabled, each agent gets an isolated git worktree during implementation.
- **streaming**: When true, agent responses stream token-by-token.

### iteration.json

```json
{
  "schema_version": 1,
  "iterations": [
    {
      "id": "iter-1",
      "title": "",
      "description": "Build a CLI calculator",
      "status": "in-progress",
      "phase": "refinement",
      "max_turns": 30
    }
  ],
  "current": "iter-1"
}
```

- **status**: `pending`, `in-progress`, or `done`.
- **max_turns**: Per-phase turn limit. 30 means 30 agent turns per phase.
- **phase**: Managed by `gotg advance`. Don't edit manually.

### grooming.json

```json
{
  "schema_version": 2,
  "slug": "adding-gui-textual",
  "topic": "adding a GUI with textual",
  "coach": true,
  "max_turns": 30,
  "status": "active",
  "context_from": "iter-1"
}
```

- **context_from**: `"iter-1"` (load that iteration's context), `null` (no context found), or `false` (user opted out with `--no-context`).

## Tips

- **Let phases converge naturally.** Don't use `--max-turns` unless conversations are running too long. The coach calls `signal_phase_complete` when the team is ready.
- **Use grooming before iterations.** A 10-turn grooming session with context saves 20+ turns of agents rediscovering existing work.
- **The PM decides when to advance.** After the coach signals, you review and decide whether to run `gotg advance`.
- **Logs are just files.** JSONL — one JSON object per line. `grep`, `jq`, pipe, or script against them.
- **Checkpoints are automatic.** After each run/advance, GOTG snapshots the iteration state. Use `gotg restore N` to roll back.
