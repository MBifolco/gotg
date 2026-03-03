# GOTG User Guide

## What GOTG Does

GOTG runs structured conversations between AI agents inside your project. You give it a task, and a team of AI engineers discusses it through a series of phases — refining requirements, planning tasks, reviewing approaches, implementing code, and reviewing diffs. An AI coach facilitates the conversation, tracking progress and surfacing unresolved issues.

Between iterations, exploration sessions let the team explore ideas with full awareness of what's already been built.

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
git clone https://github.com/biff-ai/gotg.git
cd gotg
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
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

**OpenAI:**
```bash
gotg model openai
echo "OPENAI_API_KEY=sk-..." > .env
```

**Ollama (local, free):**
```bash
ollama pull qwen2.5-coder:7b
ollama serve
gotg model ollama
# No API key needed
```

AMD GPU users likely need `HSA_OVERRIDE_GFX_VERSION=10.3.0 ollama serve`.

Note: Local models produce noticeably lower quality conversations than Anthropic/OpenAI.

| Provider | Default Model | API Key Variable |
|----------|---------------|------------------|
| `anthropic` | `claude-sonnet-4-5-20250929` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| `ollama` | `qwen2.5-coder:7b` | none |

Any OpenAI-compatible API works — set `base_url` and `model` manually in `team.json`.

## How It Works

You are the **Product Manager**. AI agents discuss and design based on your task description, guided through structured phases by an AI coach. You steer the conversation with feedback and control every transition.

### Phases

Every iteration progresses through five phases:

1. **Refinement** — Agents discuss *what* to build. Requirements, scope, edge cases, acceptance criteria.
2. **Planning** — Agents break the agreed scope into concrete, assignable tasks with dependencies, done criteria, and an agreed implementation approach per task. The coach extracts a structured `tasks.json`.
3. **Pre-code-review** — Agents propose implementation approaches for their assigned tasks. File structure, interfaces, test strategy. The coach verifies proposals are consistent with the approach agreed during planning.
4. **Implementation** — Agents write code for their assigned tasks using file tools in isolated git worktrees. Each task has an approach field that agents must follow. On completion, agents attest to following the agreed approach.
5. **Code-review** — Agents review each other's implementation diffs. The coach tracks open review concerns and signals completion with an outcome: *approved* or *changes requested*.

The coach facilitates each phase — summarizing progress, flagging gaps, and signaling when the team is ready to advance. You control transitions with `gotg advance`.

### Layer Cycle

Tasks are organized into dependency layers. Layer 0 tasks have no dependencies. Layer 1 tasks depend on layer 0, and so on.

Each layer cycles through: **implementation → code-review → merge → next-layer**

After merging a layer into main, the next layer's worktrees branch from the updated main and automatically see all previous work.

### How Conversations Work

- The conversation log (`conversation.jsonl`) is append-only, but **agents only see messages from the current phase** — a history boundary is written on each `gotg advance`.
- `max_turns` in `iteration.json` is **per-phase** — the turn counter resets on each advance. 30 is a reasonable starting point.
- `gotg continue --max-turns N` adds N turns from the current point (relative).
- The coach speaks after every full rotation of agents. It has a `signal_phase_complete` tool to recommend advancing, and an `ask_pm` tool to pause the conversation and request your input.
- Human messages (`gotg continue -m "..."`) are injected before the next agent turn. This is also how you respond to `ask_pm` questions.
- Agents have a `pass_turn` tool — when they have nothing new to add, they pass instead of restating agreement.

### Code-Review Outcomes

The coach signals code review completion with one of two outcomes:

- **approved** — Every branch has been reviewed and the code is correct as-is. You can proceed to merge.
- **changes_requested** — The review found issues that need code changes. The coach summarizes what each agent needs to fix.

When approved, you'll see:
```
Code review approved. Next: gotg review to inspect diffs, gotg merge all to merge.
```

