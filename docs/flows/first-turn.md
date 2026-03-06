# Flow: First Run — From `gotg run` Through the First Agent Turn

Assumes `gotg init` and `gotg new` have been run. The iteration is in
`phase: "refinement"` with an empty conversation log.

## Entry

`gotg run` → `commands/run.py::cmd_run`

## Step 1: Load config

```python
# commands/run.py
ctx = TeamContext.from_team_dir(team_dir)
```

`TeamContext.from_team_dir()` (`context.py`) reads all config in one shot:
- `team.json` → agents, coach, model config, file_access, worktree settings
- Resolves `$ANTHROPIC_API_KEY` from `.env` or environment
- Builds `model_resolver` for per-agent model overrides
- Returns frozen `TeamContext` dataclass

## Step 2: Get current iteration

```python
iteration, iter_dir = ctx.iteration_store.get_current()
```

Reads `iteration.json`, finds the entry matching `current` pointer.
Returns `{"id": "iter-1", "phase": "refinement", ...}` and
`.team/iterations/iter-1/`.

## Step 3: Validate

```python
validate_iteration_for_run(iteration, iter_dir, ctx.agents)
```

`session_setup.py::validate_iteration_for_run` checks:
- Phase requires tasks.json? (implementation, code-review need it — refinement doesn't)
- At least 2 agents configured?
- Implementation tasks assigned to known agents?

For a fresh refinement iteration, this passes with no issues.

## Step 4: Build infrastructure

```python
infra = build_session_infra(ctx, iteration, iter_dir)
```

`session_setup.py::build_session_infra` returns `SessionInfra`:
- `fileguard` — FileGuard from file_access config (or None)
- `approval_store` — ApprovalStore if approvals enabled (or None)
- `worktree_map` — None (worktrees only created for implementation/code-review)
- `diffs_summary` — None (only for code-review)
- `streaming` — True/False from team.json
- `warnings` — any setup warnings

## Step 5: Enter pause loop

```python
pause_ctrl = _make_pause_controller()  # PauseController if TTY, else None

while True:
    result = _cli.run_conversation(
        iter_dir, ctx.agents, iteration, ctx.model_config,
        coach=ctx.coach, fileguard=infra.fileguard, ...,
        pause_controller=pause_ctrl,
    )
    if result != "paused":
        break
    # ... handle pause (see pause-and-resume.md)
```

## Step 6: Bridge to engine — `cli.py::run_conversation`

This is the core bridge. It:

1. **Builds `SessionDeps`** — wires model functions from `gotg.model`:
   ```python
   deps = SessionDeps(
       agent_completion=agentic_completion,    # multi-round tool loop
       coach_completion=chat_completion,       # single-round chat
       single_completion=raw_completion,       # implementation tool loop
       stream_completion=raw_completion_stream, # streaming variant
       model_resolver=model_resolver,
   )
   ```
   These are module-level imports — the bridge pattern lets tests mock them
   at `gotg.model.agentic_completion` without touching engine.py.

2. **Calls `prepare_session`** (`session_setup.py`):
   - Reads conversation history (empty on first run)
   - Builds `SessionPolicy` via `iteration_policy()`:
     - `max_turns` from iteration config (default 30)
     - `agent_tools` — pass_turn + file tools (if fileguard configured)
     - `coach_tools` — signal_phase_complete + ask_pm
     - `coach_cadence` — coach speaks every N agent turns (N = agent count)
     - `kickoff_text` — phase kickoff message (computed by `scaffold.py`)
     - `refinement_summary`, `tasks_summary` — None (first phase, no artifacts yet)
   - Returns `SessionSetup` with policy, deps, history, routing flags

3. **Wires cancel_check** from pause controller onto setup

4. **Calls `run_and_persist(setup)`** → event generator

5. **Passes events to `handle_console_events()`** → prints to terminal

## Step 7: Persistence — `session_setup.py::run_and_persist`

Wraps the engine generator:

```python
for event in run_session(agents, iteration, model_config, deps, history, policy):
    persist_event(event, store=conv_store)  # write to conversation.jsonl
    yield event                              # pass through to console handler
```

Key: events are **persisted before yielded**. If the process crashes mid-session,
all completed turns are on disk.

## Step 8: Engine — `engine.py::run_session`

The generator starts:

### 8a. Yield `SessionStarted`

```python
yield SessionStarted(
    iteration_id="iter-1", description="Build the login page",
    phase="refinement", agents=["agent-1", "agent-2"],
    coach="coach", turn=0, max_turns=30, ...
)
```

`console_events.py` prints the session header:
```
Iteration: iter-1
Phase: refinement
...
Turns: 0/30
---
```

### 8b. Inject kickoff message

Policy has `kickoff_text` (first run, empty history). Engine yields:
```python
yield AppendMessage({"from": "system", "content": "--- Phase: refinement ---\n..."})
```

This gets persisted to conversation.jsonl and printed to terminal.

### 8c. First agent turn (turn=0)

**Select agent**: `agents[turn % num_agents]` → `agent-1`

**Build prompt** (`agent.py::build_prompt`):
- System message assembled from parts:
  - Base system prompt (from TOML)
  - `"Your name is agent-1."`
  - Teammate list: `"Your teammates are: agent-2 (Software Engineer)."`
  - Coach awareness text (since coach exists)
  - Message addressing conventions (@name)
  - `"Current task: Build the login page"`
  - Phase-specific guidance (refinement prompt from TOML)
  - FILE ACCESS info (if fileguard configured)
- History is empty → adds: `"The task is: Build the login page. What are your initial thoughts?"`
- Result: `[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]`

**Debug log**: Engine yields `AppendDebug` with the full prompt (written to debug.jsonl).

**Build tools** (`engine.py::build_tool_executor`):
- Tool list: `[pass_turn, file_read, file_write, file_list, ...]` (from policy)
- Tool executor: closure that routes calls through FileGuard

**Call LLM**:
- Streaming: `deps.stream_completion(...)` → yields `TextDelta` chunks → `AgentTurnComplete`
- Non-streaming: `deps.agent_completion(...)` → returns `{"content": "...", "operations": [...]}`

**Process result** (`engine.py::_process_agent_result`):
- If agent used tools → yield `AppendMessage` for each tool operation
- If agent called `pass_turn` → yield system pass message
- Otherwise → yield agent's response as `AppendMessage`:
  ```python
  yield AppendMessage({"from": "agent-1", "iteration": "iter-1",
                        "content": "I think we should start with..."})
  ```

**Persist + render**: `run_and_persist` writes to JSONL, `handle_console_events` prints:
```
agent-1:
I think we should start with...
```

### 8d. What happens next

- `turn` increments to 1
- `agents[1 % 2]` → `agent-2` gets the next turn
- agent-2's prompt includes agent-1's message in the history
- After every full rotation (turn % coach_cadence == 0), coach gets a turn
- Loop continues until `max_turns` or a stopping condition (phase_complete, ask_pm, approvals)

## Module boundary diagram

```
cmd_run (commands/run.py)
  │
  ├─ TeamContext.from_team_dir()     (context.py)
  ├─ validate_iteration_for_run()    (session_setup.py)
  ├─ build_session_infra()           (session_setup.py)
  │
  └─ run_conversation()              (cli.py)
       │
       ├─ SessionDeps(model funcs)   (engine.py)
       ├─ prepare_session()          (session_setup.py)
       │    ├─ read history          (conversation.py)
       │    ├─ iteration_policy()    (policy.py)
       │    └─ → SessionSetup
       │
       ├─ run_and_persist(setup)     (session_setup.py)
       │    │
       │    └─ run_session()         (engine.py)
       │         ├─ build_prompt()   (agent.py)
       │         ├─ LLM call         (model/)
       │         └─ yield events     (events.py)
       │
       └─ handle_console_events()    (console_events.py)
            └─ render_message()      (conversation.py)
```

## Files touched

| Module | What it does in this flow |
|--------|--------------------------|
| `commands/run.py` | CLI entry, validation, pause loop |
| `context.py` | Loads all team config into `TeamContext` |
| `session_setup.py` | Validates iteration, builds infra, prepares session, persists events |
| `cli.py` | Bridges deps + setup → engine → console handler |
| `policy.py` | Computes `SessionPolicy` (tools, turns, coach cadence, kickoff) |
| `engine.py` | Core loop — builds prompts, calls LLM, yields events |
| `agent.py` | Assembles system prompt + history for agent's LLM call |
| `model/` | LLM API dispatch (Anthropic, OpenAI, Ollama) |
| `console_events.py` | Renders events to terminal |
| `conversation.py` | JSONL read/write for conversation log |
| `events.py` | Event dataclasses (`SessionStarted`, `AppendMessage`, etc.) |
| `scaffold.py` | Phase kickoff message formatting |
