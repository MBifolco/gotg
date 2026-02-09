# Post-Run Improvement Iterations

## Issue Inventory

From initial review:
1. Agents don't know writable paths → 20 DENIED operations, 10 wasted turns
2. Worktree isolation broke cross-agent dependencies (agent-2 couldn't read agent-1's files)
3. All layers implemented in single phase (no enforcement)
4. Code review couldn't access diffs via file tools (fell back to pasting in chat)
5. Merge conflict handled conversationally, not via gotg merge
6. Empty coach messages on signal_phase_complete (messages 129, 157, 161)
7. `_validate_task_assignments` didn't gate implementation phase

From cost analysis ($9 for a calculator):
8. No coach kickoff — agents waste turns orienting at phase start
9. Full history rides along forever — 2.7M estimated input tokens
10. No per-agent task summaries — agents re-derive context from raw conversation
11. Extreme verbosity — 36K words, 91 code blocks in pre-code-review alone
12. No coach pause mechanism for admin input
13. Blind round-robin turn order — agents speak when they have nothing to add

Pre-code-review question: 10,696 words (29% of conversation) for mostly implementation-level decisions. Compress, don't eliminate.

---

## Iteration 15: Prompt Efficiency & Agent Awareness

**Goal:** Reduce token waste from verbosity, orientation confusion, and missing environmental context through prompt improvements and small behavioral changes. No structural changes to run_conversation.

**Addresses issues:** #1, #3, #6, #8, #11, pre-code-review compression

### Changes

#### 1. Conciseness instructions in DEFAULT_SYSTEM_PROMPT (scaffold.py)

Add to `DEFAULT_SYSTEM_PROMPT`:

```
Be concise. State only new information — do not repeat what teammates
have already said. If you agree with a proposal, say so in one sentence
and move on; silence on a specific point means approval. When reviewing
a teammate's proposal, comment only on what you would change or what
concerns you.

Write in short prose paragraphs. Do not use markdown headers, bullet
lists, or checkbox formatting in your messages. Do not use emoji.
```

**Rationale:** Agents currently produce 500-1000 word messages with 30+ bullets and repeat each other's points with "✅ Agreed" per item. These instructions target the specific patterns observed. The "silence means approval" norm is key — it lets agents skip the confirmation ceremony.

**Risk:** Agents may become too terse and miss important disagreements. Mitigated by: the coach still summarizes and tracks unresolved items. If something was silently approved but shouldn't have been, code review catches it.

#### 2. Coach kickoff messages per phase (scaffold.py + cli.py)

Add `COACH_KICKOFF_MESSAGES` dict in scaffold.py:

```python
COACH_KICKOFF_MESSAGES = {
    "grooming": (
        "We're starting the grooming phase. Our goal is to define WHAT "
        "we're building — scope, requirements, edge cases — without "
        "discussing HOW to build it.\n\n"
        "{agent_list_with_tasks}"  # Placeholder, no tasks yet
        "Let's begin. {first_agent}, what's your read on the requirements? "
        "What ambiguities or edge cases do you see?"
    ),
    "planning": (
        "We're starting the planning phase. The groomed scope is "
        "available above. Our goal is to break it into concrete, "
        "assignable tasks with dependencies and done criteria.\n\n"
        "{first_agent}, propose an initial task breakdown. {second_agent}, "
        "review it and suggest modifications. Let's converge quickly — "
        "we can refine details in pre-code-review."
    ),
    "pre-code-review": (
        "We're starting pre-code-review. Each person proposes their "
        "implementation approach for their assigned tasks — briefly. "
        "State: (1) files you'll create/modify, (2) public function "
        "signatures, (3) how dependent tasks should call your code.\n\n"
        "One message per task. Other engineers: respond ONLY if you see "
        "an interface mismatch with your own tasks. We don't need to "
        "agree on internal implementation details.\n\n"
        "{agent_task_assignments}"
    ),
    "implementation": (
        "We're starting the implementation phase for layer {current_layer}.\n\n"
        "{agent_task_assignments}\n\n"
        "{writable_paths_info}\n\n"
        "Write your code, then report completion with a brief summary "
        "of what you created. Do not discuss — just implement. If you "
        "have a question that blocks your work, ask it specifically."
    ),
    "code-review": (
        "We're starting code review for layer {current_layer}. "
        "Implementation diffs are included above (if available). "
        "Review your teammates' code against the task requirements.\n\n"
        "For each branch: approve, or raise specific concerns with "
        "file names and line references. One message per reviewer."
    ),
}
```

