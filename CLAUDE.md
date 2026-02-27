# CLAUDE.md — Project Context for Claude Code

## What This Is
GOTG is an AI product and engineering department tool. pip-installable CLI (`gotg`) that runs structured conversations between AI agents following real engineering team processes (refinement → planning → pre-code-review → implementation → code-review). Terminal-based, JSONL conversation log, `.team/` directory per project (like `.git/`).

## Development Environment
- Python 3.11 via pyenv (venv at `.venv/`)
- Install: `.venv/bin/pip install -e ".[tui]"` (with TUI) or `.venv/bin/pip install -e .` (CLI only)
- Tests: `.venv/bin/python -m pytest tests/ -q`
- 779 tests as of TUI iteration 1

## API & Model
- Default provider: **Anthropic** (Claude Sonnet)
- API key lives in the **project's `.env` file**: `/home/biff/eng/gotg/.env`
  - Format: `ANTHROPIC_API_KEY=sk-ant-...`
  - Do NOT rely on shell environment variable — read from `.env`
- When setting up a test project, copy `.env`: `cp /home/biff/eng/gotg/.env /tmp/gotg-test/.env`
- Configure model: `gotg model anthropic`

## Test Project Workflow
Test projects live at `/tmp/gotg-test`. Full setup from scratch:
```bash
rm -rf /tmp/gotg-test && mkdir /tmp/gotg-test
cd /tmp/gotg-test
gotg init
# Edit .team/iteration.json: set description, status to "in-progress", max_turns to 30
gotg model anthropic
cp /home/biff/eng/gotg/.env /tmp/gotg-test/.env
gotg run          # runs until max_turns or coach calls signal_phase_complete
gotg advance      # moves to next phase (produces artifacts: refinement_summary.md, tasks.json)
gotg run          # runs the next phase
```

## Copying Run Artifacts to run_history
After a test run, copy artifacts with the current commit hash as prefix:
```bash
COMMIT=$(git rev-parse --short HEAD)
cp /tmp/gotg-test/.team/iterations/iter-1/conversation.jsonl run_history/conversation-${COMMIT}.jsonl
cp /tmp/gotg-test/.team/iterations/iter-1/debug.jsonl run_history/debug-${COMMIT}.jsonl
# Also copy phase artifacts if they exist:
cp /tmp/gotg-test/.team/iterations/iter-1/refinement_summary.md run_history/groomed-${COMMIT}.md
cp /tmp/gotg-test/.team/iterations/iter-1/tasks.json run_history/tasks-${COMMIT}.json
```

## Key Conventions
- **max_turns** in iteration.json is PER PHASE (history resets at phase boundaries). 30 means 30 turns per phase.
- **Let phases converge naturally** — don't use `--max-turns` flag unless the user asks. The coach calls `signal_phase_complete` when done.
- **Don't advance phases early** — wait for the coach to signal, then let the user decide.
- **Don't run phases without being asked** — the user (PM) decides when to run.

## Project Layout
- `src/gotg/` — package code (cli, agent, model, conversation, config, scaffold, tasks, groom, tui/)
- `tests/` — pytest tests
- `run_history/` — archived conversation logs and artifacts from test runs
- `narrative.md` — design log / decision journal
- `.team/` — created per-project by `gotg init`, NOT in this repo

## Architecture
- `agent.py` — `build_prompt()` and `build_coach_prompt()` map conversation to chat API roles
- `cli.py` — `run_conversation()` is the main loop; `cmd_advance()` handles phase transitions and artifact generation
- `model.py` — `chat_completion()` routes to OpenAI or Anthropic paths; Anthropic path has prompt caching
- `scaffold.py` — all prompt constants (DEFAULT_SYSTEM_PROMPT, PHASE_PROMPTS, COACH_*_PROMPT, COACH_TOOLS)
- `tasks.py` — `compute_layers()` (topological sort) and `format_tasks_summary()`
- `config.py` — loads team.json, iteration.json, .env files

## Phases
1. **refinement** — define scope and requirements (no implementation talk)
2. **planning** — break scope into tasks with dependencies
3. **pre-code-review** — discuss implementation approaches before writing code
4. **implementation** — agents write code using file tools in worktrees
5. **code-review** — agents review each other's diffs, coach tracks concerns

On advance (each writes a history boundary marker before the transition message):
- refinement → planning: coach produces `refinement_summary.md`
- planning → pre-code-review: coach produces `tasks.json` (with computed layers)
- pre-code-review → implementation: sets `current_layer` to 0, extracts task notes from pre-code-review conversation
- implementation → code-review: auto-commits current-layer worktrees

Layer progression: `gotg next-layer` (after merging) → verifies merges, cleans up worktrees, advances to next layer's implementation

## Grooming (Freeform Exploration)
`gotg groom` runs conversations outside the iteration lifecycle — no phases, no deliverables.

```bash
gotg groom start "topic to explore" [--slug S] [--coach] [--max-turns N]
gotg groom start "topic" --context-from iter-1   # explicit iteration context
gotg groom start "topic" --no-context             # skip context injection
gotg groom continue <slug> [-m MSG] [--max-turns N]
gotg groom list
gotg groom show <slug>
```

- Lives in `.team/grooming/<slug>/` (separate from iterations)
- Uses `grooming_policy()` — system supplement overrides phase workflow, coach gets `ask_pm` only (no `signal_phase_complete`)
- `--max-turns` on continue is additive (N more turns from current point)
- Synthetic iteration dict: `{"id": slug, "description": topic, "phase": None}`
- **Iteration context injection**: auto-detects latest iteration with artifacts (refinement_summary.md or tasks.json), injects into agent system prompts. `--context-from` for explicit, `--no-context` to skip. Persisted in `grooming.json` as `context_from` (string = iteration ID, `null` = none found, `false` = user opted out).
- **Read-only file tools**: when `file_access` configured in team.json, agents get `file_read` + `file_list` (no `file_write`). FileGuard with empty `writable_paths` enforces read-only.
- **Bootstrap kickoff**: 3 variants based on available context + file tools. Orients agents to review existing work before ideating.
- TUI: press **G** from Home to start grooming (auto-detects context). `--context-from`/`--no-context` are CLI-only.

## TUI (Interactive Interface)
`gotg ui` launches a Textual-based TUI for browsing iterations and grooming conversations.

- **Optional dependency:** `pip install gotg[tui]` (textual)
- **Home screen:** tabbed view (Iterations, Grooming, Info). N=new, E=edit, R=run, C=continue, G=new grooming
- **Chat screen:** two-column layout (messages left, info tile right). P=advance, A=approvals, D=review diffs
- **Settings screen:** model provider, agents, coach, file access, worktrees. Ctrl+S to save
- Lives in `src/gotg/tui/` subpackage (app, screens, widgets, CSS)
