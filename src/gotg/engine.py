from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from gotg.agent import build_prompt, build_coach_prompt
from gotg.config import resolve_model_config
from gotg.events import (
    AgentTurnComplete,
    AppendDebug,
    AppendMessage,
    CoachAskedPM,
    IterationsProposed,
    PauseForApprovals,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
    TextDelta,
    ToolCallProgress,
)
from gotg.policy import SessionPolicy
from gotg.tools import execute_file_tool, format_agent_tool_operation, make_tool_progress


@dataclass
class SessionDeps:
    """Model function callables injected by the caller (bridge pattern)."""
    agent_completion: Callable | None
    coach_completion: Callable | None
    single_completion: Callable | None = None  # raw_completion (implementation tool loop)
    stream_completion: Callable | None = None  # raw_completion_stream (streaming)
    model_resolver: Callable | None = None     # (name: str | None) -> dict

    def validate(
        self,
        policy: SessionPolicy,
        *,
        require_agent_completion: bool = False,
        require_coach_completion: bool = False,
        require_raw_completion: bool = False,
    ) -> None:
        """Validate deps satisfy policy requirements. Raises ValueError."""
        if require_agent_completion and self.agent_completion is None:
            raise ValueError("deps.agent_completion is required")
        if require_coach_completion and self.coach_completion is None:
            raise ValueError(
                "deps.coach_completion is required (policy has coach)"
            )
        if require_raw_completion:
            has_non_streaming = self.single_completion is not None
            has_streaming = policy.streaming and self.stream_completion is not None
            if not has_non_streaming and not has_streaming:
                raise ValueError(
                    "Implementation phase requires deps.single_completion "
                    "or deps.stream_completion (with streaming enabled)"
                )


