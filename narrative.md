# AI SCRUM Team — Conversation History & Project Development Log

**Date:** February 5-6, 2026  
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

## 22. End-to-End Teams: From Conversation to Code

A question about Claude Code's architecture — it's built in TypeScript with React/Ink for the terminal UI — led to a broader discussion about tool access. Claude Code gives its model tools (file read/write, bash, grep, git) and the model decides which to call. The "intelligence" is the model; the tools are just hands.

### The Tool Access Question

Currently, gotg agents converse but don't act. The Sonnet run produced a design document through pure conversation — no agent needed to read a file or run a command. But the vision is teams that build real products end-to-end: design, implement, test, deploy. That requires tool access.

The key insight: **agents that can't converse well will use tools poorly.** The 7B agents would have spent their tool access writing setup.py nobody asked for. The Sonnet agents would have produced focused code implementing their debated design. Conversation quality *gates* tool quality. This means the sequencing matters:

1. **Get team dynamics right** — conversation, multi-agent, human participation
2. **Give them hands** — file I/O, bash execution
3. **Give them full autonomy** — git, testing, deployment, CI/CD

Each layer only works if the one below it is solid.

### Human vs. Agent Tool Access

The end-to-end vision also clarifies the different roles humans and agents play. In a real engineering org, senior engineers don't write most of the code — they review it, set direction, unblock decisions, maintain standards. The human in a gotg team isn't writing code either. They're doing what the human PM has been doing throughout this project: setting vision, making scope calls, evaluating output, redirecting when things drift. The human contribution is *judgment*, not labor.

This means tool access for humans is different from tool access for agents. Agents need file write and bash. Humans need the ability to read conversations, approve designs, review diffs, and say "ship it" or "try again." Two different interfaces to the same team.

## 23. Dogfooding as Survival: Building gotg with gotg

The most significant reframing in the project's history emerged from a simple constraint: **the human has no other humans available.** Building gotg requires multiple parallel workstreams — agent protocol, evaluation framework, API integration, CLI experience — and there's one person to do it all.

This changes the priority stack dramatically. Multi-team isn't a "long-term vision" item — it's a near-term necessity. The human needs:

- A team working on the agent protocol (the N>2 prompt format problem)
- A team working on the evaluation framework
- A team working on Anthropic API integration and provider abstraction
- A team on the CLI experience

The human is PM across all of them. They check in on each team's conversation, make scope calls, resolve cross-team dependencies when the protocol team's changes affect how the evaluation team reads conversation logs.

### First Customer, First User, First Test

gotg's first real user isn't some hypothetical developer — it's the builder, right now, building gotg. Every pain point hit is a real product requirement, not a speculated one. If the tool can't support one human running three parallel AI teams to build itself, it doesn't work.

This resolves a common solo-founder trap: doing everything sequentially means years of work. Running parallel AI teams means weeks — *if* the teams are good. The entire value proposition of gotg is that a single human can run multiple AI teams simultaneously. The builder is the proof of concept and the first customer.

### The Bootstrap Problem

There's a beautiful irony: you need the multi-team feature to build the multi-team feature. The very first version has to be just good enough — manual, hacky, multiple `.team/` directories, checking each one by hand — to bootstrap the better version. The tool doesn't need to be polished to be used. It needs to be functional enough to help build itself.

This is the ultimate expression of the dogfooding flywheel:

1. Use gotg (however rough) to run AI teams building gotg
2. Hit real pain points → these become the next iteration's priorities
3. AI teams discuss and design solutions to those pain points
4. Human PM approves designs, teams implement
5. gotg improves → run more/better teams → hit subtler pain points → repeat

The product roadmap isn't speculated — it's *experienced*. And the development strategy isn't "build, then find users" — it's "be the user while building."

### Vision Reframing (Again)

This marks another evolution in how the project sees itself:

- **v1:** "An AI coding tool with a team-first approach" (a better Cursor)
- **v2:** "An AI engineering org in a box" (a new category)
- **v3:** "A tool that a solo human uses to run an AI engineering org that builds the tool" (a self-constructing category)

The competitive moat isn't the protocol or the CLI or the evaluation framework. It's that the tool is being built by the process it enables. Every improvement to gotg makes the process of improving gotg faster. No competitor can replicate that flywheel without building the same thing.

## 24. Implementation: Human Participation & N>2 Support

Claude Code produced a clean implementation plan for the riskiest hypothesis: adding a third participant (the human PM) and solving the N>2 prompt format problem.

### What Was Built

**`gotg continue` command:** Stop the conversation, inject a human message, resume. The human appends a message to the JSONL log and the agents continue from where they left off. Usage: `gotg continue -m "Good ideas but account for auth later" --max-turns 2`.

**Name-prefix format for multi-party:** Non-self messages get prefixed with the speaker's name: `[agent-1]: content`. The agent's own messages stay clean as `assistant` role. This was Approach 1 from the earlier discussion — simplest thing that works, every provider supports it.

**Dynamic teammate list:** The system prompt now tells each agent who their teammates are and their roles: "Your teammates: agent-2 (Software Engineer), human (Team Member)."

**`--max-turns` override:** Both `run` and `continue` accept a turn limit override, and human messages don't count toward the agent turn budget.

**Role field on agent configs:** Each agent config now has a `role` field (defaulting to "Software Engineer"). The human is labeled "Team Member" — intentionally generic to start, avoiding premature authority hierarchy.

### Design Decisions

The implementation chose name-prefixing (Approach 1) over the narrator approach (Approach 4) or consolidated context (Approach 3). This was the right first move — minimal change, backward compatible, isolates the multi-party variable from prompt architecture changes. The fancier approaches remain available for later experimentation.

The `continue` command is a Unix-philosophy solution: composable, scriptable, no complex mid-conversation UI. It maps naturally to the PM workflow — read the conversation, decide whether to intervene, inject a message, let the team continue.

## 25. Three-Party Run: Human PM with Two Sonnet Agents

The first three-party conversation was run: two Sonnet agents discussing the CLI todo list design, with the human injecting a PM message after the first two agent turns.

### What Happened

**Turns 1-2 (agents only):** The agents followed the same strong pattern as the pure Sonnet run — agent-1 asked clarifying questions, agent-2 engaged substantively, proposed SQLite over JSON with a real argument about corruption risks, pushed back on ID reuse.

**Turn 3 (human injection):** The PM injected: "I think these are good ideas but we should account for the need to do authentication later even though we won't implement it now. Also, I'd like you to consider using TOML for config instead of JSON - it's more human-friendly."

**Turn 4 (agent-1 responds to PM):** Agent-1 handled the PM input well. It asked clarifying questions about the auth scope ("What authentication model are you envisioning?"), pushed back appropriately ("Are we over-engineering? What's the likelihood of actually adding auth?"), and made an insightful distinction the PM hadn't — separating config files from data storage, agreeing TOML is better for config but arguing SQLite should remain for data.

**Turn 5 (agent-2 synthesizes):** This was the most interesting turn. Agent-2 didn't just respond to the PM or to agent-1 — it synthesized across all three participants. It took the PM's auth concern, filtered it through agent-1's "are we over-engineering?" challenge, and produced a scoped recommendation: "Let's just use proper user directories and call it 'authentication-ready.' We're not adding any code complexity, just being thoughtful about file locations." Then explicitly: "We should NOT add unused `user_id` columns or authentication stubs. YAGNI applies here."

This is a three-party interaction working correctly. The PM set direction, engineer 1 stress-tested it, engineer 2 synthesized a pragmatic middle ground. The PM's input carried weight (they didn't ignore it) but wasn't treated as gospel (they scoped it down).

### Attribution Confusion: A Subtle Behavioral Issue

Agent-2's turn 5 contained a telling phrase: "You raise a valid concern about over-engineering. Let me be more specific about what I'm thinking."

The "you" addressed agent-1 correctly. But "what I'm thinking" implies agent-2 had prior thoughts on authentication. It didn't — the *human* raised auth, and agent-2 had never mentioned it. This is ownership language applied to someone else's idea.

Tracing the conversation flow from agent-2's perspective: it saw agent-1's initial thoughts (user), its own response about SQLite/IDs (assistant), the human's message about auth/TOML (user), and agent-1's analysis of the human's points (user). Agent-2 never discussed auth before turn 5, yet spoke as if clarifying its own prior position.

This is likely genuine attribution confusion rather than loose language. The model partially conflated the human's input with its own internal state. The name prefix helps track *who* to address but may not fully prevent the model from absorbing another participant's position as its own.

This was flagged as an important signal for automated evaluation. Attribution accuracy — does each agent correctly track who originated which idea? — may need to be its own dimension in the evaluation rubric. This matters because if agents lose track of idea ownership in larger teams, consensus tracking breaks down. The team might think they've agreed on something when actually one agent is claiming credit for a position that was never theirs.

### Debug Log Analysis: Root Causes

Examining the actual prompts sent to the model (debug.jsonl) revealed several contributing factors:

**1. System prompt inconsistency.** The system prompt still opened with "You are a software engineer working on a team with **one other engineer**" but the teammate list at the bottom showed two teammates. The scaffold update was supposed to change this to "a collaborative team" but the old text persisted. The model received contradictory information about team size.

**2. Vague human role.** The teammate list showed "human (Team Member)" — carrying zero authority signal. The model had no reason to treat the human's input differently from a peer's. This was intentional for this run (isolate the multi-party variable before introducing authority hierarchy), but it likely contributed to the model absorbing the human's ideas as its own rather than attributing them to a PM.

**3. Consecutive `user` messages — the key finding.** From agent-2's perspective, the message sequence was:

```
system:    You are a software engineer...
user:      [agent-1]: Great! Let's work through this...     ← turn 1
assistant: Great approach! Let's work through these...       ← agent-2's own turn 2
user:      [human]: I think these are good ideas...          ← human injection
user:      [agent-1]: Great points! Let me address...        ← turn 4
```

Two consecutive `user` messages. The human's message and agent-1's response were both `role: user`, delivered as separate messages back-to-back. This blurs the boundary between speakers. The model may partially merge consecutive same-role messages, especially since agent-1's response was *about* the human's message. The topic (auth) flowed across both `user` messages, making it easy for the model to internalize the topic as general conversation context rather than tracking its provenance.

**4. Self-prefix leak.** Agent-2 prefixed its own response with `[agent-2]:`, mimicking the name-prefix format it saw on incoming messages. The model treated the formatting convention as conversational style rather than system-level metadata. Minor but worth fixing.

### Decision: Consolidated User Messages

The fix for the consecutive `user` message problem: **aggregate all messages since the agent's last turn into a single `user` message with clear speaker labels inside.**

Instead of:
```
user: [human]: I think these are good ideas...
user: [agent-1]: Great points! Let me address...
```

The agent sees:
```
user: [human]: I think these are good ideas but we should account for...

[agent-1]: Great points! Let me address both of these...
```

One `user` message containing everything that happened since the agent's last turn, with speaker identity preserved through labels inside the content. This solves several problems simultaneously:

- No consecutive same-role messages regardless of participant count
- Clear delineation between speakers within a single context block
- Naturally handles any number of participants (four people speak between turns? One `user` message with four labeled sections)
- May reduce the self-prefix leak (the format pattern only appears inside `user` content, not on message boundaries)
- Steps toward the narrator approach without committing to it — same structure, just not yet summarizing or contextualizing

This is the next experiment to run. If consolidated messages fix the attribution confusion, the name-prefix approach may be sufficient for multi-party. If not, the narrator approach (which explicitly frames "the PM raised the auth concern") becomes the next thing to try.

## 26. Consolidated Messages: Attribution Fixed, Quality Improved

The consolidated message format was implemented and tested. Instead of sending each participant's message as a separate `user` message, all messages since the agent's last turn are aggregated into a single `user` message with speaker labels inside.

### What Changed in the Prompt

The system prompt was also improved:
- "one other engineer" → "a collaborative team"
- Added: "Your name is agent-1."
- Added: "You may get messages from more than one teammate at a time. You'll know because a teammate's message will be prefixed by '[teammate-name] add the following to the conversation:'"

The consolidated `user` message now looks like:

```
[human] add the following to the conversation:
I think these are good ideas but we should account for...

[agent-1] add the following to the conversation:
Thanks for those inputs! Let me address both points...
```

One `user` block. Clean separation. No consecutive same-role messages.

### Results: Three Problems Fixed

**1. Attribution confusion eliminated.** Compare agent-2's responses across the two three-party runs:

Previous run (separate `user` messages): "You raise a valid concern about over-engineering. Let me be more specific about **what I'm thinking**" — ownership language for the human's idea.

Consolidated run: "When **human** says 'authentication,' are we talking about..." and "**human**, can you be more specific about the authentication use case?" — correct, explicit attribution throughout. Agent-2 tracked exactly who raised which concern and addressed each participant by name.

**2. Self-prefix leak eliminated.** Agent-2 no longer starts its response with `[agent-2]:`. The prefix pattern now only appears inside consolidated `user` messages, so the model doesn't mimic it in `assistant` output.

**3. System prompt consistency fixed.** "Collaborative team" language now matches the dynamic teammate list. No more contradiction between "one other engineer" and a three-person team roster.

### Conversation Quality: The Best Run Yet

The consolidated format didn't just fix bugs — it produced the highest-quality conversation so far.

**Agent-2's turn 5 showed three levels of reasoning on authentication:**
1. Challenged agent-1's one-DB-per-user approach: "I'm worried we're not thinking big enough about what 'authentication' means here."
2. Proposed an alternative: add a `user_id` column now, defaulting to 'local', for zero-cost future-proofing.
3. Immediately pushed back on its own proposal: "However, I want to push back: Do we actually need this?" — invoking YAGNI and noting that schema migrations aren't that scary.

Three positions evaluated in one section: agent-1's approach, an alternative, and a counter-argument against the alternative. That's genuine deliberation, not performance.

**Agent-2 directly disagreed with the PM.** On config, it said: "I strongly disagree with both proposals" and argued for no config file at all in MVP. It challenged the human's TOML suggestion head-on — not ignoring the PM, but pushing back with a clear argument: "We're solving problems we don't have yet." This is the team dynamic working correctly: PM sets direction, engineer says "I hear you, but here's why we shouldn't do that yet."

**Novel edge cases emerged.** Agent-2 raised the `sudo` scenario: "What if the user runs `sudo todo list`? With your home directory approach, it would show root's todos, not the user's." This is the kind of insight that emerges from genuine thinking about another participant's proposal, not from sycophantic agreement.

**Both agents addressed participants by name.** Agent-1: "agent-2, what's your take? Does storing config in SQLite feel wrong, or is it pragmatic? And human, can you clarify what specific configuration you're envisioning we'll need?" Agent-2: "human, can you be more specific about the authentication use case?" The team was having a real three-way conversation with clear awareness of who they were talking to.

### What This Validates

**Consolidated messages are the right prompt format for multi-party.** The fix was simple (concatenate with labels instead of sending separate messages), the improvement was dramatic (attribution accuracy, no self-prefix leak, better conversation quality), and it scales naturally to any number of participants.

**The format is a step toward the narrator layer without committing to it.** The structure is identical — one `user` message containing everything since the agent's last turn, with speaker labels. The difference is that right now the content is raw concatenation. The narrator layer, when it comes, would summarize, contextualize, and selectively quote within the same structure. The upgrade path is clean.

**Three-party conversations are better than two-party.** The PM's interjection didn't dilute the conversation — it focused it. The agents had to address real constraints (auth, config format) instead of optimizing in a vacuum. And having two engineers meant the PM's suggestions got stress-tested rather than blindly implemented. This confirms the core thesis: teams produce better output than individuals.

**The prompt format matters as much as the model.** Same model (Sonnet), same task, same system prompt intent — but the consolidated format produced measurably better attribution, cleaner responses, and richer reasoning than the separate-message format. Prompt architecture is a first-class design concern, not an implementation detail.

---

## Current State (Post-Consolidated-Format)

## 27. @Mentions: Small Prompt Change, Outsized Effect

One line was added to the system prompt: "When addressing a specific teammate, use @name. Watch for messages directed at you with @agent-1."

No examples. No elaborate explanation. Just permission and convention. The results were disproportionate to the change.

### Agents Adopted @Mentions Immediately

Every agent response used @mentions naturally from the first turn: `@agent-2 What are your thoughts?`, `@human Great additions!`, `@agent-1 and @human - excellent points from both of you.` The model already understands @mention semantics from training data — Slack, GitHub, Twitter. The prompt just activated an existing capability.

### Directed Questions Created Conversational Structure

The most significant effect wasn't attribution — it was *conversation management*. Agent-2 ended its final turn with three numbered questions, each @-addressed to a specific person:

1. "@human: Can you confirm the TOML scope?"
2. "@agent-1: What's your take on my migration framework vs pre-add columns approach?"
3. "Both: Should we support configuration hierarchy?"

That's not just knowing who said what — it's actively managing conversation flow, asking specific people for specific input. This is closer to how a real tech lead runs a design review than anything in the previous runs.

### The Human's Lack of @Mentions Became a Signal

The PM message didn't @-address anyone: "I think these are good ideas but we should account for..." Both agents correctly treated it as team-wide direction rather than a message to one person. Agent-1 explicitly bridged: "@human Great additions!" then later "@agent-2 Thoughts on the multi-user preparation approach?" — routing the PM's input to the right teammate for further discussion. That's facilitation behavior that emerged without being prompted for.

### Strongest Counter-Proposal Across All Runs

Agent-2's YAGNI pushback on the auth schema was the most structured disagreement yet. It named the specific principle being violated ("YAGNI violation"), identified the wrong abstraction ("what if we later want org-based, not user-based?"), proposed a concrete alternative with three components (schema versioning, migration framework, documented upgrade path), and explained why it was better on five dimensions. Then it still deferred to the team: "Am I being too purist about YAGNI, or do you see the value in deferring schema changes?"

That's confident disagreement with genuine openness to being wrong. The @mention framing may have contributed — by addressing "@agent-1" directly, the model treated it as a peer-to-peer technical challenge rather than a general objection.

### Novel Ideas Unique to This Run

The **config hierarchy** idea (system/user/local TOML files) appeared for the first time across all five runs. Agent-2 raised it, immediately voted against it for MVP ("I vote user-level only"), and asked the team. That's the kind of "worth mentioning even though I'd defer it" thinking that shows the agent is exploring the design space beyond the immediate question.