In `cli.py`, inject kickoff as first message when entering a phase with empty conversation (or after a phase transition):

```python
# In run_conversation, before the main loop:
if coach and not history:
    kickoff = format_coach_kickoff(phase, agents, iteration, fileguard)
    kickoff_msg = {"from": coach["name"], "iteration": iteration["id"],
                   "content": kickoff}
    append_message(log_path, kickoff_msg)
    history.append(kickoff_msg)
```

The `format_coach_kickoff` function fills in the template variables:
- `{agent_list_with_tasks}`: formatted from tasks.json showing each agent's assignments
- `{first_agent}`, `{second_agent}`: from agents list
- `{current_layer}`: from iteration state
- `{writable_paths_info}`: from fileguard.writable_paths

**Key detail:** This is NOT an LLM call. It's a template message injected by the system attributed to the coach. No API cost. The coach's first real turn comes after the agents respond to the kickoff.

**When to inject:** On `gotg run` when conversation is empty, and on `gotg continue` after a phase advance (detect by comparing phase in iteration.json to phase of last system message in history). Could also simply inject on every `run_conversation` call when the last message is a system phase-advance message.

#### 3. Writable paths and worktree info in prompts (agent.py)

Add to `build_prompt`, after the phase prompt injection:

```python
if fileguard and phase in ("implementation", "code-review"):
    writable = ", ".join(fileguard.writable_paths)
    system_parts.append(
        f"FILE ACCESS: You can read any file. You can write to: {writable}. "
        "Writes to other paths will be denied."
    )
```

**Also** inject worktree awareness when worktree_map is active. This requires passing `worktree_map` and `agent_name` to `build_prompt`:

```python
if worktree_map and agent_config["name"] in worktree_map:
    system_parts.append(
        "WORKTREE: You are working in your own isolated git worktree. "
        "Files you write are only visible in your worktree — your "
        "teammates cannot read your files and you cannot read theirs. "
        "If you need to see a teammate's code, ask them to share it "
        "in the conversation."
    )
```

**Signature change:** `build_prompt` gets optional `fileguard=None` and `worktree_map=None` params. The current call site in `run_conversation` already has both available.

#### 4. Current layer enforcement in implementation prompt (scaffold.py)

Modify `PHASE_PROMPTS["implementation"]` (being added in iteration 14) to include:

```
You are implementing layer {current_layer} tasks ONLY. Do not work on
tasks from other layers. Complete your current-layer tasks, report
completion, and wait.
```

This requires `build_prompt` to accept and interpolate `current_layer`. Add as optional param with `.format()` on the phase prompt string, or inject as a separate system_part.

Implementation: add `current_layer` to `build_prompt` signature. In the phase prompt section:

```python
if phase_prompt:
    current_layer = iteration.get("current_layer", 0)
    try:
        phase_prompt = phase_prompt.format(current_layer=current_layer)
    except KeyError:
        pass  # Phase prompt doesn't use {current_layer}
    system_parts.append(phase_prompt)
```

Only the implementation phase prompt template uses `{current_layer}`.

#### 5. Compressed pre-code-review prompt (scaffold.py)

Replace current `PHASE_PROMPTS["pre-code-review"]` and `COACH_FACILITATION_PROMPTS["pre-code-review"]`:

**Agent prompt** — emphasize brevity and interface-only focus:

```
CURRENT PHASE: PRE-CODE-REVIEW

Propose implementation approaches for YOUR assigned tasks. Keep it
brief — the goal is interface alignment, not detailed design.

For each of your tasks, state in one short message:
- Files you will create or modify
- Public function/method signatures with types
- How dependent tasks should call your code
- Any questions for teammates whose tasks yours depends on

For teammate tasks: respond ONLY if you see a mismatch between their
proposed interface and what your code needs. Silence means the
interface works for you.

Do not write full implementations, pseudocode, or test code. Do not
discuss internal implementation details — those are your choice to make
during implementation.
```

**Coach facilitation prompt** — guide structured single-round:

```
You are an Agile Coach facilitating pre-code-review. You do NOT
contribute technical opinions.

The team is proposing implementation approaches. Guide them through
tasks layer by layer. After each agent presents their proposals for
a layer, check: does any engineer see an interface mismatch? If not,
move to the next layer.

Signal completion when all layers have been presented and all
interface concerns resolved. Most tasks should need only one round
of discussion.
```

#### 6. Empty coach messages on signal_phase_complete (cli.py)

