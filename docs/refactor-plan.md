# GOTG Refactor Plan

## Background

The codebase has grown through 17 iterations of feature development. The core
functionality works well but the architecture has accumulated coupling that
makes future features increasingly expensive to add. Two upcoming features
(narrative.md sections 43 and 44) will be significantly harder without
structural changes first.

### Upcoming Features That Drive This Refactor

**Section 43 — Grooming vs. Refinement (Pre-Iteration Exploration)**

The current phase called "grooming" is really refinement — it lives inside an
iteration and feeds into planning. The plan is to:
- Rename the iteration phase from "grooming" to "refinement" (mechanical)
- Add a new `gotg groom "<topic>"` command for freeform pre-iteration
  conversations that live outside iterations (`.team/grooming/<slug>/`)
- Same agents, same conversation format, but no phases, no coach by default,
  no convergence pressure, no artifacts

This needs the conversation engine to work without the iteration lifecycle.
Today that means either duplicating `run_conversation()` or threading more
conditionals through it.

**Section 44 — TUI (Textual)**

A persistent terminal UI wrapping all CLI commands into a live session.
Conversations stream in real-time, approvals appear inline, phase transitions
happen without leaving the interface. This requires:
- Core logic callable without argparse/print/sys.exit
- Event-driven output (engine yields events, UI renders them)
- Eventually async (Textual runs on asyncio)

**Parallel Agent Execution (Future)**

Some phases (pre-code-review, implementation) are inherently parallel — agents
work on independent tasks. The engine should support fan-out/fan-in, where all
agents work concurrently and the coach synthesizes when everyone reports back.
This requires async model calls and a turn router that supports both sequential
and parallel modes.

## Current State Analysis

### File Sizes (as of iteration 17)

| Source File | Lines | Responsibility | Cohesion |
|---|---|---|---|
| cli.py | 1,556 | Everything: argparse, orchestration, business logic, I/O, printing | LOW |
| scaffold.py | 656 | Prompts (~400 lines of text), project init, phase kickoff | MEDIUM |
| worktree.py | 498 | Git worktree operations | HIGH |
| model.py | 349 | LLM API integration (Anthropic, OpenAI, Ollama) | HIGH |
| agent.py | 222 | Agent & coach prompt builders | HIGH |
| approvals.py | 177 | File write approval workflow | HIGH |
| fileguard.py | 174 | File access control & security | HIGH |
| tools.py | 166 | File tool definitions & execution | HIGH |
| config.py | 133 | Config loading/saving | HIGH |
| checkpoint.py | 121 | Iteration state snapshots | HIGH |
| tasks.py | 72 | Task dependency graph, layer computation | HIGH |
| conversation.py | 55 | Conversation log I/O | HIGH |

| Test File | Lines |
|---|---|
| test_cli.py | 4,149 |
| test_agent.py | 903 |
| test_model.py | 730 |
| test_scaffold.py | 615 |
| test_worktree.py | 605 |
| test_config.py | 481 |
| test_fileguard.py | 458 |
| test_checkpoint.py | 331 |
| test_approvals.py | 292 |
| test_tools.py | 260 |
| test_conversation.py | 246 |
| test_tasks.py | 142 |

**Total: ~4,100 source lines, ~9,200 test lines, 650 tests**

### The Problem: cli.py

cli.py is a 1,556-line god file. It contains:

- **Argument parsing** (103 lines) — `main()` with argparse dispatcher
- **Conversation orchestration** (258 lines) — `run_conversation()` with agent
  turns, tool execution, pass detection, coach injection, approval pausing
- **Phase transitions** (221 lines) — `cmd_advance()` with 4 conditional
  branches, each containing config loading, LLM calls, JSON parsing, error
  handling, and file I/O
- **Approval injection** (67 lines) — approval application and denial
  injection interleaved with conversation resumption in `cmd_continue()`
- **Worktree management** (291 lines) — setup, review, merge, layer
  advancement across multiple functions
- **Checkpoint commands** (142 lines) — create, list, restore
- **16 cmd_* functions** — each loading config, validating state, running
  logic, and printing output in one monolithic block

Business logic is tangled with CLI concerns throughout:
- `print()` calls interleaved with logic (20+ in `run_conversation` alone)
- `sys.exit(1)` hardcoded in validation functions
- `args` (argparse namespace) threaded through utility functions
- Path resolution coupled to `find_team_dir()` and hardcoded `.team/` structure
- Config re-loaded from JSON in every `cmd_*` function independently

### What's Clean (Don't Touch)

- **model.py** — Provider-abstracted, clean async migration path via httpx
- **worktree.py** — Long but cohesive, pure git wrapper
- **fileguard.py + approvals.py + tools.py** — Clean pipeline, well-tested
- **tasks.py, checkpoint.py, conversation.py** — Small, focused modules
- **agent.py** — Clean prompt builders, sound structure
- **No circular dependencies** — Dependency graph is acyclic

### Data Flow Problems

All domain data flows as plain dicts with implicit schemas:

