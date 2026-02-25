# GOTG Refactor Roadmap

## Background

The codebase grew through 17 iterations of feature development plus R1–R6 refactoring rounds (TypedDict shapes, session engine, composable transitions, prompt externalization, session policies, grooming→refinement rename). The R1–R6 work established clean architectural layers but left orchestration logic duplicated across CLI, TUI, and grooming code paths. Two planning conversations (with Codex and Claude Code, Feb 2025) established this 7-phase roadmap to complete the structural cleanup.

## Phase 1: SessionService — Headless Orchestration

**Status: Complete (3 sub-phases)**

CLI and TUI become thin I/O adapters over a shared session service that owns persistence and yields domain events.

### Design Principles
- **Persist-then-emit invariant**: Service persists state first, then yields events — "committed events" only, not pre-commit intents
- **Bridge pattern**: SessionDeps carries model callables from CLI/TUI module-level imports into engine, preserving all mock targets
- **Duck-typed ctx**: `build_session_infra` takes `ctx` as `Any` to avoid import cycles with TeamContext
- **Adapters only**: parse input → call service → iterate events → render

### Sub-phase 1: Core Session Abstractions
- `SessionSetup` dataclass — everything needed to run a session
- `prepare_session()` — unified setup builder (iteration_policy + history + phase routing)
- `run_and_persist()` — unified session runner with event persistence (persist-then-emit)
- `persist_event()` — append AppendMessage/AppendDebug to disk
- CLI `run_conversation()` reduced to: build deps → prepare_session → _handle_cli_events
- TUI `_run_engine()` uses same `run_and_persist()` for its event loop

### Sub-phase 2: Infrastructure Consolidation
- Deleted backward-compat wrappers (`_run_discussion_phase`, `_run_implementation_phase`)
- Migrated 14 test callers to use `_handle_cli_events()` or `run_and_persist()` directly
- `build_session_infra()` consolidates: build_file_infra + setup_worktrees + load_diffs_for_review + load_streaming_config
- `SessionInfra` dataclass holds all infrastructure state
- `cmd_run`, `cmd_continue`, TUI `_run_engine` all use `build_session_infra()`

### Sub-phase 3: Final Deduplication
- `prepare_grooming_session()` — parallel to prepare_session for grooming conversations
- Consolidated grooming event handler into parameterized `_handle_cli_events()`
- `prepare_continue()` — extracts approval injection + turn counting for CLI/TUI reuse
- Deleted `refresh_history()` dead code

### Key Artifacts
- `src/gotg/session.py` — shared session helpers (~1200 lines)
- `src/gotg/events.py` — 10+ event dataclasses
- `src/gotg/engine.py` — SessionDeps, run_session generator
- `src/gotg/implementation.py` — run_implementation generator

---

## Phase 2: Schema Versioning

**Status: Not started**

Add version fields to on-disk schemas + in-memory migration on load. Prevents breakage when adding fields to iteration.json, tasks.json, team.json, grooming.json.

### Scope
- Add `"schema_version": 1` to each JSON schema
- Migration functions: `migrate_iteration(data) → data` that normalize old formats
- Apply on load (config.py load functions), never rewrite files on migration
- Start with iteration.json (already has `_normalize_phase()` as precedent)
- Extend to tasks.json, team.json, grooming.json

### Design Considerations
- In-memory only — don't rewrite user files on load
- Forward-compatible: unknown fields are preserved (no strict validation)
- Migration is a pipeline: v0 → v1 → v2 (each step is a small function)
- `_normalize_phase()` in config.py is the existing pattern to generalize

---

## Phase 3: Provider Split

**Status: Not started**

Split `model.py` into a `model/` package with per-provider modules.

### Scope
- `model/__init__.py` — public API (chat_completion, agentic_completion, raw_completion, raw_completion_stream)
- `model/anthropic.py` — Anthropic-specific completion paths + prompt caching
- `model/openai.py` — OpenAI-compatible completion paths (also used by Ollama)
- `model/types.py` — CompletionRound, StreamingResult, shared types
- `model/routing.py` — provider dispatch logic