def run_session(
    agents: list[dict],
    iteration: dict,
    model_config: dict,
    deps: SessionDeps,
    history: list[dict],
    policy: SessionPolicy,
) -> Iterator[SessionStarted | AppendMessage | AppendDebug | PauseForApprovals | PhaseCompleteSignaled | CoachAskedPM | IterationsProposed | SessionComplete | TextDelta | AgentTurnComplete | ToolCallProgress]:
    """Run a conversation session, yielding events. No print, no persistence."""
    deps.validate(
        policy,
        require_agent_completion=True,
        require_coach_completion=policy.coach is not None,
    )

    # Build participant list
    all_participants = [
        {"name": a["name"], "role": a.get("role", "Software Engineer")}
        for a in agents
    ]
    if policy.coach:
        all_participants.append({"name": policy.coach["name"], "role": policy.coach.get("role", "Agile Coach")})
    if any(msg["from"] == "human" for msg in history):
        all_participants.append({"name": "human", "role": "Team Member"})

    # Count initial engineering agent turns
    non_agent = {"human", "system"}
    if policy.coach:
        non_agent.add(policy.coach["name"])
    turn = sum(1 for msg in history if msg["from"] not in non_agent)
    num_agents = len(agents)

    phase = iteration.get("phase", "refinement")
    current_layer = iteration.get("current_layer")

    yield SessionStarted(
        iteration_id=iteration["id"],
        description=iteration["description"],
        phase=phase,
        current_layer=current_layer,
        agents=[a["name"] for a in agents],
        coach=policy.coach["name"] if policy.coach else None,
        has_file_tools=policy.fileguard is not None,
        writable_paths=", ".join(policy.fileguard.writable_paths) if policy.fileguard and policy.fileguard.writable_paths else None,
        worktree_count=len(policy.worktree_map) if policy.worktree_map else 0,
        turn=turn,
        max_turns=policy.max_turns,
    )

    # Inject kickoff if provided (caller pre-computes and guards truthiness)
    if policy.kickoff_text:
        kickoff_msg = {
            "from": "system",
            "iteration": iteration["id"],
            "content": policy.kickoff_text,
        }
        yield AppendMessage(kickoff_msg)
        history.append(kickoff_msg)

    while turn < policy.max_turns:
        agent = agents[turn % num_agents]

        # Build prompt
        prompt = build_prompt(
            agent, iteration, history, all_participants,
            refinement_summary=policy.refinement_summary, tasks_summary=policy.tasks_summary,
            diffs_summary=policy.diffs_summary, fileguard=policy.fileguard,
            worktree_map=policy.worktree_map,
            system_supplement=policy.system_supplement,
            phase_skeleton=policy.phase_skeleton,
            project_context=policy.project_context,
            iteration_plan=policy.iteration_plan,
        )
        yield AppendDebug({
            "turn": turn,
            "agent": agent["name"],
            "messages": prompt,
        })

        # Build tools + executor
        agent_tools, tool_executor = build_tool_executor(agent, policy)

        agent_cfg = resolve_model_config(deps.model_resolver, model_config, agent["name"])

        if policy.streaming and deps.stream_completion:
            # Engine-driven streaming tool loop
            for sub_event in _do_streaming_agent_turn(
                agent, iteration, agent_cfg, deps, history, prompt,
                agent_tools, tool_executor, turn,
            ):
                yield sub_event
                if isinstance(sub_event, AppendMessage):
                    history.append(sub_event.msg)
        else:
            # Existing non-streaming path
            result = deps.agent_completion(
                base_url=agent_cfg["base_url"],
                model=agent_cfg["model"],
                messages=prompt,
                api_key=agent_cfg.get("api_key"),
                provider=agent_cfg.get("provider", "ollama"),
                tools=agent_tools,
                tool_executor=tool_executor,
            )
            yield from _process_agent_result(agent, iteration, result, history, turn)

        turn += 1

        # Check for pending approvals
        if policy.approval_store:
            pending = policy.approval_store.get_pending()
            if pending:
                yield PauseForApprovals(len(pending))
                return

        # Coach injection after every full rotation
        if policy.coach and policy.coach_cadence and turn % policy.coach_cadence == 0:
            coach_cfg = resolve_model_config(deps.model_resolver, model_config, policy.coach["name"])
            stop = yield from _do_coach_turn(
                iteration, coach_cfg, deps, history,
                all_participants, turn, policy,
            )
            if stop:
                return

    yield SessionComplete(turn)


def build_tool_executor(
    agent: dict,
    policy: SessionPolicy,
) -> tuple[list[dict], Callable]:
    """Build tool list and executor for an agent turn."""
    agent_tools = list(policy.agent_tools)

    if policy.fileguard:
        if policy.worktree_map and agent["name"] in policy.worktree_map:
            agent_fg = policy.fileguard.with_root(policy.worktree_map[agent["name"]])
        else:
            agent_fg = policy.fileguard

        write_count = 0

        def tool_executor(name, inp):
            nonlocal write_count
            if name == "pass_turn":
                return "Turn passed."
            if name in ("file_write", "file_delete", "file_rename"):
                write_count += 1
                if write_count > agent_fg.max_files_per_turn:
                    return f"Error: write limit reached ({agent_fg.max_files_per_turn} per turn)"
            return execute_file_tool(name, inp, agent_fg, approval_store=policy.approval_store, agent_name=agent["name"])
    else:
        def tool_executor(name, inp):
            if name == "pass_turn":
                return "Turn passed."
            return f"Unknown tool: {name}"

    return agent_tools, tool_executor


