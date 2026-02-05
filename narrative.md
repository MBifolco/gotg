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