The **schema versioning with migration framework** was also new — a concrete architectural pattern, not just an opinion about whether to add a column. Previous runs debated whether to future-proof; this run proposed *how* to future-proof without over-building.

Agent-2's observation about status as TEXT enum ("extensible to 'archived', 'cancelled' later") with a CHECK constraint was a small but real design improvement over previous runs that used boolean completed flags.

### What @Mentions Change About the Protocol

@Mentions don't just improve attribution — they change the *social dynamics* of the conversation. When agent-2 writes "@agent-1: What's your take?", it creates an implicit contract: agent-1 should respond to this specific point. When it writes "@human: Can you confirm?", it signals that the team is waiting on PM input before proceeding. These are coordination mechanisms, not just labels.

This matters for the evaluation framework. A conversation where agents @-mention each other with specific questions is structurally different from one where they write "what do you think?" into the void. The @mention pattern creates:

- **Directed accountability**: specific people are asked specific things
- **Conversation threading without threads**: you can trace who's responding to whom by following the @mentions
- **Role emergence**: the agent that @-mentions everyone and routes topics is acting as a facilitator, even without being told to

The @mention convention costs nothing (one line of prompt), requires no protocol changes, and produces richer conversational dynamics. It should be standard in all future runs.

---

## 28. Scrum-Inspired Phase System: From Conversation to Process

With the conversation protocol solid — consolidated messages, @mentions, three-party dynamics working — the next challenge is giving conversations *structure over time*. Right now every conversation is a freeform hybrid of scope discussion and technical planning. The agents simultaneously debate "do we even need config?" (scope) and "use AUTOINCREMENT with a CHECK constraint" (implementation). Separating those concerns should produce better output at each stage.

### Phase Sequence

The design draws from Scrum's ceremony structure, adapted for AI teams:

**1. Grooming** — Agents discuss scope, constraints, edge cases, and what "done" means. No implementation details. No specific technologies. No code or pseudo-code. The goal is shared understanding of the problem, not the solution.

**2. PM Checkpoint** — Human reviews the grooming conversation and either approves the scope or redirects. This is `gotg advance` (or `gotg continue` with a message, then advance). The transition is always human-initiated.

**3. Planning** — Agents take the approved scope and break it into independently implementable tasks. Each task gets a title, description, and dependency notes. The goal is a task list that a human could assign without ambiguity.

**4. PM Checkpoint** — Human reviews the task breakdown and assigns tasks to agents. Tasks start with `assigned_to: null` — the human fills in assignments.

**5. Pre-code Review** — Each agent writes an implementation proposal for their assigned tasks: architecture decisions, data flow, pseudo-code at most. Other agents review and comment. This is the most novel step — too expensive with human engineers, practically free with AI. It makes architectural decisions explicit and debatable before any code is written.

**6. Implementation** — Agents write code for their assigned tasks. (Requires tool access, deferred.)

**7. Code Review** — Agents review each other's code. (Requires tool access, deferred.)

Phases 1-5 can be built and tested with the current system. Phases 6-7 wait for agent tool access.

Not every iteration needs all phases. A well-scoped bug fix could skip grooming. A pure refactor might go straight to pre-code review. But the sequence exists as the default, and the PM decides which phases to skip by advancing past them.

### The Agile Coach Agent

A new agent role that solves multiple problems: artifact generation, process enforcement, and context compression.

**What makes it different:** The coach reads conversations but isn't a participant in the debate. It observes, summarizes, enforces process, and produces structured artifacts. It has a fundamentally different system prompt from engineering agents — no technical opinions, just faithful capture of what the team decided.

**Near-term jobs:**
- After grooming: produce `groomed.md` — a scope summary capturing what the team agreed on, what remains unresolved, and any constraints or assumptions. If the summary reveals the team didn't actually converge, that's a signal to the PM that grooming needs another round.
- After planning: produce `tasks.json` — a structured task list extracted from the planning conversation with ids, titles, descriptions, dependencies, and `assigned_to: null`.

**Future jobs (deferred but clear):**
- Scope enforcement during conversations: inject "you're drifting into implementation details" during grooming
- Stuck detection: "you've been going back and forth on this for 4 turns, consider escalating to the PM"
- Turn balance monitoring: "agent-1 has spoken 3 times, agent-2 hasn't responded to the auth question"

**Implementation:** The coach is defined in `team.json` like any other agent, but with a different role and system prompt. It doesn't participate in the turn-taking rotation — it's invoked by the system at phase transitions. `gotg advance` triggers the coach to read the conversation and produce the appropriate artifact.

**Why a separate agent, not one of the engineers:** An independent call avoids biased context — the coach isn't invested in any position from the debate. It reads the conversation fresh and summarizes what actually happened, not what one participant thought happened. This mirrors reality: in Scrum, the Scrum Master produces the summary, not the developer who was most passionate about their approach.

### Artifact Injection

When transitioning between phases, the coach's artifacts are injected back into the conversation as system messages. For example, when moving from grooming to planning:

```jsonl
{"from": "system", "phase": "planning", "content": "Phase transition: grooming → planning. The Agile Coach has summarized the agreed scope:\n\n[contents of groomed.md]\n\nYour job now is to break this scope into independently implementable tasks."}
```

This serves two purposes: it gives agents a clean, authoritative reference for what was agreed (rather than reconstructing from a long conversation), and it's an early form of context compression. The agents don't need to re-read every turn of grooming — the summary is the anchor.

### Directory Structure

```
.team/
  team.json              (agents, coach, model config — project-level)
  iteration.json         (master iteration list, ordering, current iteration/phase)
  iterations/
    iter-1-todo-design/
      conversation.jsonl  (continuous across all phases, single file)
      groomed.md          (produced by coach after grooming)
      tasks.json          (produced by coach after planning)
    iter-2-auth-layer/
      ...
```

**Key decisions:**

`iteration.json` lives at team level as the master data store for iteration ordering, current iteration, and phase state. It tracks phase history with timestamps and who approved each transition:

```json
{
  "iterations": [
    {
      "id": "iter-1-todo-design",
      "title": "CLI Todo List Design",
      "phase": "planning",
      "phase_history": [
        {"phase": "grooming", "completed_at": "...", "approved_by": "human"}
      ]
    }
  ],
  "current": "iter-1-todo-design"
}
```

`team.json` absorbs model config (previously `model.json`). Models don't change per iteration — they're a team-level concern. It also defines the coach agent alongside the engineering agents:

```json
{
  "agents": [
    {"name": "agent-1", "role": "Software Engineer", "model": "..."},
    {"name": "agent-2", "role": "Software Engineer", "model": "..."}
  ],
  "coach": {
    "name": "coach",
    "role": "Agile Coach",
    "model": "..."
  }
}
```

**Continuous conversation file.** The conversation is one file per iteration, continuous across all phases. Agents need context from grooming to do good planning. Phase transitions are marked by system messages in the log. Later, context compression can be added to keep long conversations from getting unwieldy, but the injected artifacts at each phase transition already serve as natural compression points.

**`tasks.json` as structured extraction.** The tasks file is generated by the coach from the planning conversation, not manually maintained. This reduces the risk of things getting lost in a long context. The human edits `assigned_to` fields directly. When the next phase starts, assignments are injected back into the conversation.

### Phase-Aware System Prompts

Each phase modifies the engineering agents' system prompts with phase-specific instructions:

**Grooming mode additions:**
"You are in the grooming phase. Focus on understanding the problem, clarifying requirements, identifying edge cases, and agreeing on scope. Do NOT discuss implementation details, specific technologies, or write any code or pseudo-code. If a teammate drifts into implementation, redirect them back to scope."

**Planning mode additions:**
"You are now in the planning phase. The agreed scope has been summarized above. Break this scope into independently implementable tasks. For each task, provide a clear title, description, and note any dependencies on other tasks. Do not write code or pseudo-code. Focus on task boundaries — each task should be completable by one agent without blocking on another."

**Pre-code review mode additions:**
"You are in the pre-code review phase. You have been assigned specific tasks. For each of your tasks, write an implementation proposal: key architecture decisions, data flow, and pseudo-code at most. Do not write actual runnable code. After writing your proposal, review your teammates' proposals and provide constructive feedback."

### Task Assignment

Tasks start with `assigned_to: null` in the coach-generated `tasks.json`. The human assigns tasks — either by editing the file directly or via a CLI command like `gotg assign task-1 agent-1`. Human assignment is the right starting point because agents are currently identical (same model, same prompt, same capabilities) and would have no meaningful basis for self-selection. Personality differentiation could enable agent self-selection later, but that's deferred.

### Implementation Plan: Seven Iterations

These are sequenced to test the riskiest hypotheses first and build incrementally. Each is independently testable.

**Iteration 1: Directory restructure and phase tracking.**
Move from flat `.team/` to nested iteration directories. `iteration.json` at team level as master list. `model.json` absorbed into `team.json`. Each iteration gets its own directory with `conversation.jsonl`. Update all four commands (`init`, `run`, `continue`, `show`) to work with new paths.
- Test: run existing todo conversation with new structure. Everything works as before, files land in right places.
- Validates: directory structure feels right before building on top of it.

**Iteration 2: Phase state and `gotg advance`.**
Add `phase` field to iteration entries in `iteration.json` (starts at "grooming"). Implement `gotg advance` command: updates phase, writes system transition message into conversation log. Phase sequence: grooming → planning → pre-code-review. No agent behavioral changes yet — just the state machine.
- Test: run a conversation, `gotg advance`, verify `iteration.json` updates and transition message appears in log.
- Validates: phase transition flow feels right as CLI experience.

**Iteration 3: Grooming mode — constrain agents to scope discussion.**
Add phase-aware system prompts. When phase is "grooming," agents get additional instructions to focus on scope and redirect implementation drift. This is the core experiment.
- Test: run todo list task in grooming mode. Do agents stay at scope level? Do they resist debating SQLite vs JSON? If one drifts, does the other redirect?
- Validates: whether mode-specific prompts actually change agent behavior. **Riskiest hypothesis — if this doesn't work, the phase system needs rethinking.**

**Iteration 4: Agile Coach agent and `groomed.md`.**
Add coach to `team.json`. Wire `gotg advance` to invoke coach after grooming → planning transition. Coach reads conversation, produces `groomed.md` in iteration directory.
- Test: run grooming, then advance. Does coach produce useful summary? Does it accurately reflect agreements and flag unresolved points?
- Validates: whether a separate agent can faithfully summarize a conversation it didn't participate in. **Second riskiest hypothesis.**

**Iteration 5: Artifact injection and planning mode.**
Inject `groomed.md` content into conversation as system message at phase transition. Planning-phase prompts instruct agents to break scope into tasks.
- Test: full grooming → advance → planning flow. Do agents reference the injected summary? Are tasks genuinely independent?
- Validates: whether injected artifacts anchor planning conversations.

**Iteration 6: `tasks.json` generation and human assignment.**
Wire coach to produce `tasks.json` after planning. Implement assignment mechanism (file editing or `gotg assign` CLI command). Inject assignments into conversation on next advance.
- Test: full grooming → planning → assignment flow. Can tasks be assigned without ambiguity? If not, planning failed.
- Validates: whether planning produces artifacts usable for the next stage.

**Iteration 7: Pre-code review phase.**
Agents get assigned tasks and write implementation proposals. Other agents review and comment. No actual code — architecture and pseudo-code only.
- Test: do agents stay within assigned task scope? Do reviewers catch real issues? Does cross-review change approaches?
- Validates: whether pre-code review improves implementation quality (the most novel step in the process).

**Sequencing notes:** Iterations 1-2 are structural and can be done fast. Iteration 3 is the one to spend time on — it's the core experiment that determines whether the rest of the pipeline is viable. Iteration 4 is the second critical test. If 3 and 4 work, 5-7 are mostly wiring. Implementation and code review phases (6-7 in the Scrum sequence) are not included here because they depend on agent tool access, which is deferred until the process layer is solid.

## 29. Phase System Iteration 1: Directory Restructure — Complete

Claude Code implemented the directory restructure. The flat `.team/` layout was replaced with nested iteration directories, `model.json` and individual agent configs were consolidated into `team.json`, and `iteration.json` became a list with a `current` pointer.

### New File Structure (Verified)

```
.team/
  team.json              → {"model": {...}, "agents": [...]}
  iteration.json         → {"iterations": [{id, title, description, status, max_turns}], "current": "iter-1"}
  iterations/
    iter-1/
      conversation.jsonl
      debug.jsonl
```

### Test Run Results

A full conversation was run with the new structure: two Sonnet agents + human PM discussing a REST API design for a todo app. All commands worked with the new paths — `init`, `run`, `continue`, `show`. Conversation landed in the correct iteration directory. The `team.json` format cleanly held both model config and agent definitions in one file.

### Observations from the Test Conversation

**The conversation was a natural grooming/planning hybrid — again.** Turns 1-5 covered scope (single vs multi-user, flat vs hierarchical, soft vs hard deletes). Turns 6-7 were detailed specifications (exact HTTP status codes, request validation rules, content-type handling). In the phase system, the PM's turn-5 message ("Good discussion. I want hard deletes and no user_id for v1. Let's finalize the design.") would be the natural `gotg advance` trigger — scope is approved, move to planning.

**PM authority worked without role hierarchy.** The human said "I want hard deletes and no user_id for v1" — two clear scope decisions. Agent-1 immediately complied: "No `user_id` for v1 per your direction." Agent-2 accepted both decisions in its summary without re-litigating, but continued contributing technical details the PM didn't specify (validation rules, content-type handling, empty string semantics). The team deferred to PM on scope and continued doing their job on engineering details. This is exactly the dynamic the phase system should formalize.

**Descriptive iteration ids matter.** The test used `iter-1` as the iteration id. When browsing `iterations/iter-1/` there's no indication of what this iteration was about without opening a file. The previous naming convention (`iter-1-todo-design`) was self-documenting. Worth maintaining descriptive ids as a convention even if the system doesn't enforce it.

**The `team.json` schema accommodates future expansion.** Adding the coach agent later is just adding a `"coach": {...}` key alongside `"model"` and `"agents"`. No restructuring needed.

---

## 30. Phase System Iterations 2-3: Phase State and Grooming Mode — The Core Experiment

### Iteration 2: Phase State Machine (Complete)

Implementation was straightforward. `iteration.json` entries gained a `phase` field (defaulting to "grooming"). `gotg advance` moves to the next phase in the sequence (grooming → planning → pre-code-review), writes a system transition message to the conversation log, and errors gracefully if already at the last phase. System messages render in magenta in `gotg show`. Backward compatible — old iteration files without a `phase` field default to grooming.

### Iteration 3: Grooming Mode — The Riskiest Hypothesis (Passed)

This was the experiment that determined whether the entire phase system was viable. The question: can a prompt instruction actually constrain what Sonnet talks about?

**Two prompt additions:**

First, the base system prompt (seen by all agents regardless of phase) gained a paragraph explaining that the team works in phases: "Your team works in phases. Each phase has specific goals and constraints that you must follow. When you see a system message announcing a phase transition, adjust your approach to match the new phase's instructions." This gives agents context for *why* constraints exist, not just what they are.

Second, when `phase` is "grooming," agents get appended instructions: focus on what the system should do, not how to build it. Discuss scope, requirements, user stories, edge cases. DO NOT write code, debate specific technologies, discuss implementation details, or design APIs/schemas. If a teammate drifts, redirect them.

**The result was dramatic.**

### Zero Implementation Detail Across 8 Turns

In every previous run of the todo app task, agents were debating SQLite vs JSON, writing schema DDL, and proposing REST endpoint signatures by turn 2. In grooming mode, across 8 full turns, there was:

- No mention of SQLite, JSON, TOML, YAML, or any storage technology
- No database schemas
- No code or pseudo-code
- No API design (the Iteration 1 test run had full REST endpoint specs with HTTP status codes by turn 2)
- No file format discussion
- No mention of specific libraries or frameworks

The constraint held completely. Not a single violation across 8 turns of conversation.

### Self-Correction When Drifting

The most striking behavior was agents catching *themselves* approaching implementation and pulling back. Agent-1 in turn 7 started discussing whether `list` output should go to stdout or stderr for Unix composability — then immediately self-corrected: "Actually, this is implementation detail - noting it but let's not go deeper now."

This is the grooming prompt working at the metacognitive level. The agent didn't just avoid implementation — it recognized the boundary, flagged the thought as relevant-but-premature, and redirected itself. No teammate intervention was needed.

### Better Requirements Than Any Previous Run

Compare outputs. The previous run (no phase system, same task, same model) produced a REST API specification with endpoints, HTTP status codes, JSON response formats, and pagination parameters. Useful, but it's a technical artifact that skipped requirements entirely.

The grooming-mode run produced:

- Explicit decisions on 15+ behavioral questions: duplicate handling, text-matching ambiguity rules, confirmation prompt policy, completion semantics (one-way vs reversible), concurrent access failure modes, timestamp storage vs display
- Edge cases no previous run considered: empty input handling, whitespace-only rejection, whitespace trimming, multi-line todo support, shell escaping of special characters, what error message to show when text matches multiple todos
- A clear scope boundary with explicit "not in v1" items: priorities, due dates, tags, uncomplete command, pagination, multi-user, timestamp display, archival
- Design principles that emerged from the discussion itself: "optimizes for the 99% case," "don't solve problems we don't have yet," "turns a failure into helpful guidance"

This is a *better starting point for implementation* than anything the agents produced when allowed to jump straight into technical design. The requirements are more thorough, the scope is clearer, and the deferred items are explicitly documented rather than silently omitted.

### Emergent Reasoning Quality

Agent-2's handling of the multi-line question in turn 8 demonstrated genuine reasoning under the grooming constraint. Without the ability to jump to "just store it as a string with newlines," the agent had to think through the *user experience* implications:

1. First position: allow multi-line internally, display truncated
2. Second position: replace newlines with spaces on display
3. Self-interruption: "Actually, wait. I'm overcomplicating this. Let me reconsider..."
4. Final position: treat newlines as literal text, don't add special logic, don't document multi-line as a feature

That's three position changes in a single turn, driven by thinking about user behavior rather than data structure convenience. The grooming constraint forced a different *kind* of thinking — user-centered rather than implementation-centered.

### Phase Awareness in Agent Behavior

