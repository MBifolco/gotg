# Iteration 17: Pass-Turn and Coach Tools

## Summary

Give agents the ability to stay quiet when they have nothing to add, reducing
context pollution from empty confirmation messages. Add an `ask_pm` tool for
the coach to request PM decisions. Add @mention awareness so agents know when
they're being specifically asked to respond. Keep round-robin turn order — 
conversation flow emerges naturally rather than being assigned.

**Addresses issues:** #13 (agents speak when they have nothing to add), #12
(no coach pause mechanism for admin input)

**Depends on:** Iteration 15 (conciseness norms make pass_turn more likely
to trigger), Iteration 16 (phase-scoped history means passes prevent context
growth within the phase)

## Design Decisions

### Why not direct_speaker

The original iteration 17 plan had the coach controlling turns via a
`direct_speaker` tool. This turns the coach from a facilitator into a
dispatcher — architecturally different from the team conversation model
gotg is built around. In the TUI/GUI world, the PM is just another
participant who types when they want to. Nobody assigns speaking turns in
a real team chat.

The real problem is that LLMs can't stay quiet. Given a turn, they always
produce output. The cost isn't the output tokens — it's that a 200-word
"✅ Agreed, looks good!" message gets re-read by every subsequent turn.
A pass_turn tool lets agents opt out without polluting the conversation.

### pass_turn as tool call, not text

Per iteration 5b: in-band signaling is fragile. An agent saying "I'll pass
on reviewing the parser" would false-positive on text detection. A tool call
is unambiguous. Same structural pattern as coach's signal_phase_complete.

### Agent always gets prompted

The agent still receives full context and makes one API call to decide
whether to pass. The savings come after: a pass is logged as a minimal
system note, not as an agent message. It doesn't contribute to context
growth for subsequent turns.

### Always-available tools

Agents currently only have tools during implementation (file tools).
pass_turn needs to be available in all phases. Introduce an AGENT_TOOLS
list that's always provided. File tools are added alongside when file
access is enabled.

## 4 Changes

### 1. Agent tools: pass_turn (scaffold.py)

New constant after COACH_TOOLS:

```python
AGENT_TOOLS = [
    {
        "name": "pass_turn",
        "description": (
            "Call this when you have nothing new to contribute to the "
            "current discussion. Do not call this if you have concerns, "
            "questions, disagreements, or new information to share. "
            "Only pass when you genuinely agree with everything said "
            "and have nothing to add."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason for passing (e.g., 'agree with proposal', 'waiting for layer 2')",
                }
            },
            "required": ["reason"],
        },
    }
]
```

The `reason` field is required so we can log *why* the agent passed (useful
for debugging and for the PM to see in `gotg show`). It doesn't go into
the conversation context that other agents read.

### 2. Coach tool: ask_pm (scaffold.py)

Add to COACH_TOOLS (becomes 2 tools alongside signal_phase_complete):

```python
{
    "name": "ask_pm",
    "description": (
        "Pause the conversation and request input from the project "
        "manager. Use when a decision requires PM authority or when "
        "the team is stuck on a question only the PM can answer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "What you need the PM to decide or clarify",
            }
        },
        "required": ["question"],
    },
}
```

Update all 5 COACH_FACILITATION_PROMPTS to mention ask_pm. Append to each:

```
If the team is stuck on a question that requires PM authority, use the
ask_pm tool to pause and request input.
```

### 3. @mention awareness in agent prompts (agent.py)

In `build_prompt`, after building history messages but before returning,
scan the last few messages for @mentions of this agent:

```python
# @mention awareness: note if this agent was specifically asked to respond
last_messages = [m for m in history[-3:] if m["from"] != agent_name]
mentions = [m for m in last_messages if f"@{agent_name}" in m["content"]]
if mentions:
    mentioner = mentions[-1]["from"]
    system_parts.append(
        f"Note: {mentioner} specifically addressed you with @{agent_name} "
        "in a recent message. They may be waiting for your response on "
        "a specific point."
    )
```

This is a soft nudge, not a hard control. The agent sees they were asked
and is more likely to respond substantively rather than pass. Agents who
were *not* mentioned are more likely to pass if they have nothing to add.

### 4. pass_turn and ask_pm handling in run_conversation (cli.py)

**pass_turn handling:**

Currently agents are called via either `agentic_completion` (with file
tools) or `chat_completion` (without). Change: agents always go through
`agentic_completion` so pass_turn tool is always available.

