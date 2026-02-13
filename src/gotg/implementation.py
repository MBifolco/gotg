"""Implementation phase executor — per-layer dispatch, no coach."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from gotg.engine import SessionDeps, build_tool_executor
from gotg.events import (
    AgentTurnComplete,
    AppendDebug,
    AppendMessage,
    LayerComplete,
    PauseForApprovals,
    SessionComplete,
    SessionStarted,
    TaskBlocked,
    TextDelta,
    ToolCallProgress,
)
from gotg.policy import SessionPolicy
from gotg.prompts import COMPLETE_TASKS_TOOL, DRIFT_CHECK_PROMPT, REPORT_BLOCKED_TOOL
from gotg.transitions import strip_code_fences

_STATE_FILE = "implementation_state.json"
_READ_ONLY_TOOLS = {"file_read", "file_list"}


def _classify_result(result_str: str) -> str:
    """Derive status from tool result string prefix."""
    if result_str.startswith("Error:"):
        return "error"
    if result_str.startswith("Pending approval"):
        return "pending_approval"
    return "ok"


def _load_tasks(iter_dir: Path) -> list[dict]:
    """Read tasks.json from disk."""
    tasks_path = iter_dir / "tasks.json"
    return json.loads(tasks_path.read_text())


def _save_tasks(iter_dir: Path, tasks: list[dict]) -> None:
    """Write tasks.json to disk."""
    tasks_path = iter_dir / "tasks.json"
    tasks_path.write_text(json.dumps(tasks, indent=2) + "\n")


def _layer_tasks(tasks: list[dict], layer: int) -> list[dict]:
    """Filter tasks to a specific layer."""
    return [t for t in tasks if t.get("layer") == layer]


def _agent_tasks(tasks: list[dict], agent_name: str) -> list[dict]:
    """Filter tasks assigned to a specific agent."""
    return [t for t in tasks if t.get("assigned_to") == agent_name]


def _pending_tasks(tasks: list[dict]) -> list[dict]:
    """Filter tasks that are still actionable in this phase."""
    return [t for t in tasks if t.get("status") not in {"done", "blocked"}]


def _all_done(tasks: list[dict]) -> bool:
    """True when every task is explicitly marked done."""
    return all(t.get("status") == "done" for t in tasks)


def _agents_with_pending_work(
    agents: list[dict], tasks: list[dict], layer: int,
) -> list[dict]:
    """Return agents that have pending tasks in the given layer."""
    lt = _layer_tasks(tasks, layer)
    result = []
    for agent in agents:
        agent_lt = _agent_tasks(lt, agent["name"])
        if _pending_tasks(agent_lt):
            result.append(agent)
    return result


def _strip_do_not(text: str) -> str:
    """Strip leading 'Do not ' / 'Do not: ' and re-capitalise."""
    for prefix in ("Do not ", "Do not: "):
        if text.startswith(prefix):
            rest = text[len(prefix):]
            return rest[0].upper() + rest[1:] if rest else text
    return text


def _format_agent_tasks(tasks: list[dict], agent_name: str, layer: int) -> str:
    """Format task specs for a single agent's implementation prompt.

    Numbered TASK labels with explicit field prefixes. Anti-patterns
    render as "DO NOT:" items with double-negative prefixes stripped.
    """
    lt = _layer_tasks(tasks, layer)
    my_tasks = _agent_tasks(lt, agent_name)
    if not my_tasks:
        return "No tasks assigned to you in this layer."
    parts: list[str] = []
    for i, t in enumerate(my_tasks, 1):
        tag = f"TASK {i}"
        lines = [f"{tag} ID: {t['id']}"]
        lines.append(f"{tag} DESCRIPTION: {t['description']}")
        reqs = t.get("requirements")
        if reqs:
            items = "\n".join(f"- {r}" for r in reqs)
            lines.append(f"{tag} DO:\n{items}")
        approach = t.get("approach")
        if approach:
            lines.append(f"{tag} APPROACH: {approach}")
        anti = t.get("anti_patterns")
        if anti:
            items = "\n".join(f"- {_strip_do_not(a)}" for a in anti)
            lines.append(f"{tag} DO NOT:\n{items}")
        lines.append(f"{tag} DONE WHEN: {t.get('done_criteria', '')}")
        notes = t.get("notes")
        if notes:
            lines.append(f"{tag} FILES TO CREATE:\n{notes}")
        parts.append("\n\n".join(lines))
    return "\n\n".join(parts)


def _build_implementation_prompt(
    agent_name: str,
    project_description: str,
    layer: int,
    tasks_text: str,
    fileguard=None,
    worktree_map: dict | None = None,
) -> list[dict]:
    """Build a focused implementation prompt — no discussion-phase baggage.

    Returns a two-element messages list (system + user) ready for the LLM.
    """
    writable = "src/**, tests/**, docs/**"
    if fileguard and fileguard.writable_paths:
        writable = ", ".join(fileguard.writable_paths)

    parts = [
        f"You are {agent_name}, implementing assigned tasks.",
        f"These tasks are part of a larger project called: {project_description}",
        "",
        "Write exactly what is specified for the tasks below — nothing more, nothing less.",
        "Do not add features, classes, abstractions, or improvements beyond what each task requires.",
        "Do not create files that are not mentioned in your task specifications.",
        "",
        "PROCESS TO FOLLOW:",
        "1. Read existing code with file_read before writing.",
        "2. Write code based on the task specifics below.",
        "3. Call complete_tasks with task_ids and summary when done.",
        "",
        "Call report_blocked if you cannot proceed.",
        "",
        f"Files: You can read all project files and write to: {writable}.",
    ]

    if worktree_map and agent_name in worktree_map:
        parts.append("Worktree: You are in your own isolated git worktree. Your writes go only to your worktree.")

    parts.append("")
    parts.append("YOUR TASKS:\n")
    parts.append(tasks_text)

    system_content = "\n".join(parts)
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "Implement your assigned tasks."},
    ]


def _extract_scope_boundaries(summary: str) -> str:
    """Extract Out of Scope and Agreed Requirements sections from refinement summary."""
    sections: list[str] = []
    current_section: str | None = None
    current_lines: list[str] = []
    for line in summary.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_section in ("Out of Scope", "Agreed Requirements") and current_lines:
                sections.append(f"{current_section}:")
                sections.extend(current_lines)
            current_section = stripped[3:].strip()
            current_lines = []
        elif stripped and current_section:
            current_lines.append(f"  {stripped}")
    # Flush last section
    if current_section in ("Out of Scope", "Agreed Requirements") and current_lines:
        sections.append(f"{current_section}:")
        sections.extend(current_lines)
    return "\n".join(sections)


_REMINDER_CADENCE = 5
_WRITES_SINCE_REMINDER_THRESHOLD = 3


def _build_constraint_reminder(agent_tasks: list[dict]) -> str:
    """Build a brief constraint reminder for mid-turn injection.

    Uses the same field labels as the task blocks (APPROACH, DO NOT,
    DONE WHEN) for consistency.
    """
    parts = ["Reminder — your task constraints:"]
    for t in agent_tasks:
        approach = t.get("approach")
        anti = t.get("anti_patterns", [])
        done = t.get("done_criteria", "")
        if approach or anti or done:
            parts.append(f"  {t['id']}:")
            if approach:
                parts.append(f"    APPROACH: {approach}")
            for a in anti:
                parts.append(f"    DO NOT: {_strip_do_not(a)}")
            if done:
                parts.append(f"    DONE WHEN: {done}")
    return "\n".join(parts)


def _state_path(iter_dir: Path) -> Path:
    return iter_dir / _STATE_FILE


def _load_state(iter_dir: Path, layer: int) -> dict | None:
    """Load resumable implementation state for the current layer."""
    path = _state_path(iter_dir)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if state.get("layer") != layer:
        return None
    if not isinstance(state.get("agent_name"), str):
        return None
    if not isinstance(state.get("llm_messages"), list):
        return None
    return state


def _save_state(
    iter_dir: Path,
    layer: int,
    agent_name: str,
    llm_messages: list[dict],
    round_num: int,
    read_only_streak: int,
    no_tool_streak: int,
    saw_tool_activity: bool,
) -> None:
    """Persist resumable state so `gotg continue` can resume current agent loop."""
    payload = {
        "layer": layer,
        "agent_name": agent_name,
        "llm_messages": llm_messages,
        "round_num": round_num,
        "read_only_streak": read_only_streak,
        "no_tool_streak": no_tool_streak,
        "saw_tool_activity": saw_tool_activity,
    }
    _state_path(iter_dir).write_text(json.dumps(payload, indent=2) + "\n")


def _clear_state(iter_dir: Path) -> None:
    path = _state_path(iter_dir)
    if path.exists():
        path.unlink()


def _handle_complete_tasks(
    tool_input: dict,
    agent_name: str,
    tasks: list[dict],
    layer: int,
    iter_dir: Path,
) -> str:
    """Validate and persist task completion. Returns result string."""
    task_ids = tool_input.get("task_ids", [])
    summary = tool_input.get("summary", "")

    if not task_ids:
        return "Error: task_ids is empty"

    lt = _layer_tasks(tasks, layer)
    lt_ids = {t["id"] for t in lt}
    agent_lt = _agent_tasks(lt, agent_name)
    agent_lt_ids = {t["id"] for t in agent_lt}

    for tid in task_ids:
        if tid not in lt_ids:
            return f"Error: task '{tid}' is not in layer {layer}"
        if tid not in agent_lt_ids:
            return f"Error: task '{tid}' is not assigned to you"

    completed = []
    for t in tasks:
        if t["id"] in task_ids:
            if t.get("status") == "done":
                continue
            t["status"] = "done"
            t["completed_by"] = agent_name
            t["completion_summary"] = summary
            t.pop("blocked_by", None)
            t.pop("blocked_reason", None)
            completed.append(t["id"])

    _save_tasks(iter_dir, tasks)

    if completed:
        return f"Completed tasks: {', '.join(completed)}"
    return "Tasks already marked as done."


def _run_drift_check(
    file_contents: dict[str, str],
    agent_tasks: list[dict],
    model_config: dict,
    deps: SessionDeps,
) -> list[dict]:
    """One-shot LLM verification of written code against task specs.

    Returns list of {task_id, approach_ok, anti_pattern_violations, done_criteria_ok, notes}.
    Returns empty list on LLM/parse failure (non-blocking).
    """
    if not file_contents or not agent_tasks:
        return []
    fc_parts = []
    for path, content in file_contents.items():
        lines = content.split("\n")
        if len(lines) > 500:
            content = "\n".join(lines[:500]) + "\n... (truncated)"
        fc_parts.append(f"=== {path} ===\n{content}")
    file_text = "\n\n".join(fc_parts)
    specs = []
    for t in agent_tasks:
        spec = f"Task {t['id']}: {t['description']}"
        if t.get("approach"):
            spec += f"\n  APPROACH: {t['approach']}"
        for ap in t.get("anti_patterns", []):
            spec += f"\n  MUST NOT: {ap}"
        spec += f"\n  DONE WHEN: {t.get('done_criteria', '')}"
        specs.append(spec)
    task_text = "\n\n".join(specs)
    prompt = DRIFT_CHECK_PROMPT.format(
        file_contents=file_text, task_specs=task_text,
    )
    try:
        result = deps.single_completion(
            base_url=model_config["base_url"],
            model=model_config["model"],
            messages=[{"role": "user", "content": prompt}],
            api_key=model_config.get("api_key"),
            provider=model_config.get("provider", "ollama"),
        )
        text = strip_code_fences(result.content if hasattr(result, "content") else str(result))
        return json.loads(text)
    except Exception:
        return []


def _handle_report_blocked(
    tool_input: dict,
    agent_name: str,
    tasks: list[dict],
    layer: int,
    iter_dir: Path,
) -> tuple[str, tuple[str, ...] | None]:
    """Validate and persist blocked tasks."""
    task_ids = tool_input.get("task_ids", [])
    reason = (tool_input.get("reason") or "").strip()

    if not task_ids:
        return "Error: task_ids is empty", None
    if not reason:
        return "Error: reason is required", None

    lt = _layer_tasks(tasks, layer)
    lt_ids = {t["id"] for t in lt}
    agent_lt = _agent_tasks(lt, agent_name)
    agent_lt_ids = {t["id"] for t in agent_lt}

    for tid in task_ids:
        if tid not in lt_ids:
            return f"Error: task '{tid}' is not in layer {layer}", None
        if tid not in agent_lt_ids:
            return f"Error: task '{tid}' is not assigned to you", None

    blocked = []
    for t in tasks:
        if t["id"] in task_ids:
            if t.get("status") == "done":
                return f"Error: task '{t['id']}' is already done", None
            t["status"] = "blocked"
            t["blocked_by"] = agent_name
            t["blocked_reason"] = reason
            blocked.append(t["id"])

    _save_tasks(iter_dir, tasks)
    if not blocked:
        return "Tasks already marked as blocked.", tuple()
    return f"Blocked tasks: {', '.join(blocked)}", tuple(blocked)


def _completion_nudge(agent_name: str, pending_task_ids: list[str]) -> str:
    ids = ", ".join(pending_task_ids)
    return (
        f"{agent_name}: you still have pending tasks ({ids}). "
        "Take concrete action now: use file_write and then call complete_tasks. "
        "If truly blocked, call report_blocked. Do not end this round without one of those tools."
    )


def _loop_nudge() -> str:
    return (
        "You are looping on read/list calls without making progress. "
        "Stop browsing. Either write code now and call complete_tasks, or call report_blocked."
    )


def run_implementation(
    agents: list[dict],
    tasks: list[dict],
    current_layer: int,
    iteration: dict,
    iter_dir: Path,
    model_config: dict,
    deps: SessionDeps,
    history: list[dict],
    policy: SessionPolicy,
    max_tool_rounds: int | None = None,
) -> Iterator[
    SessionStarted | AppendMessage | AppendDebug |
    ToolCallProgress | TaskBlocked | PauseForApprovals |
    LayerComplete | SessionComplete | TextDelta | AgentTurnComplete
]:
    """Run implementation phase for a single layer.

    Dispatches each agent with pending tasks sequentially.
    Uses raw_completion for engine-driven tool loops.
    Yields events for the caller to persist and display.
    """
    if max_tool_rounds is None:
        max_tool_rounds = policy.max_turns if policy.max_turns else 25

    active_agents = _agents_with_pending_work(agents, tasks, current_layer)
    all_participants = [
        {"name": a["name"], "role": a.get("role", "Software Engineer")}
        for a in agents
    ]

    yield SessionStarted(
        iteration_id=iteration["id"],
        description=iteration["description"],
        phase="implementation",
        current_layer=current_layer,
        agents=[a["name"] for a in active_agents],
        coach=None,
        has_file_tools=policy.fileguard is not None,
        writable_paths=(
            ", ".join(policy.fileguard.writable_paths)
            if policy.fileguard and policy.fileguard.writable_paths
            else None
        ),
        worktree_count=len(policy.worktree_map) if policy.worktree_map else 0,
        turn=0,
        max_turns=len(active_agents),
    )

    layer_tasks = _layer_tasks(tasks, current_layer)
    if not active_agents:
        if _all_done(layer_tasks):
            _clear_state(iter_dir)
            yield LayerComplete(
                layer=current_layer,
                completed_tasks=tuple(t["id"] for t in layer_tasks),
            )
        else:
            yield SessionComplete(total_turns=0)
        return

    if policy.kickoff_text:
        kickoff_msg = {
            "from": "system",
            "iteration": iteration["id"],
            "content": policy.kickoff_text,
        }
        yield AppendMessage(kickoff_msg)
        history.append(kickoff_msg)

    impl_tools = list(policy.agent_tools) + [COMPLETE_TASKS_TOOL, REPORT_BLOCKED_TOOL]
    impl_tools = [t for t in impl_tools if t["name"] != "pass_turn"]

    resumed = _load_state(iter_dir, current_layer)
    if resumed and resumed["agent_name"] not in {a["name"] for a in active_agents}:
        _clear_state(iter_dir)
        resumed = None

    dispatched_agents = 0
    resume_gate = resumed["agent_name"] if resumed else None

    for agent in active_agents:
        agent_name = agent["name"]

        if resume_gate and agent_name != resume_gate:
            continue

        tasks = _load_tasks(iter_dir)
        lt = _layer_tasks(tasks, current_layer)
        agent_lt = _agent_tasks(lt, agent_name)
        agent_pending = _pending_tasks(agent_lt)
        if not agent_pending:
            if resume_gate == agent_name:
                resume_gate = None
            continue

        agent_tasks_text = _format_agent_tasks(
            tasks, agent_name, current_layer,
        )
        # Dedicated implementation prompt — no discussion-phase norms,
        # no team context, no overrides.  Just the agent identity, project
        # context, constraints, and task specs.
        prompt = _build_implementation_prompt(
            agent_name=agent_name,
            project_description=iteration["description"],
            layer=current_layer,
            tasks_text=agent_tasks_text,
            fileguard=policy.fileguard,
            worktree_map=policy.worktree_map,
        )

        yield AppendDebug({
            "turn": f"impl-{agent_name}",
            "agent": agent_name,
            "messages": prompt,
        })

        _, base_tool_executor = build_tool_executor(agent, policy)

        if resume_gate == agent_name and resumed is not None:
            llm_messages = list(resumed["llm_messages"])
            start_round = int(resumed.get("round_num", 0))
            read_only_streak = int(resumed.get("read_only_streak", 0))
            no_tool_streak = int(resumed.get("no_tool_streak", 0))
            saw_tool_activity = bool(resumed.get("saw_tool_activity", False))
            writes_since_reminder = int(resumed.get("writes_since_reminder", 0))
            resume_gate = None
            resumed = None
        else:
            llm_messages = list(prompt)
            start_round = 0
            read_only_streak = 0
            no_tool_streak = 0
            saw_tool_activity = False
            writes_since_reminder = 0

        agent_file_contents: dict[str, str] = {}
        dispatched_agents += 1

        for round_num in range(start_round, max_tool_rounds):
            turn_id = f"impl-{agent_name}-r{round_num}"

            if policy.streaming and deps.stream_completion:
                stream = deps.stream_completion(
                    base_url=model_config["base_url"],
                    model=model_config["model"],
                    messages=llm_messages,
                    api_key=model_config.get("api_key"),
                    provider=model_config.get("provider", "ollama"),
                    tools=impl_tools,
                )
                for chunk in stream:
                    yield TextDelta(agent=agent_name, turn_id=turn_id, text=chunk)
                rnd = stream.round
            else:
                rnd = deps.single_completion(
                    base_url=model_config["base_url"],
                    model=model_config["model"],
                    messages=llm_messages,
                    api_key=model_config.get("api_key"),
                    provider=model_config.get("provider", "ollama"),
                    tools=impl_tools,
                )

            if not rnd.tool_calls:
                tasks = _load_tasks(iter_dir)
                lt = _layer_tasks(tasks, current_layer)
                agent_lt = _agent_tasks(lt, agent_name)
                pending = _pending_tasks(agent_lt)

                if pending:
                    # Avoid burning rounds on text-only responses. We only allow
                    # one nudge-retry after the agent has taken real tool actions.
                    if saw_tool_activity and no_tool_streak == 0:
                        pending_ids = [t["id"] for t in pending]
                        no_tool_streak = 1
                        llm_messages.append({
                            "role": "system",
                            "content": _completion_nudge(agent_name, pending_ids),
                        })
                        _save_state(
                            iter_dir, current_layer, agent_name, llm_messages,
                            round_num + 1, read_only_streak, no_tool_streak,
                            saw_tool_activity,
                        )
                        continue
                    _clear_state(iter_dir)
                    break

                if rnd.content.strip():
                    if policy.streaming and deps.stream_completion:
                        yield AgentTurnComplete(
                            agent=agent_name,
                            turn_id=turn_id,
                            content=rnd.content,
                        )
                    msg = {
                        "from": agent_name,
                        "iteration": iteration["id"],
                        "content": rnd.content,
                    }
                    yield AppendMessage(msg)
                    history.append(msg)
                _clear_state(iter_dir)
                break

            if rnd.content.strip():
                if policy.streaming and deps.stream_completion:
                    yield AgentTurnComplete(
                        agent=agent_name,
                        turn_id=turn_id,
                        content=rnd.content,
                    )
                msg = {
                    "from": agent_name,
                    "iteration": iteration["id"],
                    "content": rnd.content,
                }
                yield AppendMessage(msg)
                history.append(msg)

            tool_results = []
            round_ops: list[dict] = []
            round_was_read_only = True

            for tc in rnd.tool_calls:
                tc_name = tc["name"]
                tc_input = tc["input"]
                saw_tool_activity = True

                blocked_ids: tuple[str, ...] | None = None
                if tc_name == "complete_tasks":
                    result = _handle_complete_tasks(
                        tc_input, agent_name, tasks, current_layer, iter_dir,
                    )
                    tasks = _load_tasks(iter_dir)
                    round_was_read_only = False
                elif tc_name == "report_blocked":
                    result, blocked_ids = _handle_report_blocked(
                        tc_input, agent_name, tasks, current_layer, iter_dir,
                    )
                    tasks = _load_tasks(iter_dir)
                    round_was_read_only = False
                else:
                    result = base_tool_executor(tc_name, tc_input)
                    if tc_name not in _READ_ONLY_TOOLS:
                        round_was_read_only = False

                tool_results.append({"id": tc["id"], "result": result})
                round_ops.append({
                    "name": tc_name,
                    "input": tc_input,
                    "result": result,
                })

                if tc_name == "file_write":
                    writes_since_reminder += 1
                    agent_file_contents[tc_input.get("path", "")] = tc_input.get("content", "")

                # Drift check after successful complete_tasks
                if tc_name == "complete_tasks" and not result.startswith("Error:"):
                    checks = _run_drift_check(
                        agent_file_contents,
                        _agent_tasks(_layer_tasks(tasks, current_layer), agent_name),
                        model_config, deps,
                    )
                    blocking_violations: list[tuple[str, str]] = []
                    for check in checks:
                        violations = check.get("anti_pattern_violations", [])
                        for v in violations:
                            blocking_violations.append((check["task_id"], v))
                        if not check.get("approach_ok", True):
                            warn = f"[drift-check] task {check['task_id']}: approach may not match — {check.get('notes', '')}"
                            warn_msg = {"from": "system", "iteration": iteration["id"], "content": warn}
                            yield AppendMessage(warn_msg)
                            history.append(warn_msg)
                        if not check.get("done_criteria_ok", True):
                            warn = f"[drift-check] task {check['task_id']}: done_criteria may not be satisfied — {check.get('notes', '')}"
                            warn_msg = {"from": "system", "iteration": iteration["id"], "content": warn}
                            yield AppendMessage(warn_msg)
                            history.append(warn_msg)
                    if blocking_violations:
                        violated_ids = {tid for tid, _ in blocking_violations}
                        for t in tasks:
                            if t["id"] in violated_ids and t.get("status") == "done":
                                t["status"] = "pending"
                                t.pop("completed_by", None)
                                t.pop("completion_summary", None)
                        _save_tasks(iter_dir, tasks)
                        violation_msgs = [f"MUST NOT violated on {tid}: {v}" for tid, v in blocking_violations]
                        result = "Drift detected — completion reverted. Fix these issues and call complete_tasks again:\n" + "\n".join(violation_msgs)
                        for tid, v in blocking_violations:
                            warn_msg = {"from": "system", "iteration": iteration["id"],
                                        "content": f"[drift-check] task {tid}: MUST NOT violated — {v}"}
                            yield AppendMessage(warn_msg)
                            history.append(warn_msg)

                status = _classify_result(result)
                content_size = None
                if tc_name == "file_write":
                    content_size = len(tc_input.get("content", "").encode())
                error_msg = result if status == "error" else None

                yield ToolCallProgress(
                    agent=agent_name,
                    tool_name=tc_name,
                    path=tc_input.get("path", ""),
                    status=status,
                    bytes=content_size,
                    error=error_msg,
                )

                if tc_name in {"complete_tasks", "report_blocked"}:
                    op_msg = {
                        "from": "system",
                        "iteration": iteration["id"],
                        "content": f"[{agent_name}] [{tc_name}] {result}",
                    }
                else:
                    op_msg = {
                        "from": "system",
                        "iteration": iteration["id"],
                        "content": _format_tool_op(agent_name, tc_name, tc_input, result),
                    }
                yield AppendMessage(op_msg)
                history.append(op_msg)

                if tc_name == "report_blocked" and status == "ok" and blocked_ids:
                    yield TaskBlocked(
                        agent=agent_name,
                        layer=current_layer,
                        task_ids=blocked_ids,
                        reason=tc_input.get("reason", ""),
                    )

            if round_ops:
                yield AppendDebug({
                    "turn": turn_id,
                    "agent": agent_name,
                    "tool_operations": round_ops,
                })

            continuation = rnd.build_continuation(tool_results)
            llm_messages.extend(continuation)

            if policy.approval_store:
                pending_approvals = policy.approval_store.get_pending()
                if pending_approvals:
                    _save_state(
                        iter_dir, current_layer, agent_name, llm_messages,
                        round_num + 1, read_only_streak, no_tool_streak,
                        saw_tool_activity,
                    )
                    yield PauseForApprovals(len(pending_approvals))
                    return

            tasks = _load_tasks(iter_dir)
            lt = _layer_tasks(tasks, current_layer)
            agent_lt = _agent_tasks(lt, agent_name)
            pending = _pending_tasks(agent_lt)

            if not pending:
                _clear_state(iter_dir)
                break

            if round_was_read_only:
                read_only_streak += 1
                if read_only_streak >= 2:
                    llm_messages.append({"role": "system", "content": _loop_nudge()})
            else:
                read_only_streak = 0
            no_tool_streak = 0

            # Mid-turn constraint reminder — on cadence or after N file writes
            should_remind = (
                ((round_num + 1) % _REMINDER_CADENCE == 0) or
                (writes_since_reminder >= _WRITES_SINCE_REMINDER_THRESHOLD)
            )
            if should_remind and pending:
                reminder = _build_constraint_reminder(agent_lt)
                if "APPROACH:" in reminder or "DO NOT:" in reminder:
                    llm_messages.append({"role": "system", "content": reminder})
                    writes_since_reminder = 0

            _save_state(
                iter_dir, current_layer, agent_name, llm_messages,
                round_num + 1, read_only_streak, no_tool_streak, saw_tool_activity,
            )
        else:
            _clear_state(iter_dir)

    tasks = _load_tasks(iter_dir)
    lt = _layer_tasks(tasks, current_layer)
    if _all_done(lt):
        _clear_state(iter_dir)
        _auto_commit_worktrees(policy, current_layer)
        yield LayerComplete(
            layer=current_layer,
            completed_tasks=tuple(t["id"] for t in lt if t.get("status") == "done"),
        )
    else:
        yield SessionComplete(total_turns=dispatched_agents)


def _auto_commit_worktrees(policy: SessionPolicy, layer: int) -> None:
    """Auto-commit all dirty worktrees for the current layer."""
    if not policy.worktree_map:
        return
    from gotg.worktree import WorktreeError, commit_worktree, is_worktree_dirty
    for _, wt_path in policy.worktree_map.items():
        try:
            if is_worktree_dirty(wt_path):
                commit_worktree(wt_path, f"Implementation complete (layer {layer})")
        except WorktreeError:
            pass


def _format_tool_op(agent_name: str, name: str, tool_input: dict, result: str) -> str:
    """Format a tool operation for the conversation log."""
    from gotg.tools import format_agent_tool_operation
    return format_agent_tool_operation(
        agent_name, {"name": name, "input": tool_input, "result": result}
    )