def _process_agent_result(
    agent: dict,
    iteration: dict,
    result: dict,
    history: list[dict],
    turn: int,
) -> Iterator[AppendMessage | AppendDebug]:
    """Process agent LLM result → yield events + mutate history."""
    response_text = result["content"]

    # Log file operations first (even if agent passed)
    for op in result.get("operations", []):
        if op.get("name") == "pass_turn":
            continue
        op_msg = {
            "from": "system",
            "iteration": iteration["id"],
            "content": format_agent_tool_operation(agent["name"], op),
        }
        yield AppendMessage(op_msg)
        history.append(op_msg)

    if result.get("operations"):
        yield AppendDebug({
            "turn": turn,
            "agent": agent["name"],
            "tool_operations": result["operations"],
        })

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
        pass_msg = {
            "from": "system",
            "iteration": iteration["id"],
            "content": f"({agent['name']} passes: {reason})",
            "pass_turn": True,
        }
        yield AppendMessage(pass_msg)
        history.append(pass_msg)
    else:
        msg = {
            "from": agent["name"],
            "iteration": iteration["id"],
            "content": response_text,
        }
        yield AppendMessage(msg)
        history.append(msg)


def _do_streaming_agent_turn(
    agent: dict,
    iteration: dict,
    model_config: dict,
    deps: SessionDeps,
    history: list[dict],
    prompt: list[dict],
    agent_tools: list[dict],
    tool_executor: Callable,
    turn: int,
    max_rounds: int = 10,
) -> Iterator[TextDelta | AgentTurnComplete | ToolCallProgress | AppendMessage | AppendDebug]:
    """Engine-driven streaming tool loop for discussion phases.

    Mirrors agentic_completion but yields events instead of returning a dict.
    Uses stream_completion for text streaming, executes tools inline.
    """
    turn_id = f"turn-{turn}-{agent['name']}"
    operations: list[dict] = []
    llm_messages = list(prompt)

    rnd = None
    for _round_num in range(max_rounds):
        stream = deps.stream_completion(
            base_url=model_config["base_url"],
            model=model_config["model"],
            messages=llm_messages,
            api_key=model_config.get("api_key"),
            provider=model_config.get("provider", "ollama"),
            tools=agent_tools,
            max_tokens=4096,
        )
        for chunk in stream:
            yield TextDelta(agent=agent["name"], turn_id=turn_id, text=chunk)
        rnd = stream.round

        if not rnd.tool_calls:
            break

        # Execute tool calls
        tool_results = []
        for tc in rnd.tool_calls:
            result = tool_executor(tc["name"], tc["input"])
            operations.append({"name": tc["name"], "input": tc["input"], "result": result})
            tool_results.append({"id": tc["id"], "result": result})

            yield make_tool_progress(agent["name"], tc["name"], tc["input"], result)

        # Build continuation for next round
        continuation = rnd.build_continuation(tool_results)
        llm_messages.extend(continuation)

    # Turn complete
    final_content = rnd.content if rnd else ""
    pass_called = any(op["name"] == "pass_turn" for op in operations)

    # Only emit AgentTurnComplete when the agent will emit a real message.
    # On pass_turn the next AppendMessage is a system message, so emitting
    # AgentTurnComplete would set suppression that is never consumed —
    # silently eating the agent's next real response.
    if not pass_called:
        yield AgentTurnComplete(agent=agent["name"], turn_id=turn_id, content=final_content)

    # Yield tool op AppendMessages (same format as _process_agent_result)
    for op in operations:
        if op["name"] == "pass_turn":
            continue
        op_msg = {
            "from": "system",
            "iteration": iteration["id"],
            "content": format_agent_tool_operation(agent["name"], op),
        }
        yield AppendMessage(op_msg)

    if operations:
        yield AppendDebug({
            "turn": turn,
            "agent": agent["name"],
            "tool_operations": operations,
        })

    # Yield agent message or pass_turn message
    if pass_called:
        reason = next(
            (op["input"].get("reason", "") for op in operations if op["name"] == "pass_turn"),
            "",
        )
        pass_msg = {
            "from": "system",
            "iteration": iteration["id"],
            "content": f"({agent['name']} passes: {reason})",
            "pass_turn": True,
        }
        yield AppendMessage(pass_msg)
    else:
        msg = {
            "from": agent["name"],
            "iteration": iteration["id"],
            "content": final_content,
        }
        yield AppendMessage(msg)