Currently coaches produce empty content when they call signal_phase_complete without also writing a text response. Fix in the coach turn handler in `run_conversation`:

```python
# After coach completion
if not response_text.strip():
    response_text = "(Phase complete signal sent.)"
```

Or better: check the tool result from signal_phase_complete and synthesize a message. But the simpler fix is fine for now.

### Files changed

- `scaffold.py`: DEFAULT_SYSTEM_PROMPT (conciseness), COACH_KICKOFF_MESSAGES (new), PHASE_PROMPTS["pre-code-review"] (compressed), COACH_FACILITATION_PROMPTS["pre-code-review"] (compressed), PHASE_PROMPTS["implementation"] uses {current_layer}
- `agent.py`: `build_prompt` gains `fileguard`, `worktree_map`, injects writable paths and worktree info. Phase prompt gets `.format(current_layer=...)`.
- `cli.py`: Kickoff message injection logic. Empty coach message fallback.

### Test updates

- Existing prompt tests: update expected content for conciseness instructions, writable paths
- New test: `test_coach_kickoff_injected_on_empty_conversation`
- New test: `test_coach_kickoff_injected_after_phase_advance`
- New test: `test_writable_paths_in_implementation_prompt`
- New test: `test_worktree_isolation_warning_in_prompt`
- New test: `test_current_layer_in_implementation_prompt`
- New test: `test_empty_coach_message_gets_fallback`

### Expected impact

- **Verbosity:** 50-70% reduction in agent word count. Conciseness norms + compressed pre-code-review + "silence means approval" should cut the 36K words dramatically.
- **Orientation waste:** Near elimination. Coach kickoff tells agents exactly what to do, writable paths prevent DENIED flailing, layer enforcement prevents working ahead.
- **Cost:** Fewer words per message × fewer wasted messages = significant input token reduction even before history trimming.

---

## Iteration 16: History Management

**Goal:** Reduce cumulative input token cost by trimming conversation history at phase boundaries and providing compressed artifacts so agents have context without re-reading the full discussion.

**Addresses issues:** #9, #10, #2 (partially), #4 (partially)

**Depends on:** Iteration 15 (coach kickoff messages work best with clean history starts)

### Design decisions

**When to trim:** On phase advance. When `cmd_advance` writes the phase transition system message, it also writes a history boundary marker. On next `run_conversation` call, history loading respects the boundary.

**What to preserve:** The system prompt already injects artifacts (groomed.md, tasks.json, diffs). These contain the compressed output of prior phases. The trimmed history only needs to contain messages from the current phase.

**How to implement:** Two approaches considered:

**Option A — Boundary marker in conversation.jsonl:**
Add a special system message on phase advance:
```json
{"from": "system", "content": "--- HISTORY BOUNDARY ---", "phase_boundary": true}
```
`read_log` (or a new `read_phase_log`) skips everything before the last boundary marker when loading history for `run_conversation`. Full history still available in the file for review.

**Option B — Separate log files per phase:**
Each phase gets its own `conversation-{phase}.jsonl`. On phase advance, start writing to the new file. `run_conversation` only loads the current phase's file.

**Decision: Option A.** Simpler, preserves the single-file conversation log for human review and TUI display, doesn't change the file layout. The boundary marker is a convention in the existing JSONL format.

**Per-agent task summaries:** Rather than a separate artifact, extend the tasks.json format. During planning→pre-code-review advance, the coach already extracts tasks. After pre-code-review (if kept) or planning, add a `notes` field to each task in tasks.json containing interface decisions:

```json
{
  "id": "input-parsing-validation",
  "description": "...",
  "notes": "File: src/input_parser.py. Function: parse_input(str) -> Union[Tuple[float, str, float], str]. Returns tuple on success, error string on failure.",
  ...
}
```

This is injected via `format_tasks_summary` which already exists. No new artifact file needed.

**Alternative considered:** Per-agent summary files (`task-summary-agent-1.md`). Rejected because it duplicates information already in tasks.json, and adding `notes` to tasks.json keeps everything in one place.

### Changes

#### 1. History boundary on phase advance (cli.py)

In `cmd_advance`, after writing the phase transition system message:

```python
boundary_msg = {
    "from": "system",
    "iteration": iteration["id"],
    "content": "--- HISTORY BOUNDARY ---",
    "phase_boundary": True,
}
append_message(log_path, boundary_msg)
```

#### 2. Phase-scoped history loading (cli.py or log.py)

New function or modify `read_log`:

```python
def read_phase_history(log_path: Path) -> list[dict]:
    """Read conversation log, returning only messages after the last boundary."""
    all_msgs = read_log(log_path)
    # Find last boundary
    for i in range(len(all_msgs) - 1, -1, -1):
        if all_msgs[i].get("phase_boundary"):
            return all_msgs[i + 1:]  # Everything after boundary
    return all_msgs  # No boundary, return full history
```

Update `run_conversation` to use `read_phase_history` instead of `read_log` for building prompts. Keep `read_log` available for full-history display (TUI, export).

#### 3. Task notes from pre-code-review (scaffold.py + cli.py)

Add `notes` field handling to task extraction. Two approaches:

**Option A — Coach extracts notes during phase advance:**
When advancing from pre-code-review → implementation, use a one-shot LLM call (like the grooming summary extraction) to read the pre-code-review conversation and append `notes` to each task in tasks.json.

Prompt:
```
You observed a pre-code-review discussion. For each task in the task
list, extract the agreed implementation approach as a brief note
(2-3 sentences max): files to create, public function signatures,
and key interface decisions. Output JSON matching the existing task
list with a "notes" field added to each task.
```

**Option B — Agents write notes as part of the pre-code-review prompt:**
The compressed pre-code-review prompt (iteration 15) already asks agents to state files, signatures, and interfaces. The coach's summary at phase end could be structured to extract these into task notes.

**Decision: Option A.** One-shot extraction is reliable and doesn't change agent behavior. Cost: one LLM call per advance, reading only the pre-code-review conversation (which is now short thanks to iteration 15's compression).

**Task notes in prompts:** `format_tasks_summary` already exists. Modify it to include `notes` when present:

```
Task: input-parsing-validation (agent-2) [Layer 0] - pending
  Parse input string into components...
  Done: Returns correct parsed values...
  Notes: File: src/input_parser.py. parse_input(str) -> Union[...]
```

#### 4. Cross-worktree code access for dependent layers

When loading history for a layer > 0 implementation phase, agents need access to code from prior layers that has been merged to main. With history trimming + the merge-before-next-layer enforcement from iteration 14, this should work naturally:

- Layer 0 implemented → code reviewed → merged to main
- `gotg next-layer` verifies all merged, creates new worktrees from updated main
- Layer 1 worktrees now contain layer 0's merged code
- Agents can `file_read` predecessor code in their worktrees

**The issue in the test run** was that layers weren't enforced — agents did everything in one pass, so nothing was merged between layers. With iteration 14's layer enforcement + iteration 15's prompt enforcement, this should resolve itself.

**No code change needed** — this is a workflow consequence of proper layer enforcement. Add a note to the implementation phase kickoff: "Your worktree contains all code merged from previous layers. You can read predecessor files directly."

### Files changed

- `cli.py`: `cmd_advance` writes boundary marker. `run_conversation` uses `read_phase_history`. Task notes extraction call on pre-code-review advance.
- `log.py` (or inline in cli.py): `read_phase_history` function.
- `tasks.py`: `format_tasks_summary` includes `notes` field when present.
- `scaffold.py`: Extraction prompt for task notes (similar to COACH_GROOMING_PROMPT / COACH_PLANNING_PROMPT).

### Test updates

- `test_history_boundary_written_on_advance`
- `test_read_phase_history_returns_after_boundary`
- `test_read_phase_history_no_boundary_returns_all`
- `test_task_notes_extracted_on_pre_code_review_advance`
- `test_format_tasks_summary_includes_notes`

### Expected impact

This is the biggest cost lever. Estimated token reduction:

- Grooming: 18 messages × ~380 words avg = ~6,800 words trimmed from all subsequent phases
- Planning: 16 messages × ~450 words avg = ~7,200 words trimmed from implementation onward
- Pre-code-review: 26 messages (compressed to ~8 in iteration 15) trimmed from implementation
- Cumulative: instead of each late-phase turn reading 60+ messages, it reads ~10-20 from the current phase only

Conservative estimate: 60-70% reduction in total input tokens across a full iteration. Combined with iteration 15's verbosity reduction: a $9 run might drop to $2-3.

---

## Iteration 17: Coach-Directed Conversation Flow

**Goal:** Replace blind round-robin turn order with coach-directed turns. The coach decides who speaks next and what they should address, eliminating empty confirmation turns and unnecessary responses.

**Addresses issues:** #13, #12, #5 (partially)

**Depends on:** Iteration 15 (coach kickoff establishes the pattern), Iteration 16 (shorter history makes coach decisions cheaper)

