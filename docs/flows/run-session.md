# Flow: Running Sessions

How agent conversations run from CLI command to completion.

## Detailed walkthroughs

- **[init-and-new.md](init-and-new.md)** — `gotg init` and `gotg new`: project scaffolding, directory structure, iteration creation
- **[first-turn.md](first-turn.md)** — `gotg run` on a fresh iteration: config loading, session setup, engine startup, first agent turn with prompt construction and LLM call
- **[pause-and-resume.md](pause-and-resume.md)** — Ctrl+C pause, interjection prompt, marker persistence, auto-resume
- **[phase-advance.md](phase-advance.md)** — `gotg advance`: artifact extraction, boundary markers, phase transitions
- **[approvals.md](approvals.md)** — File write approval queue, 3-way decisions, resolution on continue
- **[exploration.md](exploration.md)** — `gotg explore`: freeform sessions without phase constraints

## High-level architecture

```
CLI command (commands/*.py)
  │
  ├─ TeamContext.from_team_dir()        config loading
  ├─ validate + build_session_infra()   session setup
  │
  └─ cli.py::run_conversation()         bridge
       │
       ├─ SessionDeps (model funcs)     dependency injection
       ├─ prepare_session()             policy + history
       │
       ├─ run_and_persist()             persistence wrapper
       │    └─ run_session()            core engine (yields events)
       │         ├─ build_prompt()      prompt construction
       │         ├─ LLM call            model API
       │         └─ events              SessionStarted, AppendMessage, ...
       │
       └─ handle_console_events()       rendering + pause detection
```

## Key design patterns

- **Event-driven**: Engine yields events; consumers handle I/O and persistence
- **Bridge pattern**: `cli.py` imports model functions, passes them as `SessionDeps` — engine never imports `gotg.model` directly, so tests can mock at the import site
- **Persist-then-yield**: Events are written to JSONL before being yielded to the console handler — crash-safe
- **Phase-scoped history**: `read_phase_history()` returns only messages after the last phase boundary marker — turns reset per phase
