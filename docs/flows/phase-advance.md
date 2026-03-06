# Flow: Advancing Phases (`gotg advance`)

Traces the path from advance command through extraction to phase transition.

## Entry Point

- `gotg advance` → `commands/advance.py::cmd_advance`

## Phase Transitions

```
refinement --> planning --> pre-code-review --> implementation --> code-review
                                                                    |
                                                          (rework) implementation
```

## Step-by-step

1. **Command dispatch** (`commands/advance.py::cmd_advance`)
   - Finds `.team/` directory, loads current iteration via `IterationStore`
   - Checks iteration status is `in-progress`
   - Calls `session_advance.py::advance_phase()` with `chat_call=_cli.chat_completion`

2. **Validation** (`session_advance.py::validate_advance`)
   - Checks iteration status is `in-progress`
   - Looks up current phase in `PHASE_ORDER`, verifies not at final phase
   - Returns `(current_phase, next_phase)` tuple
   - Guards against empty phases: requires at least one agent message in phase history

3. **Artifact extraction** (`session_advance.py::advance_phase`)
   - Reads phase history from conversation log via `ConversationStore.read_phase_history()`
   - Calls `transitions.py` extraction functions via one-shot LLM:
     - **refinement -> planning**: `extract_refinement_summary()` writes `refinement_summary.md`
     - **planning -> pre-code-review**: `extract_tasks()` writes `tasks.json` (via `TaskRepo`); on parse failure, saves `tasks_raw.txt` and adds warning
     - **pre-code-review -> implementation**: `extract_task_notes()` updates tasks.json with notes and files fields; sets `current_layer=0` via `IterationStore`
     - **implementation -> code-review**: `auto_commit_layer_worktrees()` commits dirty worktrees for current layer
   - Each extraction: filter conversation (exclude system/coach), format prompt, call LLM, parse response

4. **Phase skeleton** (`transitions.py::build_phase_skeleton`)
   - Computed from pre-boundary phase history (captured BEFORE writing boundary markers)
   - Appended to `phase_skeleton.md` (accumulated across phases)
   - Provides compressed prior-phase context to agents in later phases

5. **Boundary markers** (`transitions.py::build_transition_messages`)
   - Produces `phase_boundary` message (scopes history for next phase via `read_phase_history`)
   - Produces transition notification message
   - Both appended to conversation log

6. **State update** (`iteration_store.py`)
   - `save_phase()` or `save_fields()` updates phase (and optionally `current_layer`, `review_outcome`) in iteration.json
   - Returns `AdvanceResult` with from/to phases, messages, and warnings

## Rework Loop (`gotg rework`)

- `commands/advance.py::cmd_rework` -> `session_advance.py::advance_rework`
- Requires code-review phase with `review_outcome == "changes_requested"`
- `extract_review_feedback()` maps review comments to task IDs
- Tasks with feedback get `status: "changes_requested"` and `review_feedback` field
- `build_rework_messages()` writes boundary + transition
- Phase set back to implementation (same layer, `review_outcome` cleared)

## Next Layer (`gotg next-layer`)

- `commands/advance.py::cmd_next_layer` -> `session_advance.py::advance_next_layer`
- Requires code-review phase with `review_outcome == "approved"`
- `validate_next_layer()`: verifies HEAD on main, all layer branches merged, no dirty worktrees
- `cleanup_layer_worktrees()` removes current layer's worktrees
- Checks `tasks.json` for tasks in next layer; if none, returns `all_done=True`
- Writes boundary marker with layer info, sets phase to implementation + increments layer

## Files Touched

| Module | Responsibility |
|--------|---------------|
| `commands/advance.py` | CLI entry (`cmd_advance`, `cmd_next_layer`, `cmd_rework`), output formatting |
| `session_advance.py` | Validation, orchestration, state updates, extraction coordination |
| `transitions.py` | LLM extraction calls, boundary/transition/rework message builders, phase skeleton |
| `conversation.py` | `ConversationStore.read_phase_history()`, append markers |
| `iteration_store.py` | Phase/layer/review_outcome state persistence, `PHASE_ORDER` |
| `tasks.py` | `TaskRepo` for reading/writing tasks.json, `format_tasks_summary` |
| `config.py` | `load_coach`, `load_model_config`, `load_worktree_config` |
| `worktree.py` | `auto_commit_layer_worktrees`, `cleanup_layer_worktrees`, merge verification |