Build the tool list per turn:

```python
from gotg.scaffold import AGENT_TOOLS

# Always include agent tools (pass_turn)
agent_tools = list(AGENT_TOOLS)

# Add file tools when file access is enabled
if fileguard:
    from gotg.tools import FILE_TOOLS
    agent_tools.extend(FILE_TOOLS)

result = agentic_completion(
    ...,
    tools=agent_tools,
    tool_executor=tool_executor,
)
```

The `tool_executor` needs to handle pass_turn:

```python
def tool_executor(name, inp):
    nonlocal write_count
    if name == "pass_turn":
        return "Turn passed."
    if name == "file_write":
        ...
```

After getting the result, check if pass_turn was called:

```python
# Check for pass_turn
pass_called = any(
    op.get("name") == "pass_turn" 
    for op in result.get("operations", [])
)

if pass_called:
    reason = ""
    for op in result["operations"]:
        if op.get("name") == "pass_turn":
            reason = op.get("input", {}).get("reason", "")
            break
    
    # Log as system note — does NOT go into conversation context
    pass_msg = {
        "from": "system",
        "iteration": iteration["id"],
        "content": f"({agent['name']} passes: {reason})",
    }
    append_message(log_path, pass_msg)
    print(render_message(pass_msg))
    print()
    history.append(pass_msg)
    turn += 1
    continue  # Skip logging agent's response as an agent message
```

Key: when an agent passes, their response text (which might be empty or
a brief explanation) is NOT logged as an agent message. Only the system
note goes into history. This is the core mechanism — passes don't add to
the conversation context that gets re-read by subsequent turns.

**ask_pm handling:**

In the coach turn section, after checking for signal_phase_complete:

```python
# Check for ask_pm
ask_pm_calls = [tc for tc in coach_tool_calls if tc["name"] == "ask_pm"]
if ask_pm_calls:
    question = ask_pm_calls[0]["input"]["question"]
    coach_msg = {
        "from": coach["name"],
        "iteration": iteration["id"],
        "content": coach_text if coach_text.strip() else f"(Requesting PM input: {question})",
    }
    append_message(log_path, coach_msg)
    print(render_message(coach_msg))
    print()
    
    print("---")
    print(f"Coach asks: {question}")
    print("Reply with: gotg continue -m 'your answer'")
    return
```

Same pattern as approval pause (lines 311-319 in current code). PM uses
existing `gotg continue -m` to respond.

**No-tool-call agent path:**

When fileguard is None and we switch all agents to `agentic_completion`,
agents that previously used plain `chat_completion` now get tool support.
This is fine — `agentic_completion` with only AGENT_TOOLS (just pass_turn)
behaves like chat_completion but with the option to pass. If the model
doesn't call pass_turn, the response flows through normally.

However: verify `agentic_completion` works correctly when the model
doesn't use any tools. It should return `{"content": "...", "operations": []}`
in that case. Check existing implementation.

**Prompt addition for pass_turn awareness:**

Add to DEFAULT_SYSTEM_PROMPT in scaffold.py:

```
If you have nothing new to contribute — you agree with what's been said
and have no concerns, questions, or additions — use the pass_turn tool
instead of restating agreement. Only pass when you genuinely have nothing
to add; do not pass if you have any reservations.
```

## Files Changed

- `scaffold.py`: AGENT_TOOLS (new), ask_pm in COACH_TOOLS, pass_turn
  guidance in DEFAULT_SYSTEM_PROMPT, ask_pm mention in all
  COACH_FACILITATION_PROMPTS
- `agent.py`: @mention awareness scan in build_prompt
- `cli.py`: agents always use agentic_completion, tool list construction
  (AGENT_TOOLS + FILE_TOOLS), pass_turn detection and system-note logging,
  ask_pm detection and conversation pause

## Tests

### New tests (~14)

**test_scaffold.py (3):**
- test_agent_tools_pass_turn_schema — verify pass_turn in AGENT_TOOLS with
  reason field
- test_coach_tools_ask_pm_schema — verify ask_pm in COACH_TOOLS with
  question field  
- test_coach_facilitation_prompts_mention_ask_pm — all 5 phases mention it

**test_agent.py (3):**
- test_build_prompt_mention_awareness — @agent-1 in recent message →
  "specifically addressed you" in system prompt