```python
# Iteration — shape is implicit, optional fields discovered at runtime
iteration = {
    "id": "iter-1",
    "description": "Build X",
    "status": "in-progress",
    "phase": "grooming",
    "max_turns": 30,
    "current_layer": 0,  # Optional, added in iter 14
}

# Message — heterogeneous, different keys for different message types
msg = {
    "from": "system",
    "iteration": "iter-1",
    "content": "...",
    "pass_turn": True,         # Only on pass notes (iter 17)
    "phase_boundary": True,    # Only on boundaries (iter 16)
    "from_phase": "grooming",  # Only on boundaries
    "to_phase": "planning",    # Only on boundaries
}
```

Config is re-loaded from disk in every `cmd_*` function:
```python
# cmd_run:
model_config = load_model_config(team_dir)
agents = load_agents(team_dir)
coach = load_coach(team_dir)

# cmd_continue (identical):
model_config = load_model_config(team_dir)
agents = load_agents(team_dir)
coach = load_coach(team_dir)

# cmd_advance (again):
coach = load_coach(team_dir)
model_config = load_model_config(team_dir)
```

## Design Decisions

These decisions emerged from discussion between the PM, Claude, and Codex.
Each includes rationale.

### D1: TypedDict over dataclass for domain shapes

**Decision:** Use `TypedDict` (with `NotRequired`) for Iteration, Message,
Task, etc. Keep runtime objects as dicts.

**Rationale:** Dataclasses silently drop unknown fields on round-trip. If
iteration.json gains a new field in a future iteration, a dataclass-based store
would lose it on save unless it carries an `extra: dict`. TypedDict is just a
type annotation over a regular dict — the underlying dict preserves all fields
naturally. The codebase is still evolving rapidly; unknown field preservation
matters.

**What this looks like:**
```python
from typing import TypedDict, NotRequired

class IterationDict(TypedDict):
    id: str
    description: str
    status: str
    phase: str
    max_turns: int
    current_layer: NotRequired[int]
    title: NotRequired[str]

# Functional syntax because "from" is a Python reserved word.
# All code accesses this as msg["from"] (dict subscript), never attribute.
MessageDict = TypedDict("MessageDict", {
    "from": str,
    "iteration": NotRequired[str],
    "content": str,
    "pass_turn": NotRequired[bool],
    "phase_boundary": NotRequired[bool],
    "from_phase": NotRequired[str],
    "to_phase": NotRequired[str],
    "layer": NotRequired[int],
})
```

### D2: Stores + Context, not rich domain objects

**Decision:** Use Store classes for persistence and a TeamContext for bundled
config. Keep business logic in the engine, not on domain objects.

**Rationale:** "Iteration.advance()" would pull LLM calls, file I/O, and
worktree operations into the data object, creating a different kind of god
object. Stores handle persistence (read/write), Context bundles config (loaded
once, passed everywhere), engine handles behavior (what happens when you
advance). Three layers, each simple.

**What this looks like:**
```python
class TeamContext:
    """Bundles all project config. Loaded once per command."""
    project_root: Path
    team_dir: Path
    model_config: ModelConfigDict
    agents: list[AgentDict]
    coach: CoachDict | None
    file_access: FileAccessDict | None
    worktree_config: WorktreeConfigDict | None

class ConversationStore:
    """JSONL-backed conversation persistence."""
    def __init__(self, log_path: Path): ...
    def read_full(self) -> list[MessageDict]: ...
    def read_phase_history(self) -> list[MessageDict]: ...
    def append(self, msg: MessageDict): ...

class IterationStore:
    """iteration.json persistence."""
    def __init__(self, team_dir: Path): ...
    def get_current(self) -> tuple[IterationDict, Path]: ...
    def save_phase(self, id: str, phase: str): ...
    def save_fields(self, id: str, **fields): ...
```

### D3: Sync generator engine, async-ready interfaces

**Decision:** Engine yields events via sync generator (`Iterator[Event]`).
Design interfaces so they can become async later without changing event types.

**Rationale:**
- 650 tests are sync. Async engine means every test needs pytest-asyncio.
- Textual can run sync generators in worker threads (`run_worker()`).
- httpx supports both sync and async — model.py migration path is clean.
- Converting `Iterator[Event]` to `AsyncIterator[Event]` later is mechanical;
  event types don't change.

Going async-first would mean paying the complexity tax now for a feature
(parallel agents) that's several iterations away.

### D4: Events are render-agnostic and storage-agnostic

**Decision:** Engine yields events like `AppendMessage`, `AppendDebug`,
`PauseForApprovals`, `CoachAskedPM`, `PhaseCompleteSignaled`. The engine never
calls `print()`, `append_message()`, or touches the filesystem directly.

**Rationale:** The CLI handler persists events to stores and prints to stdout.
The TUI handler persists to stores and updates widgets. The engine doesn't know
or care which. If the engine contains persistence or rendering calls, the TUI
refactor becomes a second rewrite.

