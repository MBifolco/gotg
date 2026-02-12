"""Implementation phase executor — per-layer dispatch, no coach."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from gotg.agent import build_prompt
from gotg.engine import SessionDeps, build_tool_executor
from gotg.events import (
    AppendDebug,
    AppendMessage,
    LayerComplete,
    PauseForApprovals,
    SessionComplete,
    SessionStarted,
    ToolCallProgress,
)
from gotg.policy import SessionPolicy
from gotg.prompts import COMPLETE_TASKS_TOOL


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
    """Filter tasks that are not yet done."""
    return [t for t in tasks if t.get("status") != "done"]


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


def _format_agent_tasks(tasks: list[dict], agent_name: str, layer: int) -> str:
    """Format task summary for a single agent's prompt."""
    lt = _layer_tasks(tasks, layer)
    my_tasks = _agent_tasks(lt, agent_name)
    if not my_tasks:
        return "No tasks assigned to you in this layer."
    parts = [f"### Your tasks (layer {layer})"]
    for t in my_tasks:
        status = t.get("status", "pending")
        entry = (
            f"- **{t['id']}** [{status}]\n"
            f"  {t['description']}\n"
            f"  Done when: {t['done_criteria']}"
        )
        notes = t.get("notes")
        if notes:
            entry += f"\n  Notes: {notes}"
        parts.append(entry)
    return "\n".join(parts)


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

    # Strict validation: all IDs must be valid
    for tid in task_ids:
        if tid not in lt_ids:
            return f"Error: task '{tid}' is not in layer {layer}"
        if tid not in agent_lt_ids:
            return f"Error: task '{tid}' is not assigned to you"

    # Update tasks in-place and persist
    completed = []
    for t in tasks:
        if t["id"] in task_ids:
            if t.get("status") == "done":
                continue  # Already done, skip
            t["status"] = "done"
            t["completed_by"] = agent_name
            t["completion_summary"] = summary
            completed.append(t["id"])

    _save_tasks(iter_dir, tasks)

    if completed:
        return f"Completed tasks: {', '.join(completed)}"
    return "Tasks already marked as done."


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
    ToolCallProgress | PauseForApprovals |
    LayerComplete | SessionComplete
]:
    """Run implementation phase for a single layer.

    Dispatches each agent with pending tasks sequentially.
    Uses raw_completion for engine-driven tool loops.
    Yields events for the caller to persist and display.
    """
    # Resolve max tool rounds: explicit param > policy.max_turns > default 25
    if max_tool_rounds is None:
        max_tool_rounds = policy.max_turns if policy.max_turns else 25

    # Determine which agents have pending work
    active_agents = _agents_with_pending_work(agents, tasks, current_layer)

    # Build participant list for prompt construction
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

    if not active_agents:
        # All tasks already done — immediate LayerComplete
        lt = _layer_tasks(tasks, current_layer)
        yield LayerComplete(
            layer=current_layer,
            completed_tasks=tuple(t["id"] for t in lt if t.get("status") == "done"),
        )
        return

    # Inject kickoff if provided
    if policy.kickoff_text:
        kickoff_msg = {
            "from": "system",
            "iteration": iteration["id"],
            "content": policy.kickoff_text,
        }
        yield AppendMessage(kickoff_msg)
        history.append(kickoff_msg)

    # Build tools: file tools + complete_tasks (no pass_turn in implementation)
    impl_tools = list(policy.agent_tools) + [COMPLETE_TASKS_TOOL]
    # Remove pass_turn from implementation tools
    impl_tools = [t for t in impl_tools if t["name"] != "pass_turn"]

    agent_idx = 0
    for agent in active_agents:
        agent_name = agent["name"]

        # Re-read tasks from disk (may have been updated by previous agent)
        tasks = _load_tasks(iter_dir)

        # Skip if this agent's tasks are already done
        lt = _layer_tasks(tasks, current_layer)
        agent_lt = _agent_tasks(lt, agent_name)
        if not _pending_tasks(agent_lt):
            continue

        # Build per-agent task summary
        agent_tasks_summary = _format_agent_tasks(tasks, agent_name, current_layer)

        # Build prompt
        prompt = build_prompt(
            agent, iteration, history, all_participants,
            groomed_summary=policy.groomed_summary,
            tasks_summary=agent_tasks_summary,
            fileguard=policy.fileguard,
            worktree_map=policy.worktree_map,
            system_supplement=policy.system_supplement,
        )

        yield AppendDebug({
            "turn": f"impl-{agent_name}",
            "agent": agent_name,
            "messages": prompt,
        })

        # Build tool executor (file tools + write limits)
        _, base_tool_executor = build_tool_executor(agent, policy)

        # Engine-driven tool loop using raw_completion
        llm_messages = list(prompt)
        agent_completed = False

        for round_num in range(max_tool_rounds):
            rnd = deps.single_completion(
                base_url=model_config["base_url"],
                model=model_config["model"],
                messages=llm_messages,
                api_key=model_config.get("api_key"),
                provider=model_config.get("provider", "ollama"),
                tools=impl_tools,
            )

            # No tool calls — agent is done talking
            if not rnd.tool_calls:
                if rnd.content.strip():
                    msg = {
                        "from": agent_name,
                        "iteration": iteration["id"],
                        "content": rnd.content,
                    }
                    yield AppendMessage(msg)
                    history.append(msg)
                break

            # Execute each tool call
            tool_results = []
            for tc in rnd.tool_calls:
                if tc["name"] == "complete_tasks":
                    result = _handle_complete_tasks(
                        tc["input"], agent_name, tasks, current_layer, iter_dir,
                    )
                    # Reload tasks after completion
                    tasks = _load_tasks(iter_dir)
                else:
                    result = base_tool_executor(tc["name"], tc["input"])

                tool_results.append({"id": tc["id"], "result": result})

                # Yield ToolCallProgress
                status = _classify_result(result)
                content_size = None
                if tc["name"] == "file_write":
                    content_size = len(tc["input"].get("content", "").encode())
                error_msg = result if status == "error" else None

                yield ToolCallProgress(
                    agent=agent_name,
                    tool_name=tc["name"],
                    path=tc["input"].get("path", ""),
                    status=status,
                    bytes=content_size,
                    error=error_msg,
                )

                # Log tool operations
                if tc["name"] != "complete_tasks":
                    op_msg = {
                        "from": "system",
                        "iteration": iteration["id"],
                        "content": _format_tool_op(tc["name"], tc["input"], result),
                    }
                    yield AppendMessage(op_msg)
                    history.append(op_msg)
                else:
                    # Log completion
                    op_msg = {
                        "from": "system",
                        "iteration": iteration["id"],
                        "content": f"[complete_tasks] {result}",
                    }
                    yield AppendMessage(op_msg)
                    history.append(op_msg)

            # Check for pending approvals
            if policy.approval_store:
                pending = policy.approval_store.get_pending()
                if pending:
                    # Record partial agent message if any
                    if rnd.content.strip():
                        msg = {
                            "from": agent_name,
                            "iteration": iteration["id"],
                            "content": rnd.content,
                        }
                        yield AppendMessage(msg)
                        history.append(msg)
                    yield PauseForApprovals(len(pending))
                    return

            # Build continuation for next round
            continuation = rnd.build_continuation(tool_results)
            llm_messages.extend(continuation)

            # Check if all this agent's tasks are now done
            lt = _layer_tasks(tasks, current_layer)
            agent_lt = _agent_tasks(lt, agent_name)
            if not _pending_tasks(agent_lt):
                agent_completed = True
                # Record agent's summary message if present
                if rnd.content.strip():
                    msg = {
                        "from": agent_name,
                        "iteration": iteration["id"],
                        "content": rnd.content,
                    }
                    yield AppendMessage(msg)
                    history.append(msg)
                break

        agent_idx += 1

    # Check if all layer tasks are done
    tasks = _load_tasks(iter_dir)
    lt = _layer_tasks(tasks, current_layer)
    pending = _pending_tasks(lt)

    if not pending:
        # Auto-commit worktrees before signaling layer complete
        _auto_commit_worktrees(policy, current_layer)
        yield LayerComplete(
            layer=current_layer,
            completed_tasks=tuple(t["id"] for t in lt if t.get("status") == "done"),
        )
    else:
        yield SessionComplete(total_turns=agent_idx)


def _auto_commit_worktrees(policy: SessionPolicy, layer: int) -> None:
    """Auto-commit all dirty worktrees for the current layer."""
    if not policy.worktree_map:
        return
    from gotg.worktree import WorktreeError, commit_worktree, is_worktree_dirty
    for agent_name, wt_path in policy.worktree_map.items():
        try:
            if is_worktree_dirty(wt_path):
                commit_worktree(wt_path, f"Implementation complete (layer {layer})")
        except WorktreeError:
            pass  # Best-effort; merge will catch uncommitted files


def _format_tool_op(name: str, tool_input: dict, result: str) -> str:
    """Format a tool operation for the conversation log."""
    from gotg.tools import format_tool_operation
    return format_tool_operation({"name": name, "input": tool_input, "result": result})