### Design decisions

**How the coach directs turns:**

Currently: `agent = agents[turn % num_agents]` — mechanical rotation, every agent speaks every round, coach speaks after every full rotation.

New model: coach speaks first (kickoff from iteration 15), then directs the conversation. After each agent turn, the coach gets a turn. The coach either:
1. **Directs a specific agent:** "agent-2, please respond to agent-1's concern about the parser interface." → Only agent-2 speaks next.
2. **Opens to all:** "Both engineers, please propose your task breakdowns." → All agents speak (like current rotation, but explicit).
3. **Signals completion:** Uses signal_phase_complete tool → phase ends.
4. **Pauses for admin:** Uses a new `request_admin_input` tool → conversation pauses, PM sees prompt.

**Implementation mechanism — `direct_speaker` tool:**

Add a new coach tool:

```python
{
    "name": "direct_speaker",
    "description": "Direct which team member(s) should speak next. Use 'all' for all engineers.",
    "input_schema": {
        "type": "object",
        "properties": {
            "speaker": {
                "type": "string",
                "description": "Name of next speaker, or 'all' for all engineers"
            },
            "prompt": {
                "type": "string",
                "description": "What you want them to address"
            }
        },
        "required": ["speaker", "prompt"]
    }
}
```

The tool result tells the coach it was acknowledged. The `run_conversation` loop reads the tool call to determine who speaks next.

**`request_admin_input` tool:**

```python
{
    "name": "request_admin_input",
    "description": "Pause the conversation and request input from the project manager.",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "What you need the PM to decide or clarify"
            }
        },
        "required": ["question"]
    }
}
```

Returns the conversation to the PM with a prompt. PM uses `gotg continue` with a message to respond.

### Changes

#### 1. Conversation loop restructure (cli.py)

Current loop:
```
while turn < max_turns:
    agent = agents[turn % num_agents]
    ... call agent ...
    turn += 1
    if turn % num_agents == 0:
        ... call coach ...
```

New loop:
```
while turn < max_turns:
    if not next_speakers:
        # Call coach to decide who speaks next
        ... call coach with direct_speaker tool ...
        next_speakers = parse_coach_direction(coach_result)
        if next_speakers is None:
            # Coach signaled phase complete or admin pause
            break

    agent = next_speakers.pop(0)
    ... call agent ...
    turn += 1
    
    # After the directed speaker(s) finish, coach gets another turn
    if not next_speakers:
        continue  # Back to top, coach decides again
```

When coach calls `direct_speaker(speaker="all", prompt="...")`:
- `next_speakers` = list of all agents
- Each agent gets one turn
- After all respond, coach gets another turn

When coach calls `direct_speaker(speaker="agent-1", prompt="...")`:
- `next_speakers` = ["agent-1"]
- Only agent-1 responds
- Coach immediately gets another turn

When coach calls `request_admin_input(question="...")`:
- Conversation pauses (similar to approval pause)
- PM sees the question
- `gotg continue -m "answer"` injects PM response and resumes

When coach calls `signal_phase_complete(summary="...")`:
- Phase ends as before

#### 2. Coach facilitation prompts — directing behavior (scaffold.py)

Update all `COACH_FACILITATION_PROMPTS` to include:

```
You control the conversation flow. After observing each response,
decide who should speak next using the direct_speaker tool:
- Use speaker="all" when you need input from everyone (e.g., start
  of a new topic or task)
- Use a specific speaker name when only one person needs to respond
  (e.g., answering a question, clarifying a concern)
- Use signal_phase_complete when all goals for this phase are met
- Use request_admin_input when you need a decision from the PM

Do not let the conversation continue longer than necessary. When
engineers agree, move on. When one engineer has confirmed, don't
ask the other to confirm unless there's reason to think they
might disagree.
```

#### 3. Directed prompt injection for agents (agent.py)

When coach directs a specific agent, the coach's prompt/direction should appear as the last user message. Modify the history construction to append:

```
[coach] directs you: {prompt}
```

This replaces the generic "what are your initial thoughts?" opener and gives each agent turn a specific purpose.

#### 4. Coach tool additions (scaffold.py)

Add `direct_speaker` and `request_admin_input` to COACH_TOOLS.

#### 5. Admin pause mechanism (cli.py)

Similar to approval pause:

```python
if coach_requested_admin_input:
    print("---")
    print(f"Coach asks: {question}")
    print("Reply with: gotg continue -m 'your answer'")
    return
```

