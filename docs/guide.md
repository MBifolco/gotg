# GOTG User Guide

## What GOTG Does

GOTG runs conversations between AI agents inside your project. You give it a task, and two AI engineers discuss it — debating approaches, raising concerns, and working toward a solution. The conversation is logged as JSONL so you can replay, analyze, or build on it.

Think of it as a SCRUM standup between AI teammates, happening in your terminal.

## Installation

### 1. Python

You need Python 3.10 or higher.

```bash
python --version  # check your version
```

If you're using pyenv:
```bash
pyenv install 3.11.10
pyenv local 3.11.10
```

### 2. GOTG

From the repo:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Ollama

GOTG needs a running LLM. The default is Ollama with `qwen2.5-coder:7b`.

```bash
# Install Ollama: https://ollama.ai
ollama pull qwen2.5-coder:7b
ollama serve
```

**AMD GPU users**: You likely need this environment variable:
```bash
HSA_OVERRIDE_GFX_VERSION=10.3.0 ollama serve
```

### Using Other Models

Any OpenAI-compatible API works. After `gotg init`, edit `.team/model.json`:

```json
{
  "provider": "openai",
  "base_url": "https://api.openai.com",
  "model": "gpt-4o",
  "api_key": "sk-..."
}
```

Or a different Ollama model:
```json
{
  "provider": "ollama",
  "base_url": "http://localhost:11434",
  "model": "llama3:8b"
}
```

## Usage Walkthrough

### Step 1: Initialize a Project

```bash
mkdir my-project
cd my-project
gotg init .
```

This creates a `.team/` directory:

```
.team/
  model.json           # Where to find the LLM
  iteration.json       # What the agents should work on
  conversation.jsonl   # The conversation (starts empty)
  agents/
    agent-1.json       # First agent's config
    agent-2.json       # Second agent's config
```

You can also init inside an existing project — `gotg init` only creates `.team/` and never touches your other files.

### Step 2: Define a Task

Edit `.team/iteration.json`:

```json
{
  "id": "iter-1",
  "description": "Design a CLI todo list application. Discuss the command interface, data storage format, and core features. Consider error handling and edge cases.",
  "status": "in-progress",
  "max_turns": 10
}
```

Two things must be set before `gotg run` will work:
- `description` must be non-empty
- `status` must be `"in-progress"`

`max_turns` is the total number of messages. With 2 agents and 10 turns, each agent speaks 5 times.

### Step 3: Run the Conversation

```bash
gotg run
```

You'll see agents talking in real time:

```
Starting conversation: iter-1
Task: Design a CLI todo list application...
Turns: 0/10
---
[agent-1] I think we should start by defining the core commands...

[agent-2] Good starting point. I'd suggest we also consider...

...

---
Conversation complete (10 turns)
```

Agent-1 appears in cyan, agent-2 in yellow.

### Step 4: Review

Replay the conversation:
```bash
gotg show
```

Or inspect the raw log:
```bash
cat .team/conversation.jsonl
```

Each line is a JSON object:
```json
{"from": "agent-1", "iteration": "iter-1", "content": "I think we should..."}
```

### Resuming a Conversation

If a conversation is interrupted (Ctrl+C, network error, etc.), just run `gotg run` again. It reads the existing log and picks up where it left off. If 4 of 10 turns completed, it runs the remaining 6.

### Starting a Fresh Conversation

Delete or rename the log:
```bash
rm .team/conversation.jsonl
gotg run
```

## Customizing Agents

Agent configs live in `.team/agents/`. Each is a JSON file with a name and system prompt:

```json
{
  "name": "agent-1",
  "system_prompt": "You are a software engineer..."
}
```

### Changing the Prompt

Edit the `system_prompt` to change agent behavior. Some ideas:

**More critical agent:**
```json
{
  "name": "agent-1",
  "system_prompt": "You are a senior software engineer who values simplicity and maintainability above all else. Question every added complexity. Ask 'do we really need this?' frequently. Push back on over-engineering.\n\nYou have a limited number of turns. Be substantive."
}
```

**More creative agent:**
```json
{
  "name": "agent-2",
  "system_prompt": "You are a software engineer who likes to explore unconventional approaches. Consider edge cases others might miss. Propose alternatives even when the obvious solution seems fine.\n\nYou have a limited number of turns. Be substantive."
}
```

### Adding More Agents

Add more JSON files to `.team/agents/`. Agents are loaded alphabetically by filename and take turns in order. With 3 agents and 12 max_turns, each speaks 4 times.

## Tips

- **Start with 10 turns.** 5 per agent is usually enough for a design discussion with a 7B model. Increase if conversations are getting cut off while still productive.
- **Smaller models repeat themselves.** If you see circular conversation, try reducing turns or adjusting the prompt to emphasize forward progress.
- **The log is just a file.** You can `grep` it, `jq` it, pipe it, or write scripts against it. It's JSONL — one JSON object per line.
- **You can use different models per conversation.** Change `model.json` between runs to compare how different models handle the same task.