**What this looks like:**
```python
@dataclass
class AppendMessage:
    msg: MessageDict

@dataclass
class AppendDebug:
    entry: dict

@dataclass
class AgentTurnStarted:
    agent_name: str
    turn: int

@dataclass
class PauseForApprovals:
    pending_count: int

@dataclass
class CoachAskedPM:
    question: str

@dataclass
class PhaseCompleteSignaled:
    summary: str
    phase: str

@dataclass
class ConversationComplete:
    total_turns: int

# Engine:
def run_session(ctx, policy, ...) -> Iterator[Event]:
    ...
    yield AgentTurnStarted(agent_name="agent-1", turn=0)
    ...
    yield AppendMessage(msg={...})
    ...

# CLI handler:
for event in run_session(ctx, policy, ...):
    if isinstance(event, AppendMessage):
        store.append(event.msg)
        print(render_message(event.msg))
    elif isinstance(event, PauseForApprovals):
        print(f"Paused: {event.pending_count} pending approval(s).")
        break
    ...
```

### D5: Session policies instead of if/else branching

**Decision:** Define a SessionPolicy that configures the engine's behavior.
IterationSession and GroomingSession build different policies. The engine is
policy-driven, not type-driven.

**Rationale:** `if kind == "iteration"` branching inside the engine recreates
the cli.py problem. A policy object declares: history scope, coach cadence,
kickoff behavior, stop conditions, available tools, artifact injection. The
engine reads the policy; it doesn't know what "grooming" or "iteration" means.

**What this looks like:**
```python
@dataclass
class SessionPolicy:
    history_scope: Literal["phase", "full"]  # phase = after last boundary
    coach_cadence: int | None                # every N agent turns, or None
    inject_kickoff: bool                     # system message at phase start
    stop_on_phase_complete: bool             # coach signal_phase_complete
    stop_on_ask_pm: bool                     # coach ask_pm pauses
    available_agent_tools: list[dict]        # AGENT_TOOLS, maybe FILE_TOOLS
    available_coach_tools: list[dict]        # COACH_TOOLS or subset
    groomed_summary: str | None              # injected into agent prompts
    tasks_summary: str | None                # injected into agent prompts
    diffs_summary: str | None                # injected into agent prompts

# Iteration session:
policy = SessionPolicy(
    history_scope="phase",
    coach_cadence=len(agents),
    inject_kickoff=True,
    stop_on_phase_complete=True,
    stop_on_ask_pm=True,
    available_agent_tools=AGENT_TOOLS + FILE_TOOLS,
    available_coach_tools=COACH_TOOLS,
    ...
)

# Grooming session:
policy = SessionPolicy(
    history_scope="full",
    coach_cadence=None,       # no coach by default
    inject_kickoff=False,
    stop_on_phase_complete=False,
    stop_on_ask_pm=False,
    available_agent_tools=AGENT_TOOLS,  # no file tools
    available_coach_tools=[],
    ...
)
```

### D6: TOML for prompt externalization (bump Python to 3.11+)

**Decision:** Bump minimum Python to 3.11. Use `tomllib` (stdlib) for prompt
loading. Prompts live in `.team/prompts.toml`, copied by `gotg init`, with
fallback to built-in defaults.

**Rationale:** gotg is a developer CLI tool, not a library. Nobody is running
it on a pinned 3.10. The actual dev environment is 3.11.10. Bumping to 3.11
gives `tomllib` in stdlib (zero new dependencies), better error messages, and
`ExceptionGroup`. TOML handles multiline text well and keeps all prompts in one
structured file.

**What the file looks like:**
```toml
[system]
prompt = """
You are a senior software engineer on a small, focused team.
Be direct. No filler, no preamble. Say what you mean.
...
"""

[phases.grooming]
prompt = """
Focus on WHAT to build, not HOW. Requirements, scope, edge cases,
acceptance criteria. Do not discuss implementation approaches.
"""
kickoff = """
--- Phase: grooming ---
Goal: define WHAT to build -- scope, requirements, edge cases.
Do not discuss HOW to build it.

{first_agent}, what's your read on the requirements?
...
"""

[phases.grooming.coach]
facilitation = """
You are facilitating the grooming phase of a software iteration...
"""

[tools.pass_turn]
description = """
Call this when you have nothing new to contribute to the current
discussion...
"""

[extraction.grooming_summary]
prompt = """
You are a senior Agile Coach. Below is a transcript of a team
grooming conversation...
"""
```

**Loading strategy:**
- `gotg init` copies a default `prompts.toml` into `.team/`
- At runtime: load `.team/prompts.toml` if it exists, else load built-in
  default from package data