When changes are requested, you'll see:
```
Rework needed. Run gotg rework to send tasks back to implementation.
```

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
    exploration/               # Freeform exploration conversations
      some-topic/
        exploration.json       # Session metadata (topic, coach, max_turns)
        conversation.jsonl     # Conversation log
        summary.md             # Generated by gotg explore summarize
  .worktrees/                  # Git worktrees (if enabled, gitignored)
    agent-1-layer-0/
    agent-2-layer-0/
  src/                         # Your project code
```

## CLI Walkthrough

This walks through the complete lifecycle of a project — from blank repo to working code.

### 1. Initialize

```bash
mkdir my-project && cd my-project
git init -b main

# Need at least one commit (worktrees branch from HEAD)
echo "# my-project" > README.md
git add README.md && git commit -m "init"

gotg init .
gotg model anthropic
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

### 2. Create an Iteration

```bash
gotg new "Build a CLI todo list app"
```

This creates `iter-1` with status `in-progress`. Edit `.team/iteration.json` to adjust `max_turns` (default 30) or the description:

```json
{
  "iterations": [
    {
      "id": "iter-1",
      "title": "",
      "description": "Build a CLI todo list application in Python. Support add, list, complete, and delete operations. Store todos in a JSON file.",
      "status": "in-progress",
      "phase": "refinement",
      "max_turns": 30
    }
  ],
  "current": "iter-1"
}
```

Enable worktrees in `.team/team.json` so agents get isolated branches during implementation:
```json
{
  "worktrees": { "enabled": true }
}
```

Optionally enable streaming for real-time token output:
```json
{
  "streaming": true
}
```

### 3. Refinement

Agents discuss *what* to build — requirements, scope, edge cases, acceptance criteria. No implementation details.

```bash
gotg run                                    # Agents start discussing
gotg show                                   # Read the conversation
gotg continue -m "Also handle error cases"  # Inject your feedback, agents respond
gotg continue                               # Let them keep going
```

The coach facilitates and eventually calls `signal_phase_complete` when scope is nailed down:
```
Coach recommends advancing. Run `gotg advance` to proceed, or `gotg continue` to keep discussing.
```

When you're satisfied:
```bash
gotg advance                                # Coach writes refinement_summary.md, moves to planning
```

### 4. Planning

Agents break the agreed scope into concrete tasks with dependencies and done criteria.

```bash
gotg continue                               # Agents plan tasks
# Coach signals when the task list looks complete
gotg advance                                # Coach extracts tasks.json
```

The advance produces `.team/iterations/iter-1/tasks.json` with computed dependency layers:

```json
[
  {"id": "T1", "description": "Create storage layer", "approach": "Use JSON file with pathlib.", "depends_on": [], "assigned_to": "", "layer": 0},
  {"id": "T2", "description": "Create CLI parser", "approach": "Use argparse with subcommands.", "depends_on": [], "assigned_to": "", "layer": 0},
  {"id": "T3", "description": "Wire CLI to storage", "approach": "Import storage module directly.", "depends_on": ["T1", "T2"], "assigned_to": "", "layer": 1}
]
```

**You must assign agents before continuing.** Edit `tasks.json` and fill in `assigned_to`:

```json
{"id": "T1", "assigned_to": "agent-1", ...},
{"id": "T2", "assigned_to": "agent-2", ...},
{"id": "T3", "assigned_to": "agent-1", ...}
```

### 5. Pre-code-review

Agents propose implementation approaches — file structure, interfaces, test strategy. One task at a time, layer by layer. No actual code yet.

```bash
gotg continue                               # Agents discuss approaches
# Coach signals when all tasks have been discussed
gotg advance                                # Moves to implementation, sets current_layer=0
```

### 6. Implementation

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

Run `gotg continue` as many times as needed until agents finish their layer 0 tasks. When agents call `complete_tasks`, they must attest to following the agreed approach. The coach tracks progress and flags approach deviations.

You can check worktree status and manually commit at any time:
```bash
gotg worktrees                              # See worktree status (dirty/clean)
gotg commit-worktrees                       # Commit all dirty worktrees
gotg commit-worktrees -m "WIP"              # With a custom commit message
```

When ready:
```bash
gotg advance                                # Auto-commits dirty worktrees, moves to code-review
```

### 7. Code-review

