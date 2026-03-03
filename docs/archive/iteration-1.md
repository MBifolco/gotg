 Iteration 1 Implementation Plan: gotg

 Overview

 Build a pip-installable Python CLI tool that scaffolds a .team/ directory in any project and runs a conversation
 between two AI agents via a local Ollama model. No code output — just design conversation, logged as JSONL.

 Project Structure

 gotg/                           # repo root
 ├── narrative.md                # design context (exists)
 ├── gotg.code-workspace         # vscode (exists)
 ├── pyproject.toml              # package config, CLI entry point
 └── src/
     └── gotg/
         ├── __init__.py
         ├── cli.py              # argparse subcommands: init, run, show
         ├── scaffold.py         # gotg init — create .team/ structure
         ├── agent.py            # build prompt, run one agent turn
         ├── model.py            # HTTP call to OpenAI-compatible API
         ├── conversation.py     # read/append JSONL, render to terminal
         └── config.py           # load .team/*.json files

 Using src/ layout per modern Python packaging conventions. The .team/ directory is created per-project by gotg
 init, not shipped with the package.

 Files to Create

 1. pyproject.toml

 - Build system: setuptools or hatchling
 - Single dependency: httpx
 - CLI entry point: gotg = "gotg.cli:main"
 - Python >= 3.10

 2. src/gotg/__init__.py

 Empty or version string only.

 3. src/gotg/cli.py — Entry Point

 argparse with three subcommands:

 - gotg init [path] — calls scaffold.init_project(path). Defaults to . (current dir).
 - gotg run — loads config from .team/, runs the agent conversation loop, prints each message to terminal as it
 happens.
 - gotg show — reads and renders the existing conversation log. Useful for replaying after the fact.

 4. src/gotg/scaffold.py — Project Init

 init_project(path):
 - Creates .team/, .team/agents/
 - Writes .team/model.json with Ollama defaults:
 {
   "provider": "ollama",
   "base_url": "http://localhost:11434",
   "model": "qwen2.5-coder:7b"
 }
 - Writes .team/agents/agent-1.json and .team/agents/agent-2.json:
 {
   "name": "agent-1",
   "system_prompt": "You are a software engineer working on a team with one other engineer. You are collaborating on
  a design task. Discuss approaches, raise concerns, and work toward a good solution together.\n\nDo not just agree
 to be agreeable. If you see a problem, say so. If you have a different idea, propose it. Good teams push back on
 each other.\n\nYou have a limited number of turns. Be substantive and move the conversation forward.\n\nWhen you
 believe the team has reached a solid conclusion, say so clearly and summarize what was decided."
 }
 - Writes .team/iteration.json:
 {
   "id": "iter-1",
   "description": "",
   "status": "pending",
   "max_turns": 10
 }
 - Creates empty .team/conversation.jsonl
 - Prints what was created. Does NOT touch any existing files outside .team/.

 If .team/ already exists, warn and exit (don't overwrite).

 5. src/gotg/config.py — Config Loading

 - load_model_config(team_dir) -> dict — reads .team/model.json
 - load_agents(team_dir) -> list[dict] — reads all JSON files from .team/agents/, returns sorted by name
 - load_iteration(team_dir) -> dict — reads .team/iteration.json
 - All functions take the .team/ directory path. cli.py finds it by looking for .team/ in CWD.

 6. src/gotg/conversation.py — JSONL Operations

 - read_log(path) -> list[dict] — read JSONL file, return list of message dicts
 - append_message(path, msg: dict) — json-serialize + append + newline + flush
 - render_message(msg: dict) -> str — format for terminal: agent name in color, content in plain text. Agent-1 gets
 one color (e.g., cyan), agent-2 gets another (e.g., yellow). Raw ANSI escape codes, no library.

 7. src/gotg/model.py — Model Interface

 Single function:
 def chat_completion(base_url: str, model: str, messages: list[dict], api_key: str | None = None) -> str

 - POST to {base_url}/v1/chat/completions
 - Body: {"model": model, "messages": messages}
 - Auth header if api_key provided
 - Returns response["choices"][0]["message"]["content"]
 - Uses httpx with a generous timeout (120s — local 7B models can be slow on first token)

 That's it. ~20 lines.

 8. src/gotg/agent.py — Agent Logic

 def build_prompt(agent_config: dict, iteration: dict, history: list[dict]) -> list[dict]:

 Constructs the messages list for the chat API:

 1. System message: agent's system_prompt + "\n\nCurrent task: {iteration['description']}"
 2. History mapping: Walk through history list. For each message:
   - If msg["from"] == this_agent_name → role "assistant"
   - Otherwise → role "user"
 3. Seed case: If history is empty (agent-1 going first), add one user message: "The task is:
 {iteration['description']}. What are your initial thoughts?"

 This role-mapping is what allows two LLMs to converse through a standard chat completion API without any
 multi-agent framework.

 The Run Loop (cli.py orchestrates)

 1. Find .team/ in CWD
 2. Load iteration.json, model.json, agent configs
 3. Validate: iteration.description is non-empty, status is "in-progress"
 4. Read existing conversation.jsonl (could be resuming)
 5. Determine whose turn it is (len(history) % 2 → agent index)
 6. Loop until max_turns:
    a. current_agent = agents[turn % 2]
    b. prompt = build_prompt(current_agent, iteration, history)
    c. response = chat_completion(base_url, model, prompt)
    d. msg = {"from": current_agent["name"], "iteration": iteration["id"], "content": response}
    e. append_message(conversation_path, msg)
    f. print rendered message to terminal
    g. history.append(msg)
    h. turn += 1
 7. Print "Conversation complete ({n} turns)"

 Resume support is free — if conversation.jsonl already has messages, we pick up where we left off.

 Decisions Incorporated

 From the narrative + browser Claude feedback:
 ┌────────────────────────┬───────────────────────────────────────────────────────┐
 │        Decision        │                         Value                         │
 ├────────────────────────┼───────────────────────────────────────────────────────┤
 │ Max turns              │ 10 (5 per agent)                                      │
 ├────────────────────────┼───────────────────────────────────────────────────────┤
 │ Terminal output        │ Raw ANSI, no rich                                     │
 ├────────────────────────┼───────────────────────────────────────────────────────┤
 │ Who goes first         │ agent-1                                               │
 ├────────────────────────┼───────────────────────────────────────────────────────┤
 │ Seed message           │ Iteration description as user prompt                  │
 ├────────────────────────┼───────────────────────────────────────────────────────┤
 │ System prompt addition │ "You have a limited number of turns"                  │
 ├────────────────────────┼───────────────────────────────────────────────────────┤
 │ Dependencies           │ httpx only                                            │
 ├────────────────────────┼───────────────────────────────────────────────────────┤
 │ Install method         │ pip install -e . for dev, pip install gotg eventually │
 └────────────────────────┴───────────────────────────────────────────────────────┘
 What This Intentionally Does NOT Include

 - No id or ts on messages
 - No message types or threading
 - No self-termination detection (just max_turns ceiling)
 - No git integration
 - No human participation in conversation
 - No TUI library
 - No async (agents alternate, no concurrency needed)
 - No tests (first iteration — we're learning what the right behavior even is)

 Verification

 1. pip install -e . from repo root
 2. mkdir /tmp/test-project && cd /tmp/test-project
 3. gotg init . — verify .team/ structure is created with correct defaults
 4. Edit .team/iteration.json — set description to "Design a CLI todo list application. Discuss the command
 interface, data storage format, and core features." and status to "in-progress"
 5. Ensure Ollama is running with qwen2.5-coder:7b pulled
 6. gotg run — watch two agents discuss the todo list design
 7. gotg show — replay the conversation from the log
 8. Verify .team/conversation.jsonl contains valid JSONL with from, iteration, content fields