### Design Considerations
- Zero change to public API — all existing imports from `gotg.model` still work
- `__init__.py` re-exports everything
- Provider dispatch stays in routing.py (currently the `if provider == "anthropic"` branches)
- Prompt caching logic stays in anthropic.py

---

## Phase 4: Per-Agent Model Routing

**Status: Not started**

Allow different agents to use different models (e.g., coach on GPT-4, agents on Claude Sonnet).

### Scope
- Config extension: `team.json` agent entries get optional `"model"` override
- Resolver with merge semantics: agent model config = team default ∪ agent override
- SessionDeps carries resolver function instead of single model_config dict
- Engine calls resolver per-agent before each completion

### Design Considerations
- Backwards compatible: agents without `"model"` key use team default
- Coach can have its own model config too
- API key resolution per-provider (agent using OpenAI needs OPENAI_API_KEY even if team default is Anthropic)

---

## Phase 5: CLI Command Split

**Status: Not started**

Split `cli.py` (~1175 lines) into a `commands/` directory.

### Scope
- `cli.py` becomes pure dispatcher: argparse setup + command routing
- `commands/run.py` — cmd_run, cmd_continue, run_conversation
- `commands/advance.py` — cmd_advance, cmd_next_layer
- `commands/review.py` — cmd_review, cmd_merge, cmd_worktrees, cmd_commit_worktrees
- `commands/groom.py` — cmd_groom_start, cmd_groom_continue, cmd_groom_list, cmd_groom_show
- `commands/admin.py` — cmd_init, cmd_model, cmd_checkpoint, cmd_checkpoints, cmd_restore, cmd_approvals, cmd_approve, cmd_deny

### Design Considerations
- Shared helpers stay in cli.py or move to a commands/helpers.py
- `find_team_dir()`, `_auto_checkpoint()`, `_print_session_header()`, `_handle_cli_events()` are shared
- Import structure: commands import from session.py and shared helpers, never from each other

---

## Phase 6: Shared Tool-Loop Helpers

**Status: Not started**

Extract tool execution primitives shared between engine.py and implementation.py.

### Scope
- Both engine.py (`_do_streaming_agent_turn`) and implementation.py (`run_implementation`) have tool execution loops
- Extract: tool call parsing, tool result formatting, multi-round loop scaffolding
- Defer full unification — the loops have genuinely different semantics (round-robin vs per-agent sequential)

### Design Considerations
- Don't over-abstract: extract shared primitives, not a generic "tool loop framework"
- implementation.py has task completion tracking that engine.py doesn't
- engine.py has coach turn interleaving that implementation.py doesn't
- The shared parts: tool call extraction from response, tool result formatting, safety classification

---

## Phase 7: Phase Capability Table

**Status: Deferred**

Replace hardcoded phase logic with a declarative capability table.

### Scope
- Each phase declares: allowed tools, coach behavior, file access, worktree usage
- Currently scattered across: policy.py (iteration_policy), engine.py (phase checks), session.py (setup_worktrees phase gate)
- Deferred until configurable/custom phases are on the roadmap

### Design Considerations
- Only worth doing when users need to define custom phases
- Current hardcoded approach is readable and well-tested
- The phase capability table would replace ~5 different `if phase == "implementation"` checks

---

## Architecture After All Phases

```
CLI commands/ ──→ session.py (service) ──→ engine.py (generator)
TUI screens/  ──→ session.py (service) ──→ implementation.py (generator)
                        ↓
                  events.py (typed events)
                        ↓
              model/ (per-provider completion)
```

- **session.py**: owns persistence, setup, transitions, review/merge
- **engine.py**: stateless generator, yields events, no I/O
- **model/**: per-provider completion, prompt caching, streaming
- **CLI/TUI**: thin I/O adapters that iterate events and render