Agents review each other's diffs. The coach tracks open concerns and signals when all are resolved, with an outcome of **approved** or **changes_requested**.

```bash
gotg continue                               # Agents review each other's code
```

**If approved:**
```
Code review approved. Next: gotg review to inspect diffs, gotg merge all to merge.
```

**If changes requested:**
```
Rework needed. Run gotg rework to send tasks back to implementation.
```

### 8. Review and Merge

After an approved code review, inspect diffs and merge:

```bash
gotg review                                 # See all diffs for the current layer
gotg review --stat-only                     # Just file stats
gotg review agent-1/layer-0                 # Review a specific branch

gotg merge all                              # Merge all branches into main
```

If a merge has conflicts, it stops on the first conflicting branch. You can resolve manually or abort:

```bash
# Fix conflicts in your editor, then:
git add <resolved-files>
gotg merge all                              # Continues with remaining branches

# Or abort the merge entirely:
gotg merge --abort
```

> If `merge` reports "uncommitted changes on main", commit any local changes first before merging.

### 9. Next Layer or Rework

**If code review was approved and all branches are merged:**

```bash
gotg next-layer
```

This verifies all branches for the current layer are merged, removes current-layer worktrees, and sets the phase to implementation with the next layer number. Repeat from step 6.

If all layers are complete:
```
All layers complete (through layer 1). Iteration is done.
```

**If code review requested changes:**

```bash
gotg rework
```

This extracts review feedback from the code-review conversation, applies it to the relevant tasks in `tasks.json`, and transitions back to implementation. Agents see the feedback and fix the issues. After implementation, it cycles back to code-review.

Then `gotg continue` to resume implementation with the feedback injected.

### 10. Done

Mark the iteration complete when you're satisfied:
```bash
# Edit .team/iteration.json and set status to "done"
```

Your code is on `main` with a clean git history:
```
$ git log --oneline
abc1234 Merge agent-1/layer-1 into main
def5678 Implementation complete
111aaaa Merge agent-2/layer-0 into main
222bbbb Merge agent-1/layer-0 into main
333cccc init
```

## TUI Walkthrough

The TUI provides an interactive interface for everything the CLI does.

```bash
pip install -e ".[tui]"   # One-time setup (installs Textual)
gotg ui
```

Press **?** from any screen to see all available keybindings for that screen.

### Home Screen

The home screen shows all iterations and exploration sessions in tabbed tables (Iterations, Exploration, Info).

| Key | Action |
|-----|--------|
| **Enter** | Open a conversation to read it |
| **R** | Run a session (starts the engine) |
| **C** | Continue a session |
| **N** | Create a new iteration or exploration (depends on active tab) |
| **E** | Edit iteration properties (description, max turns, status) |
| **G** | New exploration session (works from any tab) |
| **S** | Open settings |
| **r** | Refresh tables |

### Running a Session

Press **R** from the Home screen to start a run. The Chat screen opens and messages stream in real time. Each agent gets a distinct border color. Markdown is fully rendered — headings, bold, lists, and syntax-highlighted code blocks.

- Smart auto-scroll keeps you at the bottom, but won't yank you back if you scroll up to read earlier messages
- Type a message in the input field and press **Enter** to reply (equivalent to `gotg continue -m`)
- Press **Esc** to stop the session and return to viewing mode
- **Home/End** jump to top/bottom of the conversation

### Phase Advance

When the coach signals phase complete, the action bar shows guidance. Press **P** to advance to the next phase. The advance runs in the background — extraction and artifact generation happen without blocking the UI.

### Code Review and Merge

During code-review, the coach signals completion with an outcome. If approved, press **D** to open the Review screen:

| Key | Action |
|-----|--------|
| **M** | Merge the selected branch |
| **Y** | Merge all branches |
| **N** | Advance to next implementation layer (after all merged) |
| **F** | Mark iteration as done (when all layers complete) |
| **R** | Refresh branch list |

Select a branch to see its diff with syntax highlighting in the right panel.

### Handling Merge Conflicts

If a merge produces conflicts, the Conflict screen opens automatically:

| Key | Action |
|-----|--------|
| **O** | Resolve with ours (main branch version) |
| **T** | Resolve with theirs (agent branch version) |
| **A** | AI resolve (LLM generates a merged version) |
| **Y** | Accept AI resolution (after preview) |
| **N** | Reject AI resolution |
| **C** | Complete merge (when all conflicts resolved) |
| **Esc** | Abort merge (confirms if files already resolved) |

### Rework

When code review signals **changes_requested**, press **W** to send tasks back to implementation with review feedback injected. Then press **R** to resume implementation.

### Approvals

When agents request file writes outside writable paths (with approvals enabled), the session pauses.

**CLI:**
```bash
gotg approvals                  # Show pending requests
gotg approve a1                 # Approve request a1
gotg approve all                # Approve all pending
gotg deny a1 -m "wrong path"   # Deny with reason
```

**TUI:** Press **A** from the Chat screen to open the Approval screen:

| Key | Action |
|-----|--------|
| **A** | Approve selected request |
| **Y** | Approve all pending requests |
| **D** | Deny selected (opens reason input) |

Select a request to see the file content with syntax highlighting.

### Settings

Press **S** from the Home screen to configure:

- **Model** — Provider selection with presets (Anthropic, OpenAI, Ollama), base URL, model name
- **Agents** — Add (**A**), edit (**E**), and remove (**Delete**) agents (minimum 2)
- **Coach** — Toggle on/off with a switch, edit name and role
- **File Access** — Writable paths, protected paths, approvals toggle
- **Worktrees** — Enable/disable isolated git worktrees
- **Streaming** — Enable real-time token output

Press **Ctrl+S** to save changes.

## Exploration

Exploration sessions are freeform conversations outside the iteration lifecycle. No phases, no deliverables — just the team discussing a topic.

### Why Exploration Exists

Between iterations, you often want the team to explore ideas before committing to a formal iteration. Exploration sessions let agents brainstorm with full awareness of what's already been built — they can reference previous iteration artifacts and browse the codebase.

### Starting a Session

```bash
gotg explore start "how should we handle file conflicts?"
gotg explore start "adding a TUI" --coach            # with coach facilitation
gotg explore start "new feature" --max-turns 20       # custom turn limit
gotg explore start "topic" --slug my-custom-slug      # override auto-slug
```

Key properties:
- **No iteration lifecycle.** No phases, no planning, no tasks. Just conversation.
- **Lives outside iterations.** `.team/exploration/<slug>/` is a sibling of `.team/iterations/`.
- **No coach by default.** Add `--coach` for a facilitator who keeps the conversation broad.
- **Multiple concurrent conversations.** Explore several ideas in parallel, each in its own slug.
- **Slugs are auto-generated** from the topic. Override with `--slug`.

### Iteration Context Injection

By default, exploration sessions auto-detect the latest iteration with artifacts (`refinement_summary.md` or `tasks.json`) and inject them into agent system prompts. Agents start aware of existing decisions and task structure.

```bash
gotg explore start "improving the calculator"              # auto-detect latest
gotg explore start "rethinking auth" --context-from iter-2  # explicit iteration
gotg explore start "random brainstorm" --no-context         # no context (pure freeform)
```

`--context-from` and `--no-context` are mutually exclusive. The choice is persisted in `exploration.json` — on `explore continue`, the same context is reloaded automatically.

### Read-Only File Tools

When `file_access` is configured in `team.json`, exploration agents get `file_read` and `file_list` tools. They can browse the codebase to verify claims and reference existing implementations, but cannot write files.

### Bootstrap Kickoff

The first turn of an exploration session orients the team based on what's available:

- **Context + file tools** — Agents review iteration artifacts and inspect the codebase before proposing.
- **Context only** — Agents review the iteration context in their system prompt before ideating.
- **Generic** (no context) — Open exploration. Agents start from scratch.

### Continuing and Viewing

```bash
gotg explore continue <slug>                  # resume
gotg explore continue <slug> -m "consider X"  # inject a PM message first
gotg explore continue <slug> --max-turns 10   # 10 more turns from current point
gotg explore list                             # list all sessions
gotg explore show <slug>                      # print the conversation
```

