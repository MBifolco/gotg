# CLAUDE.md — Project Context for Claude Code

## What This Is
GOTG is an AI product and engineering department tool. pip-installable CLI (`gotg`) that runs structured conversations between AI agents following real engineering team processes (grooming → planning → pre-code-review → implementation → code-review). Terminal-based, JSONL conversation log, `.team/` directory per project (like `.git/`).

## Development Environment
- Python 3.11 via pyenv (venv at `.venv/`)
- Install: `.venv/bin/pip install -e .`
- Tests: `.venv/bin/python -m pytest tests/ -q`
- 575 tests as of iteration 14

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
gotg advance      # moves to next phase (produces artifacts: groomed.md, tasks.json)
gotg run          # runs the next phase
```

## Copying Run Artifacts to run_history
After a test run, copy artifacts with the current commit hash as prefix:
```bash
COMMIT=$(git rev-parse --short HEAD)
cp /tmp/gotg-test/.team/iterations/iter-1/conversation.jsonl run_history/conversation-${COMMIT}.jsonl
cp /tmp/gotg-test/.team/iterations/iter-1/debug.jsonl run_history/debug-${COMMIT}.jsonl
# Also copy phase artifacts if they exist:
cp /tmp/gotg-test/.team/iterations/iter-1/groomed.md run_history/groomed-${COMMIT}.md
cp /tmp/gotg-test/.team/iterations/iter-1/tasks.json run_history/tasks-${COMMIT}.json
```

## Key Conventions
- **max_turns** in iteration.json is a TOTAL across all phases (conversation.jsonl is cumulative). Set high enough for all phases (e.g., 90 for 3 phases × 30).
- **Let phases converge naturally** — don't use `--max-turns` flag unless the user asks. The coach calls `signal_phase_complete` when done.
- **Don't advance phases early** — wait for the coach to signal, then let the user decide.
- **Don't run phases without being asked** — the user (PM) decides when to run.

## Project Layout
- `src/gotg/` — package code (cli, agent, model, conversation, config, scaffold, tasks)
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
1. **grooming** — define scope and requirements (no implementation talk)
2. **planning** — break scope into tasks with dependencies
3. **pre-code-review** — discuss implementation approaches before writing code
4. **implementation** — agents write code using file tools in worktrees
5. **code-review** — agents review each other's diffs, coach tracks concerns

On advance:
- grooming → planning: coach produces `groomed.md`
- planning → pre-code-review: coach produces `tasks.json` (with computed layers)
- pre-code-review → implementation: sets `current_layer` to 0
- implementation → code-review: auto-commits current-layer worktrees

Layer progression: `gotg next-layer` (after merging) → verifies merges, cleans up worktrees, advances to next layer's implementation
