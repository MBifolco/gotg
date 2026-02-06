# AI SCRUM Team — Conversation History & Project Development Log

**Date:** February 5, 2026  
**Participants:** Human (PM/Architect), Claude (Design Partner)

---

## 1. Opening Vision

The human opened with a clear, high-level vision: build an AI coding tool similar to Cursor but with a **team-first approach** modeled on SCRUM. The key differentiator from existing tools (Cursor, Copilot) is that AI agents aren't treated as tools within a developer's workflow — they're **team members** with roles, autonomy, and communication responsibilities.

The initial scope described:
- One or more AI engineers operating as independent agents
- One human acting as PM and/or engineer
- Future expansion to AI participants in other roles (designer, PM, agile coach, etc.)
- Future expansion to multiple human participants requiring decentralized communication
- **Conversation takes priority over implementation** as a guiding principle

## 2. Claude's Initial Architecture Proposal

Claude responded with an extensive architectural breakdown, identifying five layers:

1. **Communication Bus** — a shared, persistent, structured message channel with typed messages (decision, question, status-update, code-proposal, review-request, blocker)
2. **Project State** — a living document replacing the "system prompt" approach, containing backlog, sprint items, ownership, acceptance criteria, architectural decisions
3. **Agent Runtime** — independent agent loops (pick up task → plan → communicate → implement → request review → iterate) with their own branches and sandboxed environments
4. **Human Interface** — a dashboard (not a code editor) showing sprint progress, decisions needing approval, review requests
5. **Orchestrator** — a meta-agent acting as Scrum Master, managing process rather than writing code