### Summarizing

Generate a structured summary from an exploration conversation:

```bash
gotg explore summarize <slug>
```

This uses an LLM call to produce a summary covering key points, agreements, decisions against, open questions, and proposed next steps. The output is written to `.team/exploration/<slug>/summary.md`.

### Exploration in the TUI

Press **G** from the Home screen to create a new exploration session. The TUI prompts for a topic, auto-detects iteration context, and opens the conversation directly. Existing sessions appear in the **Exploration** tab — select one and press Enter to view, **R** to run, or **C** to continue.

Note: `--context-from` and `--no-context` options are CLI-only. The TUI always auto-detects context.

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
    "max_files_per_turn": 10,
    "enable_approvals": false
  },
  "worktrees": {
    "enabled": true
  },
  "streaming": true
}
```

- **model.api_key** — Use `$VAR` syntax to reference `.env` or shell environment variables.
- **file_access** — Enables file tools for agents. `writable_paths` controls where agents can write during implementation. Exploration sessions get read-only access regardless.
- **file_access.protected_paths** — Glob patterns that require approval even within writable paths.
- **file_access.enable_approvals** — When `true`, writes outside `writable_paths` go to a pending queue instead of failing. Review with `gotg approvals`.
- **Hard-denied paths** — `.team/`, `.git/`, `.env*` are always blocked regardless of configuration.
- **worktrees** — When enabled, each agent gets an isolated git worktree during implementation and code-review. Requires at least one commit on `main` and HEAD on `main`.
- **streaming** — When `true`, agent responses stream token-by-token to the terminal and TUI.

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

- **status** — `pending`, `in-progress`, or `done`.
- **max_turns** — Per-phase turn limit. Resets on each `gotg advance`.
- **phase** — Managed by `gotg advance`. Don't edit manually.

### exploration.json

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

- **context_from** — `"iter-1"` (load that iteration's context), `null` (no context found), or `false` (user opted out with `--no-context`).

## Checkpoints

GOTG automatically checkpoints after every `run`, `continue`, `advance`, and `next-layer` command. You can also create manual checkpoints.

Checkpoints are stored per-iteration under `.team/iterations/<id>/checkpoints/<N>/`. Each checkpoint contains a copy of all iteration files plus metadata.

```bash
gotg checkpoints                               # List all checkpoints
gotg checkpoint "before prompt experiment"      # Manual snapshot
gotg restore 3                                 # Roll back (prompts for safety checkpoint)
```

Example output:
```
   Phase              Turns   Trigger   Description                    Timestamp
----------------------------------------------------------------------------------------------------
1  refinement         8       auto                                     2026-02-07T20:15:33
2  planning           14      auto                                     2026-02-07T20:22:10
3  planning           14      manual    before prompt experiment       2026-02-07T20:25:00
```

## Conversation Log Format

Messages are stored as newline-delimited JSON (JSONL):

```json
{"from":"agent-1","iteration":"iter-1","content":"I think we should store todos as JSON..."}
{"from":"agent-2","iteration":"iter-1","content":"What about collisions though?"}
{"from":"human","iteration":"iter-1","content":"Good points. Also consider auth later."}
{"from":"coach","iteration":"iter-1","content":"Let me summarize what we've agreed on..."}
{"from":"system","iteration":"iter-1","content":"--- Phase advanced: refinement → planning ---"}
```

The log is append-only. Read with `gotg show`, or directly with `cat`, `jq`, or any JSONL tool.

## Tips

- **Let phases converge naturally.** Don't use `--max-turns` unless conversations are running too long. The coach calls `signal_phase_complete` when the team is ready.
- **Use exploration before iterations.** A 10-turn exploration session with context saves 20+ turns of agents rediscovering existing work.
- **The PM decides when to advance.** After the coach signals, you review and decide whether to run `gotg advance`.
- **Logs are just files.** JSONL — one JSON object per line. `grep`, `jq`, pipe, or script against them.
- **Checkpoints are automatic.** After each run/advance, GOTG snapshots the iteration state. Use `gotg restore N` to roll back.
