# GOTG Architecture

This document explains how the codebase works — what each module does, how they connect, and the key design decisions.

## Overview

GOTG is a pip-installable Python CLI. You install it once, then use it to initialize and run AI team conversations inside any project directory. The mental model is `git` — you don't think of git as "a library inside my project," it's a tool on your system that manages state within your project.

```
gotg (the tool, installed globally)
  │
  └── operates on ──► .team/ (per-project state, like .git/)
                        ├── model.json
                        ├── iteration.json
                        ├── conversation.jsonl
                        └── agents/*.json
```

## Module Map

```
src/gotg/
├── cli.py           ─── Entry point. Parses commands, orchestrates the run loop.
├── scaffold.py      ─── Creates the .team/ directory structure.
├── config.py        ─── Loads JSON config files from .team/.
├── agent.py         ─── Builds chat API prompts with role mapping.
├── model.py         ─── Makes HTTP calls to the model API.
└── conversation.py  ─── Reads/writes JSONL log, renders messages for terminal.
```

### Dependency flow

```
cli.py
  ├── scaffold.py        (for init)
  ├── config.py          (for run/show)
  ├── agent.py           (for run)
  ├── model.py           (for run)
  └── conversation.py    (for run/show)
```

No module imports another module in this package except `cli.py`, which imports all of them. Every other module is self-contained with only standard library + httpx dependencies.

## Module Details

### `cli.py` — Entry Point & Run Loop

**Functions:**

- `main()` — Parses `init`, `run`, `show` subcommands via argparse and dispatches to handlers.
- `find_team_dir(cwd)` — Looks for a `.team/` directory in the given path. Returns the path or `None`.
- `cmd_init(args)` — Delegates to `scaffold.init_project()`.
- `cmd_run(args)` — Validates config, then calls `run_conversation()`.
- `cmd_show(args)` — Reads the log and prints each message.
- `run_conversation(team_dir, agents, iteration, model_config)` — The core loop (see below).

**The run loop** is the heart of the tool:

```
1. Read existing conversation.jsonl → history
2. Set turn = len(history)  (enables resume)
3. While turn < max_turns:
   a. Pick agent: agents[turn % 2]
   b. Build prompt via agent.build_prompt()
   c. Call model via model.chat_completion()
   d. Construct message dict: {from, iteration, content}
   e. Append to JSONL log
   f. Print to terminal
   g. Append to in-memory history
   h. Increment turn
```

**Resume** is free — if the log already has 4 messages and max_turns is 10, we start at turn 4 and run 6 more. No special resume logic needed.

**Validation** before running:
- `.team/` directory must exist
- `iteration.json` description must be non-empty
- `iteration.json` status must be `"in-progress"`
- At least 2 agent configs must be present

### `scaffold.py` — Project Initialization

**Functions:**

- `init_project(path)` — Creates the `.team/` directory tree with default configs.

Creates:
- `.team/model.json` — Ollama defaults (localhost:11434, qwen2.5-coder:7b)
- `.team/agents/agent-1.json` and `agent-2.json` — Identical system prompts
- `.team/iteration.json` — Empty description, pending status, 10 max turns
- `.team/conversation.jsonl` — Empty file

If `.team/` already exists, prints an error and exits. Never touches files outside `.team/`.

The default system prompt tells agents to collaborate, push back on each other (anti-sycophancy), be substantive with limited turns, and summarize conclusions. This prompt is the same for both agents — differentiation comes later based on observed behavior.

### `config.py` — Config Loading

Three functions, each reading one JSON file:

- `load_model_config(team_dir)` — Returns dict from `model.json`
- `load_agents(team_dir)` — Globs `agents/*.json`, returns list of dicts sorted by filename
- `load_iteration(team_dir)` — Returns dict from `iteration.json`

Sorting agents by filename means `agent-1.json` loads before `agent-2.json`, which determines who speaks first.

### `agent.py` — Prompt Construction

**Functions:**

- `build_prompt(agent_config, iteration, history)` — Returns a list of chat messages for the model API.

This is the key architectural insight of the project. Two LLMs converse through a standard chat completion API by **role-mapping**:

```
From agent-1's perspective:
  agent-1's messages  →  role: "assistant"  (my own past responses)
  agent-2's messages  →  role: "user"       (incoming messages to respond to)

From agent-2's perspective:
  agent-2's messages  →  role: "assistant"
  agent-1's messages  →  role: "user"
```

Each agent sees the same conversation but from its own point of view. No multi-agent framework needed — just a standard `[system, user, assistant, user, assistant, ...]` message list that any chat API accepts.