Claude also raised several design tensions:
- Communication as the primary artifact (the system's backbone is a communication layer, not a code editor)
- Agent autonomy vs. coordination (sprint planning, standups, code ownership, PR cycles)
- The human's special role as bottleneck and authority — framed as an **attention management** problem

Claude suggested the platform could be "Linear meets Replit meets Slack, not better Cursor."

## 3. Human Redirects: Define the MVP First

Rather than diving into architecture, the human redirected to defining the **iteration plan** and establishing a consistent evaluation approach. Key points raised:

- Need a **basic coding project** that all iterations work on for consistent evaluation
- The project can grow over time but needs measurable quality criteria
- Proposed starting even simpler than expected: **Iteration 1 wouldn't even produce code** — just prove two AI agents can have a productive conversation where both contribute substantively
- Raised the platform question: custom IDE? Cloud-based? VSCode extension? Recognized this as an important early decision for scalability

This was the first instance of the human demonstrating the PM role — pulling back from engineering details to focus on process and evaluation strategy.

## 4. Platform Discussion

Claude laid out trade-offs for each option:

- **VSCode Extension:** Mature ecosystem but extension API designed for tools, not team communication. Cursor itself is a fork, not an extension, because the model was too limiting. Couples to Microsoft's decisions.
- **Custom IDE / Electron App (Cursor approach):** Maximum control but enormous surface area. Months on editor basics before reaching the interesting team dynamics. A trap for early iterations.
- **Cloud-based / Web App:** Claude initially pushed for this, arguing that the core innovation is communication/coordination (naturally web-native), decentralized participation is native to web, AI agents don't need an IDE, and you avoid building editor infrastructure.

Claude proposed thinking of it as "a team coordination platform that happens to produce code" rather than "an IDE with team features."

## 5. Human Redirects Again: Terminal-Based Application

The human pushed back on the web app suggestion, proposing instead a **custom terminal-based application**. Reasoning:

- Lightweight — no web infrastructure overhead
- Use whatever editor/IDE you want for actual code
- Conversation can be local for now, add pub/sub later easily
- No need to worry about websites and everything that comes with that
- Start simple, scale later

Claude acknowledged this was the right call and recognized the irony — Claude was over-engineering the platform before proving the core concept. The human was "PM'ing" Claude away from premature complexity, which was itself a demonstration of why the project matters.

**Benefits of terminal-based approach identified:**
- Gets out of the way — no frontend framework decisions, CSS, or deployment
- Native to developers who already live in the terminal
- Symmetric — agents and humans interact through the same medium
- Makes the conversation log the obvious centerpiece
- Trivially extensible — swap local file for message broker later, nothing about core experience changes
- Forces you to get the protocol right (can't hide bad coordination behind a pretty UI)

Claude proposed a project structure where team state lives alongside the code (`.team/` directory analogous to `.git/`), with a CLI entry point for human interaction and agents as background processes watching the conversation log.

## 6. Conversation Log Format

Claude proposed JSONL (newline-delimited JSON) for the conversation log. Reasoning:
- Human-readable (`tail -f conversation.log` works without the CLI)
- Machine-parseable (agents parse line by line)
- Appendable (multiple writers, no read-modify-write conflicts)
- Typed messages could distinguish status updates from proposals from questions

The human agreed that **JSONL makes sense**.

## 7. Message Schema: Claude Over-Engineers, Human Corrects

Claude proposed a detailed message schema with fields for `id`, `ts`, `from`, `role`, `type`, `ref`, and `content`. Claude went further and proposed a taxonomy of message types (`proposal`, `critique`, `question`, `answer`, `agreement`, `decision`, `status`) and behavioral protocol rules (e.g., "a proposal must receive at least one critique before becoming a decision").

The human pulled back firmly: **"I think we're getting ahead of ourselves."** The preference was to iterate on the message format based on experimentation — fail because it's too simple, then understand *why* it fails and add fields as needed. The schema should be evidence-driven.

**Decision: Messages start with only `from` and `content`.** Nothing else.

```json
{"from":"agent-1","content":"I suggest we use a hash-based approach..."}
{"from":"agent-2","content":"What about collisions though?"}
```

When the team finds themselves wishing they knew whether a message was a question or a proposal, *that's* when `type` gets added. When threading is needed, *that's* when `ref` gets added. Schema evolution driven by observed failure modes, not anticipated ones.

This was a recurring theme: **the human consistently favored learning from failure over designing for completeness.**

## 8. Agent Configuration

Claude raised the question of how to differentiate agents so they don't just echo each other. The human proposed each agent gets a config that defines their role — essentially behavioral instructions that form part of their context/prompt.

Example of the kind of system prompt discussed:
> "You are a software engineer working on a team with one other AI engineer. You must collaborate with your teammate before building anything. Discuss approaches, raise concerns, and come to consensus as a team before writing any code."

Claude highlighted a key concern: **LLM sycophancy**. Without explicit instruction to push back, agents will likely just agree with each other immediately, producing a two-person team with one person's output. Suggested adding something like "Don't just agree to be agreeable."

### Identical vs. Differentiated Agents

Claude asked whether to give agents identical configs or subtly differentiate them (e.g., one nudged toward simplicity, the other toward robustness).

**Decision: Start identical.** Observe the failure mode (predicted: instant agreement), then use that observation to inform differentiation. Consistent with the "fail simple, learn why" approach.

The human noted that eventually it would be great to model agents after real team dynamics — e.g., "the extremely nerdy engineer who thinks we should only ever write functional code and looks down on anyone who doesn't use Spacemacs." Real team dynamics come from people who care deeply about *different* things, and those tensions produce better software than any individual perspective. But that's a later experiment — for now, identical agents will teach the most.

## 9. Iteration Plan

### Test Project: URL Shortener

Claude suggested a URL shortener web app as the consistent evaluation project — REST API, simple frontend, persistent storage. Rationale: clear components, natural boundaries for splitting work, obvious quality criteria. Can be expanded over time (add auth, analytics, rate limiting) to test more sophisticated coordination.

### Iteration 1: Two Agents, Conversation Only

- Hardcoded task provided by human (no interactive human participation yet)
- Two AI agents discuss the API design for a URL shortener
- **No code output** — just a design discussion
- Success criteria: both agents contribute substantively, they don't just immediately agree, the resulting design is coherent
- What's actually being built: the communication protocol, agent loop, and conversation rendering
- Could be as simple as a Python/Node script running two agent loops appending to a shared JSONL file

### Iteration 2: Conversation Produces Working Code

- Same setup but agents now implement the design from Iteration 1
- Work split between agents (e.g., Agent A does API routes, Agent B does data layer)
- Coordination through the communication channel when interfaces need to align
- Evaluation: Does it run? Does it meet the spec? Human review + AI evaluator agent with special understanding of the project
- What's being built: sandboxed execution for agents, git integration, review/merge flow

### Iteration 3: The Human Joins the Team

- Human participates as PM: sets priorities, answers questions, approves designs, reviews code
- System must manage human attention: what's worth showing vs. what agents resolve themselves
- Human can redirect, reprioritize, or override mid-sprint
- What's being built: the human dashboard/CLI, notification/escalation logic, "needs human input" as a blocker concept

### Iteration 4: Role Differentiation

- Introduce orchestrator/scrum master agent
- Agents have explicit roles and capabilities
- Sprint ceremonies become part of the system
- Test project gets harder (add auth, second service)
- What's being built: role-based agent templates, orchestration layer, multi-sprint workflows

## 10. Recurring Themes & Principles

Several principles emerged organically through the conversation that seem to be guiding the project:

1. **Conversation over implementation** — This isn't just a feature priority; it's the project's thesis. The value is in the dialogue, not the code output. The code is a byproduct of good team process.

2. **Fail simple, learn why** — Repeatedly, when Claude proposed complex upfront designs (rich message schemas, behavioral protocols, platform architecture), the human pulled back to the simplest possible version. The belief is that observed failure modes teach more than anticipated ones.

3. **Evidence-driven evolution** — Don't add fields, features, or complexity until there's a concrete reason. The schema starts minimal and grows based on what breaks. The agent differentiation starts identical and evolves based on what's boring.

4. **The human is the PM** — The conversation itself demonstrated the dynamic the tool is trying to create. Claude repeatedly played the eager engineer wanting to build more, and the human repeatedly redirected to scope, priorities, and "what do we actually need to learn right now?" This pattern is the product.

5. **Platform is transport, protocol is product** — The terminal vs. web vs. IDE decision matters less than the communication protocol and team dynamics. The platform can change; the way agents collaborate is the real IP.

---

## Current State & Open Items

### Decided
- Terminal-based CLI application
- JSONL conversation log
- Minimal message schema: `from` + `content` only
- Two agents with identical system prompts for Iteration 1
- URL shortener as evaluation project
- Four-iteration roadmap from conversation-only to role differentiation
- "Don't just agree to be agreeable" as a key agent instruction

### Open (Ready to Decide)
- **Task prompt** — exact wording of the URL shortener design task given to agents
- **Turn structure** — alternating seems right but not formally decided
- **Termination condition** — fixed turn count? Magic word? Human kills process?
- **Tech stack** — Python? Node? Which model API for agents?

### Deferred (Intentionally)
- Message types / typed messages (add when observed as needed)
- Message threading / `ref` field (add when observed as needed)
- Agent personality differentiation (after observing identical agent behavior)
- Orchestrator / scrum master agent (Iteration 4)
- Decentralized communication / pub-sub (future, when multi-participant)
- Human dashboard / attention management (Iteration 3)
- AI evaluator agent for quality assessment (Iteration 2)

---

## 11. Refining the Remaining Open Items

With the big architectural decisions behind us, the conversation turned to resolving the remaining open items: test project, message schema refinements, turn structure, termination, and tech stack.

### Simpler Test Project

Claude initially proposed a URL shortener as the evaluation project (back in Section 9). The human pushed back — not rejecting it outright, but recognizing it might be too much for early iterations where the goal is testing *conversation quality*, not code output. The human asked about typical first coding exercises: task managers, Twitter knockoffs, etc.

Claude offered several candidates ordered by complexity (calculator CLI, todo list CLI, markdown notes, password generator) and recommended the **CLI todo list app** as the Goldilocks choice. It has just enough design decisions (storage format, command interface, ID handling, filtering/sorting) to generate real discussion without overwhelming anyone. And it scales: later iterations can add priorities, due dates, tags, persistence options.

**Decision: CLI todo list app as the test project.** The human also noted the reality that they'd probably test on *all* of the simple project ideas before moving to the next iteration of the tool itself. The test project isn't precious — it's a means to evaluate the team dynamics.

### Schema Evolution: Adding `iteration` (not `task`)

The human proposed that messages need a reference to the current piece of work being done — what iteration are we on? This was the project's second schema evolution (the first being the minimal `from` + `content` starting point).

The human specifically requested calling the field `iteration` rather than `task`, reasoning that "iteration" is more generic and carries less baggage with engineers. "Task" invites debates about whether it's a story, an epic, a ticket. "Iteration" is just "the thing we're working on right now." Claude agreed this was smart naming.

**The message format became:**

```json
{"from":"agent-1","iteration":"iter-1-todo-design","content":"I think we should store todos as JSON..."}
```

Alongside this, the human's point implied the need for an **iteration tracker** — a file that defines what the current iteration is. Claude proposed `iteration.json`:

```json
{
  "id": "iter-1-todo-design",
  "description": "Design a CLI todo list application. Discuss the command interface, data storage approach, and core features before writing any code.",
  "status": "in-progress",
  "max_turns": 20
}
```

This is the seed of a backlog/sprint system, but nobody's calling it that yet. Just a file that says "here's what we're working on."

### Turn Structure & Termination Refined

Alternating turns were confirmed. Max turns would be defined per iteration in the config as a safety net.

But the human added an important nuance: **the real goal is for agents to self-terminate.** Rather than always hitting the max turn ceiling, a key early success metric should be: "Can two agents have a productive conversation and *conclude it themselves*?" This means agents need to recognize when they've reached agreement, summarize what they decided, and stop. The human noted that achieving agent self-termination would likely be an entire iteration's worth of work.

This reframing turned termination from a simple config parameter into one of the most interesting design challenges of the project. It tests whether agents can do something that even humans on Zoom calls struggle with — know when they're done.

## 12. Tech Stack Decisions

### Python + Ollama + Qwen2.5-Coder-7B

The human wanted Python as the language and preferred using open-source local models to avoid burning API credits during development. They noted they have an **AMD GPU with 8GB VRAM**.

Claude researched the current state of open-source coding LLMs and recommended **Qwen2.5-Coder-7B-Instruct** via **Ollama**. Key reasons:

- It's specifically designed for coding tasks (code generation, reasoning, fixing) and outperforms many larger models at the 7B size
- Apache 2.0 license — no restrictions
- 8GB VRAM is the sweet spot for 7B models with Q4_K_M quantization (~40+ tokens/second)
- Ollama provides an OpenAI-compatible local API (`localhost:11434`), meaning the Python code talks to the same REST interface whether hitting a local model, OpenAI, Anthropic, or anything else — model-agnostic from day one

The human confirmed they need to run `HSA_OVERRIDE_GFX_VERSION=10.3.0` for their AMD GPU (indicating an RX 6000 series or similar gfx1030-family card).

### Model-Agnostic Architecture

Claude proposed structuring the model config so swapping providers is trivial:

```python
{
  "provider": "ollama",
  "base_url": "http://localhost:11434",
  "model": "qwen2.5-coder:7b",
  "api_key": null
}
```

This means later testing with Claude, GPT-4, or other models is just a config change. One agent could even use a different model than another — an interesting future experiment.

### Honest Caveat About Small Models

Claude flagged that for Iteration 1, where agents are having a *design conversation* (not writing code), a 7B model will be noticeably less sophisticated in discussion quality than a frontier model. The sycophancy problem (instant agreement) will likely be *worse* with a smaller model. Claude framed this as useful data rather than a problem: "That's exactly the kind of failure we want to observe. Set expectations accordingly — the first conversations may be pretty shallow, and that's data, not defeat."

## 13. The Handoff: Meta-Moment

With all decisions made, the human prepared to hand implementation off to **Claude Code** (a local CLI coding agent). They asked for the narrative document to be extended, then planned to have Claude Code produce an implementation proposal and paste it back into this conversation for review.

The human explicitly called out the irony: **"See why I want to build this tool? :)"** — they were manually performing the exact PM-to-engineer, conversation-to-implementation handoff workflow that the AI SCRUM team tool is designed to automate. Copying context between Claude instances, translating design decisions into implementation specs, acting as the communication bridge between AI participants. The friction of this manual process is itself the strongest argument for the product.

This meta-moment reinforced the project's core thesis: the bottleneck in AI-assisted development isn't the AI's coding ability — it's the **coordination overhead** between participants (human or AI). The tool exists to make that coordination native and seamless.

---

## Current State (Post-Conversation, Pre-Implementation)

### All Decisions Finalized
- **Platform:** Terminal-based CLI application
- **Message format:** JSONL — `from`, `iteration`, `content`
- **Iteration tracker:** `iteration.json` with id, description, status, max_turns
- **Test project:** CLI todo list app (and likely others before advancing)
- **Agent config:** Identical system prompts to start, emphasizing collaboration and pushback
- **Turn structure:** Alternating, max turns as safety net, self-termination as a goal
- **Tech stack:** Python + Ollama + Qwen2.5-Coder-7B-Instruct
- **AMD GPU config:** `HSA_OVERRIDE_GFX_VERSION=10.3.0`
- **Model interface:** OpenAI-compatible API for future provider swapping

### Implementation Handoff
The design conversation is complete. Implementation is being handed to Claude Code locally, with the human acting as PM bridging the design context (this document) to the implementing agent. The implementation proposal will be reviewed back in the design conversation — closing the loop between design and implementation, which is itself a preview of the workflow the tool will eventually automate.

### Deferred (Intentionally)
- Message types / typed messages (add when observed as needed)
- Message threading / `ref` field (add when observed as needed)
- Agent personality differentiation (after observing identical agent behavior)
- Orchestrator / scrum master agent (Iteration 4)
- Decentralized communication / pub-sub (future, when multi-participant)
- Human dashboard / attention management (Iteration 3)
- AI evaluator agent for quality assessment (Iteration 2)
- `id` and `ts` fields on messages (add when needed)

### Key Principles Established
1. **Conversation over implementation**
2. **Fail simple, learn why**
3. **Evidence-driven schema evolution**
4. **The human is the PM**
5. **Platform is transport, protocol is product**
6. **"Iteration" not "task"** — language matters, avoid engineering baggage
7. **Self-termination as a success metric** — agents should know when they're done

---

## 14. Implementation Complete — First Code Review

Claude Code executed the implementation plan and produced a clean, working codebase. The human uploaded all source files and tests to the browser Claude instance for review. The repo was also pushed to GitHub as a public repository: https://github.com/MBifolco/gotg

### Project Structure (As Built)

```
gotg/
├── src/gotg/
│   ├── __init__.py
│   ├── cli.py          # argparse subcommands: init, run, show
│   ├── scaffold.py     # gotg init — creates .team/ structure
│   ├── agent.py        # build_prompt — the role-mapping logic
│   ├── model.py        # HTTP call to OpenAI-compatible API (~20 lines)
│   ├── conversation.py # read/append JSONL, terminal rendering
│   └── config.py       # load .team/*.json files
├── tests/
│   ├── test_agent.py
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_conversation.py
│   ├── test_model.py
│   ├── test_scaffold.py
│   └── test_smoke.py
├── docs/
├── narrative.md
├── pyproject.toml
└── README.md
```

Uses `src/` layout per modern Python packaging conventions. Single dependency: `httpx`. CLI entry point: `gotg`.

### Code Review Findings

**What was done well:**
- Remarkably disciplined code — every file does one thing, total source under 200 lines
- The role-mapping in `agent.py` is the heart of the system: each agent sees its own messages as `assistant` and the other's as `user`, allowing two LLMs to converse through a standard chat completion API without any multi-agent framework. Elegant and correct.
- `model.py` is exactly as specified — ~20 lines, raw HTTP, no SDK dependency, swappable via config
- Resume support falls out naturally from the design — if `conversation.jsonl` has existing messages, the loop picks up where it left off
- Surprisingly thorough test suite (30+ cases) covering happy paths, edge cases (empty logs, missing files, resume), and validation logic
- 120s timeout on model calls is smart for local 7B models that can be slow on first token

**Issues flagged (none blocking):**
- **Dead code in tests:** `monkeypatch_cwd` helper in `test_cli.py` does nothing. Test works anyway because it patches `find_team_dir` directly. Misleading but harmless.
- **Context window growth:** `build_prompt` sends the entire conversation history every call. Fine for 10 turns. Will hit context limits on 7B models (8K-32K tokens) when `max_turns` increases. Not a problem now — will surface naturally and indicate when to add message windowing.
- **No error handling on model calls:** If Ollama is down or returns garbage, the run loop crashes with a raw `httpx` traceback. The conversation log is safe (everything prior was flushed), and resume works. But the UX is poor. Worth a `try/except` eventually.
- **Hardcoded color map:** `AGENT_COLORS` in `conversation.py` only has entries for `agent-1` and `agent-2`. A third agent would get default white. Trivial to fix when N>2 agents are needed.

**Design observation:** The system prompt tells agents to "say so clearly and summarize what was decided" when they reach consensus, but nothing in the run loop detects this. Agents might declare consensus on turn 4, and the loop continues through turn 10 anyway — both agents awkwardly talking past the natural end of the conversation. This is intentional (self-termination is a future iteration goal) but was called out as one of the most obvious things to improve. The conversation logs from real runs will show what "consensus" actually looks like, enabling detection based on real examples rather than guessing.

### GitHub Access Attempt

An attempt was made to have the browser Claude clone the repo directly from GitHub. The repo is public and accessible via HTTP (returned 200), but `git clone` was blocked by the proxy infrastructure. Files were reviewed via direct upload instead. This is a limitation of the current Claude environment, not the repo. For future reviews, file upload remains the most reliable path.

## 15. Open Source Business Model Discussion

The human raised a tangential but strategically relevant question: how does a company like Kilo.ai (an AI coding tool) make money while open-sourcing their core product?

### The Kilo Model

Kilo follows the **open client, paid platform** pattern (a variant of "open core"):

- **Open source (free):** The VS Code / JetBrains extension — the client that runs on your machine, talks to LLMs, edits code. Fully open, Apache 2.0, on GitHub.
- **Revenue streams:**
  - **API Gateway:** Routes LLM calls through Kilo's infrastructure to 500+ models. Claims no markup on raw model pricing, but owns the billing relationship and usage data. "Kilo Pass" offers bonus credits on prepaid subscriptions — margin on float and volume.
  - **Teams & Enterprise:** Pooled credits, unified billing, admin dashboards, managed codebase indexing, AI adoption scoring, compliance/security features. This is where the real revenue is. Their pricing page explicitly states "we make money on Teams/Enterprise."
  - **Cloud compute:** Cloud-hosted agent execution, managed indexing, deployment pipelines. Compute-intensive features running on Kilo's infrastructure, not the user's machine.

### Why Open Source the Core?

The human asked: "Can't someone just change the project to not go through their proxies?" The answer is yes — and Kilo explicitly supports it. Users can bring their own API keys, point at their own providers, or run local models.

**Kilo isn't worried because those users aren't the customer — they're the distribution channel.** The path is: individual developer uses Kilo with own keys → loves it → tells their team → team lead wants to roll it out to 50 engineers → now needs centralized billing, usage tracking, access controls, compliance, onboarding → that's an enterprise purchase. Nobody is going to fork the open source project and build their own admin dashboard to avoid the enterprise tier.

The companies that get burned by open source are those whose paid value is just "hosting the open source thing" (e.g., Elastic vs. AWS). Kilo's paid value is the platform *around* the open source thing. Forking the extension doesn't give you any of that.

### Relevance to gotg

This model maps directly to gotg's potential future. The CLI tool and agent protocol could be fully open source — that's the distribution and trust layer. The monetizable value would be in the orchestration, multi-team coordination, managed model routing, team analytics, and enterprise management features that come later.

## 16. Long-Term Vision Crystallizes: Fine-Tuned Role Models & AI Engineering Orgs

The human proposed what became the most significant vision expansion in the project's history: **fine-tuning models to excel at specific team roles**, and using gotg to manage **multiple AI teams** while dogfooding the product to build itself.

### Fine-Tuned Role Models

Current AI coding tools use general-purpose models and coerce role behavior through system prompts. This works for "write code" but falls apart for softer roles. A general model prompted to be a scrum master produces a *parody* — it says the right words but doesn't actually behave like one (tracking blockers, knowing when to escalate, recognizing circular conversations).

Fine-tuned role models could be genuinely different in *how they think*, not just what they say:
- A fine-tuned **code reviewer** would naturally focus on edge cases, naming, testability
- A fine-tuned **PM** would think in terms of user impact, scope creep, trade-offs
- A fine-tuned **scrum master** would recognize process breakdowns and intervene

**The key insight:** gotg generates its own training data. The conversation logs are literally labeled examples of agents attempting to play roles. Curate the good conversations, train on them, and the models improve at their roles.

### The Dogfooding Flywheel

The human described a self-reinforcing loop:

1. Build gotg with a single team (human + 2 AI engineers)
2. Once it works, add an AI PM to the team that manages iterations for gotg itself
3. Now the human is the "group PM" overseeing an AI-managed team that's building the tool they're working inside of
4. Every conversation the team has generates training data for better role models
5. Better role models produce better conversations → better training data → better models

**The product improves itself by being used to build itself.** This is a genuine flywheel, not a marketing concept.

### Multi-Team AI Engineering Org

The natural extension: run multiple AI teams in parallel, each with their own AI PM, backlog, and velocity. The human acts as "group PM" or engineering director providing alignment across teams.

Example for gotg itself — three parallel workstreams:
- **Team A:** Agent protocol and conversation mechanics
- **Team B:** CLI experience and human interface
- **Team C:** Model integration and provider abstraction

Each team has an AI PM managing scope and AI engineers doing the work. The human checks in on each team's conversation, approves designs, resolves conflicts when Team A's interface changes break Team B's assumptions.

This isn't just dogfooding — it's a **genuinely new way of building software.** The human's role shifts from "person who writes code with AI help" to "person who leads an organization of AI teams." Which is probably where the entire industry is heading.

### Vision Reframing

This discussion marked a pivot in how the project sees itself. It evolved from:
- **Original:** "An AI coding tool with a team-first approach" (a better Cursor)
- **Evolved:** "An AI engineering org in a box" (a new category)

The tool isn't competing with Cursor or Copilot. It's building the infrastructure for a future where software is built by AI teams managed by humans, not by humans assisted by AI tools.

---

## 17. First Run: Two 7B Agents Discuss a Todo App

The first real conversation was run: two Qwen2.5-Coder-7B agents, 10 turns, discussing the design of a CLI todo list application. The iteration description was well-crafted and specific:

> "Design a CLI todo list application. Discuss the command interface (add, list, complete, delete), data storage format (JSON file, SQLite, plain text), ID scheme for todos, and core features. Consider error handling and edge cases. Produce a clear, actionable design document by the end of the conversation."

The system prompt had been improved by Claude Code between the initial scaffold version and the first run, adding more explicit instructions about staying in design mode and pushing back on proposals.

### What Happened (Turn by Turn)

**Turn 1 (agent-1):** Dumped an entire complete design document in one message. Covered commands, storage, IDs, features, error handling — and made every decision unilaterally. Didn't ask a single question. The 7B model treated "initial thoughts" as "write the whole thing."

**Turn 2 (agent-2):** Opened with "Your proposed design document provides a clear roadmap" — immediate capitulation. Added some useful points about concurrency and scalability, but framed them as additions to an already-approved plan, not challenges.

**Turn 3 (agent-1):** "Great job refining..." — mutual congratulation. The design conversation was effectively over by turn 3.

**Turns 4-10:** Progressively worse. Agents started writing implementation code, unit tests, deployment scripts, and README documentation. By turn 10, agent-2 was producing a full `setup.py` and integration test plan. They completely ignored "reach consensus before writing code" and performed an unrequested pair-programming session.

### Claude Code's Analysis

Claude Code (which observed the run locally) provided its own assessment:

- **Improved from baseline:** Turn 2 actually engaged with agent-1's proposal somewhat — "let's go through each component" and raised concurrency/scalability points. The tradeoff discussion (JSON vs SQLite vs plain text) got real consideration.
- **Still broken:** Agent-2 agreed immediately. Jumped to implementation by turns 4-5 despite explicit instructions not to. Turns 7-10 were circular "great summary, let's implement" dead air.
- **Root cause:** "The 7B model just doesn't have enough reasoning depth to sustain genuine disagreement."

### Browser Claude's Analysis

The browser Claude instance did a deeper turn-by-turn analysis and identified three structural problems:

**Problem 1: First-mover monopoly.** Agent-1 proposes everything in turn 1, leaving agent-2 nothing to do but agree. The seed prompt ("What are your initial thoughts?") plus a 7B model's tendency to be exhaustively helpful means the first agent tries to solve the entire problem in one shot. **Possible fix:** Constrain the seed — "What's the first design decision we should make? Pick ONE aspect and propose your approach."

**Problem 2: Sycophancy is structural, not just prompt-fixable.** The system prompt says "don't just agree" but the 7B model can't help itself. This isn't a prompt engineering problem at this model size — it's a capability limitation. The model doesn't have the reasoning depth to hold a contrary position when presented with a plausible-sounding plan. **Possible fixes:** Try a bigger model, give agents explicit contrary instructions ("find at least two problems with every proposal"), or give agents different priorities (one optimizes for simplicity, the other for extensibility).

**Problem 3: No concept of conversation phases.** Agents don't distinguish between "we're still discussing" and "we've decided." They slide from design into implementation without transition. The model interprets "consensus" as "the other person said something reasonable." **Possible fix:** This might be where a `type` field on messages starts earning its keep — not for agents to read, but for the system to enforce conversation phases.

### Key Takeaway

The protocol works. The infrastructure works. The role-mapping works. The conversation log captured exactly what happened and is perfectly readable. The *model* isn't up to the task of genuine deliberation at 7B. This confirms the prediction from the design conversation: "the sycophancy problem will likely be worse with a smaller model... that's exactly the kind of failure we want to observe."

The most important next experiment: run the same setup with a frontier model to separate "is the tool broken?" from "is the model too small?"

## 18. The Multi-Agent Prompt Format Problem

The first run's results naturally led to a forward-looking architectural discussion. The human raised a critical question: **when we go beyond two team members, will the standard system/assistant/user format be an issue?**

### The Core Problem

The current `build_prompt` function does a binary mapping: my messages → `assistant`, everything else → `user`. With two agents that's a clean conversation. With three agents (A, B, C), from A's perspective:

```
A's message  → assistant
B's message  → user
C's message  → user
```

The model sees B and C as the same speaker. It can't distinguish between them. If B proposes something and C critiques it, agent A sees "the user" contradicting themselves. The model loses track of who holds which position, who agreed with whom, and what the actual state of consensus is. It gets worse with a human PM — directives carry different authority than peer suggestions, but the model sees them all as `user`.

### Five Approaches Identified

**Approach 1: Name-prefix in content (simplest hack)**
Stuff speaker identity into the message content: `{"role": "user", "content": "[agent-2]: I think we should use SQLite..."}`. Hacky, but models are surprisingly good at tracking named speakers. This is how most multi-agent frameworks actually work under the hood. Works with every provider.

**Approach 2: The `name` field in OpenAI's format**
The OpenAI chat API supports an optional `name` field: `{"role": "user", "name": "agent-2", "content": "..."}`. Cleaner, but not all providers support it, and model behavior with `name` is inconsistent.

**Approach 3: Structured conversation as single context**
Instead of mapping history to individual messages, feed the entire conversation as one formatted `user` message. The model always sees a complete log and responds as itself. Sidesteps the binary role format entirely. Tradeoff: loses the model's built-in turn-taking behavior.

**Approach 4: The "narrator" approach (the human's suggestion)**
The human proposed mimicking how they'd been working throughout this project — relaying what other participants said in natural language:

```
Content: "Ok so agent-1 said 'use JSON for storage' and then agent-3 said 'no, use SQLite for querying'"
```

This is subtly different from the structured log (Approach 3). It's *narrative*, not documentary. It's how a human relays a conversation to a colleague — contextualizing, emphasizing what matters, naturally summarizing.

**Approach 5: Multi-party conversation APIs (future)**
Some newer APIs are starting to support actual multi-party formats. Not broadly available yet.

### The Narrator Layer: A Potentially Significant Architecture

The narrator approach evolved into something deeper during discussion. Rather than just a prompt formatting trick, it implies a **narrator layer** — a function (or eventually an agent) that sits between the conversation log and the model, constructing a briefing for each participant.

The prompt construction would look like:

```python
{"role": "system", "content": "You are agent-2, a software engineer..."},
{"role": "user", "content": 
    "Here's what's happened in the conversation so far:\n\n"
    "agent-1 proposed using JSON for storage. They said:\n"
    "\"I think JSON is the simplest option, we can always migrate later.\"\n\n"
    "agent-3 pushed back and said:\n"  
    "\"SQLite gives us querying for free, and it's still a single file.\"\n\n"
    "What are your thoughts?"
}
```

The agent is always `assistant`. There's always one `user` message that's the narrator — the "room" telling the agent what's been said and asking for input. The system does what the human has been doing manually throughout this project: being the PM who relays context between team members.

Properties that make this approach compelling:

1. **It's how humans actually coordinate.** Nobody reads raw meeting transcripts. Someone summarizes: "So-and-so said X, someone else disagreed because Y, we need your take."

2. **It enables selective context.** The narrator can summarize older turns and only quote recent ones verbatim. "Earlier the team agreed on JSON storage. In the last round, agent-1 said: '...'" This is natural context windowing without arbitrary truncation.

3. **It provides a place for meta-instructions.** The narrator can say "agent-1 and agent-3 disagree — what's your view?" or "the PM asked the team to finalize this decision this round." Process guidance is injected naturally, not through system prompt hacks.

4. **It separates the conversation record from the prompt.** The JSONL log stays clean and complete. The prompt is a *rendering* of the log, tailored for each agent's perspective. Different participants could receive different renderings — the PM gets a summary, the engineer gets full technical quotes.

5. **It's where intelligence about context management, role awareness, and attention management eventually lives.** The narrator is effectively the orchestrator — it decides what each participant needs to know and how to frame it.

### Decision: Try All of Them

Rather than picking one approach upfront, the decision was to experiment with all of them. Each will fail differently and teach something different. The conversation logs will reveal which approach produces the best actual team dynamics. This is consistent with the "fail simple, learn why" principle — but now applied to prompt architecture rather than schema design.

The key architectural insight: **the conversation log format doesn't need to change for any of these approaches.** The JSONL log is already multi-party. It's only the prompt construction in `agent.py` (the rendering from log to model input) that adapts. The log is the source of truth; the prompt is a view of it.

## 19. Scaling Up: Bigger Local Model, Then Sonnet

The first run with Qwen2.5-Coder-7B confirmed the protocol worked but the model couldn't sustain genuine deliberation. The next step was to try a larger local model to see if scale alone fixed the sycophancy problem. It didn't help much — the bigger local model showed the same patterns of premature agreement and sliding into implementation.

This led to a significant infrastructure decision: **add Anthropic API support to gotg.** The tool was designed to be model-agnostic from day one, so the provider abstraction held up — adding an Anthropic provider meant the same conversation protocol could now run against Claude Sonnet.

The result was dramatic.

## 20. Second Run: Two Sonnet Agents Discuss a Todo App

Same iteration, same system prompts, same 10-turn limit, same todo list design task. Two Claude Sonnet agents instead of two 7B agents.

### What Happened: A Real Design Conversation

**Turn 1 — Agent-1 asks questions instead of answering them.** This alone was the single biggest behavioral difference from the 7B run. Instead of dumping a complete design document, agent-1 opened with "Before I propose anything, I want to understand the requirements and constraints better" and listed clarifying questions about scale, portability, features, and command style. It shared initial leanings (JSON, auto-increment IDs, git-style subcommands) but framed them as open positions with explicit tradeoffs, ending with "What are your thoughts on these questions and initial directions?"

The 7B agent treated "initial thoughts" as "solve the entire problem." Sonnet treated it as "start a conversation."

**Turn 2 — Agent-2 genuinely disagrees.** "I partially disagree on JSON" — not a nitpick, not a hedge, a substantive architectural challenge. Agent-2 made a concrete case for SQLite based on data corruption risks, concurrent access safety, and future-proofing. It directly addressed agent-1's reasoning and explained why the tradeoffs favored a different choice. It also pushed the conversation forward by raising new questions: "What happens if someone runs `todo add` and `todo complete` in separate terminals at the same time?"

**Turn 3 — Agent-1 changes position based on evidence, then pushes back on something else.** "You've convinced me on SQLite, and I think you're right about the corruption risk." A genuine position change — not capitulation, but persuasion. Then agent-1 pivoted to push back on the ID scheme, proposing display position vs. persistent ID. Remarkably, agent-1 **talked itself out of its own proposal mid-message**: "Actually, as I'm writing this out, I'm talking myself out of it. The position approach is too magical and error-prone." Real-time reasoning, visible in the conversation.

**Turn 4 — Both agents building, not just agreeing.** Agent-2 confirmed the ID decision, proposed a display format, then worked through five detailed command interface questions. Each one was posed as a genuine open question with arguments for different approaches.

**Turn 5 — Strong disagreement on a core design decision.** Agent-1 said "I'm going to push back hard here" on the delete workflow. Agent-2 had proposed simple hard delete with no recovery. Agent-1 made a compelling case for soft delete with specific failure scenarios (typo deleting wrong task, script bugs). The argument was structured, the stakes were clear, and the position was held firmly.

**Turn 6 — Genuine persuasion.** Agent-2 opened with "You're making me rethink this. Let me work through your argument carefully because I think you're right." Not instant agreement — a visible process of evaluating the argument and arriving at a new position. Agent-2 then added implementation specifics (schema impact, filtering matrix) that improved on the original proposal.

**Turns 7-9 — Refinement and resolution.** The agents worked through remaining decisions: language choice (Go), error handling patterns, database location, edge cases. Each turn produced real decisions with real rationale. Disagreements were resolved through argument, not deference. Agent-1 pushed back on filtering composability; agent-2 pushed back on database file location.

**Turn 10 — A team artifact, not a unilateral dump.** Agent-2 produced a comprehensive design document. But unlike the 7B run where agent-1's turn-1 monologue became the de facto plan, this document reflected 10 turns of genuine deliberation. Every decision had a history: SQLite was chosen because agent-1 was persuaded by corruption risk arguments. Soft delete was chosen because agent-1 made a compelling case that changed agent-2's mind. The ID scheme survived because agent-1 stress-tested it and found the alternative wanting.

### Comparative Analysis: 7B vs Sonnet

| Dimension | 7B Run | Sonnet Run |
|-----------|--------|------------|
| **Turn 1 behavior** | Complete design document, all decisions made | Clarifying questions, open positions with tradeoffs |
| **First disagreement** | Never (substantive) | Turn 2 — "I partially disagree on JSON" |
| **Position changes** | None meaningful | Multiple — SQLite, soft delete, filtering, DB location |
| **Self-persuasion** | None | Turn 3 — agent talks itself out of own proposal |
| **"Push back hard"** | Never | Turn 5 — firm disagreement on delete workflow |
| **Code written** | Turns 4-10 (majority of conversation) | Turn 10 only (implementation notes in design doc) |
| **Conversation phases** | Instant consensus → unasked implementation | Questions → debate → refinement → documentation |
| **Final artifact** | Agent-1's turn-1 monologue, unmodified | Team document reflecting 10 turns of decisions |
| **Stayed in design mode** | No — wrote code, tests, README, setup.py | Yes — remained in design discussion throughout |

### What This Proves

**The protocol works.** The same conversation format, the same JSONL log, the same turn structure, the same system prompts produced two radically different outcomes. The only variable was the model. This validates the core architectural bet: the tool is the protocol and the conversation format, not the model. When the model is capable enough to hold a position, disagree substantively, and track conversational state, the protocol produces exactly the team dynamic the project was designed to enable.

**Sycophancy is a model capability problem, not a prompt problem.** The system prompt told both models to push back and not just agree. The 7B model couldn't do it. Sonnet could. No amount of prompt engineering would have given the 7B model the reasoning depth to say "I'm going to push back hard here" and sustain a multi-turn argument about soft delete.

**The quality ceiling is the model, but the quality floor is the protocol.** Even with Sonnet, a bad protocol (no turn structure, no iteration context, no conversation history) would produce worse results. The protocol provides the scaffolding; the model provides the intelligence. Both matter.

**The design document is better because it was debated.** The Sonnet agents' final design document covers edge cases (operating on deleted items, concurrent modifications, empty results) that emerged from genuine back-and-forth. These aren't things one agent would think of in a monologue — they're the product of adversarial collaboration. This is exactly what the "conversation over implementation" principle predicted.

### Implications for the Project

This run changes the development calculus. With a capable model, gotg produces genuinely useful design conversations. The next questions become:

1. **Can we get closer to this quality with cheaper/local models?** The narrator approach, constrained seeds, and role differentiation become experiments worth running — not to match Sonnet, but to close the gap.

2. **What happens with three agents?** The two-agent conversation was rich. Adding a third voice (PM, devil's advocate, domain specialist) could make it richer — or could dilute it. The multi-agent prompt format experiments are now more urgent.

3. **Can the human participate mid-conversation?** The PM should be able to drop in at turn 5 and say "I like the SQLite direction, but let's keep v1 simpler — skip the soft delete for now." The protocol supports this (just append to the JSONL log), but the UX doesn't exist yet.

4. **Self-termination becomes realistic.** The Sonnet agents naturally converged — by turn 9 they were doing final checklists. With a capable model, detecting consensus and ending the conversation automatically is now a tractable problem, not a fantasy.

## 21. The Evaluation Problem

With the Sonnet run proving the protocol can produce genuinely good conversations, the next question became: **how do you know a conversation was good?** Not by gut feel — consistently, comparably, across runs. This matters both for development (is this prompt change better?) and for the long-term vision (if users run thousands of conversations, which ones produced good outcomes?).

### Four Layers of Evaluation

The evaluation framework has four layers, each depending on the ones below, but with value flowing from the top:

**Layer 1: Process Quality** — Was the conversation good?

This is the most novel dimension. Nobody has good benchmarks for multi-agent design deliberation. The signals include: did agents disagree substantively when warranted? Did positions change based on evidence? Did they maintain phase discipline (staying in design mode vs. sliding into implementation)? Did they converge naturally rather than one agent capitulating? Was contribution balanced (not first-mover monopoly)?

The tricky nuance: a conversation where agents agree immediately could mean sycophancy *or* could mean the first proposal was genuinely good. Debate length isn't inherently a quality signal. The evaluation needs to assess whether disagreement was *warranted* and whether it happened when it should have.

**Layer 2: Artifact Quality** — Is the output good on its own merits?

Architecture: does the design handle edge cases, justify decisions with tradeoffs, maintain internal consistency, scope appropriately? Code: correctness, tests, readability, maintainability. This layer is more established territory — existing code quality tools and design review rubrics apply.

**Layer 3: Coherence** — Do the artifacts fit together?

Architecture-code fit: does the code implement what was designed? If the team debated soft delete for four turns, is there a `deleted_at` column? Conversation-architecture fit: does the design doc reflect what was actually debated, or did the summarizing agent inject decisions that were never discussed? Cross-iteration coherence: do later iterations build on earlier decisions?

**Layer 4: Alignment** — Does it serve the actual goal?

Product vision fit: did the team solve the right problem? The Sonnet agents chose Go — technically defensible, but if the PM's vision required Python ecosystem integration, it's the wrong answer no matter how well-reasoned. Scope discipline: did they stay within iteration boundaries? PM directive adherence: when the human said something, did it stick?

Each layer depends on the ones below being measurable, but nobody cares about conversation quality if the product doesn't serve the vision. Layer 4 is the most important and the hardest to automate.

### Evaluation Approach: Manual First, Then Automate

The plan is to evaluate manually first to build intuition and develop a rubric, then automate once the rubric is trusted. This follows the same evidence-driven pattern as the rest of the project — don't automate what you don't understand yet.

The 7B-vs-Sonnet comparison serves as the first calibration: score both conversations on the rubric, verify the scores match intuition, refine. If the rubric can't clearly distinguish the 7B sycophancy-fest from the Sonnet deliberation, it's not a useful rubric.

For automation, an LLM evaluator is the natural tool — poetically, an AI evaluating an AI team's conversation. But it needs calibration against human judgment before it's trusted.

### Training Data for Conversation Quality Evaluation

A key question arose: are there existing datasets that could help train or fine-tune a model to evaluate conversation quality?

**What exists but doesn't quite fit:**

Stack Overflow has quality signals (accepted answers, upvotes, view counts) but SO threads are Q&A, not collaborative deliberation. A top-voted answer isn't a *conversation* — it's a popularity contest among monologues.

**Closer proxies:**

**Wikipedia Talk Pages** may be the best existing analog. Editors debate content, structure, and accuracy on Talk pages, and articles have quality ratings (Featured, Good, B, C, Start, Stub). A Featured Article with extensive Talk page debate gives you a conversation that *produced* a measurably high-quality artifact. The data is public and massive.

**Code review data (GitHub PRs, Gerrit)** provides review threads where positions change and code evolves through discussion. The signal is whether the PR was merged and the delta between initial submission and final version. Google's Gerrit data (Chromium, Android) is particularly rich with formal approve/reject signals.

**RFC and design doc discussions** from open source projects are the closest match to what gotg produces. Python PEP discussions, Rust RFC threads, Go proposal discussions — these are literal design conversations with binary outcomes (accepted/rejected). Discussion dynamics can be correlated with outcome quality.

**Debate datasets** (Kialo, IBM Debater) have explicit quality annotations but are adversarial (win/lose) rather than collaborative (converge). The mechanics of "substantive disagreement" and "evidence-supported positions" transfer, but the goal structure doesn't.

**The gap:** None of these datasets are labeled for *conversation quality* specifically. They have outcome quality signals used as proxies. The assumption that good outcomes imply good conversations is mostly but not always true.

**The real play:** gotg generates its own training data. Run conversations, manually evaluate them, score on the rubric. After 50-100 scored conversations, you have a labeled dataset of exactly the task distribution you care about. Bootstrap with proxy datasets (Wikipedia Talk + article quality, or GitHub PRs + merge outcomes) for a baseline evaluator, then fine-tune on gotg's own data as it accumulates.

### Implicit Quality Signals from User Behavior

The most important insight in this discussion: **you don't need users to rate conversations explicitly.** Their behavior carries signal.

**Strong positive signals:**
- Human takes the design doc and starts implementing
- Human copies code snippets from the conversation
- Human starts a new iteration referencing decisions from the previous one
- Human lets the full conversation run without interruption

**Strong negative signals:**
- Human re-runs the same iteration with different agents or models
- Human manually edits the design doc after the conversation (team got it wrong)
- Human abandons an iteration partway through
- Human injects a correction at turn 2-3 ("no, that's completely wrong")

**Subtle signals:**
- How far into the conversation before the human interjects
- Whether they re-read the log later (via `gotg show`)
- Whether they share the conversation
- Time between conversation completion and next action

These signals are all observable from within the tool. No rating button needed — just instrument what the human does after the conversation. This is the Google Search insight applied to AI team coordination: don't ask users to rate results, watch which results they act on and whether they come back to re-search.

### Human Message Sentiment as Direct Signal

The richest quality signal may be the simplest: **what did the human actually say when they intervened?** Unlike behavioral signals that require inference, the human's words directly express their evaluation. And it's granular — a re-run tells you the whole conversation failed, but "this is great, one small tweak on the error handling" tells you turns 1-7 were good and turn 8 missed something specific.

Human interventions map naturally to a sentiment spectrum:

- "Perfect, let's implement this" → strong positive, full conversation validated
- "This is great, one small tweak" → positive with localized correction
- "I like the direction but you're overcomplicating the storage layer" → partial positive, structural issue
- "Let's back up — you skipped the most important decision" → process failure, agents missed something
- "You're off the rails here" → strong negative, fundamental misalignment
- "No. Stop. We're building a CLI tool, not a distributed system." → vision drift, scope explosion

The sentiment maps to different evaluation layers. "One small tweak" is a Layer 2 issue (artifact quality). "You skipped the most important decision" is Layer 1 (process quality). "We're building a CLI tool, not a distributed system" is Layer 4 (alignment). A classifier trained on human interventions could not only score conversation quality but *diagnose which layer failed*.

Even more valuable: the human's message combined with what agents do *after* the correction is a compound signal. Do they course-correct cleanly? Do they over-correct and become sycophantic? Do they absorb the feedback into the next three turns or forget it by turn 8? This measures conversation *resilience* — how well the team responds to PM feedback. Which is arguably the most important team dynamic to get right.

### The Flywheel

This feeds the flywheel: users use the tool normally → their behavior generates implicit labels → their words generate explicit, granular labels → labels train the evaluator → evaluator improves the tool → better tool produces more/better conversations → more training data.

The `.team/` directory already contains the raw data for most of these signals. It just needs to be instrumented.

---

## Current State (Post-Sonnet-Run)

### What Exists
- Working Python CLI tool (`gotg`) installable via pip
- Three commands: `init`, `run`, `show`
- JSONL conversation log with `from`, `iteration`, `content`
- Alternating turn-based agent conversation with max turn ceiling
- OpenAI-compatible model interface (local Ollama or any provider)
- Anthropic API provider support
- 30+ tests passing
- Public GitHub repo: https://github.com/MBifolco/gotg
- Two conversation logs: 7B run (sycophantic) and Sonnet run (genuine deliberation)

### Key Findings
- The protocol produces genuine team dynamics when the model is capable enough
- 7B models can't sustain disagreement; Sonnet can argue, persuade, and change positions
- The quality ceiling is the model; the quality floor is the protocol
- Bigger local models didn't close the gap — the jump to frontier models was necessary
- Design documents produced through debate are substantively better than monologues

### What's Next
- **Riskiest hypothesis first:** Solve the N>2 prompt format problem and test with human as third participant
- Develop manual evaluation rubric using 7B-vs-Sonnet comparison as calibration
- Experiment with prompt approaches to improve local model quality (narrator, constrained seeds, role differentiation)
- Investigate self-termination detection now that Sonnet shows natural convergence patterns

### Deferred (Intentionally)
- Message types / typed messages (add when observed as needed)
- Message threading / `ref` field (add when observed as needed)
- Agent personality differentiation (after observing identical agent behavior)
- Self-termination detection (after observing what "consensus" looks like in practice)
- Narrator layer implementation (after experimenting with prompt format approaches)
- Automated evaluation (after manual rubric is trusted)
- Implicit signal instrumentation (after evaluation framework is validated)
- Model capability threshold testing (after evaluation rubric exists)
- Orchestrator / scrum master agent (Iteration 4)
- Decentralized communication / pub-sub (future, when multi-participant)
- Human dashboard / attention management (Iteration 3)
- `id` and `ts` fields on messages (add when needed)
- Error handling on model calls (add when it becomes annoying)
- Context window management / message windowing (add when turns increase)
- Fine-tuned role models (long-term vision)
- Multi-team orchestration (long-term vision)

### Key Principles Established
1. **Conversation over implementation**
2. **Fail simple, learn why**
3. **Evidence-driven schema evolution**
4. **The human is the PM**
5. **Platform is transport, protocol is product**
6. **"Iteration" not "task"** — language matters, avoid engineering baggage
7. **Self-termination as a success metric** — agents should know when they're done
8. **Open source the core, monetize the platform** — distribution through openness, revenue through coordination
9. **The product builds itself** — dogfooding as a flywheel for training data and product improvement
10. **The log is the source of truth; the prompt is a view of it** — conversation format and prompt format are independent concerns
11. **The quality ceiling is the model; the quality floor is the protocol** — both matter, neither is sufficient alone
12. **Observe behavior, don't ask for ratings** — implicit signals from what users do after a conversation are more reliable than explicit feedback
