# GOTG Refactor Roadmap

## Background

The codebase grew through 17 iterations of feature development, TUI iterations 1–9, streaming stages 1–2, and refactoring phases R1–R6 plus Phase 7 (phase capability table). The original 7-phase roadmap is complete:

| Phase | Status | What it did |
|-------|--------|-------------|
| 1. SessionService | Complete | Headless orchestration — CLI/TUI as thin adapters over shared session.py |
| 2. Schema Versioning | Complete | migration.py with per-schema pipelines, forward-compatible |
| 3. Provider Split | Complete | model/ package with per-provider modules (anthropic.py, openai.py) |
| 4. Per-Agent Model Routing | Complete | Agent-level model overrides, SessionDeps carries resolver |
| 5. CLI Command Split | Complete | commands/ package (run, advance, review, groom, admin) |
| 6. Shared Tool-Loop Helpers | Complete | tools.py extracts shared primitives from engine.py + implementation.py |
| 7. Phase Capability Table | Complete | phases.py — declarative PhaseCapabilities, replaces ~16 string checks |

### Architecture assessment (post-Phase 7)

**Overall: 8.0 / 10** — well-structured with honestly-earned abstractions. Strengths: event-driven engine (pure generator, no I/O), bridge pattern DI (SessionDeps), immutable policies, schema migration, 1378-test suite. Key remaining risks: session.py supermodule (1,278 LOC), SystemExit in lower layers, domain logic leaking into TUI, scattered persistence I/O.

**Scores:**
- Modularity: 7.5 — good adapter split, session.py still too broad
- Extensibility: 7.8 — phase caps + events + bridge pattern are strong foundations
- Data model durability: 7.5 — schema migration is real and forward-safe
- Operational robustness: 7.0 — single-process assumption is fine for CLI; SystemExit leaks are the concern
- Testability: 9.0 — standout strength, bridge pattern preserves mock targets

---

## Phase 8: Split session.py by Bounded Context

**Status: Not started**

session.py is 1,278 LOC with 40+ functions across 8 responsibility areas. Commands already consume it in distinct clusters — this split formalizes those boundaries.

### Target Modules

**session_setup.py** — preparation and validation (~400 LOC)
- `SessionSetup`, `SessionInfra`, `ContinueContext` dataclasses
- `validate_iteration_for_run()`, `build_file_infra()`, `setup_worktrees()`
- `build_session_infra()`, `prepare_session()`, `prepare_grooming_session()`, `prepare_continue()`
- `resolve_layer()`, `run_and_persist()`, `persist_event()`, `apply_and_inject()`
- Consumed by: `commands/run.py`, `commands/groom.py`, `tui/screens/chat.py`

**session_advance.py** — phase transitions and layer progression (~350 LOC)
- `PhaseAdvanceError`, `AdvanceResult` dataclasses
- `validate_advance()`, `advance_phase()`, `validate_next_layer()`, `advance_next_layer()`
- Consumed by: `commands/advance.py`, `tui/screens/chat.py`

**session_review.py** — review, merge, and conflict resolution (~500 LOC)
- `ReviewError`, `BranchReview`, `ReviewResult`, `MergeResult`, `NextLayerResult` dataclasses
- `ConflictFileInfo`, `ConflictInfo`, `AiResolutionResult`, `ResolutionStrategy`
- `load_diffs_for_review()`, `load_review_branches()`, `merge_branches()`
- `load_conflict_info()`, `resolve_conflict_file()`, `ai_resolve_conflict()`, `finalize_merge()`
- Consumed by: `commands/review.py`, `tui/screens/review.py`, `tui/screens/conflict.py`

**session.py** becomes a re-export shim for backward compatibility:
```python
from gotg.session_setup import *    # noqa: F401,F403
from gotg.session_advance import *  # noqa: F401,F403
from gotg.session_review import *   # noqa: F401,F403
```

### Design Considerations
- Re-export shim means zero test modifications — all existing `from gotg.session import X` continue to work
- New code should import from the specific module (`from gotg.session_setup import prepare_session`)
- `SessionSetupError` stays in session_setup.py; `ReviewError` in session_review.py; `PhaseAdvanceError` in session_advance.py
- Cross-module dependency: `advance_phase()` calls `auto_commit_layer_worktrees()` from transitions.py and `create_checkpoint()` from checkpoint.py — those stay external, no circular deps
- Expected blast radius: ~50 import updates in tests if we migrate them, 0 if we keep the re-export shim

