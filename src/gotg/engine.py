from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from gotg.agent import build_prompt, build_coach_prompt
from gotg.events import (
    AppendDebug,
    AppendMessage,
    CoachAskedPM,
    PauseForApprovals,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
)
from gotg.scaffold import AGENT_TOOLS, COACH_TOOLS
from gotg.tools import FILE_TOOLS, execute_file_tool, format_tool_operation


@dataclass
class SessionDeps:
    """Model function callables injected by the caller (bridge pattern)."""
    agent_completion: Callable
    coach_completion: Callable


def run_session(
    agents: list[dict],
    iteration: dict,
    model_config: dict,
    deps: SessionDeps,
    history: list[dict],
    max_turns: int,
    coach: dict | None = None,
    fileguard=None,
    approval_store=None,
    worktree_map: dict | None = None,
    groomed_summary: str | None = None,
    tasks_summary: str | None = None,
    diffs_summary: str | None = None,
    kickoff_text: str | None = None,
) -> Iterator[SessionStarted | AppendMessage | AppendDebug | PauseForApprovals | PhaseCompleteSignaled | CoachAskedPM | SessionComplete]:
    """Run a conversation session, yielding events. No print, no persistence."""

    # Build participant list
    all_participants = [
        {"name": a["name"], "role": a.get("role", "Software Engineer")}
        for a in agents
    ]
    if coach:
        all_participants.append({"name": coach["name"], "role": coach.get("role", "Agile Coach")})
    if any(msg["from"] == "human" for msg in history):
        all_participants.append({"name": "human", "role": "Team Member"})

    # Count initial engineering agent turns
    non_agent = {"human", "system"}
    if coach:
        non_agent.add(coach["name"])
    turn = sum(1 for msg in history if msg["from"] not in non_agent)
    num_agents = len(agents)

    phase = iteration.get("phase", "grooming")
    current_layer = iteration.get("current_layer")

    yield SessionStarted(
        iteration_id=iteration["id"],
        description=iteration["description"],
        phase=phase,
        current_layer=current_layer,
        agents=[a["name"] for a in agents],
        coach=coach["name"] if coach else None,
        has_file_tools=fileguard is not None,
        writable_paths=", ".join(fileguard.writable_paths) if fileguard and fileguard.writable_paths else None,
        worktree_count=len(worktree_map) if worktree_map else 0,
        turn=turn,
        max_turns=max_turns,
    )

    # Inject kickoff if provided (caller pre-computes and guards truthiness)
    if kickoff_text:
        kickoff_msg = {
            "from": "system",
            "iteration": iteration["id"],
            "content": kickoff_text,
        }
        yield AppendMessage(kickoff_msg)
        history.append(kickoff_msg)

    while turn < max_turns:
        agent = agents[turn % num_agents]

        # Build prompt
        prompt = build_prompt(
            agent, iteration, history, all_participants,
            groomed_summary=groomed_summary, tasks_summary=tasks_summary,
            diffs_summary=diffs_summary, fileguard=fileguard,
            worktree_map=worktree_map,
        )
        yield AppendDebug({
            "turn": turn,
            "agent": agent["name"],
            "messages": prompt,
        })

        # Build tools + executor
        agent_tools, tool_executor = _build_tool_executor(
            agent, fileguard, approval_store, worktree_map,
        )

        # Call LLM — exact same kwargs as original run_conversation
        result = deps.agent_completion(
            base_url=model_config["base_url"],
            model=model_config["model"],
            messages=prompt,
            api_key=model_config.get("api_key"),
            provider=model_config.get("provider", "ollama"),
            tools=agent_tools,
            tool_executor=tool_executor,
        )

        # Process result → yield events + mutate history
        yield from _process_agent_result(agent, iteration, result, history, turn)

        turn += 1

        # Check for pending approvals
        if approval_store:
            pending = approval_store.get_pending()
            if pending:
                yield PauseForApprovals(len(pending))
                return

        # Coach injection after every full rotation
        if coach and turn % num_agents == 0:
            stop = yield from _do_coach_turn(
                coach, iteration, model_config, deps, history,
                all_participants, turn, groomed_summary, tasks_summary,
                diffs_summary,
            )
            if stop:
                return

    yield SessionComplete(turn)


def _build_tool_executor(
    agent: dict,
    fileguard,
    approval_store,
    worktree_map: dict | None,
) -> tuple[list[dict], Callable]:
    """Build tool list and executor for an agent turn."""
    agent_tools = list(AGENT_TOOLS)

    if fileguard:
        if worktree_map and agent["name"] in worktree_map:
            agent_fg = fileguard.with_root(worktree_map[agent["name"]])
        else:
            agent_fg = fileguard

        agent_tools.extend(FILE_TOOLS)
        write_count = 0

        def tool_executor(name, inp):
            nonlocal write_count
            if name == "pass_turn":
                return "Turn passed."
            if name == "file_write":
                write_count += 1
                if write_count > agent_fg.max_files_per_turn:
                    return f"Error: write limit reached ({agent_fg.max_files_per_turn} per turn)"
            return execute_file_tool(name, inp, agent_fg, approval_store=approval_store, agent_name=agent["name"])
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
            "content": format_tool_operation(op),
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


def _do_coach_turn(
    coach: dict,
    iteration: dict,
    model_config: dict,
    deps: SessionDeps,
    history: list[dict],
    all_participants: list[dict],
    turn: int,
    groomed_summary: str | None,
    tasks_summary: str | None,
    diffs_summary: str | None,
) -> Iterator[AppendMessage | AppendDebug | PhaseCompleteSignaled | CoachAskedPM]:
    """Run a coach turn. Yields events, returns True if session should stop."""
    coach_prompt = build_coach_prompt(
        coach, iteration, history, all_participants,
        groomed_summary=groomed_summary, tasks_summary=tasks_summary,
        diffs_summary=diffs_summary,
    )
    yield AppendDebug({
        "turn": f"coach-after-{turn}",
        "agent": coach["name"],
        "messages": coach_prompt,
    })

    # Call LLM — exact same kwargs as original run_conversation
    coach_response = deps.coach_completion(
        base_url=model_config["base_url"],
        model=model_config["model"],
        messages=coach_prompt,
        api_key=model_config.get("api_key"),
        provider=model_config.get("provider", "ollama"),
        tools=COACH_TOOLS,
    )
    coach_text = coach_response["content"]
    coach_tool_calls = coach_response.get("tool_calls", [])

    # Fallback for empty coach messages with signal_phase_complete
    if not coach_text.strip() and any(tc["name"] == "signal_phase_complete" for tc in coach_tool_calls):
        coach_text = "(Phase complete signal sent.)"

    # Fallback for empty coach messages with ask_pm
    if not coach_text.strip() and any(tc["name"] == "ask_pm" for tc in coach_tool_calls):
        question = next(tc["input"]["question"] for tc in coach_tool_calls if tc["name"] == "ask_pm")
        coach_text = f"(Requesting PM input: {question})"

    coach_msg = {
        "from": coach["name"],
        "iteration": iteration["id"],
        "content": coach_text,
    }
    yield AppendMessage(coach_msg)
    history.append(coach_msg)

    # Coach signals phase complete via tool call
    if any(tc["name"] == "signal_phase_complete" for tc in coach_tool_calls):
        yield PhaseCompleteSignaled(iteration.get("phase"))
        return True

    # Coach requests PM input
    ask_pm_calls = [tc for tc in coach_tool_calls if tc["name"] == "ask_pm"]
    if ask_pm_calls:
        question = ask_pm_calls[0]["input"]["question"]
        yield CoachAskedPM(question)
        return True

    return False