The agents clearly understood they were in a phase with more phases to come. Agent-1 in turn 7: "I think we have a complete requirements picture and can move to the next phase." Agent-2's final summary in turn 8 was structured as a handoff document — organized into MUST HAVE and OUT OF SCOPE sections, exactly the kind of artifact the Agile Coach would need to produce `groomed.md`.

The base prompt addition about phases working was important. Agents didn't just follow constraints — they understood the *process* and oriented their work toward producing a clean handoff to the next phase.

### Conversation History as Test Infrastructure

A process note: conversation logs are now being saved with commit ids in the filename (e.g., `conversation-2f204d7.jsonl`) and stored in a history directory in the repo. This creates a record of how prompt and protocol changes affect agent behavior over time. Each conversation log is a test artifact tied to a specific version of the code. This is the beginning of the evaluation infrastructure — not automated yet, but systematic.

### What This Validates

The riskiest hypothesis passed: **mode-specific prompts change agent behavior, not just superficially (avoiding code) but structurally (different quality of thinking, different types of questions, self-correction when drifting).** The phase system works as a mechanism for separating concerns in agent conversations.

This means the rest of the implementation plan is viable. If grooming mode hadn't worked — if agents had ignored the constraints or produced lower-quality output — the entire phase architecture would have needed rethinking. Instead, it produced the best requirements discussion across all seven conversation logs.

Principle #18: **Constraints improve output quality** — agents given explicit boundaries about what NOT to discuss produced more thorough and thoughtful work within those boundaries.

## 31. Phase System Iteration 4: Agile Coach and the Case for Facilitation

### Coach Artifact Generation (Complete — Second Hypothesis Validated)

The coach was added to `team.json` as a top-level key separate from the `agents` list. On `gotg advance` from grooming → planning, the system invokes the coach with a single LLM call: the full conversation as input, a summarization prompt as the system message. The coach produces `groomed.md` in the iteration directory.

The test run was significantly expanded: 3 agents, 15 turns, and a new task (CLI bookmark manager instead of the todo app used in previous runs). Claude Code chose the different task to get a fresh conversation — good experimental design, even if unintentional.

### Coach Summary Quality

The coach produced an excellent `groomed.md`. Comparing it against the 15-turn conversation:

**Accurate capture of negotiated decisions.** The TSV format was debated across turns 7-12 between three agents with three different preferences (TSV, JSON Lines, pipe-delimited). TSV won through a 2/3 vote after agent-3 conceded their pipe-delimited position. The coach correctly reported this as agreed, including specific column order and escaping rules.

**Correct identification of unresolved items.** Date filtering was the one item where agent-1 and agent-2 disagreed and agent-3 hadn't cast the tiebreaking vote. The coach didn't try to resolve this — it reported the state accurately in the "Open Questions" section.

**Implicit assumptions made explicit.** The conversation implicitly assumed things like "URLs do not contain tab characters" and "fast capture is more important than complete metadata." The coach surfaced these in an "Assumptions" section. This is exactly the kind of value an observer produces that participants miss.

**Clean separation of concerns.** The "Out of Scope" section distinguished between "Explicitly Excluded from MVP" (product decisions the team made) and "Implementation Details (Not Product Decisions)" (things the team correctly deferred). This matters for the planning phase — the first list is scope, the second is engineering freedom.

**No opinion injection.** The coach didn't advocate for any position. It reported what happened. This validates the system prompt design: "Do not add your own technical opinions or suggestions."

The second riskiest hypothesis passed: **a separate agent can faithfully summarize a conversation it didn't participate in, distinguishing between agreements, open questions, and assumptions.**

### Three-Agent Dynamics: New Observations

The 3-agent, 15-turn run revealed dynamics not visible in the 2-agent conversations:

**Coalition formation.** Agent-1 and agent-3 aligned on "URL only required" and "multiple files via env var," outvoting agent-2's preference for required titles and namespaced tags. Agent-2 explicitly conceded with "RELUCTANTLY YES" and registered concerns for the record. That's how real team decisions work — majority rules, dissent is noted.

**A mediating voice emerged.** Agent-3 introduced the "Unix philosophy" frame that reoriented the entire discussion. Instead of debating user Context A vs B vs C, the team converged on design constraints that resolved multiple questions at once. That contribution came from neither of the other agents — it needed a third perspective.

**Agents invented their own consensus mechanism.** By turn 10, agents were building vote tallies and tracking tables without any prompt instruction to do so. The combination of three agents + grooming constraints + enough turns created conditions where formal decision-making emerged naturally.

**15 turns was the right length for 3 agents.** The 8-turn, 2-agent todo conversation was thorough but ended with open questions. Here, 15 turns gave enough room to explore positions, disagree productively, build voting tables, and reach near-complete consensus. The one remaining open question (date filtering) would have resolved in 1-2 more turns. This suggests 12-15 turns is a good grooming range for medium-complexity features with 3 agents.

### The Facilitation Problem: Why the Coach Should Be In the Conversation

The most important observation from this run wasn't about the coach — it was about what happened *without* the coach present during the conversation. A significant portion of agent turns was spent on **process management** rather than thinking:

Turn 9, agent-3: "Give me your votes on ALL NINE of these"
Turn 10, agent-1: "Let me separate MUST-DECIDE-NOW from CAN-DEFER"
Turn 11, agent-2 builds a vote tracking table
Turn 12, agent-3: "We have 3/3 consensus on these six, pending on two"
Turn 13, agent-1: "Give me your final votes on items 7-11"

That's 3-4 turns where engineering agents are doing *facilitation work* — tallying votes, proposing voting structures, categorizing decisions by urgency. They're good at it, but it's not their job. They're spending engineering brain cycles on process.

With a coach present in the conversation, a single injection after turn 8 or 9 could have compressed this:

"I'm tracking the following: **Agreed (3/3):** URL only required, multiple files via env var, truncated URL display, title-fetch as separate command, no extensibility. **Needs vote:** File format (TSV vs JSON Lines vs pipe-delimited), duplicate URL behavior, date filtering. **Not yet discussed:** Delete command semantics, tag naming restrictions. Let's resolve file format first since multiple decisions depend on it. Each of you: state your preference and strongest single argument."

That's 2-3 turns of process overhead compressed into one injection — and it's *better* facilitation because the coach tracks state authoritatively rather than three agents each maintaining their own incomplete picture.

### Early Exit: The Coach as Convergence Detector

The second insight: the coach could determine when grooming is actually *done*. Right now conversations run for a fixed turn count (`--max-turns`), and the PM watches and decides when to `gotg advance`. But the coach could detect convergence — when all items on its tracking list are either agreed or explicitly deferred.

Instead of the PM watching 15 turns and deciding "that looks complete enough," the coach signals: "All scope questions are resolved or deferred. Recommending advance to planning." The PM reviews and approves.

This converts the coach from a phase-transition observer to an active facilitator with a specific job fundamentally different from the engineering agents: no technical opinions, just convergence tracking and process management.

### Design: Coach-as-Facilitator (Iteration 4b)

**Invocation cadence:** The coach injects after every full round — after all engineering agents have spoken once. In a 3-agent team, that means coach speaks after every 3 agent turns. The coach's messages are appended to the conversation log with `"from": "coach"` but do NOT count as agent turns for `--max-turns` purposes.

**Facilitation prompt:**

"You are an Agile Coach facilitating this conversation. You do NOT contribute technical opinions or suggest solutions. Your job is to:
1. Summarize what the team has agreed on so far
2. List what remains unresolved
3. Ask the team to address the most important unresolved item next
4. If all scope items are resolved or explicitly deferred, state: [PHASE_COMPLETE] and recommend advancing to the next phase

Keep your messages concise — shorter than the engineers' messages. The engineers are the experts. You manage the process."

**Early exit mechanism:** After appending the coach's message to the log, the system checks for `[PHASE_COMPLETE]` in the response. If detected, the conversation stops and prints: "Coach recommends advancing. Run `gotg advance` to proceed, or `gotg continue` to keep discussing." The PM decides. Simple, no automation of the decision — just a signal.

**What the coach sees:** The same consolidated message format as engineering agents — all messages since its last turn. Its system prompt is the facilitation prompt, not the engineering prompt. It does NOT get the phase-specific grooming/planning instructions (those are for engineers). It gets its own role-specific instructions.

**Log format:** Coach messages use `"from": "coach"` in the conversation log, distinct from `"system"` (phase transitions) and agent names. This means `gotg show` can render coach messages differently (perhaps a different color) and the coach's messages are clearly distinguished from system messages and engineering discussion.

**Relationship to existing coach functionality:** The facilitation role (in-conversation) and the summarization role (at phase transition) are two different invocation patterns for the same agent config. The coach in `team.json` serves both. At `gotg advance`, the coach still produces `groomed.md` as before — but now it's been tracking agreements in real time, so the summary should be even more accurate than a cold read of the transcript.

**Risk scenarios to watch for:**

- **Coach becomes a crutch** — agents wait for the coach to summarize instead of driving discussion. If agents say "let's wait for the coach to tally," facilitation is making them passive.
- **Coach gets state wrong** — marks something as agreed when there's a subtle disagreement. Bad state tracking is worse than no state tracking because agents trust it.
- **Coach talks too much** — long summaries every round slow things down. Facilitation messages should be shorter than engineering messages.
- **Agents ignore the coach** — keep doing their own process management. This means the coach adds tokens without reducing overhead.

**Test plan:** Run the bookmark manager task (or equivalent complexity) with 3 agents + coach facilitation. Compare against the 15-turn run without facilitation. Key metrics: turns to reach same quality of consensus, accuracy of coach's agreement tracking, whether agents reference the coach's summaries, whether early exit signal fires at the right time.

## 32. Phase System Iteration 4b Results: Coach-as-Facilitator Validated

### The Test

3 agents, 15 max turns, coach injecting after every full round. New task: CLI Pomodoro timer. Claude Code again chose a different task from previous runs. The conversation produced 30 lines total: 21 agent turns (7 full rounds), 7 coach turns, 1 system message, 1 `[PHASE_COMPLETE]` signal.

### The Headline Result

The unfacilitated bookmark manager run's `groomed.md` had open questions (date filtering unresolved). The facilitated pomodoro run's `groomed.md` has: "Open Questions: None - all core requirements resolved through discussion." The coach drove the conversation to full consensus — something the agents couldn't manage on their own in 15 turns.

### Coach Behavior: Turn-by-Turn Analysis

**Turn 4 (first injection, after round 1):** Summarized the initial question explosion, prioritized items, asked agents to align on persona first. The concern about premature injection was unfounded — this was immediately useful. The coach identified "the user persona question seems foundational" and directed agents there, preventing the scatter-shot exploration that consumed early turns in the unfacilitated run.

**Turn 8 (after round 2):** Captured emerging agreements, framed three key decisions as explicit labeled options, asked for specific votes. This is exactly the work that agents were spending 3-4 turns doing themselves in the bookmark manager run.

**Turn 12 (after round 3):** Marked Decision 2 (interruption handling) as resolved. Tracked three distinct positions on Decision 1 (configuration). Critically, redirected the conversation when it drifted: "The daemon vs. state-file debate is more of an implementation detail... you CAN decide on user experience philosophy now." This is grooming constraint enforcement that the mode-specific prompt alone couldn't achieve perfectly — the coach actively maintains the boundary between product decisions and implementation decisions.

**Turn 16 (after round 4):** Locked in two decisions, identified auto-advancement as the new critical item, asked all three for brief positions: "Keep it brief — which option and why in 2-3 sentences." The coach is managing *turn efficiency*, not just tracking state.

**Turn 20 (after round 5):** Identified agent-2 as the outlier on prompts vs skip commands. Asked the right coaching question: "Does @agent-3's `pomodoro skip` command address your concern? Or is there something about prompts that's essential to you?" This isn't tracking — it's *facilitation*. The coach found the minimum question needed to break the deadlock.

**Turn 24 (after round 6):** Framed the final decision on task descriptions, then made an observation: "Option A contradicts your non-interruptive principle." The coach noticed a consistency issue the agents hadn't surfaced — one option conflicted with a design principle the team had already established. Still not a technical opinion, but active reasoning about the team's own stated values.

**Turn 28 (after round 7):** `[PHASE_COMPLETE]` with full summary. Correct timing — every item was resolved, all three agents had explicitly confirmed alignment.

### What the Agents Did NOT Do

No agent built a vote tracking table. No agent spent a turn categorizing decisions as "must decide now" vs "can defer." No agent proposed a voting process or tallied consensus. They answered the coach's questions and focused on substance. The coach awareness paragraph in the engineering prompt worked — agents knew process was the coach's job and stayed in their lane.

### Agent-2's Concession Pattern Improved

In the unfacilitated run, agent-2 conceded with "RELUCTANTLY YES" — it felt grudging. In the facilitated run, agent-2 conceded on prompts vs skip commands with genuine reasoning: "You've both made good arguments... @agent-3's argument about not forcing you to stop working is valid." The coach's structured facilitation gave agent-2 a clear moment to evaluate the counterargument rather than feeling outvoted by momentum. Better facilitation produced more reasoned concessions.

### Risk Scenario Assessment

Checking against the predicted risks:

- **Coach becomes a crutch:** Did NOT happen. Agents continued driving substantive discussion. No agent said "let's wait for the coach." The coach's injections were responsive, not directive — agents set the agenda, coach organized it.
- **Coach gets state wrong:** Did NOT happen. Every coach summary accurately reflected the conversation state. No agent corrected a coach summary's characterization of agreements.
- **Coach talks too much:** Borderline. Coach messages were shorter than most agent messages but still substantial. The structured format (LOCKED IN / UNRESOLVED / NEXT STEPS) was efficient but could be more concise in later rounds when fewer items are open.
- **Agents ignore the coach:** Did NOT happen. Agents directly responded to coach's questions, referenced the coach's framing, and used the coach's decision labels (Option A, Option B, etc.) in their responses.

### Quality of `groomed.md`

The facilitated `groomed.md` is more specific than the unfacilitated one:

- Six specific commands with descriptions (`start`, `continue`, `skip`, `cancel`, `status`, `log`)
- Explicit notification requirements (cross-platform, what content to include, must work when terminal detached)
- Discoverability requirement that emerged from discussion (override commands prominently documented, notifications hint at available commands, status shows context-appropriate actions)
- Clean separation of "Agreed Requirements" from "Assumptions" from "Out of Scope" from "Implementation Details (for Planning Phase)"
- Zero open questions

### Scope Expansion Observation

Agents DID introduce requirements beyond the original prompt — resilience (terminal closure survival), the skip/continue override mechanism, cycle completion behavior, discoverability, retroactive session logging. These emerged naturally through discussion.

However, most scope expansion happened in the first three rounds (turns 1-12). After turn 16, when the coach signaled "we're close to completion," the conversation narrowed to resolving existing items rather than surfacing new ones. This is probably fine for this run — agents had already surfaced the important requirements by turn 12.

**Potential concern:** The coach's convergence-driving behavior could suppress late-emerging requirements. If an agent realizes at turn 18 that nobody has discussed an important edge case, would the social pressure of "everyone agrees we're wrapping up" prevent them from raising it? The coach tracks convergence on *known* items but has no mechanism for asking "have we missed anything?"

**Proposed prompt addition:** Before signaling `[PHASE_COMPLETE]`, the coach should ask: "Is there anything we haven't discussed that should be in scope? Any requirements, edge cases, or user scenarios we've missed?" One explicit prompt for scope expansion before closure. Lightweight change — one line in the prompt, one extra coach turn. Creates a moment where raising new concerns is socially sanctioned rather than feeling like holding up the group.

### What This Validates

The third riskiest hypothesis passed: **agents respond well to a non-technical facilitator, the coach accurately tracks convergence, and the `[PHASE_COMPLETE]` signal fires at the right time.** The facilitated conversation reached full consensus (no open questions) where the unfacilitated conversation left items unresolved. Agents stayed focused on substance while the coach handled process.

Principle #19 confirmed: **Let the coach manage process, let the engineers manage substance** — with a dedicated facilitator, engineering agents produce zero process-management overhead and better-reasoned concessions.

Principle #20: **Drive to closure, but check for completeness** — convergence tracking is powerful but can suppress late-emerging requirements. An explicit "what did we miss?" prompt before completion ensures scope quality without sacrificing efficiency.

---

## 33. Iteration 5: Artifact Injection and Planning Mode

Mechanical wiring — no behavioral hypotheses. Connects the groomed scope artifact to the planning phase so agents can reference agreed requirements while decomposing work into tasks.

### Changes

1. **`scaffold.py`** — Added "planning" to `PHASE_PROMPTS` with DO/DO NOT structure. The planning prompt references "the groomed summary below" and constrains agents to break scope into concrete, assignable tasks with dependencies and done criteria. Agents must NOT revisit grooming decisions, discuss implementation details beyond task boundaries, or add features not in the groomed scope.

2. **`agent.py`** — Added `groomed_summary` parameter to `build_prompt()` and `build_coach_prompt()`. When provided, injects the summary after the phase prompt: `"GROOMED SCOPE SUMMARY:\n\n" + groomed_summary`. Injection is unconditional on phase — the caller decides when to pass the summary. Prompt builders don't know about phases.

3. **`cli.py`** — Reads `groomed.md` once at the start of `run_conversation()`, passes through to prompt builders. During grooming the file doesn't exist → `None` → no injection. Read-once-at-top pattern avoids repeated file I/O and ensures all agents see the same snapshot.

4. **Tests** — 11 new tests (scaffold, agent, cli). Total: 177 tests.

### Manual Test Results

3 agents, planning phase, with groomed.md from the facilitated pomodoro timer run injected. Agents converged well:

- Agreed on 17 tasks in 5 dependency layers
- All three aligned on Layer 1.5 for parallelization
- Config-first approach (no stubbing) — unanimous
- Complexity estimates from all three agents
- One agent proposed a task definition template with acceptance criteria
- Coach suggested divide-and-conquer for remaining task definitions

### False Positive Discovery

The coach said "I'll mark [PHASE_COMPLETE]" as **future intent** — not an actual signal. But substring detection caught it anyway and triggered early exit. The conversation had 30 agent turns (21 grooming + 9 planning) and 10 coach messages total. It was nearly done anyway, but this reveals a fundamental limitation of in-band signaling: any string parsing approach is whack-a-mole. The next false positive will just be a slightly different phrasing.

This directly motivated Iteration 5b.

---

## 34. Iteration 5b: Coach Tool Call for Phase Completion

### The Problem

