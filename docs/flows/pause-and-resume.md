# Flow: Interactive Pause & Resume

Traces how users pause sessions, inject messages, and resume.

## CLI Pause

1. User presses Ctrl+C during session
2. `PauseController._handle_sigint()` sets `_pause_requested` flag, prints hint to stderr
3. Double Ctrl+C within 2s: restores `SIG_DFL` and re-raises SIGINT (exit 130)

### Discussion Pause
- `console_events.py::handle_console_events`: after each `AppendMessage`, checks if it is a turn boundary (agent message or `pass_turn`, but NOT system/human/coach) AND pause flag is set
- Deferred: sets `_pause_pending = True` and continues to next event
- If next event is a terminal event (`PauseForApprovals`, `PhaseCompleteSignaled`, `CoachAskedPM`, `IterationsProposed`, `SessionComplete`, `LayerComplete`, `UserPauseComplete`), terminal event wins and pause is cancelled
- Otherwise returns `"paused"` to the pause loop

### Implementation Pause
- `implementation.py`: `cancel_check()` fires at top of agent dispatch loop
- Only after first agent has been dispatched (`dispatched_agents > 0`)
- Current agent completes all tool rounds before pause
- Yields `UserPauseComplete` event with dispatch count

## Pause Loop (`commands/run.py`)

```
while True:
    result = _cli.run_conversation(...)
    if result != "paused" or pause_ctrl is None:
        break
    user_input = prompt_for_interjection(...)
    if None:                              # Ctrl+C or EOF -> stop
        write user_pause marker, break
    if RESUME:                            # Enter -> resume without message
        reset controller, loop
    else:                                 # typed text -> inject and resume
        append human message, reset, loop
```

The same pause loop structure is used in `cmd_run`, `cmd_continue`, `cmd_explore_start`, and `cmd_explore_continue`.

## `prompt_for_interjection` (`pause.py`)

- Prints pause prompt with resume hint command
- Returns one of three values:
  - `str`: user typed a message to inject
  - `RESUME` sentinel: user pressed Enter (resume without message)
  - `None`: user pressed Ctrl+C or EOF (stop session)

## Persistence

- **Pause marker**: `{"from": "system", "user_pause": True}` appended to conversation log on stop
- **On `gotg continue`**: `cmd_continue` scans phase history for unresolved `user_pause` marker (no `user_pause_resolved` after it, no human/agent message after it)
- **Resolution**: after first successful `run_conversation()` call, writes `{"user_pause_resolved": True}` to log
- **Prompt filtering**: both marker types excluded from agent/coach prompts by `agent.py`

## TUI Pause

- ChatScreen has Pause/Resume button that toggles with session state
- Press Pause or Esc while RUNNING sets `_cancel_requested = True`
- Same turn-boundary / cancel_check logic applies through the engine
- State machine: VIEWING -> RUNNING -> PAUSED -> RUNNING (or COMPLETE)
- `on_screen_resume` handles state refresh when returning from pushed screens

## Files Touched

| Module | Responsibility |
|--------|---------------|
| `pause.py` | `PauseController` (SIGINT handler), `prompt_for_interjection`, `RESUME` sentinel |
| `console_events.py` | Turn boundary detection via `_is_turn_boundary`, deferred pause logic |
| `implementation.py` | `cancel_check` between agent dispatches, `UserPauseComplete` event |
| `commands/run.py` | Pause loop in `cmd_run`/`cmd_continue`, marker write/consume |
| `commands/explore.py` | Pause loop in `cmd_explore_start`/`cmd_explore_continue` |
| `agent.py` | Filters `user_pause`/`user_pause_resolved` markers from prompts |
| `session_types.py` | `PauseReason` enum, `reconstruct_resume_state` |
| `events.py` | `UserPauseComplete` event dataclass |
| `tui/screens/chat.py` | Button toggle, `_cancel_requested`, state machine |