- test_build_prompt_no_mention_no_note — no @agent-1 → no mention note
- test_build_prompt_mention_from_correct_speaker — mentioner name is
  correct in the note

**test_cli.py (8):**
- test_pass_turn_logged_as_system_note — pass produces system msg, not
  agent msg
- test_pass_turn_reason_in_system_note — reason text appears in note
- test_pass_turn_not_in_agent_history — subsequent agent prompt doesn't
  contain pass agent's "response"
- test_pass_turn_counts_as_turn — turn counter increments
- test_agent_always_has_pass_turn_tool — tools param includes pass_turn
  even without fileguard
- test_ask_pm_pauses_conversation — coach calls ask_pm → conversation
  returns with question
- test_ask_pm_resume_with_continue — human message visible after resume
- test_ask_pm_empty_text_gets_fallback — "(Requesting PM input: ...)" when
  coach text empty

### Existing tests to update (~4)

- test_coach_tools_exists — change len == 1 to len == 2 (signal_phase_complete
  + ask_pm)
- test_run_conversation_basic / test_run_conversation_records_messages — agents
  now go through agentic_completion; mock needs to return
  {"content": "...", "operations": []} format instead of plain string. OR:
  keep chat_completion path when no tools configured (but this contradicts
  the "always agentic" change). Decision: update mocks.
- test_empty_coach_message_gets_fallback — may need adjustment for ask_pm
  fallback

## Implementation Order

1. scaffold.py — AGENT_TOOLS constant, ask_pm in COACH_TOOLS, prompt updates
2. tests/test_scaffold.py — 3 new tests + update test_coach_tools_exists
3. agent.py — @mention awareness in build_prompt
4. tests/test_agent.py — 3 new tests
5. cli.py — always-agentic agent calls, tool list construction, pass_turn
   detection, ask_pm handling
6. tests/test_cli.py — update existing mocks, add 8 new tests
7. Full test run + fix breakage
8. Manual smoke test
9. Update CLAUDE.md test count

## Expected Impact

**Turn reduction:** 15-25% fewer substantive agent messages. Agents pass
on confirmation turns, "I'll wait" turns, and "yes I'm ready" turns.
Less dramatic than the 30-50% from directed flow, but preserves natural
conversation dynamics.

**Context growth:** The bigger win. Each pass prevents ~150-300 words
from entering the conversation history. Over a 50-turn conversation,
even 10 passes saves 1,500-3,000 words from being re-read by every
subsequent turn. Cumulative input token savings compound.

**Combined with iterations 15+16:** Conciseness norms (15) make passes
more likely — agents are already told "silence means approval," and now
they have a mechanism to actually be silent. History trimming (16) means
passes within a phase have amplified impact since context doesn't carry
across phases anyway.

**Estimated combined impact (15+16+17):** $9 → $2-3 for equivalent task.
More conservative than the directed-flow estimate ($1-2), but the
conversation quality is preserved. The PM can still jump in naturally,
agents can still develop their own rhythm, and the coach facilitates
rather than orchestrates.

## Risks and Mitigations

**Risk: Agents never pass.** LLMs are trained to be helpful, which means
producing output. They may resist calling pass_turn even when told to.

**Mitigation:** The prompt is explicit: "use pass_turn instead of restating
agreement." Combined with iteration 15's conciseness norms, there's
consistent pressure toward brevity. If agents still don't pass, the cost
is the same as today — no regression. Monitor pass rates in test runs and
tune prompts if needed.

**Risk: Agents pass too aggressively.** Important concerns get swallowed
because agents pass instead of raising them.

**Mitigation:** The tool description says "do not call this if you have
concerns, questions, disagreements, or new information." The `reason`
field forces agents to articulate why they're passing — "agree with
proposal" is fine, "not sure about the parser interface" should have been
a real response. Monitor reasons in debug.jsonl.

**Risk: agentic_completion overhead.** Switching all agent calls to
agentic_completion adds tool-handling overhead even in phases where
file tools aren't used.

**Mitigation:** agentic_completion with a single simple tool (pass_turn)
should have negligible overhead versus chat_completion. The tool schema
is tiny. If benchmarking shows a problem, we can make it conditional.

**Risk: Models that don't support tool use.** Some Ollama models may not
handle tool calls well.

**Mitigation:** If agentic_completion fails or the model ignores tools,
the response flows through as a normal message (no pass, no tool calls).
Graceful degradation — worst case is current behavior.