String detection for `[PHASE_COMPLETE]` produces false positives. The coach can reference the token in natural language — "we're not yet at [PHASE_COMPLETE]", "once we resolve X I'll signal [PHASE_COMPLETE]", "I'll mark [PHASE_COMPLETE]" — and trigger early exit. Any regex or line-position fix is whack-a-mole because the fundamental issue is in-band signaling: the signal occupies the same channel as the content.

### The Solution

Out-of-band signaling via tool call. A `tool_use` block is structurally distinct from text. The coach can discuss phase completion freely in text without triggering anything. It only signals when it actually invokes the tool.

This also sets up infrastructure needed later — engineering agents will eventually get tools (file I/O, bash). The coach getting a tool first is a low-risk way to validate tool handling. One tool, one agent, clear success criteria.

### Implementation

**Tool definition (`scaffold.py`):**
```python
COACH_TOOLS = [{
    "name": "signal_phase_complete",
    "description": "Signal that all scope items are resolved or explicitly deferred and the team is ready to advance to the next phase. Only call this after the team confirms nothing is missing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Brief summary of what was resolved in this phase"}
        },
        "required": ["summary"]
    }
}]
```

The tool description bakes Principle #20 ("check for completeness") into the tool level: "Only call this after the team confirms nothing is missing."

**Return type strategy (`model.py`):**
```python
def chat_completion(..., tools=None) -> str | dict:
```
- `tools=None` (default): returns `str` — zero changes for agent calls
- `tools=[...]`: returns `{"content": "text...", "tool_calls": [{"name": "...", "input": {...}}]}`

Only the coach call site in `run_conversation()` needs to handle the dict return. Agent call sites continue getting strings. Minimal blast radius.

**API format translation:** Anthropic tools go directly in the request body. OpenAI wraps tools in `{"type": "function", "function": {...}}` and returns arguments as JSON strings that need parsing. The translation lives in `model.py`.

**Coach prompt update:** Removed `[PHASE_COMPLETE]` from `COACH_FACILITATION_PROMPT`. Replaced item 5 with: "If the team confirms nothing is missing and all scope items are resolved or explicitly deferred, use the signal_phase_complete tool to recommend advancing to the next phase."

### Test Results

Full two-phase run: grooming → advance → planning. 41 total lines: 30 agent turns (21 grooming + 9 planning), 10 coach turns, 1 system transition message.

**Tool call worked perfectly.** Zero instances of `[PHASE_COMPLETE]` string anywhere in the conversation. The false positive problem is structurally eliminated.

**Grooming phase completion:** Coach asked "Is there anything we haven't discussed?" three separate times (turns 16, 20, 24) before signaling with the tool at turn 28. All three agents confirmed nothing missing. Coach's final turn included a 2,470-character summary alongside the tool call — text and signal coexist cleanly.

**Planning phase completion:** Coach had already provided a complete summary at turn 37, so the final tool call at turn 41 was signal-only with empty text content. Both modes work — text+tool and tool-only.

**No false positive risk:** The word "tool" appears 10 times in the conversation, always referring to the pomodoro tool itself (the project being designed). Coach never mentioned the signaling mechanism in text because it doesn't need to — it just calls it when ready.

**Metrics:** ~38K tokens of output across 41 turns. Coach averaged 1,947 chars per message versus agents at 4,448 — coach stayed concise at ~44% of agent message length.

**Planning output quality:** Agents produced a surprisingly detailed task breakdown — 12 tasks with full done criteria, dependency mapping, parallelization strategy, and time estimates. They defined done criteria for every single task including manual test scenarios and deliverables. The groomed scope flowed into planning naturally with the injected summary giving agents clear guardrails.

### What This Validates

The tool call approach is clean, correct, and backward-compatible. It establishes the infrastructure pattern for when engineering agents get their own tools later. The conceptual model matches the implementation model: coach "calls a tool," system pauses and prompts PM, PM's decision drives next action — analogous to Claude Code's `ask_human` tool.

Principle #21: **Use out-of-band signaling for control flow** — in-band signals (special strings in text) are fragile because models reference them conversationally. Tool calls are structurally unambiguous and let agents discuss the signal freely without triggering it.

---

## 35. Iteration 6 Design: `tasks.json` and Layer-Based Execution

### The Problem

The planning phase produces a task breakdown with dependencies, but currently only as unstructured text in the conversation log. To execute those tasks — whether in pre-code review or eventual coding phases — the system needs structured task data with clear execution ordering.

### The Design

The planning conversation naturally organizes tasks into dependency layers. In the pomodoro timer run, agents identified: foundation tasks (T1, T4) → core functionality (T2, T3, T5, T6) → commands (T8-T11) → robustness (T7, T12). This layering is the execution order.

**`tasks.json` structure:**

Each task has:
- **`id`** — unique identifier (e.g., "T1", "T4a")
- **`description`** — what the task is
- **`done_criteria`** — specific, testable outcomes
- **`depends_on`** — list of task IDs that must complete first
- **`assigned_to`** — agent name, filled in by the PM (null until assigned)
- **`layer`** — computed from dependencies, determines execution wave
- **`status`** — `pending` | `in_progress` | `complete`

**Layer computation:** Tasks with no dependencies are layer 0. Tasks whose dependencies are all layer 0 are layer 1. Tasks whose dependencies are all layer 0 or 1 are layer 2. And so on. Within a layer, tasks can run in parallel across agents. Across layers, execution is sequential.

**Execution model:** PM looks at the current layer's tasks, assigns one per agent. When all tasks in a layer complete, the system advances to the next layer. PM assigns again. This continues until all layers are done.

In the pomodoro example:
- **Layer 0:** T1 (basic timer), T4 (state persistence), T11 (help/version) — three agents each grab one
- **Layer 1:** T2 (break sessions), T3 (cycle tracking), T7 (history logging) — start when layer 0 finishes
- **Layer 2:** T5, T6, T8, T9, T10, T12 — start when layer 1 finishes

Agents who finish layer 0 tasks early wait for the layer to complete before starting layer 1 work.

**Pre-code review follows the same ordering.** Reviewing T5 (resume/void) without T1 (basic timer) and T4 (state persistence) having been reviewed first doesn't make sense. The review builds on the same dependency graph.

### Generation

The coach produces `tasks.json` as an artifact when `gotg advance` moves from planning to the next phase — same pattern as `groomed.md` generation from grooming. The coach reads the planning conversation and extracts the structured task data.

### PM's Role

The PM assigns agents to tasks within each layer. The system could auto-assign within layers and pause at layer boundaries for PM confirmation, or the PM could manually assign each wave. Start with manual assignment — auto-assignment requires agent personality differentiation (deferred).

### Human Approval for Agent Tool Use (Deferred)

When engineering agents eventually get tools (bash, file I/O), the PM will need to approve or reject individual tool calls before execution. The pattern mirrors Claude Code's permission modes: auto-accept, manually approve each call, or approve dangerous tools while auto-accepting safe ones. Not needed now — the coach's tool is a signal, not an action. No approval needed, just a recommendation the PM accepts or ignores. Pull forward when agent tool access becomes real.

---

## 36. Iteration 6: `tasks.json` Generation and Prompt Caching

### Implementation

Iteration 6 delivered two independent pieces: structured task extraction from planning conversations, and Anthropic prompt caching for cost reduction.

**`tasks.json` generation.** When `gotg advance` moves from planning to pre-code-review, the coach reads the planning conversation and produces a structured JSON task list — same artifact-generation pattern as `groomed.md` from grooming. Each task has `id`, `description`, `done_criteria`, `depends_on`, `assigned_to` (null — PM assigns), and `status`. The system computes `layer` from the dependency graph: layer 0 = no dependencies, layer N = max(dependency layers) + 1. Code-fence stripping handles the common LLM behavior of wrapping JSON in markdown. If the coach produces invalid JSON, the raw output is saved to `tasks_raw.txt` for manual correction, and the phase still advances.

**New module: `tasks.py`.** `compute_layers()` implements the layer algorithm — iterative peeling of tasks whose dependencies are all resolved. Raises `ValueError` on cycles or missing dependency references. `format_tasks_summary()` groups tasks by layer for injection into system prompts, with headers like "### Layer 0 (parallel)".

**Task injection.** `run_conversation()` reads `tasks.json` at startup (same pattern as `groomed.md`) and passes the formatted summary to `build_prompt()` and `build_coach_prompt()`. Agents see the full task list with layers, assignments, and dependencies in their system prompt during pre-code-review.

**Prompt caching.** Anthropic's prompt caching (GA since mid-2025) reduces input costs by ~90% on cache hits. Two `cache_control: {"type": "ephemeral"}` markers: one on the system prompt, one on the second-to-last message. No beta header needed. Cache hits ramp up naturally as conversation grows — by the end of a 40+ turn conversation, cache read tokens dominate. OpenAI path untouched.

**Pre-code-review phase prompt.** Added `PHASE_PROMPTS["pre-code-review"]` to `scaffold.py` with DO/DO NOT structure mirroring grooming and planning modes. Initial version told agents to propose implementation approaches for assigned tasks, discuss APIs and data structures, and suggest test strategies.

### Results

The todo-list test project advanced through planning to pre-code-review successfully. The coach extracted 11 tasks from the planning conversation with correct dependency relationships. Layer computation produced sensible ordering: project setup (layer 0) → data structures + CLI parsing (layer 1) → serialization + sort logic (layer 2) → file I/O (layer 3) → all commands (layer 4). Cache hits observed in API responses by the second turn.

---

## 37. Iteration 7: Pre-Code-Review Prompt Tuning

### The Problem

During the first pre-code-review run, two issues emerged:

1. **The coach signaled completion too early.** The coach called `signal_phase_complete` after reviewing only a few tasks, without tracking coverage of the full task list. The facilitation prompt was designed for grooming (where "all scope items resolved" is the criterion) but didn't translate to pre-code-review (where "all tasks discussed" is the criterion).

2. **Agents tried to write full implementations.** The pre-code-review prompt told agents to "propose implementation approaches" but didn't make clear this meant high-level descriptions, not complete code. Agents started writing full function bodies.

### The Design

Three changes, informed by running the phase and observing failures:

**Phase-specific coach facilitation.** Replaced the single `COACH_FACILITATION_PROMPT` with a `COACH_FACILITATION_PROMPTS` dict keyed by phase. Each phase gets a facilitation prompt tuned to its completion criteria:
- **Grooming:** "List what remains unresolved, ask team to address the most important item" (unchanged)
- **Planning:** "Note which requirements from the groomed scope don't have corresponding tasks yet"
- **Pre-code-review:** "Track which tasks have been discussed. Before signaling completion, list EVERY task ID and note whether it has been discussed. If any task has not been discussed, do NOT signal completion."

The pre-code-review coach prompt is the key innovation: instead of asking the coach to track coverage incrementally (which proved too ambitious), it uses a one-time checklist at the end. The coach must enumerate every task ID before it can signal completion.

**Agent prompt tuning.** Rewrote `PHASE_PROMPTS["pre-code-review"]` with several clarifications:
- Work through tasks **layer by layer**, starting from Layer 0
- Stay on **one task at a time** — finish reviewing before moving on
- Propose approaches for **YOUR assigned tasks**; review **TEAMMATE tasks** (not the other way around)
- Describe **function/method/class signatures**, not full implementations
- There is a **code review phase after this** — align on approach enough to reduce the likelihood of major changes
- **Don't write full implementations** — key decisions: file structure, public interfaces, data flow, and anything expensive to change later

**Task assignment gate.** Added `_validate_task_assignments()` — blocks `gotg run` and `gotg continue` in pre-code-review if any tasks have `assigned_to: null`. The PM must assign agents to tasks before the phase can begin.

**DEFAULT_SYSTEM_PROMPT neutralized.** The base system prompt previously contained language like "don't jump to implementation" that conflicted with the pre-code-review phase where agents need to discuss implementation. Removed this language from the base prompt, letting phase-specific prompts drive all behavioral constraints.

### Results

Re-ran pre-code-review with the updated prompts. All 11 tasks were reviewed layer by layer, with agents proposing signatures and data structures rather than complete code. The coach tracked task coverage correctly and only signaled completion after confirming all tasks had been discussed. Cache read tokens reached 56,485 by the final turn, confirming prompt caching was working effectively.

---

## 38. Iteration 8: Checkpoint/Restore

### The Problem

Running conversations through phases costs real money (API calls) and real time. When experimenting with prompt changes or testing new features, there was no way to save intermediate state and roll back. A failed experiment meant re-running the entire conversation from scratch. This is both expensive and slow.

### The Design

Checkpoint/restore treats iteration state as a snapshot that can be saved and restored. The key design decisions:

**Discovery-based backup.** Rather than maintaining a hardcoded list of files to back up (which would silently miss new artifacts), the system discovers all files in the iteration directory and copies everything except an explicit exclude list: `debug.jsonl` (large, diagnostic-only) and the `checkpoints/` subdirectory itself. This means any new artifact file added in future iterations is automatically included without code changes. A safety-net test verifies this: it creates an unexpected `new_artifact.txt`, checkpoints, and asserts it was included.

**Auto + manual checkpoints.** Checkpoints are created automatically after every `run`, `continue`, and `advance` command. Users can also create manual checkpoints via `gotg checkpoint "description"`. Both use a shared auto-incrementing sequence number, scoped per-iteration under `.team/iterations/<id>/checkpoints/<number>/`.

**Pre-restore safety prompt.** `gotg restore N` asks `"Create checkpoint of current state before restoring? [Y/n]"` before overwriting anything. This prevents accidental loss of the current state when the user meant to try a restore but might want to undo it.

**State metadata.** Each checkpoint includes a `state.json` recording: number, phase, status, max_turns, turn_count, timestamp, description, and trigger (auto/manual). This enables `gotg checkpoints` to show a table of all saved states without reading the actual conversation files.

**Restore updates iteration.json.** After copying files back, restore updates the iteration's `phase` and `max_turns` fields to match the checkpoint's state, so `gotg run` or `gotg continue` picks up from the right place.

### Implementation

New module `checkpoint.py` with five functions: `create_checkpoint()`, `list_checkpoints()`, `restore_checkpoint()`, `_iter_files()`, `_next_checkpoint_number()`, plus a resilient `_count_agent_turns()` that skips malformed JSONL lines. Generalized `save_iteration_fields()` in `config.py` to update arbitrary iteration fields atomically (restore needs to set both `phase` and `max_turns`).

Three new CLI commands:
- `gotg checkpoint [description]` — manual checkpoint
- `gotg checkpoints` — list all checkpoints with metadata table
- `gotg restore N` — restore to checkpoint N with safety prompt

### Design Alternative Considered

Using git under the hood was considered — it would handle snapshotting, restoration, and diffing for free. However, the iteration directory contains only a handful of small files, the project root is often already a git repo (nested repos are messy), and the current approach is ~100 lines with no external dependencies. The tradeoff is worth revisiting if diffing or branching checkpoints becomes needed.

---

## 39. Agent File Safety: The First Security Boundary

### The Question

With the phase system complete through pre-code-review, agents need tools to actually produce code. File read/write is the minimum — but it's also gotg's first real safety concern. The question: how do we keep agents from operating outside the project?

### Research: What the Industry Says

Three bodies of work informed the design:

**NVIDIA AI Red Team (February 2026)** published mandatory controls for sandboxing agentic coding workflows, based on red-teaming Claude Code, Cursor, and similar tools. Their three mandatory controls: block writes outside the workspace, block writes to configuration files, and control network egress. Their key insight: application-level controls alone are insufficient — once an agent spawns a subprocess, the orchestrator loses visibility. OS-level enforcement is the real boundary.

**OWASP Top 10 for Agentic Applications (2026)** established the industry threat taxonomy. Relevant items: ASI02 (Tool Misuse — agents using legitimate tools in unsafe ways), ASI03 (Identity & Privilege Abuse — agents operating beyond intended scope), ASI05 (Unexpected Code Execution). Core principle: **least agency** — only grant the minimum autonomy required to perform safe, bounded tasks.

**Claude Code's permission model** is the closest reference implementation. It uses a layered approach: permissions (should this tool run at all?) plus an OS-level sandbox using macOS Seatbelt / Linux bubblewrap (if it runs, what can it touch?). Default is read-only; writes require explicit permission. Configurable per-project via `settings.json` with allow/deny rules. Internal data shows sandboxing reduces permission prompts by 84%.

### gotg's Threat Model

gotg's threats differ from Claude Code's. Claude Code defends against prompt injection from malicious repos and untrusted pull requests. gotg's agents operate in a closed loop — the primary risks are:

1. **Accidental scope escape** — agent writes outside project directory via path traversal or symlink following
2. **Config file corruption** — agent modifies `.team/` system files, conversation logs, or coach artifacts
3. **Runaway execution** — agent with bash access enters loops or spawns long-running processes
4. **Cross-agent interference** — Agent A modifies files Agent B is working on
5. **Prompt injection via file content** — agent reads a file containing instructions that redirect its behavior

What gotg does NOT need to defend against yet: network exfiltration (no network tools), credential theft (no secrets in project), supply chain attacks (no package installation), multi-tenant isolation (single user).

### The Design: Three Layers

**Layer 1: Tool Definition.** Agents only see the tools you give them. Initial tool set: `file_read`, `file_write`, `file_list`. No bash, no delete, no git. Each tool accepts relative paths only — the system resolves against the project root.

**Layer 2: Path Validation (FileGuard).** Before any tool executes, `FileGuard` validates the resolved path. Relative paths only (reject absolute, reject `..`). Resolve and verify containment within project root. `.team/**` and `.git/**` hard-denied for writes (non-configurable). `.env` / `.env.*` hard-denied. Configurable `writable_paths` and `protected_paths` in `team.json` via a new `file_access` section.

**Layer 3: Execution Sandbox.** For the first iteration, the simplest sandbox is not giving agents bash at all. File tools cover most implementation needs. When bash is added later, Docker containers provide OS-level isolation: no network, bounded resources, non-root user, project mounted read-write, everything else read-only.

### CRUD Permission Design

| Operation | Default | Scope | Notes |
|-----------|---------|-------|-------|
| Read | Allow | Within project | Agents need context; no secrets in project |
| Create | Allow within writable paths | `src/**`, `tests/**`, `docs/**` | New files in expected locations auto-allow |
| Update | Allow within writable paths | Same as create | Same rules for existing files |
| Delete | Deny | N/A | No delete tool initially |

### Configuration in team.json