### Conversation flow example (planning phase)

```
coach: [kickoff] We're starting planning. agent-1, propose a task breakdown.
       [direct_speaker: agent-1]
agent-1: Here's my proposed 5-task breakdown...
coach: Good start. agent-2, review this and suggest modifications.
       [direct_speaker: agent-2]  
agent-2: I'd merge tasks 2 and 3, and split task 4...
coach: You both agree on the merge. agent-1, does splitting task 4 work?
       [direct_speaker: agent-1]
agent-1: Yes, that's cleaner.
coach: All tasks defined. Both engineers confirm?
       [direct_speaker: all]
agent-1: Confirmed.
agent-2: Confirmed.
coach: [signal_phase_complete]
```

That's 5 agent turns instead of the current 10. The coach skips agent-2's confirmation when agent-1 already agreed, directs specific questions to specific people, and doesn't ask for final confirmation from someone who just confirmed.

### Files changed

- `scaffold.py`: COACH_TOOLS (add direct_speaker, request_admin_input). All COACH_FACILITATION_PROMPTS (add directing instructions).
- `cli.py`: `run_conversation` loop restructured. Admin pause handling.
- `agent.py`: `build_prompt` appends coach direction when present.

### Test updates

- `test_coach_directs_specific_speaker`
- `test_coach_directs_all_speakers`
- `test_coach_admin_pause`
- `test_coach_admin_resume_with_message`
- `test_directed_prompt_appears_in_agent_context`
- `test_undirected_fallback_to_round_robin` (backward compat if coach doesn't use tool)

### Risks and mitigations

**Risk: Coach becomes a bottleneck.** Every turn now requires a coach call. If the coach is slow or expensive, this adds latency and cost.

**Mitigation:** Coach turns are shorter (facilitation only, no technical content). With history trimming (iteration 16), coach context is smaller. Net effect: more coach calls but each is cheaper, and significantly fewer agent calls. The math should work out — trading 2 wasted agent calls for 1 short coach call is a win.

**Risk: Coach makes bad directing decisions.** Sends to wrong agent, loops unnecessarily, or doesn't know when to stop.

**Mitigation:** Max turns still enforced as a hard stop. Coach facilitation prompts are specific about when to direct whom. Fall back to round-robin if coach doesn't call direct_speaker (backward compat). Worst case is same behavior as today.

**Risk: Coach doesn't use the tools.** Just writes text without calling direct_speaker.

**Mitigation:** If coach turn completes without a tool call, fall back to directing all agents (round-robin for one cycle), then coach gets another chance. Log a warning. The prompt makes tool use mandatory: "You MUST use either direct_speaker, signal_phase_complete, or request_admin_input at the end of every turn."

### Expected impact

- **Turns:** 30-50% reduction in agent turns. Eliminates empty confirmations, unnecessary responses, and "I'll wait" messages.
- **Cost:** Combined with iterations 15 and 16: a $9 run could drop to $1-2. Fewer turns × shorter history × less verbose messages is multiplicative.
- **Quality:** Coach-directed flow is more focused. Each agent turn has a purpose. Conversations converge faster because the coach can drive toward resolution rather than waiting for organic alignment.

---

## Implementation Order and Dependencies

```
Iteration 14 (already planned): Layer lifecycle, implementation phase, next-layer
    ↓
Iteration 15: Prompt efficiency & agent awareness
    ↓
Iteration 16: History management
    ↓
Iteration 17: Coach-directed conversation flow
```

Iterations 15 and 16 are relatively independent and could be done in either order, but 15 first makes sense because:
- Prompt changes reduce verbosity, which makes history trimming more impactful (trimming verbose history saves more than trimming concise history)
- Coach kickoff establishes the pattern that iteration 17 builds on
- Writable paths fix is the most urgent usability issue

Iteration 17 depends on both because:
- Coach-directed flow assumes concise agent responses (15)
- Cheap coach turns require trimmed history (16)
- The kickoff pattern from 15 naturally extends to the directed flow

### Combined impact estimate

| Metric | Current (calculator run) | After 15 | After 15+16 | After 15+16+17 |
|--------|------------------------|----------|-------------|----------------|
| Agent turns | 68 | ~55 | ~55 | ~30-35 |
| Words per message | ~440 | ~150-200 | ~150-200 | ~150-200 |
| Messages in context (late phase) | 60+ | 60+ | 10-20 | 10-20 |
| Estimated cost | $9 | $4-5 | $2-3 | $1-2 |