- Template variables (`{first_agent}`, `{current_layer}`, etc.) resolved at
  runtime via `str.format_map()` with a defaults dict (unknown placeholders
  don't crash)
- Users edit their copy to customize behavior

### D7: Grooming-to-refinement rename is isolated

**Decision:** The rename of the iteration phase from "grooming" to
"refinement" is its own isolated change, separate from all structural
refactoring. It includes backward-compat parsing (accept "grooming" in existing
iteration.json files as an alias for "refinement").

**Rationale:** Mixing a rename with structural refactoring contaminates diffs
and makes review harder. The rename touches phase strings in scaffold.py,
config.py (PHASE_ORDER), coach prompts, phase transition messages, tests, and
documentation. It should be a clean, reviewable commit.

## Refactor Iterations

Each iteration is behavior-preserving: same inputs produce same outputs, all
tests pass before and after. No feature changes mixed with refactoring.

### R1: TypedDict Shapes + TeamContext + Stores

**Goal:** Introduce typed data shapes, a bundled config context, and store
abstractions. Eliminate duplicated config loading across cmd_* functions.
Foundation for everything that follows.

**New files:**
- `src/gotg/types.py` — TypedDict definitions for all domain shapes
- `src/gotg/context.py` — TeamContext class + factory function
- `tests/test_context.py` — TeamContext tests

**Changes to existing files:**
- `conversation.py` — Wrap existing functions in a `ConversationStore` class.
  Keep the free functions as thin wrappers for backward compat during
  transition. The store takes a `log_path` in its constructor and owns all JSONL
  operations: `read_full()`, `read_phase_history()`, `append()`,
  `append_debug()`.
- `config.py` — Add an `IterationStore` class wrapping existing load/save
  functions. `get_current() -> tuple[IterationDict, Path]`,
  `save_phase(id, phase)`, `save_fields(id, **fields)`.
  Optionally wrap `load_model_config`, `load_agents`, etc. into a
  `TeamContext.from_team_dir(team_dir)` factory. Keep free functions for
  backward compat.
- `cli.py` — Update `cmd_run`, `cmd_continue`, `cmd_advance`, and other
  functions to build a `TeamContext` once and pass it through instead of calling
  `load_model_config()`, `load_agents()`, `load_coach()` independently. This is
  a mechanical replacement — behavior doesn't change.
- Type annotations added to function signatures where TypedDicts are used (no
  runtime behavior change).

**What does NOT change:**
- `run_conversation()` internals — still prints, still takes positional args.
  This iteration is about data access, not the conversation loop.
- Test patterns — tests still use plain dicts (which satisfy TypedDict at type
  check time). No test rewrites needed.

**Done criteria:**
- [ ] `types.py` exists with TypedDict definitions for: IterationDict,
  MessageDict, AgentDict, CoachDict, ModelConfigDict, FileAccessDict,
  WorktreeConfigDict, TaskDict
- [ ] `TeamContext` class exists with `from_team_dir(team_dir)` factory
- [ ] `ConversationStore` class wraps existing conversation.py functions
- [ ] `IterationStore` class wraps existing config.py load/save functions
- [ ] `cmd_run` and `cmd_continue` build TeamContext once (not N separate
  load calls)
- [ ] All 667+ tests pass unchanged
- [ ] `mypy --strict` on types.py passes (or at least no errors in new code)

**Risks:**
- Backward-compat wrappers around free functions may look like dead code. Add a
  comment: "# Backward compat — remove after R2 engine migration"
- Don't over-engineer the TeamContext. It's a bag of config, not a service. No
  methods beyond the factory.

---

### R2: Extract Session Engine with Events

**Goal:** Extract `run_conversation()` from cli.py into a new `engine.py`
module that yields events instead of printing. Decompose the 258-line function
into composable pieces. cli.py becomes a thin event handler.

This is the keystone refactor. Everything downstream (session types, TUI, async)
depends on this.

**New files:**
- `src/gotg/engine.py` — Session engine
- `src/gotg/events.py` — Event dataclasses
- `tests/test_engine.py` — Engine tests (assert on yielded events, no capsys)

**engine.py structure:**

```
run_session(ctx, policy, stores, ...) -> Iterator[Event]
  |
  +-- _do_agent_turn(agent, ctx, policy, history) -> Iterator[Event]
  |     Build prompt, call LLM, process result, yield events
  |     Handles: tool execution, pass_turn detection, file ops logging
  |
  +-- _do_coach_turn(coach, ctx, policy, history) -> Iterator[Event]
  |     Build prompt, call LLM, check tool calls, yield events
  |     Handles: signal_phase_complete, ask_pm, empty text fallback
  |
  +-- _should_inject_coach(turn, policy) -> bool
  |     Policy-driven coach cadence check
  |
  +-- _build_tool_executor(ctx, agent, policy) -> Callable
        Constructs the tool executor closure (pass_turn + file tools)
```

**events.py (initial event types):**

```python
@dataclass
class SessionStarted:
    iteration_id: str
    phase: str | None
    agents: list[str]
    coach: str | None
    current_layer: int | None
    max_turns: int

@dataclass
class KickoffInjected:
    msg: MessageDict

@dataclass
class AgentTurnStarted:
    agent_name: str
    turn: int

@dataclass
class AppendMessage:
    msg: MessageDict

@dataclass
class AppendDebug:
    entry: dict

@dataclass
class AgentPassed:
    agent_name: str
    reason: str
    msg: MessageDict  # The system note to log

@dataclass
class FileOperationLogged:
    agent_name: str
    operation: dict
    msg: MessageDict

@dataclass
class CoachTurnStarted:
    turn: int

@dataclass
class PhaseCompleteSignaled:
    summary: str
    phase: str | None

@dataclass
class CoachAskedPM:
    question: str

@dataclass
class PauseForApprovals:
    pending_count: int

@dataclass
class SessionComplete:
    total_turns: int
```

**Changes to cli.py:**

`run_conversation()` is replaced with a handler loop:

```python
def _handle_session_events(events, store, debug_store):
    """CLI event handler: persists + prints."""
    for event in events:
        if isinstance(event, AppendMessage):
            store.append(event.msg)
            print(render_message(event.msg))
            print()
        elif isinstance(event, AppendDebug):
            debug_store.append(event.entry)
        elif isinstance(event, AgentTurnStarted):
            pass  # Could print status line later
        elif isinstance(event, PauseForApprovals):
            print("---")
            print(f"Paused: {event.pending_count} pending approval(s).")
            ...
            break
        elif isinstance(event, PhaseCompleteSignaled):
            print("---")
            _print_phase_complete_message(event.phase)
            break
        elif isinstance(event, CoachAskedPM):
            print("---")
            print(f"Coach asks: {event.question}")
            print("Reply with: gotg continue -m 'your answer'")
            break
        elif isinstance(event, SessionComplete):
            print("---")
            print(f"Conversation complete ({event.total_turns} turns)")
        elif isinstance(event, SessionStarted):
            _print_session_header(event)
```

`cmd_run` and `cmd_continue` build context + policy, call `run_session()`, and
pass events to the handler.

**Migration strategy:**

1. Write `engine.py` and `events.py` as new modules
2. Write `test_engine.py` testing the engine directly (no capsys, no CLI)
3. Rewrite `run_conversation()` in cli.py to delegate to the engine
4. Verify existing cli tests still pass (they test the same behavior, just
   through the handler now)
5. Optionally: migrate some test_cli.py tests to test_engine.py where they're
   testing engine logic rather than CLI behavior

**What moves out of cli.py:**
- Agent turn logic (prompt building dispatch, LLM call, result processing)
- Coach injection logic (cadence check, prompt building, tool call processing)
- Pass_turn detection and system note creation
- File operation logging
- Kickoff injection
- Approval pause detection

**What stays in cli.py:**
- Argparse setup and `main()`
- `cmd_*` functions as thin wrappers
- The event handler (printing, session header, phase complete messages)
- Config loading and TeamContext construction
- Checkpoint auto-creation

**Done criteria:**
- [ ] `engine.py` exists with `run_session()` yielding events
- [ ] `events.py` exists with all event dataclasses
- [ ] `run_session` is decomposed into `_do_agent_turn`, `_do_coach_turn`, etc.
- [ ] Engine has no `print()`, no `sys.exit()`, no direct JSONL/artifact writes;
  side effects only through injected dependencies (tool executor, approval store)
- [ ] `test_engine.py` has tests for: agent turn events, coach turn events,
  pass_turn events, phase_complete signal, ask_pm signal, approval pause,
  max_turns stop, kickoff injection
- [ ] cli.py's `run_conversation()` delegates to engine (or is removed)
- [ ] All 650+ tests pass (existing CLI tests work through the handler)
- [ ] cli.py is significantly shorter (target: under 1,000 lines)

**Risks:**
- This is the largest single change. The decomposition of `run_conversation`
  into 4 sub-functions plus an event handler is the hardest part.
- Existing test_cli.py tests mock `agentic_completion` and `chat_completion`
  and check capsys output. After migration, these tests still work (the mocks
  are still called, the handler still prints), but the mock targets may change
  if the engine imports differently. Plan for mock target updates.
- The event handler must handle all events — a missed event type means silent
  data loss. Use an exhaustive match or a fallback warning.

---

### R3: Decompose cmd_advance() into Composable Transitions

**Goal:** Extract the 221-line `cmd_advance()` into composable transition step
functions. Each phase transition's coach LLM call becomes a standalone function
that takes inputs and returns outputs.

**New file:**
- `src/gotg/transitions.py` — Phase transition logic
- `tests/test_transitions.py` — Transition function tests

**transitions.py functions:**

```python
def extract_grooming_summary(
    history: list[MessageDict],
    model_config: ModelConfigDict,
    coach_name: str,
) -> str:
    """One-shot LLM call to summarize grooming conversation.
    Returns markdown summary text."""

def extract_tasks(
    history: list[MessageDict],
    model_config: ModelConfigDict,
    coach_name: str,
) -> tuple[list[TaskDict] | None, str | None]:
    """One-shot LLM call to extract tasks from planning conversation.
    Returns (parsed_tasks, raw_text_on_failure)."""

def extract_task_notes(
    history: list[MessageDict],
    tasks: list[TaskDict],
    model_config: ModelConfigDict,
    coach_name: str,
) -> tuple[dict[str, str] | None, str | None]:
    """One-shot LLM call to extract implementation notes.
    Returns (notes_map, raw_text_on_failure)."""

def auto_commit_layer_worktrees(
    project_root: Path,
    layer: int,
) -> list[str]:
    """Commit all dirty worktrees for the given layer.
    Returns list of commit messages."""

def build_transition_messages(
    from_phase: str,
    to_phase: str,
    iteration_id: str,
    coach_ran: bool,
    tasks_written: bool,
) -> tuple[MessageDict, MessageDict]:
    """Build boundary marker and transition message."""
```

**Changes to cli.py:**

`cmd_advance()` becomes a thin orchestrator:

```python
def cmd_advance(args):
    ctx = TeamContext.from_team_dir(...)
    iteration, iter_dir = ctx.iteration_store.get_current()
    # ... validation ...

    from gotg.transitions import (
        extract_grooming_summary, extract_tasks,
        extract_task_notes, auto_commit_layer_worktrees,
        build_transition_messages,
    )

    if current_phase == "grooming" and ctx.coach:
        summary = extract_grooming_summary(history, ctx.model_config, ctx.coach["name"])
        (iter_dir / "groomed.md").write_text(summary + "\n")
        print(f"Wrote groomed.md")

    # ... etc: each branch is 3-5 lines instead of 30-50 ...
```

**Done criteria:**
- [ ] `transitions.py` exists with the 5 functions listed above
- [ ] Each function is pure-ish: takes inputs, returns outputs, no print/exit
- [ ] `test_transitions.py` tests each function independently (mock LLM calls)
- [ ] `cmd_advance()` is under 80 lines (currently 221)
- [ ] All existing advance tests pass unchanged
- [ ] Extraction tests (grooming summary, tasks, notes) can be tested without
  argparse/CLI scaffolding

**Risks:**
- Low risk — these functions already exist as blocks within cmd_advance. The
  extraction is mostly copy-paste with interface cleanup.
- The JSON-stripping logic (markdown code fences) should go in a shared utility
  rather than being duplicated.

---

### R4: Prompt Externalization (TOML)

**Goal:** Move all prompt text from scaffold.py into a `.team/prompts.toml`
file that users can customize. scaffold.py drops from ~656 to ~250 lines.

**New files:**
- `src/gotg/prompts.py` — Prompt loading, template resolution, defaults
- `src/gotg/data/default_prompts.toml` — Built-in default prompts (package data)
- `tests/test_prompts.py` — Prompt loading and template tests

**Changes to existing files:**
- `scaffold.py` — Remove all prompt constants (DEFAULT_SYSTEM_PROMPT,
  PHASE_PROMPTS, COACH_FACILITATION_PROMPTS, COACH_GROOMING_PROMPT,
  COACH_PLANNING_PROMPT, COACH_NOTES_EXTRACTION_PROMPT, PHASE_KICKOFF_MESSAGES,
  tool descriptions in AGENT_TOOLS and COACH_TOOLS). Replace with imports from
  `prompts.py`. Keep `init_project()`, `_ensure_gitignore()`, and
  non-prompt functions.
- `scaffold.py init_project()` — Copy default_prompts.toml to
  `.team/prompts.toml` during init
- `agent.py` — Import prompts from `prompts.py` instead of `scaffold.py`
- `pyproject.toml` — Bump `python_requires` to `>=3.11`. Add
  `src/gotg/data/` to package data.

**prompts.py structure:**

```python
import tomllib
from pathlib import Path

_BUILTIN_PATH = Path(__file__).parent / "data" / "default_prompts.toml"
_cache: dict | None = None

def load_prompts(team_dir: Path | None = None) -> dict:
    """Load prompts. .team/prompts.toml if it exists, else built-in defaults."""
    global _cache
    if _cache is not None:
        return _cache
    if team_dir:
        custom = team_dir / "prompts.toml"
        if custom.exists():
            with open(custom, "rb") as f:
                _cache = tomllib.load(f)
                return _cache
    with open(_BUILTIN_PATH, "rb") as f:
        _cache = tomllib.load(f)
        return _cache

def get_system_prompt(prompts: dict) -> str:
    return prompts["system"]["prompt"]

def get_phase_prompt(prompts: dict, phase: str) -> str | None:
    return prompts.get("phases", {}).get(phase, {}).get("prompt")

def get_phase_kickoff(prompts: dict, phase: str) -> str | None:
    return prompts.get("phases", {}).get(phase, {}).get("kickoff")

def get_coach_facilitation(prompts: dict, phase: str) -> str | None:
    return prompts.get("phases", {}).get(phase, {}).get("coach", {}).get("facilitation")

def resolve_template(template: str, **kwargs) -> str:
    """Safe template resolution — unknown placeholders pass through."""
    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"
    return template.format_map(SafeDict(**kwargs))
```

**TOML structure for default_prompts.toml:**

```toml
[system]
prompt = """
You are a senior software engineer on a small, focused team.
...
"""

[phases.grooming]
prompt = """
Focus on WHAT to build, not HOW...
"""
kickoff = """
--- Phase: grooming ---
Goal: define WHAT to build...
{first_agent}, what's your read on the requirements?
The coach will facilitate from here.
"""

[phases.grooming.coach]
facilitation = """
You are facilitating the grooming phase...
"""

[phases.planning]
prompt = "..."
kickoff = "..."

[phases.planning.coach]
facilitation = "..."

# ... etc for all 5 phases ...

[extraction.grooming_summary]
prompt = """
You are a senior Agile Coach. Below is a transcript...
"""

[extraction.task_extraction]
prompt = """
You are a senior Agile Coach. Below is a transcript of a team
planning conversation...
"""

[extraction.notes_extraction]
prompt = """
Extract implementation notes from this pre-code-review transcript...
{tasks_json}
{conversation}
"""

[tools.pass_turn]
description = """
Call this when you have nothing new to contribute...
"""

[tools.signal_phase_complete]
description = "..."

[tools.ask_pm]
description = "..."

[tools.file_read]
description = "..."

[tools.file_write]
description = "..."

[tools.file_list]
description = "..."
```

**Done criteria:**
- [ ] `prompts.py` exists with load, get, and template resolution functions
- [ ] `data/default_prompts.toml` contains all current prompt text (verified
  identical to current Python constants)
- [ ] `gotg init` copies prompts.toml to `.team/`
- [ ] scaffold.py no longer contains prompt text (imports from prompts.py)
- [ ] agent.py uses prompts from prompts.py
- [ ] pyproject.toml requires Python >=3.11
- [ ] All tests pass — prompt content is identical, just sourced differently
- [ ] Editing `.team/prompts.toml` changes agent behavior (manual verification)

**Risks:**
- Template variable names must be documented in the TOML file (comments) so
  users know what's available per section.
- The `_cache` global needs to be cleared in tests (add a `_clear_cache()`
  function or use a non-global approach).
- TOML multiline strings use `"""` — if a prompt contains literal `"""`, it
  needs escaping. Unlikely but worth noting.

---

### R5: Session Policies

**Goal:** Introduce SessionPolicy to configure engine behavior. This makes the
engine policy-driven rather than hardcoded, enabling different session types
(iteration conversations, freeform grooming) without engine branching.

**New file:**
- `src/gotg/policy.py` — SessionPolicy dataclass + factory functions
- `tests/test_policy.py` — Policy construction tests

**policy.py:**

```python
@dataclass
class SessionPolicy:
    history_scope: Literal["phase", "full"]
    coach_cadence: int | None       # every N agent turns, or None (no coach)
    inject_kickoff: bool
    stop_on_phase_complete: bool
    stop_on_ask_pm: bool
    agent_tools: list[dict]
    coach_tools: list[dict]
    groomed_summary: str | None
    tasks_summary: str | None
    diffs_summary: str | None

def iteration_policy(
    ctx: TeamContext,
    iteration: IterationDict,
    iter_dir: Path,
    fileguard=None,
    worktree_map=None,
) -> SessionPolicy:
    """Build policy for an iteration conversation."""
    ...

def grooming_policy(
    ctx: TeamContext,
    topic: str,
) -> SessionPolicy:
    """Build policy for a freeform grooming conversation."""
    ...
```

**Changes to engine.py:**
- `run_session()` takes a `SessionPolicy` instead of individual parameters
  (groomed_summary, tasks_summary, diffs_summary, etc.)
- Coach cadence check uses `policy.coach_cadence` instead of hardcoded
  `turn % num_agents == 0`
- History loading uses `policy.history_scope`
- Tool lists come from `policy.agent_tools` and `policy.coach_tools`
- Stop conditions check `policy.stop_on_phase_complete` and
  `policy.stop_on_ask_pm`

**Changes to cli.py:**
- `cmd_run` and `cmd_continue` build a policy via `iteration_policy()` and pass
  it to the engine
- No more passing 5+ optional parameters to `run_conversation`

**Done criteria:**
- [ ] `SessionPolicy` dataclass exists with all fields
- [ ] `iteration_policy()` produces the same configuration as current hardcoded
  behavior
- [ ] Engine uses policy fields instead of hardcoded values
- [ ] All tests pass — behavior is identical
- [ ] `grooming_policy()` exists (even if `gotg groom` command doesn't yet)

**Risks:**
- Policy construction must exactly reproduce current behavior. Any difference
  (e.g., wrong coach cadence, missing tool) breaks existing conversations.
- The transition from positional parameters to a policy object touches many
  test mocks. Plan for mock updates similar to the iter-17 migration.

---

### R6: Grooming-to-Refinement Rename

**Goal:** Rename the iteration phase from "grooming" to "refinement." Isolated,
mechanical change with backward compatibility.

**Prerequisites:** R4 (prompts externalized — rename is mostly a TOML edit)

**Changes:**
- `prompts.toml` — Rename `[phases.grooming]` to `[phases.refinement]`
- `config.py` — Update `PHASE_ORDER` (grooming → refinement)
- `config.py` — Add backward-compat parsing: when loading iteration.json, if
  `phase == "grooming"`, silently treat as `"refinement"`
- `scaffold.py` — Update any remaining references
- `cli.py` — Update phase string references in advance logic, messages
- `agent.py` — Update if any phase-specific logic references "grooming"
- Tests — Update phase strings throughout
- Documentation — README.md, narrative.md references

**Done criteria:**
- [ ] `PHASE_ORDER` uses "refinement" instead of "grooming"
- [ ] Existing iteration.json files with `"phase": "grooming"` still work
  (loaded as "refinement")
- [ ] All prompts reference "refinement" where they previously said "grooming"
- [ ] All tests pass
- [ ] New iterations start with `"phase": "refinement"`

**Risks:**
- Backward compat is the main concern. Existing projects have iteration.json
  files, conversation logs with "grooming" in phase transition messages,
  checkpoints with "grooming" phase. These must all continue to work.
- The rename should NOT touch conversation.jsonl content — historical messages
  saying "grooming" are historical facts, not broken data.

---

## Sequencing and Dependencies

```
R1: Types + Context + Stores
 |
 +---> R2: Session Engine with Events
 |      |
 |      +---> R5: Session Policies
 |
 +---> R3: Decompose cmd_advance()
 |
 +---> R4: Prompt Externalization (TOML)
         |
         +---> R6: Rename (grooming → refinement)
```

R1 is the foundation. R2, R3, and R4 can proceed in parallel after R1 (they
don't depend on each other). R5 depends on R2. R6 depends on R4.

**Recommended execution order:**
1. R1 (foundation — unblocks everything)
2. R3 (lowest risk, quick win, reduces cmd_advance complexity)
3. R4 (independent, reduces scaffold.py, enables R6)
4. R2 (largest change, keystone for TUI/async/grooming)
5. R5 (builds on R2, enables section 43)
6. R6 (isolated rename after prompts are externalized)

R3 before R2 is intentional: decomposing cmd_advance is simpler and reduces
the surface area that R2 needs to touch. R4 before R2 means prompt loading is
already clean when the engine needs prompts.

## Post-Refactor: Feature Readiness

After R1-R6, the codebase is ready for:

**Section 43 (gotg groom):**
- Add `cmd_groom` to cli.py (thin wrapper)
- Build a `grooming_policy()` (already stubbed in R5)
- Create `.team/grooming/<slug>/` directory structure
- Reuse the engine with a different policy
- Estimated: 1 iteration

**Section 44 (TUI):**
- Add Textual dependency
- Build TUI app that constructs TeamContext and iterates engine events
- Panels subscribe to events via Textual's reactive system
- Engine runs in a worker thread (sync generator)
- Estimated: 2-3 iterations

**Parallel agents:**
- Convert `Iterator[Event]` to `AsyncIterator[Event]` in engine
- Add async model calls to model.py (httpx.AsyncClient)
- Add parallel turn mode to SessionPolicy
- Engine fan-out: concurrent agent turns, coach synthesizes
- Estimated: 2 iterations

## Rake Warnings

Things that will bite us if we're not careful:

1. **Don't extract run_conversation as-is.** Extract it as a decomposed engine
   with events. Otherwise the TUI refactor is a second rewrite.

2. **Don't let the engine touch the filesystem.** It yields events; the handler
   persists. Mixing persistence into the engine defeats the purpose.

3. **Don't change behavior during refactoring.** Each R-iteration must be
   behavior-preserving. The test suite is the proof. If a test needs to change,
   the behavior changed — understand why before proceeding.

4. **Mock target updates.** R2 will change where `agentic_completion` and
   `chat_completion` are imported. Tests that patch `gotg.cli.agentic_completion`
   may need to patch `gotg.engine.agentic_completion` instead. Plan for this
   systematically (like the iter-17 migration), not test-by-test.

5. **TypedDict and `from` key.** Python's `from` is a reserved word. The
   message dict uses `"from"` as a key. TypedDict can handle this with
   `from_` as the Python-side name, but it requires careful mapping. Consider
   just using the key `"from"` and accessing via `msg["from"]` rather than
   attribute access.

6. **Prompt TOML escaping.** Prompts contain curly braces for template
   variables (`{current_layer}`). TOML doesn't interpret these, but
   `str.format_map()` does. Make sure the `SafeDict` fallback works for all
   prompts, and add a test that renders every prompt with empty kwargs to catch
   any stray format strings.

7. **ConversationStore and append ordering.** The engine yields AppendMessage
   events; the handler persists them. If the handler crashes between two
   appends, the log is inconsistent. This is the same risk as today (print
   could crash between two append_message calls), so it's not a regression,
   but worth noting for the TUI where the event loop is more complex.

8. **Session policy must exactly reproduce current behavior.** Any difference
   in coach cadence, tool availability, or stop conditions will change
   conversation dynamics. Test by running the same manual smoke test
   (calculator grooming) and comparing output quality.