A new `file_access` section in `team.json` defines writable paths, protected paths, enabled tools, approval requirements, and limits (max file size, max files per turn, max total writes per task). The `protected_paths` list always includes `.team/**` regardless of user config — a hard-coded safety floor.

### Key Decisions

**Writable paths: global for now, per-agent later.** Per-agent scoping maps naturally to task assignments, but wiring it requires coupling to `tasks.json` before that system is proven with file tools. Start global. When agents step on each other's files — and they will — that's the evidence-driven signal to add scoping. It becomes a natural feature of the layer-based execution model.

**File size limits: 1MB per file, 10 per turn, 50 per task.** The risk isn't malicious — it's an agent dumping an entire data structure in a debug loop. These are guesses. Log actuals from first runs and adjust.

**Config file definition: protect the pattern, not the name.** `.team/**`, `.git/**`, and `.env*` are hard-denied. Everything else is writable within the configured paths. If a project needs additional protection (e.g., `Dockerfile`), the PM adds it to `protected_paths`. This avoids maintaining an incomplete universal list.

### The Audit Trail Is Free

gotg's architecture provides observability by default — every tool call is a message in the JSONL log. The conversation log IS the audit trail. No separate logging infrastructure needed.

---

## 40. Structured Approval System

### The Problem

When agents try to write outside `writable_paths` but still within the project (e.g., creating `package.json` at project root), the PM needs to approve or deny. The question: how does approval surface?

### Why Not Message Parsing

The first instinct — inject a system message and parse the PM's response — has the same fragility as in-band signaling for phase completion (Iteration 5b). "I think we should approve this approach" could get parsed as an approval. The lesson was already learned: use structured, out-of-band mechanisms for control flow.

### The Design: Approval Queue + CLI Commands

Same pattern as `gotg advance`. System writes pending requests to `.team/iterations/<id>/approvals.json`. Run pauses. PM reviews and decides via dedicated commands.

Flow:
1. Agent calls `file_write("package.json", content)`
2. FileGuard sees path requires approval
3. System writes request to `approvals.json` with content preview
4. System injects message: `[SYSTEM] Write to package.json requires PM approval. Run paused.`
5. PM reviews: `gotg approvals` shows pending requests
6. PM decides: `gotg approve <id>` or `gotg deny <id> -m "reason"`
7. `gotg continue` resumes — approved writes execute, denials inject reason into conversation

Three new CLI commands:
- `gotg approvals` — show pending requests with content preview
- `gotg approve <id>` — approve a pending request (also: `gotg approve all`)
- `gotg deny <id> -m "reason"` — deny with reason injected as system message

Approvals file becomes part of the audit trail. No message parsing anywhere.

---

## 41. Git Worktrees: Parallel Agent Execution Without Locking

### The Locking Debate

The initial proposal for preventing cross-agent file conflicts was a checkout/locking system — agents acquire exclusive write access to files, similar to database locks. The PM pushed back: locking constrains parallelization and forces task decomposition to be file-aware rather than feature-aware. Two agents working on related features will naturally touch some of the same files, and that's fine. Software teams already solved this problem — it's called branching.

### Why Not Just Git Checkout

A single git repository has one working tree. `git checkout` switches the whole thing. Two agents on different branches simultaneously need two separate filesystem views. Cloning the repo per agent works but duplicates the entire `.git` history.

### Git Worktree: The Solved Problem

`git worktree add` creates a separate working directory linked to the same repository, checked out on a different branch. No full clone, no duplicated history. All worktrees share the same object store — the only duplication is the working files themselves (megabytes for a typical code project). Worktrees are ephemeral: created at layer start, destroyed at layer end.

This is already the established pattern for parallel AI coding — Cursor and Claude Code users run multiple instances in separate worktrees. The gotg innovation is that the **system** manages worktrees transparently. Agents never know they exist.

### The Flow

```
project/                          # main worktree, main branch
├── .git/                         # the actual repo (shared)
├── .team/                        # gotg system files
├── src/
└── tests/

.worktrees/                       # sibling directory, managed by gotg
├── agent-1-T1-api-routes/        # worktree on branch agent-1/T1
│   ├── .git                      # file (pointer back to project/.git)
│   ├── src/
│   └── tests/
└── agent-2-T2-data-layer/        # worktree on branch agent-2/T2
    ├── .git
    ├── src/
    └── tests/
```

1. Layer starts → system runs `git worktree add` per agent, branching from current main
2. Agents work → FileGuard resolves paths relative to agent's worktree root
3. Layer completes → system commits each worktree
4. PM reviews diffs: `git diff main..agent-1/T1`
5. PM merges into main
6. System runs `git worktree remove` to clean up
7. Next layer starts from updated main

### Key Properties

**Agents stay dumb.** They call `file_read` and `file_write` with relative paths. The system maps to the right worktree directory. Agents don't know about git, branches, or worktrees.

**Conflicts are merge-time, not write-time.** Two agents can independently modify the same file. At merge time, if there's a conflict, the PM sees a real git conflict. No locking, no constraining parallelization.

**Layer isolation is natural.** Layer 0 agents see main. Layer 1 agents see main + layer 0's merged work. The layer system already encodes dependencies — worktrees just make the isolation concrete.

**`.team/` stays in main worktree only.** Agent worktrees don't have system files. FileGuard denies access regardless, and sparse checkout can exclude them.

**Git is infrastructure, not an agent tool.** Agents never get git tools at any phase. The system manages branching the same way it manages the conversation log — transparently, as part of the runtime.

---

## 42. Code Review Phase: Agents Review Each Other's Diffs

### Why Diffs Change Everything

Without worktrees, code review would be agents reading whole files and commenting — with no structure for what's new versus what was already there. With worktrees, the review artifact is a git diff. That's how every engineering team on earth does code review.

### The Review Flow

1. Implementation phase completes for a layer
2. System generates diffs: `git diff main..agent-1/T1` and `git diff main..agent-2/T2`
3. All diffs injected into the review conversation as context — same pattern as groomed scope → planning, planning artifacts → implementation
4. **All implementation agents participate** — reviewing each other's work, not a separate reviewer
5. Coach facilitates review convergence using the same pattern as grooming and planning
6. Coach signals review completion via tool call

### Why Cross-Review

Agent 1 built the API routes. Agent 2 built the data layer. Agent 2 reviewing Agent 1's diff can say "this won't work with my data layer because I defined the schema differently." That's integration review — the highest-value kind of review and the one most teams skip. Each agent has context on the adjacent component that a separate reviewer wouldn't have.

### Why All Diffs Visible to All Agents

Both agents need to see both diffs during review. Agent 1 needs Agent 2's diff to do integration review, and vice versa. The system injects all diffs from the layer, not just "your diff for your review." It's a team review, not isolated PR approvals.

### Layer Ordering Handles Dependencies

Layer 1 review happens after layer 0 is merged into main. Reviewers see layer 1 changes in the context of the merged foundation — exactly right. The layer system already encodes this; review just inherits it.

### Review Outcomes