**Prompt structure:**

1. **System message**: Agent's `system_prompt` + `"\n\nCurrent task: {description}"`
2. **Conversation history**: Each message mapped to `assistant` or `user` per the rule above
3. **Seed case** (empty history): A single `user` message — `"The task is: {description}. What are your initial thoughts?"` — to kick off agent-1's first response

### `model.py` — Model Interface

**Functions:**

- `chat_completion(base_url, model, messages, api_key=None)` — POSTs to the OpenAI-compatible chat completions endpoint and returns the response content string.

This is ~20 lines of code. It:
- POSTs to `{base_url}/v1/chat/completions`
- Sends `{"model": model, "messages": messages}`
- Adds `Authorization: Bearer {api_key}` header if a key is provided
- Uses a 120-second timeout (local 7B models can be slow on first token)
- Returns `response["choices"][0]["message"]["content"]`

Because it targets the OpenAI-compatible API format, it works with Ollama, OpenAI, Azure, vLLM, llama.cpp server, or any compatible provider. Swapping models is a config change, not a code change.

### `conversation.py` — JSONL Log & Rendering

**Functions:**

- `read_log(path)` — Reads a JSONL file, returns list of message dicts. Returns empty list if file doesn't exist.
- `append_message(path, msg)` — JSON-serializes a message and appends it as a new line. Flushes immediately.
- `render_message(msg)` — Formats a message for terminal display with ANSI colors. Agent-1 is cyan, agent-2 is yellow.

The JSONL format was chosen because:
- Human-readable (`cat conversation.jsonl` works)
- Machine-parseable (one `json.loads()` per line)
- Append-only (no read-modify-write, safe for concurrent writers in the future)
- Works with standard tools (`tail -f`, `jq`, `wc -l`)

## Data Flow

A complete `gotg run` execution:

```
                    ┌──────────────┐
                    │ .team/ files │
                    └──────┬───────┘
                           │ config.py reads
                           ▼
                    ┌──────────────┐
                    │   cli.py     │
                    │  (run loop)  │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌───────────────┐
        │ agent.py │ │ model.py │ │conversation.py│
        │ (prompt) │ │  (HTTP)  │ │ (log + render)│
        └──────────┘ └──────────┘ └───────────────┘
              │            │            │
              │   build    │   POST     │  append
              │   prompt   │   to API   │  to JSONL
              ▼            ▼            ▼
        [messages]    [response]   [conversation.jsonl]
```

Each turn:
1. `agent.py` builds the prompt from config + history
2. `model.py` sends it to the LLM and gets a response
3. `conversation.py` writes the response to the log and renders it to the terminal

## Design Principles

These emerged from the design conversation (see [narrative.md](../narrative.md)) and are enforced in the code:

1. **Fail simple, learn why** — The message schema has 3 fields. No message types, no threading, no timestamps. When we observe a need for these, we add them.

2. **Conversation over implementation** — The JSONL log is the primary artifact. The tool exists to produce good conversations, not good code (yet).

3. **Evidence-driven evolution** — Agents start with identical prompts. We'll differentiate them after observing what identical agents do wrong.

4. **Platform is transport, protocol is product** — The terminal CLI, JSONL format, and HTTP calls are all replaceable transport. The role-mapping protocol and turn structure are the real design.

5. **Model-agnostic** — Any OpenAI-compatible API works. One agent could even use a different model than the other (a future experiment).

## What's Intentionally Missing

These are not oversights — they're deferred by design:

| Feature | Why deferred |
|---------|-------------|
| Message `id` and `ts` fields | Add when we need to reference or order messages beyond sequence |
| Message types (proposal, question) | Add when agents need to behave differently based on message type |
| Threading / `ref` field | Add when conversations need branching |
| Self-termination detection | Observe how agents end conversations first, then formalize |
| Git integration | Iteration 2, when agents produce code |
| Human in the conversation | Iteration 3 |
| Role differentiation / orchestrator | Iteration 4 |
| Async / concurrent agents | Not needed when agents alternate turns |

## Test Structure

```
tests/
├── test_smoke.py         # Package imports correctly
├── test_config.py        # Config loading from .team/ files
├── test_conversation.py  # JSONL read/write/render
├── test_scaffold.py      # gotg init creates correct structure
├── test_model.py         # HTTP calls (mocked)
├── test_agent.py         # Prompt construction and role mapping
└── test_cli.py           # Subcommands, validation, run loop
```

43 tests total. Model API calls are mocked in tests — no live model needed to run the test suite.

```bash
pytest -v   # run all
pytest tests/test_agent.py -v   # run one module
```