---

## Phase 9: SessionDeps Invariant Validation

**Status: Not started**

SessionDeps carries 5 optional callables. The engine assumes certain invariants (e.g., `stream_completion` is set when `policy.streaming` is True) but doesn't validate them. A misconfigured SessionDeps produces an AttributeError at runtime, deep in a tool loop.

### Scope
- Add `SessionDeps.validate(policy: SessionPolicy)` method
- Check invariants:
  - `policy.streaming` requires `deps.stream_completion is not None`
  - `policy.use_implementation_executor` requires `deps.single_completion is not None or deps.stream_completion is not None`
  - `policy.coach_tools` requires `deps.coach_completion is not None`
- Call `deps.validate(policy)` at the top of `run_session()` and `run_implementation()`
- Raise `ValueError` with diagnostic message on violation

### Design Considerations
- Cheap to implement (~20 lines + ~10 test cases)
- High safety payoff: catches misconfiguration at session start, not mid-conversation
- No behavior change for correctly configured sessions
- Validation is on the deps+policy *pair*, not on deps alone (deps are reusable across policies)

---

## Phase 10: Remove SystemExit from Non-Adapter Layers

**Status: Not started**

Lower-layer modules raise `SystemExit` in ~15 sites, which is correct for CLI but crashes TUI worker threads and blocks embedding in other runtimes (API server, test harness).

### Sites to Fix

**config.py** (3 sites):
- `resolve_api_key()` line 65 — env var not found → raise `ConfigError`
- `load_iteration()` line 155 — current ID not found → raise `ConfigError`
- `save_iteration_fields()` line 225 — iteration ID not found → raise `ConfigError`

**context.py** (1 site):
- `TeamContext.from_team_dir()` line 49 — invalid model override → raise `ConfigError`

**model/helpers.py** (1 site):
- `_check_response()` line 16 — HTTP error → raise `ModelError`

**groom.py** (1 site):
- `load_grooming_metadata()` line 99 — session not found → raise `GroomingError`

**scaffold.py** (1 site):
- `init_project()` — init failure → raise `ConfigError`

### New Exception Hierarchy
```python
# gotg/errors.py (new, ~15 lines)
class GotgError(Exception):
    """Base for all gotg domain errors."""

class ConfigError(GotgError):
    """Configuration loading/validation failure."""

class ModelError(GotgError):
    """Model/provider communication failure."""

class GroomingError(GotgError):
    """Grooming session lifecycle error."""
```

### Adapter Mapping
Each command handler (`commands/*.py`) wraps its entry point:
```python
try:
    ctx = TeamContext.from_team_dir(team_dir)
except ConfigError as e:
    print(f"Error: {e}", file=sys.stderr)
    raise SystemExit(1) from e
```

### Design Considerations
- `SessionSetupError`, `PhaseAdvanceError`, `ReviewError` already follow this pattern — they're domain errors caught by commands
- The TUI already catches `SessionSetupError` in worker threads — extending to `ConfigError` is mechanical
- Expected blast radius: ~20 call sites in commands, ~15 test sites that assert SystemExit behavior
- Do NOT change the error messages — just change the exception type
- `GotgError` base class enables `except GotgError` catch-all in adapters if desired

---

## Phase 11: Extract Resume-State Reconstruction

**Status: Not started**

TUI `chat.py:_restore_pause_state()` (~45 lines) reconstructs "what was happening when we last stopped?" by scanning persisted messages. This is domain logic that belongs in session code — a web adapter would need the same logic.

### Scope
- New function in session_setup.py: `reconstruct_session_state(history, metadata) → SessionState`
- `SessionState` dataclass with fields:
  - `pause_reason: PauseReason | None` — phase_complete, coach_question, approvals, or None (running/viewing)
  - `phase_complete_data: dict | None` — phase name if paused on phase complete
  - `ask_pm_data: dict | None` — question + options if paused on coach question
  - `unassigned_task_count: int` — for task status bar
