# Flow: Exploration Sessions (`gotg explore`)

Freeform conversations without phase constraints, used for pre-iteration exploration.

## Entry Points

- `gotg explore start "topic"` → `commands/explore.py::cmd_explore_start`
- `gotg explore continue <slug>` → `commands/explore.py::cmd_explore_continue`
- `gotg explore list` / `show` / `summarize` — read-only commands

## Start Flow

1. **Slug generation** (`explore.py`)
   - `generate_slug()`: strips stop words, kebab-cases, truncates to 50 chars, deduplicates
   - User can override with `--slug`; validated by `validate_slug()` (regex: `^[a-z0-9][a-z0-9-]{0,49}$`)

2. **Iteration context** (`commands/explore.py`)
   - `--context-from <iter-id>`: explicit iteration for context injection (strict validation)
   - `--no-context`: skip context injection entirely
   - Default: `session_setup.py::load_iteration_context()` auto-detects latest non-pending iteration with artifacts (refinement_summary.md or tasks.json)

3. **Metadata creation** (`explore.py::write_exploration_metadata`)
   - Creates `.team/exploration/<slug>/` directory
   - Writes `exploration.json` with slug, topic, coach flag, max_turns, context_from
   - Creates empty `conversation.jsonl`

4. **Session execution** enters pause loop (same structure as `cmd_run`)

## Session Execution

`explore.py::run_exploration_conversation()` builds deps and setup, then delegates:

1. **Build deps** (`engine.py::SessionDeps`) — late imports preserve mock targets
2. **Prepare session** (`session_setup.py::prepare_exploration_session`)
   - Builds `exploration_policy()` with:
     - No phase (`iteration.phase = None`)
     - Exploration-specific system supplement and coach prompt (from TOML)
     - Optional read-only file tools (if `file_access` configured and `project_root` available)
     - Optional project context injection
   - Returns `SessionSetup` with `use_implementation=False`
3. **Run and persist** (`session_setup.py::run_and_persist`) → `engine.py::run_session`
4. **Render events** (`console_events.py::handle_console_events`) with exploration-specific callbacks:
   - Custom `on_started`: `_print_exploration_header` (topic-focused, no phase)
   - `resume_hint`: `gotg explore continue <slug>`
   - `summarize_hint`: `gotg explore summarize <slug>`
   - `complete_label`: `"Exploration"`

## Continue Flow

`commands/explore.py::cmd_explore_continue`:

1. Loads metadata from `.team/exploration/<slug>/exploration.json`
2. Handles `--approve-iterations`: finds last unapproved proposal batch, calls `session_setup.py::apply_iteration_proposals()` to create/update iterations
3. Counts existing agent turns for turn budget
4. Injects human message if `-m` provided
5. Detects stale `user_pause` markers (same logic as iteration continue)
6. Enters pause loop calling `run_exploration_conversation()`

## Iteration Proposals

Coach can call `propose_iterations` tool during exploration:
- Engine yields `IterationsProposed` event with batch ID and proposal list
- CLI prints proposals, prompts user to approve or give feedback
- `gotg explore continue <slug> --approve-iterations` calls `apply_iteration_proposals()`:
  - Validates proposals (action, title, description required)
  - Pre-computes IDs for creates (batch-safe deduplication)
  - Creates/updates iterations via `IterationStore`
  - Writes structured `iterations_batch_approved` marker to prevent re-proposal

## Summarize

`gotg explore summarize <slug>` → `commands/explore.py::cmd_explore_summarize`:
- Loads full conversation history
- Calls `transitions.py::extract_exploration_summary_doc()` via one-shot LLM
- Writes summary to `.team/exploration/<slug>/summary.md`

## Key Differences from Iterations

| Aspect | Iteration | Exploration |
|--------|-----------|-------------|
| Phase | refinement -> ... -> code-review | None |
| Directory | `.team/iterations/<id>/` | `.team/exploration/<slug>/` |
| File tools | Full read/write with approvals | Read-only (if configured) |
| Coach tools | `signal_phase_complete`, `ask_pm` | `ask_pm`, `propose_iterations`, `end_exploration` |
| Outcome | Phase artifacts, code changes | Summary doc, iteration proposals |
| Policy factory | `iteration_policy()` | `exploration_policy()` |

## Files Touched

| Module | Responsibility |
|--------|---------------|
| `commands/explore.py` | CLI entry (start/continue/list/show/summarize), pause loop, proposal approval |
| `explore.py` | Slug gen, metadata CRUD, session runner, exploration header |
| `session_setup.py` | `prepare_exploration_session`, `load_iteration_context`, `apply_iteration_proposals` |
| `policy.py` | `exploration_policy()` factory |
| `engine.py` | Same `run_session` loop (phase=None, no `signal_phase_complete` stop) |
| `console_events.py` | Event rendering with exploration-specific labels |
| `transitions.py` | `extract_exploration_summary_doc` |
| `prompts.py` | `EXPLORATION_*` prompt constants (from TOML) |
