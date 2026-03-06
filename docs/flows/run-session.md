# Flow: Running a Session (`gotg run` / `gotg continue`)

Traces the path from CLI command to agent conversation and back.

## Entry Points

- `gotg run` → `commands/run.py::cmd_run`
- `gotg continue` → `commands/run.py::cmd_continue`

## Step-by-step

1. **Command parsing** (`cli.py::main`)
   - argparse dispatches to `cmd_run` or `cmd_continue` via lazy imports

2. **Team config loading** (`commands/run.py`)
   - `TeamContext.from_team_dir()` loads agents, coach, model config, file access
   - `validate_iteration_for_run()` checks phase, status, task assignments, agent count

3. **Session infrastructure** (`session_setup.py::build_session_infra`)
   - `build_file_infra()` creates FileGuard + ApprovalStore from file_access config
   - `setup_worktrees()` creates git worktrees per agent (implementation/code-review only)
   - `load_diffs_for_review()` loads branch diffs for code-review phase
   - `load_streaming_config()` checks for streaming opt-in
   - Returns `SessionInfra` dataclass with all resources

4. **Continue-specific setup** (`session_setup.py::prepare_continue`)
   - `apply_and_inject()` executes approved writes, injects denial messages into log
   - Counts existing agent turns in current phase for turn budget calculation
   - Detects (but does not consume) stale `user_pause` markers

5. **Pause controller** (`commands/run.py::_make_pause_controller`)
   - Creates `PauseController` if stdin is a TTY, else None
   - Controller installs SIGINT handler (Ctrl+C sets cooperative pause flag)

6. **Conversation bridge** (`cli.py::run_conversation`)
   - Builds `SessionDeps` from module-level model imports (bridge pattern for mocking)
   - `prepare_session()` reads phase history, builds `SessionPolicy`, determines phase routing
   - Wires `cancel_check` from pause controller onto `SessionSetup`
   - Wraps engine generator in `_persist_outcome` to save `review_outcome` on `PhaseCompleteSignaled`
   - Passes `run_and_persist(setup)` into `handle_console_events()`

7. **Session engine** (`engine.py::run_session`)
   - Yields `SessionStarted` with metadata
   - Injects kickoff message if `policy.kickoff_text` is set
   - **Discussion phases**: round-robin agent turns with optional coach
     - `build_prompt()` constructs agent's system + history messages
     - `agentic_completion()` or streaming tool loop calls LLM
     - `_process_agent_result()` yields `AppendMessage` events for tool ops and agent text
     - Coach injected every N turns (`policy.coach_cadence`) via `_do_coach_turn()`
     - Checks: `signal_phase_complete`, `ask_pm`, `pass_turn`, `propose_iterations`, `end_exploration`
   - **Implementation phase**: `run_and_persist()` delegates to `implementation.py::run_implementation`
     - Per-task dispatch within current layer
     - `cancel_check` fires between agent dispatches

8. **Persistence** (`session_setup.py::run_and_persist`)
   - Wraps engine/implementation generator
   - Routes to `run_session()` for discussion or `run_implementation()` for implementation
   - `persist_event()` writes `AppendMessage` to conversation.jsonl, `AppendDebug` to debug.jsonl
   - Persist-then-emit: events are persisted BEFORE being yielded to consumer

9. **Console rendering** (`console_events.py::handle_console_events`)
   - Consumes event stream, prints messages via `render_message()`
   - Handles streaming: `TextDelta` writes to stdout, `AgentTurnComplete` suppresses duplicate print
   - Discussion pause: after each `AppendMessage` at a turn boundary, checks pause flag
   - Deferred pause: terminal events (PauseForApprovals, PhaseCompleteSignaled, etc.) win over pause
   - Implementation pause: `UserPauseComplete` event returns `"paused"` immediately
   - Returns `"paused"` or `None`

10. **Pause loop** (`commands/run.py`)
    - If `"paused"`: `prompt_for_interjection()` offers tri-state choice
    - None (Ctrl+C/EOF): writes `user_pause` marker to conversation log, breaks
    - RESUME sentinel (Enter): resets controller, loops back to step 6
    - String (typed message): appends human message, resets controller, loops back to step 6
    - On `cmd_continue`: after first successful run, writes `user_pause_resolved` marker

## Key Module Boundaries

```
commands/run.py  -->  cli.py::run_conversation  -->  session_setup.py::run_and_persist
                                                          |
                                                 engine.py::run_session (discussion)
                                                          OR
                                                 implementation.py::run_implementation
                                                          |
                                                 console_events.py::handle_console_events
                                                 (rendering + pause detection)
```

## Files Touched

| Module | Responsibility |
|--------|---------------|
| `commands/run.py` | CLI entry, pause loop, marker I/O |
| `cli.py` | Session bridge, `SessionDeps` construction, `run_conversation` |
| `session_setup.py` | Validation, infrastructure, `prepare_session`, `run_and_persist` |
| `session_types.py` | `SessionInfra`, `SessionSetup`, `ContinueContext`, exception classes |
| `engine.py` | Core discussion loop, agent/coach orchestration, `SessionDeps` |
| `agent.py` | `build_prompt`, `build_coach_prompt` |
| `implementation.py` | Per-task dispatch within layers, `run_implementation` |
| `console_events.py` | Event rendering, turn boundary detection, deferred pause |
| `pause.py` | `PauseController` (SIGINT handler), `prompt_for_interjection` |
| `policy.py` | `SessionPolicy`, `iteration_policy` factory |
| `events.py` | Event dataclasses (`SessionStarted`, `AppendMessage`, etc.) |
| `context.py` | `TeamContext` frozen dataclass with `from_team_dir()` factory |