def _do_coach_turn(
    iteration: dict,
    model_config: dict,
    deps: SessionDeps,
    history: list[dict],
    all_participants: list[dict],
    turn: int,
    policy: SessionPolicy,
) -> Iterator[AppendMessage | AppendDebug | PhaseCompleteSignaled | CoachAskedPM | IterationsProposed | TextDelta | AgentTurnComplete]:
    """Run a coach turn. Yields events, returns True if session should stop."""
    coach = policy.coach
    coach_prompt = build_coach_prompt(
        coach, iteration, history, all_participants,
        refinement_summary=policy.refinement_summary, tasks_summary=policy.tasks_summary,
        diffs_summary=policy.diffs_summary,
        coach_system_prompt=policy.coach_system_prompt,
        project_context=policy.project_context,
        iteration_plan=policy.iteration_plan,
    )
    yield AppendDebug({
        "turn": f"coach-after-{turn}",
        "agent": coach["name"],
        "messages": coach_prompt,
        "tools": list(policy.coach_tools) if policy.coach_tools else None,
    })

    # Call LLM — tool_choice "any" forces coach to call a tool every turn
    _coach_tool_choice = {"type": "any"} if policy.coach_tools else None
    streamed = False
    if policy.streaming and deps.stream_completion:
        turn_id = f"coach-after-{turn}-{coach['name']}"
        stream = deps.stream_completion(
            base_url=model_config["base_url"],
            model=model_config["model"],
            messages=coach_prompt,
            api_key=model_config.get("api_key"),
            provider=model_config.get("provider", "ollama"),
            tools=policy.coach_tools,
            max_tokens=4096,
            tool_choice=_coach_tool_choice,
        )
        for chunk in stream:
            streamed = True
            yield TextDelta(agent=coach["name"], turn_id=turn_id, text=chunk)
        rnd = stream.round
        coach_text = rnd.content
        coach_tool_calls = rnd.tool_calls
    else:
        coach_response = deps.coach_completion(
            base_url=model_config["base_url"],
            model=model_config["model"],
            messages=coach_prompt,
            api_key=model_config.get("api_key"),
            provider=model_config.get("provider", "ollama"),
            tools=policy.coach_tools,
            tool_choice=_coach_tool_choice,
        )
        coach_text = coach_response["content"]
        coach_tool_calls = coach_response.get("tool_calls", [])

    yield AppendDebug({
        "turn": f"coach-after-{turn}-response",
        "agent": coach["name"],
        "content": coach_text,
        "tool_calls": coach_tool_calls,
    })

    # Extract signal_phase_complete tool calls
    signal_calls = [tc for tc in coach_tool_calls if tc["name"] == "signal_phase_complete"]
    signal_input = signal_calls[0]["input"] if signal_calls else None

    # Extract propose_iterations and end_exploration tool calls
    propose_calls = [tc for tc in coach_tool_calls if tc["name"] == "propose_iterations"]
    propose_input = propose_calls[0]["input"] if propose_calls else None
    end_exploration_calls = [tc for tc in coach_tool_calls if tc["name"] == "end_exploration"]
    end_exploration_input = end_exploration_calls[0]["input"] if end_exploration_calls else None

    # Coach pass_turn — minimal output, mark on message for filtering
    coach_passed = any(tc["name"] == "coach_pass_turn" for tc in coach_tool_calls)
    if coach_passed and not coach_text.strip():
        coach_text = "(Coach observing — no intervention needed.)"

    # guide_discussion — extract message from tool input if content is empty
    guide_calls = [tc for tc in coach_tool_calls if tc["name"] == "guide_discussion"]
    if not coach_text.strip() and guide_calls:
        guide_msg = guide_calls[0].get("input", {}).get("message", "")
        if guide_msg:
            coach_text = guide_msg

    # Fallback for empty coach messages with signal_phase_complete
    if not coach_text.strip() and signal_input:
        summary = signal_input.get("summary", "")
        outcome = signal_input.get("outcome", "approved")
        coach_text = f"(Phase complete: {outcome}. {summary})" if summary else f"(Phase complete: {outcome}.)"

    # Fallback for empty coach messages with propose_iterations
    if not coach_text.strip() and propose_input:
        coach_text = "(Iteration proposals submitted for PM review.)"

    # Fallback for empty coach messages with end_exploration
    if not coach_text.strip() and end_exploration_input:
        coach_text = "(Exploration concluded.)"

    # Fallback for empty coach messages with ask_pm (only when no other tool takes priority)
    if not coach_text.strip() and not propose_input and not end_exploration_input and any(tc["name"] == "ask_pm" for tc in coach_tool_calls):
        question = next(tc["input"]["question"] for tc in coach_tool_calls if tc["name"] == "ask_pm")
        coach_text = f"(Requesting PM input: {question})"

    # Only emit completion when text was actually streamed. This avoids suppressing
    # fallback coach messages for tool-call-only responses with no text deltas.
    if streamed:
        yield AgentTurnComplete(
            agent=coach["name"],
            turn_id=f"coach-after-{turn}-{coach['name']}",
            content=coach_text,
        )

    # Check for ask_pm tool calls before building coach message
    ask_pm_calls = [tc for tc in coach_tool_calls if tc["name"] == "ask_pm"] if policy.stop_on_ask_pm else []
    ask_pm_input = ask_pm_calls[0]["input"] if ask_pm_calls else None

    coach_msg = {
        "from": coach["name"],
        "iteration": iteration["id"],
        "content": coach_text,
    }
    if coach_passed:
        coach_msg["coach_pass_turn"] = True
    # Suppress ask_pm when propose_input or end_exploration is present (they take priority)
    if ask_pm_input and not propose_input and not end_exploration_input:
        coach_msg["ask_pm"] = {
            "question": ask_pm_input["question"],
            "response_type": ask_pm_input.get("response_type", "feedback"),
            "options": list(ask_pm_input.get("options") or []),
        }

    # Attach propose_iterations data to coach message (structured marker)
    if propose_input:
        existing_batches = sum(
            1 for m in history if "propose_iterations" in m
        )
        batch_id = f"p{existing_batches + 1}"
        coach_msg["propose_iterations"] = {
            "batch_id": batch_id,
            "proposals": propose_input["proposals"],
            "rationale": propose_input.get("rationale", ""),
        }

    # Attach signal_phase_complete data to coach message (structured marker)
    if signal_input:
        coach_msg["signal_phase_complete"] = {
            "summary": signal_input.get("summary", ""),
            "outcome": signal_input.get("outcome", "approved"),
        }

    yield AppendMessage(coach_msg)
    history.append(coach_msg)

    # Coach signals phase complete via tool call
    if policy.stop_on_phase_complete and signal_input:
        outcome = signal_input.get("outcome", "approved")
        yield PhaseCompleteSignaled(iteration.get("phase"), outcome=outcome)
        return True

    # Coach proposes iterations (exploration only — tool not in COACH_TOOLS)
    if propose_input:
        yield IterationsProposed(
            batch_id=batch_id,
            proposals=tuple(propose_input["proposals"]),
            rationale=propose_input.get("rationale", ""),
        )
        return True

    # Coach ends exploration session (exploration only — tool not in COACH_TOOLS)
    if end_exploration_input:
        yield SessionComplete(turn)
        return True

    # Coach requests PM input
    if ask_pm_input and not propose_input and not end_exploration_input:
        question = ask_pm_input["question"]
        response_type = ask_pm_input.get("response_type", "feedback")
        options = tuple(ask_pm_input.get("options") or [])
        yield CoachAskedPM(question, response_type=response_type, options=options)
        return True

    return False