- TUI `_restore_pause_state()` becomes a thin call to `reconstruct_session_state()` + UI rendering
- CLI `cmd_continue()` could also use this to print "Resuming from phase-complete pause..." instead of silently continuing

### Design Considerations
- Only extract the *detection* logic (scanning messages for phase-complete signals, ask_pm data, etc.)
- UI rendering (which ActionBar text to show, which modal to push) stays in chat.py — that's presentation
- The phase gating one-liners (`get_phase_caps_safe(phase).show_task_status_bar`) are fine in chat.py — they're UI visibility decisions, not domain logic
- Expected blast radius: 0 behavior changes — refactoring internal structure only

---

## Phase 12: Thin Persistence Repositories

**Status: Not started**

Persistence I/O is scattered across conversation.py (JSONL), config.py (iteration/team JSON), tasks.py (tasks JSON), approvals.py (approvals JSON), and checkpoint.py. Changing storage format or adding a new adapter requires touching many files.

### Scope
Centralize persistence behind repository interfaces. No locking, no infra change — just consistent access patterns.

**ConversationRepo** (wraps conversation.py):
- `append(msg)`, `append_debug(entry)`, `read_full()`, `read_phase_history()`
- Already partially exists as `ConversationStore` — promote to primary interface

**IterationRepo** (wraps config.py iteration functions):
- `load()`, `save_fields()`, `save_phase()`, `get_current()`
- Already partially exists as `IterationStore` — promote to primary interface

**TaskRepo** (wraps tasks.py I/O):
- `load(path)`, `save(path, tasks)`, `format_summary(layer=None)`
- Currently: `load_tasks_file()`, manual `json.dumps()` writes in transitions.py

**ApprovalRepo** (wraps approvals.py):
- Already well-encapsulated in `ApprovalStore` — no change needed

### Design Considerations
- `ConversationStore` and `IterationStore` already exist from R1 but aren't used consistently — some callers use the store, others call free functions directly
- Phase 1: make stores the *only* interface (deprecate free function usage)
- Phase 2: if needed later, swap implementation (e.g., SQLite) without changing callers
- No new abstractions for checkpoint.py — it's already self-contained
- Expected blast radius: moderate — need to audit every `append_message()`, `read_log()`, `load_tasks_file()` call site

---

## Deferred: Participant Identity Model

**Not scheduled — implement when multi-human collaboration is on the roadmap.**

Current model: `msg["from"]` carries string sentinels ("human", "system", coach name, or agent name). This is adequate for single-PM operation and well-tested across 1378 tests.

### When to do this
- When adding multi-human support (multiple PMs, observers, approvers)
- When adding audit logging that needs typed sender identity
- When adding role-based permissions beyond PM/agent/coach

### What it would look like
```python
class SenderKind(Enum):
    HUMAN = "human"
    AGENT = "agent"
    COACH = "coach"
    SYSTEM = "system"
```

A small typed abstraction that stops further spread of string-sentinel checks. The existing `msg["from"]` field stays (backward compat), but new code uses `SenderKind` for comparisons instead of raw strings.

### Why defer
- Every existing test works with strings
- The string model is simple and readable
- Adding a type layer before there's a concrete multi-human requirement risks over-engineering
- The migration cost grows slowly (~2 new string checks per feature iteration)

---

## Architecture Target (Post-Phase 12)

```
CLI commands/ ──→ session_setup.py ──→ engine.py (generator)
TUI screens/  ──→ session_advance.py ──→ implementation.py (generator)
                  session_review.py        ↓
                        ↓              events.py (typed events)
                  repos (conversation,     ↓
                   iteration, tasks)   model/ (per-provider)
                        ↓
                  phases.py (capability table)
                  errors.py (domain exceptions)
```

- **session_*.py**: bounded contexts for setup, transitions, review
- **engine.py / implementation.py**: stateless generators, yield events, no I/O
- **repos**: centralized persistence semantics, swappable backends
- **model/**: per-provider completion with routing and streaming
- **CLI/TUI**: thin I/O adapters that iterate events and render
- **errors.py**: domain exceptions, mapped to SystemExit only at adapter boundary