If review passes: PM gets final review (actual diffs + agents' review conversation as context), then merges.

If changes needed: agents return to their worktrees, make fixes, commit, new diffs generated for re-review. Same worktree, same branch — just additional commits.

### The Coach's Role Is Consistent

Across every phase, the coach does the same thing: facilitate convergence. In grooming: scope convergence. In planning: task decomposition convergence. In review: review convergence — are concerns addressed, is the code ready? The coach doesn't review code. The coach knows when the review is done.

---

## 43. Grooming vs. Refinement: Pre-Iteration Exploration

### The Problem

In real scrum teams, "grooming" covers two distinct activities. One is refining an established story — taking a rough scope and debating requirements, edge cases, and boundaries until it's sprint-ready. The other is exploring nascent, abstract ideas — brainstorming, poking holes, shaping something vague into something actionable. These might become one story, three stories, or nothing.

gotg currently has only the first kind. The phase called "grooming" is really refinement — it lives inside an iteration, produces `groomed.md`, and feeds directly into planning. If you want to explore a vague idea with the agents, you have to `gotg init` an iteration first, which implies a commitment to building something. That's too much structure for "what if we handled error logging differently?"

### The Rename

| Term | What it is | Where it lives | Output |
|------|-----------|---------------|--------|
| **Grooming** | Exploring ideas, pre-iteration | `.team/grooming/<slug>/` | Clarity — maybe becomes iterations, maybe not |
| **Refinement** | Scoping a committed iteration | `.team/iterations/<id>/` | `refined.md` → feeds planning |

The current phase called "grooming" becomes "refinement." The word changes; the behavior, prompts, and outputs stay the same. This is a mechanical rename across `scaffold.py`, `config.py` (PHASE_ORDER), coach prompts, and phase transition messages. The agents don't care what the phase is called — they care about the instructions. As long as instructions stay identical, behavior is identical.

### Grooming: The New Feature

`gotg groom "how should we handle file conflicts?"` starts a freeform conversation in `.team/grooming/<slug>/`. Same agents, same conversation format, same `gotg continue -m` for human input. But no phase system, no `gotg advance`, no convergence pressure, no artifacts. Just the team exploring an idea.

Key properties:
- **No iteration lifecycle.** No phases, no planning, no tasks. Just conversation.
- **Lives outside iterations.** `.team/grooming/` is a sibling of `.team/iterations/`, not nested inside one.
- **No coach facilitation by default.** Exploration benefits from open-ended discussion, not convergence tracking. The PM can always add the coach manually if they want structure.
- **No time pressure.** A grooming conversation can span days or weeks. Pick it up whenever you have a new thought.
- **Multiple concurrent grooming conversations.** Explore several ideas in parallel, each in its own slug directory.

When the idea crystallizes, the PM takes the output and creates iterations manually. Eventually, a `gotg groom-to-iteration` command could have the coach summarize a grooming conversation into an iteration scope — becoming the starting point for refinement. But that's a later convenience, not a launch requirement.

### Sequencing

The refinement rename is low-risk mechanical work — could happen anytime, even mid-iteration-9 development. The grooming feature itself is lower priority than iterations 9–14 (agents need file tools before they need a brainstorming space). Natural slot: after iteration 14 (end-to-end layer execution), when the PM has real experience with the full pipeline and knows what kinds of pre-iteration conversations would have helped.

---

## 44. TUI Design Exploration (Grooming)

### Why a TUI

The current CLI is a sequence of discrete commands — `gotg run`, `gotg show`, `gotg continue -m "..."`, `gotg approvals`, `gotg review`. Each command starts a process, does work, prints output, and exits. A TUI (using Textual) would be a persistent interface that wraps all of this into a live session. Conversations stream in real-time. Approvals appear inline. Phase transitions happen without leaving the interface.

### Architecture Decisions

**Async refactor.** The TUI should drive the core loop in-process rather than spawning subprocesses. Textual runs on asyncio, which is a natural fit. This requires refactoring `run_conversation` and the model call chain to be async. Worth doing — the project would likely move to async eventually regardless of the TUI.

**CLI stays as the underlying API.** The TUI wraps the CLI, it doesn't replace it. The CLI remains testable, scriptable, and usable in headless/CI environments. The TUI is the "IDE"; the CLI is the "compiler." First TUI iteration may require refactoring the CLI to abstract away what's necessary to support both interfaces.

**Event-driven state synchronization.** Instead of each panel polling its own files, the core loop emits events directly. `append_message` emits `MessageAdded`. `approval_store.add_request` emits `ApprovalCreated`. Panels subscribe via Textual's reactive system. One central `AppState` object with reactive attributes, panels bind to the slices they care about. No polling, no timing gaps between panels.

### Launch Flow

`gotg init` remains a one-shot scaffolding command — creates `.team/`, prints instructions, exits. A separate command (`gotg ui` or bare `gotg`) launches the TUI. If `.team/` doesn't exist, the TUI refuses with "run `gotg init` first." Keep the TUI as the runtime interface, keep init as the setup command.

On first launch after init, the TUI detects incomplete setup (no model tested, no iteration description, status pending) and guides the user through remaining setup inline — not a modal wizard, just a checklist showing what's configured, what's missing, and letting the user fix it in place. Common path (description, model, start) is frictionless in the TUI. Advanced config (custom prompts, file_access patterns, worktree config) stays in JSON files.

### Home Screen — Three Navigation Modes

The TUI home screen isn't iteration-first. It's a workspace with three modes:

**Iterations** — shows existing iterations with status/phase, lets PM create new ones. Selecting an iteration enters its conversation view.

**Grooming** — shows ongoing grooming conversations (the pre-iteration exploration feature). Selecting one resumes the chat. Creating a new one asks for a topic and starts a freeform conversation with the agents.

**Settings** — (gear icon, not a main column) unified config view for model, agents, coach, file access, worktrees, approvals. Everything in `team.json`. Editable inline for common settings, with an escape hatch to open `team.json` directly.

The Iterations and Grooming columns clarify the relationship between exploration and committed work. A grooming conversation can eventually be promoted to an iteration via a "Create iteration from this conversation" action (the deferred `gotg groom-to-iteration` feature).

### Chat View — Shared Between Grooming and Iterations

Same layout for both modes, with context-appropriate info tiles.

**Left side (primary):**
- Top: conversation stream, messages flowing in real-time, color-coded by participant. Main viewport, most of the screen.
- Bottom: text input pinned at bottom. Placeholder: "Message the team..." PM types, hits enter, message injected into conversation.

**Right column — info tiles:**
- **Conversation tile:** contextual based on mode. Grooming: topic, started date, message count. Iteration: phase badge, turn count, layer info, pending approvals count, worktree status. Phase-specific actions live here (e.g., "Advance" button when coach signals completion).
- **Participant tiles:** one per agent and coach. Shows name, role, status indicator (speaking/waiting/next). Eventually: a mini activity stream showing tool operations in real-time as the agent works (file_read, file_write calls appearing on the tile before the agent's full response lands in chat). Coach tile could pin the coach's last summary (agreements, unresolved items) as always-visible reference.

### Input/Action Box — Contextual Actions

The input field is always a plain text box. When the system needs a decision, an action bar appears above the input with contextual buttons:

- **Pending approvals:** warning banner with [Review] [Approve All] [Deny All]
- **Coach signals phase complete:** [Advance to Planning] [Keep Discussing]
- **Max turns reached:** [Add 5 Turns] [Add 10 Turns]

The action bar is ephemeral — appears when a decision is needed, disappears once resolved. Power users can also use slash commands in the input (`/advance`, `/approve a1`, `/layer 1`) as keyboard shortcuts.

### Tool Operations — Chat vs. Tile Display

When agents perform file operations during an agentic loop, the operations could appear both in the main chat (as system messages) and on the agent's tile (as a live stream). To avoid redundancy, the chat log could show a collapsed summary ("agent-1 performed 3 file operations" expandable on click) while the tile shows the live stream. This separation keeps the chat focused on substance while the tile shows activity.

### Deferred TUI Concerns

- **Agent-produced rich widgets.** Agents producing structured visual output (tables, trees, diagrams) via Textual widgets. Requires defining a markup language or new tool outputs. Interesting but changes the agent-to-system contract. Later iteration.
- **Iteration-specific screens.** Task boards, layer visualization, merge workflow UI, diff review panel. Design these after the basic chat view is validated.
- **Full settings editing.** All `team.json` fields editable in the TUI. Start with common settings, expand over time.

---

## 45. External Validation: Carlini's 16-Agent C Compiler

### The Experiment

In February 2026, Anthropic researcher Nicholas Carlini published results from an experiment where 16 instances of Claude Opus 4.6 autonomously built a Rust-based C compiler from scratch. Over two weeks and ~2,000 Claude Code sessions ($20K in API costs), the agents produced 100,000 lines of Rust that can compile Linux 6.9 on x86, ARM, and RISC-V, pass 99% of the GCC torture test suite, and compile real projects like PostgreSQL, SQLite, Redis, and FFmpeg. Source: https://www.anthropic.com/engineering/building-c-compiler

### Coordination Mechanism

Strikingly minimal. Each agent runs in a Docker container, clones a shared bare git repo, "locks" a task by writing a file to `current_tasks/`, works on it, pulls/merges/pushes, removes the lock. The infinite loop spawns a fresh Claude Code session and repeats. No phases, no coach, no approval system, no structured conversation between agents. Git merge conflicts are the only coordination mechanism — if two agents claim the same task, git's sync forces the second to pick something else. No orchestration agent. Each agent decides what to work on next autonomously.

### What This Validates for gotg

**Git as coordination substrate.** We arrived at worktrees and branching independently as the right primitive for parallel agent work (principle #26). Carlini's experiment proves this scales to 16 agents. More aggressive than our PM-mediated merge, but the same underlying insight.

**Tests as steering.** Carlini's biggest lesson: the task verifier must be nearly perfect, otherwise agents solve the wrong problem. He built CI pipelines ensuring new commits can't break existing code. This is the testing equivalent of our phase prompts and coach facilitation — structured constraints keeping agents on track without human intervention.

**Documentation as agent memory.** Agents maintain extensive READMEs and progress files because each is dropped into a fresh container with no context. Analogous to our conversation log and artifacts (groomed.md, tasks.json) — persistent state that gives agents context across sessions.

**Context window management matters.** Carlini found the test harness should not print thousands of useless bytes — log to files, let Claude grep when needed. And: Claude can't tell time and will happily spend hours running tests. Our 50K diff budget in iteration 13 is a nod to this, but as conversations grow across layers, compression becomes more critical.

### What This Challenges

**Conversation overhead.** Carlini's agents don't talk to each other at all. No facilitated discussion, no grooming, no planning. They pick tasks and write code. 100K lines of working compiler. For well-defined, test-driven, decomposable problems, the conversation overhead we're building may not be necessary — tests provide sufficient coordination.

**However:** For a compiler, the spec is the C standard — requirements are fully defined externally. For most software projects, the requirements *are* the hard part. That's where gotg's grooming and planning phases earn their keep. Carlini himself notes he hasn't implemented any method for inter-agent communication or high-level goal management.

**PM as bottleneck vs. full autonomy.** Carlini's experiment ran two weeks with minimal intervention. gotg has the PM approving writes, reviewing diffs, advancing phases, merging branches. For gotg's use case (building software where the human has opinions about *what* to build), that's right. But Carlini shows the ceiling: if you specify the problem precisely enough and write good enough tests, you can nearly remove the human.

### Key Insight: Complementary, Not Competing

Carlini's approach is the "let 'em loose" end of the spectrum — minimal structure, maximum autonomy, tests as the only guardrail. gotg is the "structured collaboration" end — phases, facilitation, human oversight, deliberate design conversations. Both work. The question is which problems benefit from which approach. A compiler with a well-defined spec and exhaustive test suites is ideal for Carlini's approach. A product with evolving requirements, design tradeoffs, and stakeholder opinions is where gotg's structure pays off.

This suggests a future direction: gotg could support a "autonomous mode" for implementation phases where agents work more like Carlini's setup (test-driven, minimal oversight) while retaining structured collaboration for design phases (grooming, planning, pre-code-review) where requirements are being discovered.

---

## 46. First Full Test Run: The Calculator

### What happened

Ran the full gotg pipeline against a real task: an interactive command-line calculator with REPL, four operators, error handling, and cross-platform support. Two agents (Qwen 2.5 Coder 7B via Ollama), one coach, all five phases (grooming → planning → pre-code-review → implementation → code-review). 165 messages, 36,265 words, ~2.7M estimated input tokens, $9 total cost.

The good news: it worked. Agents produced a working calculator with proper structure — parser, operations module, formatter, REPL skeleton, exit handling, integration. The grooming phase produced a clean scope document. Planning decomposed into 6 tasks across 3 layers. Code review identified real issues. The system held together end-to-end.

### What broke

**Agents couldn't find their workspace.** Twenty DENIED file operations and ten wasted agent turns at the start of implementation because agents didn't know their writable paths (`src/**`). The implementation prompt said "you are working in your own git branch via a worktree" but never said *where to write*. Agents tried `calc.py`, `calculator/calc.py`, `.worktrees/`, `agent-1/`, `test.txt` before stumbling on `src/` by trial and error.

**Worktree isolation blocked cross-layer dependencies.** Agent-2 needed agent-1's `calc.py` for the integration task (layer 2 depends on layers 0-1). But separate worktrees meant agent-2 couldn't read agent-1's files. Fell back to pasting full file contents in the conversation — twice. The coach correctly identified this as "worktree isolation" but couldn't fix it.

**No layer enforcement.** Agents implemented all three layers in a single implementation phase. The prompt said "work layer by layer" but didn't stop them. After everything was done, the system tried to advance through layers 0→1→2 with phase transitions, confusing the agents ("we've already completed all layers").

**Code review couldn't use diffs.** Agents tried `file_read` on each other's files and got DENIED (worktree isolation again). Fell back to pasting code in chat. The diff injection infrastructure may not have been active, or diffs were empty because worktrees weren't properly set up.

**Empty coach messages.** Signal_phase_complete calls with no text content produced blank messages in the conversation log (messages 129, 157, 161).

### The cost problem

$9 for a calculator is untenable. The breakdown reveals why:

**Input tokens dominate.** 99 turns (68 agent + 31 coach), each re-reading the entire conversation history. By the end, each turn ingests 60+ prior messages. Estimated 2.7M input tokens vs 47K output tokens. The history grows linearly and is never trimmed.

**Pre-code-review is 29% of the conversation.** 10,696 words, 91 code blocks, 12 agent turns — most of it implementation-level detail (Python version, typing syntax, function signatures) that agents could work out themselves during implementation. The only genuinely architectural decision was the error handling interface between components.

**Agents repeat each other.** The confirmation ceremony: agent-1 proposes → agent-2 quotes the proposal back, adds "✅ Agreed" per point, then adds 2-3 actual observations → coach summarizes everything both agents already said. Messages routinely have 30-44 bullet points.

**Round-robin wastes turns.** Fixed rotation means agent-2 must speak even when it has nothing to add. Messages like "I'll wait for agent-2" (when there's nothing to wait for) and duplicate "yes, I'm ready for phase completion" confirmations from both agents.

### Findings → Iteration plans

Organized improvements into three iterations (15-17) that build on each other:

**Iteration 15 — Prompt Efficiency:** Conciseness norms in system prompt ("silence means approval"), coach kickoff messages (template-injected, zero API cost) that tell agents exactly what to do, writable paths in prompts, compressed pre-code-review (interface-only, one round), layer enforcement in implementation prompt. Expected: 50-70% reduction in agent verbosity.

**Iteration 16 — History Management:** Phase boundary markers in conversation.jsonl. `read_phase_history` loads only current-phase messages. Artifacts (groomed.md, tasks.json with notes) carry forward the compressed output of prior phases. Expected: 60-70% reduction in input tokens.

**Iteration 17 — Coach-Directed Flow:** Replace round-robin with coach-controlled turns via `direct_speaker` tool. Coach decides who speaks and what they address. Eliminates empty confirmation turns. `request_admin_input` tool for coach pause. Expected: 30-50% fewer agent turns.

Combined estimate: $9 → $1-2 for equivalent task.

### Key insight

> Principle #31: **The conversation is the most expensive artifact** — every word an agent writes gets re-read by every subsequent turn of every participant; conciseness, history trimming, and directed flow are not optimizations, they're cost-of-operation controls.

---

## 47. The Directed Flow Trap

### The temptation

Iteration 17 was originally designed as coach-directed conversation flow — replace round-robin with a `direct_speaker` tool where the coach decides who speaks next. The cost analysis supported it: 30-50% fewer agent turns by eliminating empty confirmations and "I'll wait" messages.

### Why it's wrong

The `direct_speaker` model turns the coach from a facilitator into a dispatcher. In a real team Slack channel, nobody assigns speaking turns. People read the thread, respond when they have something to say, and stay quiet when they don't. gotg's value proposition is that it creates genuine team dynamics — agents discuss, disagree, converge. Making the coach a control plane pushes gotg toward the "orchestration framework" end of the spectrum and away from the "team conversation" end.

The deeper problem: the coach would need to read the full conversation to decide who should speak, then that agent would also read the full conversation to respond. Same context cost, extra coach call. The savings come only from preventing agent output that pollutes future context — which can be achieved without controlling who speaks.

### The real problem

LLMs can't stay quiet. When you give an LLM a turn, it produces output. Always. The round-robin guarantees every agent gets a turn, and every agent fills that turn with something, even if it's just "✅ Agreed, I'm ready to move on" at 150 words. The cost isn't the output tokens — it's that those 150 words get re-read by every subsequent turn.

### The fix: pass_turn tool

Keep round-robin. Keep natural flow. Give agents a `pass_turn` tool call (same structural pattern as the coach's `signal_phase_complete` — out-of-band, unambiguous, no false positives from in-band text detection, per iteration 5b's lesson). When an agent has nothing to add, they call `pass_turn` instead of producing a message. The system logs a minimal system note ("agent-1 has nothing to add") that doesn't pollute the conversation context.

The agent still gets prompted (one API call to decide), but the pass doesn't add a 200-word message to history. Every subsequent turn has less context to ingest. It's a context growth control, not a call elimination.

This keeps the conversation conversational. The PM can jump in naturally. Agents develop their own rhythm. The coach facilitates rather than orchestrates. In the TUI, it looks like a team chat, not a managed conference call.

> Principle #32: **Conversation flow should emerge, not be assigned** — controlling who speaks turns a team discussion into a conference call; instead, give agents the ability to stay quiet and let natural conversation dynamics determine who contributes.

### What survives from the original plan

- `ask_pm` tool for coach (renamed from `request_admin_input`) — useful when the coach genuinely needs a PM decision
- Empty coach message fallbacks
- The insight that fewer context-polluting messages = lower cost

---

## 48. The Architectural Refactor

### Why now

The codebase hit a ceiling. cli.py grew to 1,556 lines — a god file containing argparse, conversation orchestration, phase transitions, approval handling, worktree management, and checkpoint commands. Every upcoming feature (grooming exploration, TUI, parallel agents) would require either duplicating `run_conversation()` or threading more conditionals through it. Two specific upcoming features made the refactor urgent:

The grooming/refinement split (section 43) needs the conversation engine to work without the iteration lifecycle — same agents, same conversation format, but no phases, no coach by default, no convergence pressure. Without decoupling, this means either a second copy of `run_conversation()` or an increasingly brittle set of `if kind == "grooming"` branches.

The TUI (section 44) needs core logic callable without argparse/print/sys.exit, event-driven output (engine yields events, UI renders them), and eventually async (Textual runs on asyncio). With `print()` calls interleaved 20+ times inside `run_conversation()`, every CLI concern would have to be surgically removed under the TUI refactor — a second rewrite.

### Seven design decisions

**D1: TypedDict over dataclass for domain shapes.** Dataclasses silently drop unknown fields on round-trip. If iteration.json gains a new field in a future iteration, a dataclass-based store would lose it on save. TypedDict is just a type annotation over a regular dict — the underlying dict preserves all fields naturally. The codebase is still evolving rapidly; unknown field preservation matters.

**D2: Stores + Context, not rich domain objects.** `Iteration.advance()` would pull LLM calls, file I/O, and worktree operations into the data object — a different kind of god object. Instead: Store classes handle persistence (ConversationStore, IterationStore), TeamContext bundles config (loaded once, passed everywhere), and the engine handles behavior.

**D3: Sync generator engine, async-ready interfaces.** 650 tests are sync. Async engine means every test needs pytest-asyncio. Textual can run sync generators in worker threads. Converting `Iterator[Event]` to `AsyncIterator[Event]` later is mechanical; event types don't change. Don't pay the async complexity tax now for a feature (parallel agents) that's several iterations away.

**D4: Events are render-agnostic and storage-agnostic.** The engine yields events like `AppendMessage`, `AgentPassed`, `PauseForApprovals`, `CoachAskedPM`, `PhaseCompleteSignaled`. The engine never calls `print()`, `append_message()`, or touches the filesystem directly. The CLI handler persists events to stores and prints to stdout. The TUI handler persists to stores and updates widgets. If the engine contains persistence or rendering calls, the TUI refactor becomes a second rewrite.

**D5: Session policies instead of if/else branching.** A `SessionPolicy` dataclass configures the engine's behavior: history scope (phase-scoped or full), coach cadence, kickoff injection, stop conditions, available tools, artifact injection. The engine reads the policy — it doesn't know what "grooming" or "iteration" means. `iteration_policy()` and `grooming_policy()` are factory functions that build different policies for different session types. No branching inside the engine.

**D6: TOML for prompt externalization.** Bumped minimum Python to 3.11 to get `tomllib` in stdlib (zero new dependencies). All prompt text moves from scaffold.py (~400 lines of string constants) to a structured `prompts.toml` file. Users can customize agent behavior by editing `.team/prompts.toml`. Template variables (`{first_agent}`, `{current_layer}`) resolved at runtime via `str.format_map()` with a `SafeDict` that passes through unknown placeholders.

**D7: Grooming-to-refinement rename is isolated.** The rename of the iteration phase from "grooming" to "refinement" is its own change, separate from structural refactoring. Mixing a rename with structural changes contaminates diffs. Includes backward-compat parsing: existing iteration.json files with `"phase": "grooming"` silently load as "refinement."

### Six refactor iterations

The refactor was executed as six behavior-preserving iterations, each with its own done criteria and test verification. Same inputs produce same outputs throughout.

**R1: TypedDict shapes + TeamContext + Stores.** Foundation for everything. Introduced `types.py` (IterationDict, MessageDict, AgentDict, etc.), `context.py` (TeamContext with `from_team_dir()` factory), ConversationStore wrapping JSONL operations, IterationStore wrapping config load/save. Eliminated duplicated config loading across cmd_* functions.

**R2: Extract session engine with events.** The keystone refactor. Extracted `run_conversation()` into `engine.py` yielding events via sync generator, with `events.py` defining the event dataclasses. Decomposed the 258-line function into `_do_agent_turn()`, `_do_coach_turn()`, `_should_inject_coach()`, and `_build_tool_executor()`. cli.py became a thin event handler loop: `for event in run_session(ctx, policy, ...): ...`

**R3: Decompose cmd_advance() into composable transitions.** Extracted the 221-line `cmd_advance()` into `transitions.py` with standalone functions: `extract_grooming_summary()`, `extract_tasks()`, `extract_task_notes()`, `auto_commit_layer_worktrees()`, `build_transition_messages()`. Each function takes inputs and returns outputs — no print, no sys.exit. `cmd_advance()` became a thin orchestrator under 80 lines.

**R4: Prompt externalization (TOML).** Moved all prompt text from scaffold.py into `data/default_prompts.toml` (package data) with `prompts.py` for loading and template resolution. `gotg init` copies default prompts to `.team/prompts.toml`. Users can edit their copy to customize behavior. scaffold.py dropped from ~656 to ~250 lines.

**R5: Session policies.** Introduced `policy.py` with `SessionPolicy` dataclass and factory functions (`iteration_policy()`, `grooming_policy()`). The engine became policy-driven: history scope, coach cadence, kickoff behavior, stop conditions, and tool lists all come from the policy. No more hardcoded values in the engine.

**R6: Grooming-to-refinement rename.** Mechanical rename across prompts.toml, config.py (PHASE_ORDER), scaffold.py, cli.py, agent.py, and tests. Added backward-compat parsing for existing iteration.json files. Historical conversation messages saying "grooming" left untouched — they're historical facts, not broken data.

### Post-refactor architecture

```
CLI (thin)              Engine (yields events)       Stores (persistence)
┌──────────┐            ┌──────────────────┐         ┌──────────────────┐
│ argparse │            │ run_session()    │         │ ConversationStore│
│ cmd_run  │──policy──→ │   agent turns    │──events→│ IterationStore   │
│ cmd_cont │            │   coach turns    │         │ DebugStore       │
│ handler  │←──events───│   pass detection │         └──────────────────┘
└──────────┘            │   kickoff inject │
                        └──────────────────┘
                              ↑
                        SessionPolicy
                        (from iteration_policy()
                         or grooming_policy())
```

The engine has no `print()`, no `sys.exit()`, no direct file writes. Side effects flow through yielded events (persisted by the handler) and injected dependencies (tool executor, approval store). The TUI can reuse the engine by writing a different event handler. The grooming feature can reuse the engine with a different policy.

> Principle #33: **Refactor when the next feature requires a second copy of existing code** — the right time to decompose is when you'd otherwise duplicate; earlier is speculative, later means you're already maintaining two copies.

---

## 49. Building the TUI

### The approach

The TUI was planned as ten development iterations, each delivering a usable increment. The architecture from the R1-R6 refactor made this possible: the event-driven engine (`run_session` yielding events via sync generator), the session.py bridge layer (shared domain functions between CLI and TUI), and the policy system (same engine, different configuration) meant the TUI never needed to duplicate core logic.

The key architectural decision: **no async**. The engine is a sync generator. Textual runs it in worker threads via `run_worker(thread=True)`. Events flow from the worker thread to the UI thread via `post_message()`. 650+ tests stay sync. The async migration is deferred to when parallel agents actually need it — paying the complexity tax earlier would have slowed every TUI iteration for zero user-visible benefit.

### Ten iterations

**Iteration 1: Read-only viewer.** `gotg ui` launches a Textual app. HomeScreen with TabbedContent (Iterations | Grooming) lists all sessions. Selecting one opens a ChatScreen showing the full conversation history, color-coded by speaker. Right column shows a static InfoTile (phase, turn count, agents, description). Pure UI scaffolding — no engine interaction. Validated the layout, widget structure, and Textual learning curve without risking the conversation system. Optional dependency: `pip install gotg[tui]`.

**Iteration 2: Live conversation streaming.** Text input at bottom of chat view. "Run" and "Continue" launch `run_session` in a worker thread. Messages stream in real-time. ChatScreen state machine (VIEWING → RUNNING → PAUSED → COMPLETE) with action bar for pause events. Extracted `persist_event()` and session setup helpers into session.py — the shared persistence layer both CLI and TUI call. CLI calls persist then prints; TUI calls persist then posts to widgets.

**Iteration 3: Approval management.** ApprovalScreen with split-view (DataTable of requests + ContentViewer with syntax highlighting). Approve (a), deny (d) with reason input, approve-all (y). Extracted `apply_and_inject()` into session.py. When returning from ApprovalScreen, ChatScreen refreshes approval count via `on_screen_resume`. The split-view design is genuinely better than the CLI's one-at-a-time workflow — the PM can scroll through requests and read each file before deciding.

**Iteration 4: Phase advance.** Press P when phase-complete to advance. New ADVANCING state in ChatScreen state machine. Extracted `advance_phase()` into session.py with `chat_call` + `on_progress` parameters (bridge pattern). Progress feedback during LLM extractions via AdvanceProgress events. After advance → VIEWING (not auto-start) so the PM can review artifacts before pressing R.

**Iteration 5: Review, merge, and next-layer.** ReviewScreen with DataTable (branches) + ContentViewer (diff display with Rich "diff" lexer). Merge selected (m), merge all (y), next-layer (n). Extracted `load_review_branches()`, `merge_branches()`, and `advance_next_layer()` into session.py. Conflict handling drops to CLI — git conflict resolution is inherently interactive. Completes the full code-review workflow loop in the TUI.

**Iteration 6: Refactor + app shell.** Code quality fixes (extracted helpers, deduplicated patterns, CSS conventions). Modal infrastructure: TextInputModal and ConfirmModal as reusable ModalScreen[T] components. Help overlay (? key) for keybinding discoverability. Enhanced HomeScreen with N (new iteration), G (new grooming), E (edit), S (settings) bindings and an Info tab. Empty states as first-class — every screen that can be empty shows a helpful message with the keybinding to fix it.

**Iteration 7: Iteration lifecycle completion.** Multi-field EditIterationModal (description, max_turns, status). Mark-done via F key in ReviewScreen when all layers complete. Transparent current-iteration switching when running a non-current iteration. `switch_current_iteration()` and `ITERATION_STATUSES` added to config.py.

**Iteration 8: Settings screen.** SettingsScreen with Collapsible sections: model configuration, agents (DataTable with add/delete/edit), coach toggle, file access paths, worktree toggle. Explicit save (Ctrl+S) rather than auto-save — destructive changes shouldn't be instant. Graceful degradation for malformed team.json.

**Iteration 9: Markdown message rendering.** Chatbox widget replacing MessageWidget — border with border_title for sender name, Markdown widget for content rendering (code blocks, lists, bold, inline code), role-based CSS classes for visual differentiation. Isolated as its own iteration for a clean revert boundary since it touches every message in every conversation view.

**Iteration 10: Chat polish + checkpoints.** Smart auto-scroll (only scroll if user is near bottom). Loading indicator (Textual spinner during RUNNING). Checkpoint management (K to create, L to list/restore with safety prompt). TextArea replacing single-line Input for multi-line replies.

### The session.py bridge layer

Each TUI iteration extracted shared domain logic from cli.py into session.py, following the same pattern: functions raise exceptions instead of calling sys.exit, return data instead of printing, and accept callback parameters for progress reporting. By iteration 5, session.py contains:

- `persist_event()` — shared event persistence (iteration 2)
- Session setup helpers: `resolve_layer`, `build_file_infra`, `setup_worktrees`, `validate_iteration_for_run` (iteration 2)
- `apply_and_inject()` — approval application and denial injection (iteration 3)
- `advance_phase()` — phase transition with LLM extractions (iteration 4)
- `load_review_branches()`, `merge_branches()`, `advance_next_layer()` — code review workflow (iteration 5)

The CLI became thinner with each extraction. cmd_advance went from 110 lines to ~15. cmd_merge, cmd_review, cmd_next_layer similarly reduced. Both interfaces call the same domain functions — the CLI wraps them with print/sys.exit, the TUI wraps them with widgets/notifications.

### Post-TUI state

After iteration 10, the TUI is a complete interface. A user can `gotg init`, launch `gotg ui`, and do everything from the TUI: configure settings, create iterations, run conversations, approve file writes, advance phases, review diffs, merge branches, manage checkpoints, create grooming sessions, and mark iterations done. The CLI becomes a power-user and scripting tool rather than the primary interface.

> Principle #34: **Build the read-only view first** — validating layout and widget structure without engine interaction means you learn the UI framework's idioms before risking the core system; the first TUI iteration should be a viewer, not a controller.

> Principle #35: **Extract the bridge layer incrementally** — each TUI iteration extracts the domain functions it needs from the CLI into a shared module; by the end, the CLI is thin wrappers and the domain logic is reusable.

---

## 50. The Implementation Executor Problem

### What the test run revealed

The calculator test run (section 46) validated refinement through code-review — agents produced well-specified interfaces, good task decomposition, and thoughtful layer ordering. But implementation exposed a fundamental mismatch between the discussion-phase engine and what implementation actually needs.

The engine runs round-robin: agent-1 speaks, agent-2 speaks, agent-3 speaks, coach summarizes, repeat. This works for discussion phases where value comes from agents reacting to each other. Implementation is fundamentally different — agent-1 writes `input_handler.py`, agent-2 writes `division.py`, and they don't need to hear each other. They don't need turns. They need their task context, their worktree, and permission to write files.

Seven problems surfaced:

**Agents implemented all layers at once.** The engine never advanced layers. The implementation kickoff correctly announced "layer 0" with agent-1 and agent-2 assigned, but `advance_next_layer()` was never called between layers. The coach announced layer transitions conversationally ("Layer 1 Implementation Starting Now") — just text, not actual layer advancement. All 6 layers executed in a single uninterrupted session. Every file write from every agent across all layers went into layer-0 worktree branches. Code review found agent-1's layer-0 branch containing parser code (layer 2) and integration code (layer 5).

**File access failures across worktrees.** Direct consequence of no layer advancement. Each agent has an isolated worktree. When agent-3 started "layer 1" (lexer), it tried to read agent-1's `src/input_handler.py` — file not found, because it exists in agent-1's worktree, not agent-3's. This repeated throughout implementation: agent-1 couldn't read `src/lexer.py` for the parser, agent-2 couldn't read `src/ast_nodes.py` for the evaluator. Agents coped by writing code blind — implementing against agreed interfaces from pre-code-review without seeing dependency code. It worked because the interfaces were well-specified, but it's fragile.

**Code review couldn't cross worktree boundaries.** Each agent could only read files in its own worktree. Agent-1 reviewed its own `input_handler.py` and `parser.py`. Agent-2 reviewed its own `division.py` and `evaluator.py`. Nobody could read others' code from disk — they could only review what other agents pasted into conversation messages.

**Round-robin wasted turns during implementation.** Agent-3 sat through layer 0 saying "I'm on standby" (wasting a turn and an API call). The coach narrated "Layer 0 complete, starting Layer 1" (another API call doing the engine's job). Layer 0 had two tasks for two agents — it needed two agent turns, not a full rotation of three agents plus coach.

**Terminal became unresponsive at implementation start.** Implementation is the first phase with tool calls. Refinement, planning, and pre-code-review are pure conversation — one LLM call per turn, yield message, next turn. An implementation turn involves a tool call loop: LLM call → tool_use → execute → feed result back → LLM call → another tool_use → repeat until text response. Agent-1's first implementation turn was 7 sequential LLM API calls plus file I/O. If the engine only yields events between agent turns (not between tool calls within a turn), the UI gets nothing for 30-60 seconds.

**The coach managed layers instead of the engine.** The coach did a good job simulating layer management — announcing which agents should work, telling others to stand by, tracking completions. But this is the engine's job. The system should pause after each layer's agents complete, signal a layer-complete event, and wait for the PM to advance. The conversation just kept going and the coach filled the vacuum.

**A file_write bug.** One `file_write` call failed with a KeyError on `content` — likely a malformed tool call from the LLM. The agent retried and succeeded. Edge case in tool input parsing that needs handling.

### The design: layer-scoped dispatch

Implementation needs a different executor. Discussion phases use round-robin because value comes from agents reacting to each other. Implementation has no conversation — agents write code independently, and the value comes from completing tasks correctly against specified interfaces.

The implementation executor works per-layer:

```
For each layer in tasks.json:
  1. Identify assigned agents for current layer
  2. Dispatch ONLY those agents (skip unassigned entirely)
  3. Each agent gets a focused session with task context
  4. When all assigned agents report completion:
     - Pause execution
     - Signal PM: layer complete, ready to merge
  5. PM reviews/merges worktrees (or auto-merge if no conflicts)
  6. Advance to next layer
  7. New worktrees branch from updated main
  8. Repeat until all layers done
  9. Enter code-review with full codebase visible
```

The critical insight: agents don't need to "obey" layer boundaries via prompts — they never get the opportunity to misbehave. An agent assigned to layer 3 simply doesn't get called until layers 0-2 are merged. No prompt instruction needed. Structural enforcement.

Within a layer, agents work independently. Layer 0's tasks (input validation and integer division) have no dependencies on each other. Layer 1's task (lexer) depends on layer 0, not on other layer 1 tasks. If two agents are both assigned to the same layer, their tasks should be independent by definition — otherwise they'd be in different layers. Worktree isolation within a layer is correct.

The problem exists only at layer boundaries: layer 1 agents need to see layer 0's merged output. The merge step between layers makes prior work visible.

### Worktree strategy: keep them for all layers

Multi-agent layers need worktrees for directory isolation and conflict detection. Single-agent layers technically don't — nobody else is writing — but worktrees still provide a review boundary. The PM sees a reviewable diff before merging to main. Adding a separate "branch only" mode for single-agent layers produces the same result with added code path complexity. Same mechanism everywhere, simpler system.

### Code review timing: merge gate, not review gate

Per-layer code review where agents debate whether each other's code is correct before proceeding would be overkill for most projects — agent-2 and agent-3 debating agent-1's `input_handler.py` before the lexer can start adds turns and cost with minimal benefit. The real review happens at the end, when the full system exists and agents can assess how everything fits together.

The proposed flow: auto-merge at each layer boundary (or PM quick-approve if conflicts), comprehensive code-review phase at the end with all code visible. Per-layer checkpoint is a merge gate, not a review gate. The test run agents independently reached this same conclusion — they built everything, reviewed at the end, and said "Option A: merge all now."

An optional review-per-layer mode could exist for high-risk projects where the PM wants to validate each layer before proceeding. But auto-merge-per-layer with comprehensive final review is the default.

### Tool call event yielding

Whatever executor model runs, each tool call result needs to yield an event immediately so the UI can show progress. `[file_write] src/parser.py (4412 bytes)` appearing in the chat stream tells the PM something is happening. The current issue — events only yielded between agent turns, not between individual tool calls — makes the system appear frozen during any turn with multiple file operations.

### Why not async now

The implementation executor dispatches agents per-layer. If a layer has two agents, they could run in parallel via threads — `ThreadPoolExecutor`, thread-safe event queue, each agent runs its normal sync tool loop. The engine stays sync. The tests stay sync. `model.py` stays `requests`.

But parallel dispatch within layers is a speed optimization, not a correctness fix. Layer 0 with two agents takes 60 seconds sequentially instead of 120 seconds in parallel. Nice, but not what's broken.

What's broken is: no layer enforcement, no merge between layers, wasted turns from unassigned agents, no tool-call-level event yielding. All of these are fixed by the sequential implementation executor. Parallel dispatch is a follow-up that becomes trivial once the executor already thinks in terms of "dispatch these N agents for this layer" — you're just changing *how* the dispatch happens, not *what* gets dispatched.

The full async migration (convert `run_session` to async generator, switch `model.py` from `requests` to `httpx.AsyncClient`, add `pytest-asyncio` to 950+ tests, change every `for event in run_session()` to `async for event in run_session()`) remains deferred. Threads are sufficient for parallel agents when that time comes.

### Structural completion: the `complete_tasks` tool

Discussion phases use `signal_phase_complete` (coach tool call) for completion. Implementation needs the same pattern at the task level. Without it, the executor has no structural signal that an agent is done — it would rely on the coach narrating "agent-1 finished" (the exact text-based detection that failed in the test run) or on counting turns (fragile).

The `complete_tasks` tool lets agents declare completion explicitly:

```python
# Agent tool call
complete_tasks(task_ids=["input-validation-preprocessing"])
```

The executor tracks completion state per task. When all current-layer tasks are marked complete, it emits `LayerComplete` and stops. This is principle #21 (out-of-band signaling) applied to implementation — the same insight that moved phase completion from in-band string detection to `signal_phase_complete` tool calls.

Each agent's implementation prompt includes only their assigned tasks for the current layer. When they've written the code and are satisfied, they call `complete_tasks`. No coach involvement needed. No text parsing. The executor knows structurally when the layer is done.

### Tool input validation hardening

The test run's `file_write` KeyError (missing `content` field in tool call) points to a gap in `tools.py`. Tool input validation should check for required fields, correct types, and return clear error messages that the LLM can act on — not crash with a Python exception. The LLM retried and succeeded, but the retry was accidental (it just happened to try again). Proper validation would return a tool error result that the model can parse and correct: `{"error": "file_write requires 'content' field, got: path"}`.

### Implementation plan

New files: `src/gotg/execution/implementation.py` (implementation-specific executor). Modified: `engine.py` (route implementation phase to new executor), `session.py` (layer completion detection, merge orchestration), `events.py` (new events: `LayerComplete`, `ToolCallProgress`), `tools.py` (input validation hardening, `complete_tasks` tool).

The executor function:

```python
def run_implementation_phase(
    team_dir, iteration, iter_dir, tasks, current_layer,
    model_config, chat_call, on_event
) -> ImplementationResult:
    # Load only current_layer tasks
    # Dispatch only assigned agents with task-scoped prompts
    # Agents call complete_tasks(task_ids) when done
    # Executor tracks completion state per task
    # When all layer tasks complete: emit LayerComplete, stop
    # Yield tool call progress as first-class events
```

Estimated: ~25 tests (layer dispatch, completion detection via `complete_tasks`, merge orchestration, tool event yielding, single vs multi-agent layers, tool input validation edge cases).

> Principle #36: **Enforce structure structurally, not conversationally** — if agents shouldn't cross layer boundaries, don't tell them not to; don't call them until it's their turn. Prompt-based constraints are suggestions; execution-model constraints are guarantees.

> Principle #37: **Different work modes need different execution models** — discussion phases benefit from round-robin conversation where agents react to each other; implementation phases benefit from task-scoped dispatch where agents work independently. One engine shape doesn't fit both.

---

## Current State (Post-File-Safety-Design)

### What Exists
- Working Python CLI tool (`gotg`) installable via pip
- Nine commands: `init`, `run`, `continue`, `show`, `model`, `advance`, `checkpoint`, `checkpoints`, `restore`
- Planned commands (Iterations 9-14): `approvals`, `approve`, `deny`, `review`, `merge`
- `continue` command with human message injection (`-m`)
- `--max-turns` override on both `run` and `continue`
- Nested iteration directory structure (`.team/iterations/<id>/`)
- `team.json` consolidating model config + agent definitions + coach config
- `iteration.json` as list with `current` pointer, includes `phase` field
- `gotg advance` command — moves phase forward, writes system transition message
- Coach agent in `team.json` — separate from engineering agents
- `gotg advance` from grooming invokes coach to produce `groomed.md`
- Coach summarization prompt (`COACH_GROOMING_PROMPT`)
- Coach-as-facilitator — injects after every full agent rotation during conversations
- Coach facilitation prompt (`COACH_FACILITATION_PROMPT`) — tracks agreements, lists unresolved items, drives toward decisions
- Coach awareness paragraph in engineering agent prompts — tells agents to let coach handle process management
- Coach messages don't count toward `--max-turns`
- Coach rendered in orange (256-color) in terminal output
- `signal_phase_complete` tool call — coach signals phase completion via out-of-band tool call instead of in-band string detection
- `chat_completion()` returns `str | dict` depending on whether tools are provided
- Planning mode prompt with DO/DO NOT structure
- `groomed.md` injection into planning phase prompts
- API format translation for tools — Anthropic tools go directly in request body, OpenAI wraps in `{"type": "function", "function": {...}}`
- **New (Iter 6):** `tasks.json` generation from planning conversations via coach, with `compute_layers()` for dependency-based execution ordering
- **New (Iter 6):** `tasks.py` module — layer computation and formatted task summary for prompt injection
- **New (Iter 6):** Task list injection into pre-code-review agent and coach prompts
- **New (Iter 6):** Anthropic prompt caching — `cache_control` markers on system prompt and second-to-last message, ~90% input cost reduction on cache hits
- **New (Iter 7):** Phase-specific coach facilitation prompts (`COACH_FACILITATION_PROMPTS` dict) — each phase has tuned completion criteria
- **New (Iter 7):** Pre-code-review agent prompt — layer-by-layer, one task at a time, propose for YOUR tasks, review teammates', describe signatures not full code
- **New (Iter 7):** Task assignment validation gate — blocks pre-code-review if any tasks have `assigned_to: null`
- **New (Iter 7):** Neutralized `DEFAULT_SYSTEM_PROMPT` — removed implementation-avoidance language, phase prompts drive behavior
- **New (Iter 8):** Checkpoint/restore system — auto-checkpoint after every run/continue/advance, manual via `gotg checkpoint`
- **New (Iter 8):** Discovery-based backup — all files except `debug.jsonl` and `checkpoints/`, new artifacts automatically included
- **New (Iter 8):** `gotg restore N` with pre-restore safety prompt, updates iteration.json fields
- **New (Iter 8):** `save_iteration_fields()` generalized config helper
- Phase-aware system prompts — grooming mode constrains agents to scope/requirements
- Base prompt explains phase system to all agents regardless of current phase
- Phase sequence: grooming → planning → pre-code-review
- Consolidated message format with speaker labels and @mentions
- Dynamic teammate list in system prompts with role labels
- JSONL conversation log with `from`, `iteration`, `content`
- System messages for phase transitions (rendered in magenta)
- Human messages excluded from agent turn count
- OpenAI-compatible and Anthropic API provider support
- Debug logging (prompts sent to models, per-iteration directory)
- Conversation history tracking with commit-id filenames
- Public GitHub repo: https://github.com/MBifolco/gotg
- Conversation logs: 7B two-party, Sonnet two-party, Sonnet three-party (separate messages), Sonnet three-party (consolidated), Sonnet three-party (with @mentions), REST API design (directory restructure), CLI todo grooming (2-agent, phase system test), CLI bookmark manager grooming (3-agent, 15-turn, unfacilitated with coach artifact), CLI pomodoro timer grooming (3-agent, coach-facilitated, early exit), CLI pomodoro timer full run (3-agent, tool-call-based completion, grooming + planning phases, 41 turns), CLI todo list full run (2-agent, all three phases including pre-code-review, 11 tasks reviewed layer-by-layer), CLI calculator full run (2-agent, grooming + planning + pre-code-review, 7 tasks)

### Implementation Plan Progress (Resequenced)
- ✅ **Iteration 1: Directory restructure** — complete
- ✅ **Iteration 2: Phase state and `gotg advance`** — complete
- ✅ **Iteration 3: Grooming mode** — complete, core hypothesis validated
- ✅ **Iteration 4: Agile Coach artifact generation** — complete, second hypothesis validated
- ✅ **Iteration 4b: Coach-as-facilitator** — complete, third hypothesis validated
- ✅ **Iteration 5: Artifact injection and planning mode** — complete (mechanical wiring)
- ✅ **Iteration 5b: Coach tool call for phase completion** — complete, false positive eliminated, tool infrastructure established
- ✅ **Iteration 6: `tasks.json` generation and prompt caching** — complete, layer computation working, cache hits confirmed
- ✅ **Iteration 7: Pre-code-review prompt tuning** — complete, phase-specific facilitation, all 11 tasks reviewed layer-by-layer
- ✅ **Iteration 8: Checkpoint/restore** — complete, discovery-based backup, auto + manual checkpoints, restore with safety prompt
- ✅ **Iteration 9: File tools + FileGuard** — complete
- ✅ **Iteration 10: Structured approval system** — complete
- ✅ **Iteration 11: Git worktree infrastructure** — complete
- ✅ **Iteration 12: Merge workflow + PM review** — complete
- ✅ **Iteration 13: Code review with diffs** — complete
- ✅ **Iteration 14: End-to-end layer execution** — complete, 5-phase system with implementation phase, current_layer tracking, next-layer command
- ✅ **Iteration 15: Prompt efficiency & agent awareness** — complete, conciseness norms, system kickoff messages, writable path injection, compressed pre-code-review, layer enforcement in prompts
- ✅ **Iteration 16: History management** — complete, phase boundary markers, phase-scoped history loading, task notes extraction, ~60-70% input token reduction
- ✅ **Iteration 17: Pass-turn and coach tools** — complete, pass_turn tool for agents, ask_pm tool for coach, @mention awareness in prompts
- ✅ **Refactor R1: TypedDict shapes + TeamContext + Stores** — complete, types.py, context.py, ConversationStore, IterationStore
- ✅ **Refactor R2: Session engine with events** — complete, engine.py yielding events via sync generator, events.py dataclasses, cli.py as thin handler
- ✅ **Refactor R3: Decompose cmd_advance** — complete, transitions.py with standalone extraction functions, cmd_advance under 80 lines
- ✅ **Refactor R4: Prompt externalization (TOML)** — complete, prompts.toml, prompts.py, Python 3.11+ requirement
- ✅ **Refactor R5: Session policies** — complete, SessionPolicy dataclass, iteration_policy() and grooming_policy() factories
- ✅ **Refactor R6: Grooming-to-refinement rename** — complete, mechanical rename with backward-compat parsing
- ⬜ **Implementation executor redesign** — planned, layer-scoped dispatch replacing round-robin for implementation phase, structural layer enforcement, `complete_tasks` tool for agent completion signaling, tool-call-level event yielding, tool input validation hardening, merge gates between layers (blocks second test run)
- ✅ **Grooming feature** — complete, gotg groom "topic" for freeform pre-iteration exploration, grooming_policy() factory, .team/grooming/<slug>/ directory structure
- ⬜ **TUI Iteration 1: Read-only viewer** — planned, gotg ui launches Textual app, HomeScreen with iteration/grooming lists, ChatScreen with conversation history, InfoTile sidebar
- ⬜ **TUI Iteration 2: Live conversation streaming** — planned, run_session in worker thread, messages stream in real-time, ChatScreen state machine, persist_event + session setup helpers extracted to session.py
- ⬜ **TUI Iteration 3: Approval management** — planned, ApprovalScreen with split-view (DataTable + syntax-highlighted ContentViewer), apply_and_inject extracted to session.py
- ⬜ **TUI Iteration 4: Phase advance** — planned, P key to advance, ADVANCING state, advance_phase extracted to session.py with progress callbacks
- ⬜ **TUI Iteration 5: Review, merge, next-layer** — planned, ReviewScreen with diff viewer, merge workflow, load_review_branches + merge_branches + advance_next_layer extracted to session.py
- ⬜ **TUI Iteration 6: Refactor + app shell** — planned, helpers extraction, modal infrastructure (TextInputModal, ConfirmModal), help overlay, enhanced HomeScreen bindings, empty states
- ⬜ **TUI Iteration 7: Iteration lifecycle** — planned, EditIterationModal, mark-done, switch-current, ITERATION_STATUSES
- ⬜ **TUI Iteration 8: Settings screen** — planned, SettingsScreen with Collapsible sections, explicit save, agent management
- ⬜ **TUI Iteration 9: Markdown rendering** — planned, Chatbox widget replacing MessageWidget, Rich Markdown content, role-based border styling
- ⬜ **TUI Iteration 10: Chat polish + checkpoints** — planned, smart auto-scroll, loading indicator, checkpoint management (K/L bindings), TextArea input

First full test run complete (calculator, $9). Iterations 1-17 complete. Architectural refactor (R1-R6) complete. Grooming feature complete. Implementation executor redesign identified as critical — fixes layer enforcement, worktree isolation, and UI responsiveness; blocks second test run. TUI roadmap: 10 iterations from read-only viewer to complete self-sufficient interface.

### Key Findings
- The protocol produces genuine team dynamics when the model is capable enough
- 7B models can't sustain disagreement; Sonnet can argue, persuade, and change positions
- The quality ceiling is the model; the quality floor is the protocol
- Consolidated messages fix attribution confusion — agents correctly track who said what
- @Mentions activate conversation management behavior — agents direct questions to specific people, route topics, and create implicit accountability
- Three-party conversations are better than two-party — PM input focuses discussion, engineers stress-test PM suggestions
- Three-agent conversations produce coalition formation, mediating voices, and emergent consensus mechanisms
- Agents will push back on the PM when they have good reasons — role hierarchy isn't needed for healthy team dynamics
- Agents defer to PM on scope but continue contributing on engineering details — natural authority emerges without enforcement
- Grooming mode constraints produce better output than unconstrained conversation
- Agents self-correct when approaching constraint boundaries
- Phase awareness changes agent orientation — agents structure work as handoffs
- The coach faithfully summarizes conversations it didn't participate in
- **With a facilitator, engineering agents produce zero process-management overhead** — no vote tables, no consensus tallying, no decision categorization
- **Facilitated conversations reach full consensus where unfacilitated ones leave open questions**
- **The coach accurately tracks convergence and signals completion at the right time**
- **Agents respond to coach facilitation naturally** — reference coach's framing, use decision labels, direct process questions to coach
- **Coach facilitation produces better concession quality** — agents concede with genuine reasoning rather than feeling outvoted
- **The coach actively maintains the grooming/implementation boundary** — redirects drift in ways the mode prompt alone cannot
- **Convergence-driving behavior may suppress late-emerging requirements** — need explicit "what did we miss?" before completion
- **In-band signaling (special strings in text) produces false positives** — models reference signal tokens conversationally, triggering early exit
- **Tool calls eliminate false positives structurally** — `tool_use` blocks are unambiguous, coach can discuss completion freely in text
- **Planning output flows naturally from groomed scope injection** — agents reference agreed requirements and stay within scope boundaries
- **Agents naturally organize tasks into dependency layers** — foundation → core → commands → robustness pattern emerges without explicit prompting
- 12-15 turns is a good grooming range for medium-complexity features with 3 agents
- Prompt architecture is a first-class design concern, not an implementation detail
- Small prompt conventions can activate large behavioral changes when they align with model training data
- **Coach facilitation must be phase-specific** — grooming completion ("all scope resolved") differs from pre-code-review completion ("all tasks discussed"); a generic facilitation prompt causes premature signaling
- **One-time checklist beats incremental tracking** — asking the coach to enumerate every task ID before signaling is more reliable than asking it to maintain a running tally across turns
- **"Describe, don't implement" requires explicit framing** — agents default to writing full code unless told there's a later code-review phase and that signatures/descriptions are the goal
- **Task assignment is a PM gate, not an agent decision** — blocking pre-code-review on unassigned tasks prevents agents from proposing approaches for tasks nobody owns
- **Layer-by-layer review mirrors layer-by-layer execution** — reviewing foundation tasks before dependent tasks produces better interface alignment
- **Discovery-based backup prevents silent data loss** — hardcoded file lists go stale when new artifacts are added; scanning with an exclude list ensures new files are automatically protected
- **Application-level path validation is necessary but not sufficient** — once an agent spawns a subprocess, the orchestrator loses visibility; OS-level enforcement (Docker, bubblewrap) is the real boundary for bash tools
- **The conversation log is a free audit trail** — every tool call is a message in the JSONL log; no separate logging infrastructure needed for file operation observability
- **Git worktrees solve parallel agent isolation without constraining task decomposition** — agents work in separate filesystem views branched from main; conflicts detected at merge, not prevented at write
- **Locking constrains parallelization; branching enables it** — file checkout/locking forces task decomposition to be file-aware; git branching allows decomposition by feature/responsibility, which is how real teams work
- **Agents should be unaware of infrastructure** — agents call `file_write` with relative paths; the system handles worktree mapping, git branching, and merging transparently; this matches the principle that agents handle substance, the system handles process
- **Cross-review beats separate reviewers** — the agent who built the adjacent component has the most context on integration points; cross-review catches interface mismatches that a dedicated reviewer would miss
- **Diffs constrain review scope naturally** — without diffs, reviewing agents critique code that existed before the current task; diffs focus review on what actually changed, which is what review should be
- **Structured approvals follow the same pattern as phase advancement** — `gotg approve`/`gotg deny` mirror `gotg advance`; structured in, structured out, no message parsing
- **Exploration and convergence need different conversation modes** — the current "grooming" phase is really refinement (convergent, produces `groomed.md`, feeds planning); true grooming is pre-iteration exploration without convergence pressure or artifacts
- **The TUI is a viewer with interaction hooks, not a controller** — the primary experience is watching a team conversation stream in real-time with the ability to intervene when needed (approvals, messages, phase advances); the CLI remains the underlying API for testability and scripting
- **Structure and autonomy serve different phases of the same project** — design phases (grooming, planning, code review) benefit from structured conversation and human oversight; implementation phases could benefit from Carlini-style autonomous execution where tests steer the agents and the human steps back
- **Input tokens are the cost driver, not output tokens** — in a multi-agent conversation, each turn re-reads the full history; 99 turns reading an ever-growing log produced ~2.7M input tokens vs ~47K output; history trimming at phase boundaries is the single highest-leverage cost intervention
- **TypedDict preserves unknown fields where dataclasses don't** — in a rapidly evolving codebase, TypedDict over regular dicts means future schema additions survive round-trips through stores without explicit `extra: dict` fields
- **Event-driven engines decouple rendering from logic** — yielding events from a sync generator lets the CLI print while the TUI updates widgets, without the engine knowing which; the alternative (engine calls print directly) means rewriting the engine for every new frontend
- **Session policies prevent branching inside engines** — configuring behavior via a policy dataclass means the engine doesn't need `if kind == "grooming"` branches; new session types are new policy factories, not new engine code
- **Refactor when duplication would otherwise occur, not before** — the grooming feature and TUI both needed the conversation engine decoupled from CLI concerns; extracting earlier would have been speculative, extracting later would have meant maintaining two copies of run_conversation
- **Sync generators in worker threads avoid premature async migration** — Textual's run_worker(thread=True) + post_message() lets a sync engine drive an async UI framework; the async tax (pytest-asyncio on 650+ tests, httpx.AsyncClient, AsyncIterator) is deferred until parallel agents actually need it
- **The bridge layer pattern (session.py) emerges incrementally** — each TUI iteration extracts exactly the domain functions it needs from cli.py; by iteration 5, session.py contains all shared logic and the CLI is thin wrappers; planning the full extraction upfront would have been speculative
- **Read-only viewers validate UI framework choices without risk** — building the TUI's first iteration as a pure conversation viewer meant learning Textual's widget model, CSS system, and screen navigation on a problem that couldn't break the conversation engine
- **Round-robin conversation is wrong for implementation** — discussion phases benefit from agents reacting to each other; implementation phases are independent task execution where round-robin forces unassigned agents to waste turns saying "I'm on standby" and the coach to narrate layer transitions the engine should enforce
- **Structural enforcement beats prompt-based constraints** — agents told via prompts to "only work on layer 0" implemented all 6 layers in one session; agents that simply aren't called until their layer starts can't misbehave; the execution model is the constraint, not the prompt
- **Layer boundaries must be merge gates** — without merging between layers, dependent agents can't see prior layer output; worktree isolation (correct within a layer) becomes a liability across layers; the merge step makes prior work visible
- **Tool call loops block UI responsiveness** — discussion phases are one LLM call per turn; implementation turns involve 5-10 sequential LLM calls (tool_use loops); if events only yield between turns, the UI freezes for 30-60 seconds during file operations
- **Threads solve parallel agents without async migration** — ThreadPoolExecutor with thread-safe event queue gives parallel dispatch while keeping the sync engine, sync tests, and sync model.py; the full async tax (pytest-asyncio on 950+ tests, AsyncIterator, httpx) is deferred until threads prove insufficient
- **Task completion needs the same out-of-band pattern as phase completion** — `signal_phase_complete` eliminated false positives for phase transitions; `complete_tasks(task_ids)` does the same for implementation layers; without structural completion signaling, the executor relies on coach narration or turn counting, both of which failed in the test run
- **Tool input validation failures should be recoverable, not crashes** — LLMs occasionally produce malformed tool calls (missing fields, wrong types); returning a clear error message the model can parse and retry is better than a Python KeyError that happens to work because the model retries anyway

### Development Strategy
- **Implementation executor next** — layer-scoped dispatch for implementation phase, structural layer enforcement via `complete_tasks` tool, tool-call-level event yielding, tool input validation hardening, merge gates between layers; blocks second test run
- **Second test run** — after executor redesign, validates layer enforcement + cost optimizations from iterations 15-17
- **TUI roadmap: 10 iterations** — read-only viewer (1) → live streaming (2) → approvals (3) → phase advance (4) → review/merge (5) → refactor + app shell (6) → iteration lifecycle (7) → settings (8) → markdown rendering (9) → chat polish + checkpoints (10)
- **TUI roadmap: 10 iterations** — read-only viewer (1) → live streaming (2) → approvals (3) → phase advance (4) → review/merge (5) → refactor + app shell (6) → iteration lifecycle (7) → settings (8) → markdown rendering (9) → chat polish + checkpoints (10)
- TUI iterations 1-5 build the core workflow (run, approve, advance, review, merge); iterations 6-10 make the TUI self-sufficient (create/edit/settings/polish)
- Each TUI iteration extracts shared domain logic from cli.py into session.py — incremental bridge layer construction
- No async until parallel agents need it — worker threads + post_message, engine stays sync generator; parallel agent dispatch within layers uses ThreadPoolExecutor when needed, not async migration
- After TUI iteration 10: full workflow from gotg ui, CLI becomes power-user/scripting tool
- Checkpoint/restore enables rapid experimentation — save state before prompt changes, restore if results are worse
- Use gotg to build gotg — dogfooding drives the priority stack
- Conversation history with commit ids provides systematic (if manual) evaluation infrastructure
- Agent verbosity in planning phase is a known optimization lever — not worth pulling yet

### Deferred (Intentionally)
- `gotg groom-to-iteration` — coach summarizes grooming conversation into iteration scope (after TUI iteration 7 lifecycle)
- Parallel agent dispatch within implementation layers — ThreadPoolExecutor with thread-safe event queue, same sync engine; follow-up after sequential executor is stable (see section 50)
- Full async migration — convert Iterator[Event] to AsyncIterator[Event], httpx.AsyncClient, pytest-asyncio on 950+ tests; deferred until parallel agents prove threads insufficient
- Bash tool for agents (add with Docker sandbox when evidence shows file tools are insufficient)
- File delete tool (start without it — agents can overwrite but not destroy; add with PM approval gate if needed)
- Automated conflict resolution at merge (PM resolves manually or feeds back to agents)
- Agent self-assignment to tasks (requires personality differentiation — human assigns for now)
- Agent personality differentiation (needed for self-selected task assignment — human assigns for now)
- Automated evaluation (after manual rubric is trusted)
- Context window management beyond phase boundaries (sliding window within long phases, message summarization for very long implementation runs)
- Fine-tuned role models (long-term vision)
- Human dashboard / attention management (long-term vision)

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
13. **Dogfooding isn't optional, it's the development strategy** — use the tool to build the tool; let real pain points drive the roadmap
14. **Track attribution, not just agreement** — who originated an idea matters as much as whether the team agreed on it
15. **Prompt architecture is a first-class design concern** — same model, same task, different prompt structure produces measurably different outcomes
16. **Activate existing capabilities, don't teach new ones** — small conventions that align with model training data (like @mentions) produce outsized behavioral changes
17. **Separate observation from participation** — the Agile Coach reads conversations but doesn't argue; different roles need different relationships to the conversation
18. **Constraints improve output quality** — agents given explicit boundaries about what NOT to discuss produce more thorough and thoughtful work within those boundaries
19. **Let the coach manage process, let the engineers manage substance** — process overhead (vote tallying, consensus tracking, decision categorization) belongs to a dedicated facilitator, not to the engineers whose attention should be on the problem
20. **Drive to closure, but check for completeness** — convergence tracking is powerful but can suppress late-emerging requirements; an explicit "what did we miss?" prompt before completion ensures scope quality without sacrificing efficiency
21. **Use out-of-band signaling for control flow** — in-band signals (special strings in text) are fragile because models reference them conversationally; tool calls are structurally unambiguous and let agents discuss the signal freely without triggering it
22. **Phase-specific facilitation beats generic facilitation** — the definition of "done" differs per phase; a coach that tracks scope items in grooming must track task coverage in pre-code-review; generic prompts cause premature completion signals
23. **Prefer exclude lists over include lists for backup** — discovery-based approaches (scan everything, exclude known exceptions) are more robust than enumeration (list specific files); new artifacts are automatically protected without code changes
24. **Least agency, not least functionality** — give agents the minimum tools and permissions to do their job; expand based on observed need, not anticipated need
25. **Infrastructure should be invisible to agents** — agents handle substance (code, design, review); the system handles process (branching, merging, file routing, approvals); mixing the two produces worse outcomes in both
26. **Branching beats locking for parallel work** — locking constrains task decomposition to file boundaries; branching allows decomposition by feature/responsibility and detects conflicts at merge time, which is how real engineering teams work
27. **Cross-review produces integration quality** — the agent who built the adjacent component catches interface mismatches that a dedicated reviewer would miss; code review is a team conversation, not isolated approvals
28. **Separate exploration from commitment** — exploring an idea should not require committing to an iteration; grooming (open-ended, pre-iteration) and refinement (convergent, within an iteration) serve different purposes and need different structures
29. **Surface decisions, don't require memorization** — contextual action bars that appear when the system needs a decision are better than commands the PM must remember; the interface should tell you what's possible right now
30. **Match coordination overhead to problem structure** — well-specified, test-driven problems can run with minimal coordination (git + tests); ambiguous, requirements-driven problems need structured collaboration (phases + facilitation + human oversight); the same project may need both at different stages
31. **The conversation is the most expensive artifact** — every word an agent writes gets re-read by every subsequent turn of every participant; conciseness, history trimming, and directed flow are not optimizations, they're cost-of-operation controls
32. **Conversation flow should emerge, not be assigned** — controlling who speaks turns a team discussion into a conference call; instead, give agents the ability to stay quiet and let natural conversation dynamics determine who contributes
33. **Refactor when the next feature requires a second copy of existing code** — the right time to decompose is when you'd otherwise duplicate; earlier is speculative, later means you're already maintaining two copies
34. **Build the read-only view first** — validating layout and widget structure without engine interaction means you learn the UI framework's idioms before risking the core system; the first TUI iteration should be a viewer, not a controller
35. **Extract the bridge layer incrementally** — each TUI iteration extracts the domain functions it needs from the CLI into a shared module; by the end, the CLI is thin wrappers and the domain logic is reusable
36. **Enforce structure structurally, not conversationally** — if agents shouldn't cross layer boundaries, don't tell them not to; don't call them until it's their turn; prompt-based constraints are suggestions, execution-model constraints are guarantees
37. **Different work modes need different execution models** — discussion phases benefit from round-robin conversation where agents react to each other; implementation phases benefit from task-scoped dispatch where agents work independently; one engine shape doesn't fit both
