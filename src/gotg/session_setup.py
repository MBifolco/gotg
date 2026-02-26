"""Session preparation, validation, and infrastructure."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterator

from gotg.conversation import append_debug, append_message
from gotg.engine import SessionDeps
from gotg.events import AppendDebug, AppendMessage
from gotg.session_types import (
    ContinueContext,
    SessionInfra,
    SessionSetup,
    SessionSetupError,
    resolve_layer,
)

__all__ = [
    "build_session_infra",
    "prepare_session",
    "prepare_grooming_session",
    "prepare_continue",
    "run_and_persist",
    "persist_event",
    "validate_iteration_for_run",
    "build_file_infra",
    "setup_worktrees",
    "apply_and_inject",
    "load_diffs_for_review",
]


def build_session_infra(
    ctx,  # TeamContext — duck-typed to avoid import cycle
    iteration: dict,
    iter_dir: Path,
    *,
    layer_override: int | None = None,
) -> SessionInfra:
    """Build all session infrastructure from team context.

    Consolidates build_file_infra + setup_worktrees + load_diffs_for_review
    + load_streaming_config into a single call.

    ctx must have: project_root, file_access, team_dir, agents attributes.
    """
    fileguard, approval_store = build_file_infra(
        ctx.project_root, ctx.file_access, iter_dir
    )

    worktree_map, wt_warnings = setup_worktrees(
        ctx.team_dir, ctx.agents, fileguard, layer_override, iteration
    )

    diffs_summary, diff_warnings = load_diffs_for_review(
        ctx.team_dir, iteration, layer_override
    )

    from gotg.config import load_streaming_config
    streaming = load_streaming_config(ctx.team_dir)

    warnings = list(wt_warnings) + list(diff_warnings)

    return SessionInfra(
        fileguard=fileguard,
        approval_store=approval_store,
        worktree_map=worktree_map,
        diffs_summary=diffs_summary,
        streaming=streaming,
        warnings=warnings,
    )


def prepare_grooming_session(
    groom_dir: Path,
    agents: list[dict],
    iteration: dict,
    model_config: dict,
    deps: SessionDeps,
    *,
    topic: str,
    coach: dict | None = None,
    max_turns: int = 30,
    streaming: bool = False,
) -> SessionSetup:
    """Build everything needed to run a grooming session.

    Parallel to prepare_session() but uses grooming_policy.
    Caller provides deps (preserves mock targets — bridge pattern).
    """
    from gotg.conversation import read_log
    from gotg.policy import grooming_policy

    log_path = groom_dir / "conversation.jsonl"
    debug_path = groom_dir / "debug.jsonl"
    history = read_log(log_path)

    policy = grooming_policy(
        agents=agents, topic=topic, history=history,
        coach=coach, max_turns=max_turns, streaming=streaming,
    )

    return SessionSetup(
        agents=agents, iteration=iteration, iter_dir=groom_dir,
        model_config=model_config, history=history, policy=policy,
        deps=deps, log_path=log_path, debug_path=debug_path,
        use_implementation=False, tasks_data=None, current_layer=0,
        fileguard=None, approval_store=None, worktree_map=None,
    )


def prepare_continue(
    infra: SessionInfra,
    iteration: dict,
    log_path: Path,
    coach_name: str | None = None,
) -> ContinueContext:
    """Prepare approval injection + turn counting for a continue operation.

    Side effect: calls apply_and_inject() which persists to log_path.
    Caller renders injected_messages and decides whether to bail on has_pending_approvals.
    Caller applies its own max_turns semantics using current_agent_turns.
    """
    from gotg.conversation import read_phase_history

    injected: list[dict] = []
    pending_count = 0
    has_pending = False

    if infra.approval_store:
        injected = apply_and_inject(
            infra.approval_store, infra.fileguard, iteration, log_path,
            worktree_map=infra.worktree_map,
        )
        remaining = infra.approval_store.get_pending()
        if remaining:
            has_pending = True
            pending_count = len(remaining)

    # Count current engineering agent turns (not human/coach/system)
    history = read_phase_history(log_path)
    non_agent = {"human", "system"}
    if coach_name:
        non_agent.add(coach_name)
    current_agent_turns = sum(1 for msg in history if msg["from"] not in non_agent)

    return ContinueContext(
        injected_messages=injected,
        has_pending_approvals=has_pending,
        pending_count=pending_count,
        current_agent_turns=current_agent_turns,
    )


def prepare_session(
    iter_dir: Path,
    agents: list[dict],
    iteration: dict,
    model_config: dict,
    deps: SessionDeps,
    *,
    max_turns_override: int | None = None,
    coach: dict | None = None,
    fileguard=None,
    approval_store=None,
    worktree_map: dict | None = None,
    diffs_summary: str | None = None,
    streaming: bool = False,
) -> SessionSetup:
    """Build everything needed to run a session.

    Single setup path for all consumers (CLI, TUI).
    Reads phase history, builds policy, resolves phase routing.
    Caller provides deps (preserves mock targets — bridge pattern).
    """
    from gotg.conversation import read_phase_history
    from gotg.policy import iteration_policy

    log_path = iter_dir / "conversation.jsonl"
    debug_path = iter_dir / "debug.jsonl"
    history = read_phase_history(log_path)

    policy = iteration_policy(
        agents=agents, iteration=iteration, iter_dir=iter_dir,
        history=history, coach=coach, fileguard=fileguard,
        approval_store=approval_store, worktree_map=worktree_map,
        diffs_summary=diffs_summary, max_turns_override=max_turns_override,
        streaming=streaming,
    )

    # Phase routing: implementation phase uses dedicated executor
    # Needs at least one completion callable (single or stream) for the tool loop
    from gotg.phases import get_phase_caps
    try:
        caps = get_phase_caps(iteration.get("phase"))
    except ValueError as e:
        raise SessionSetupError(str(e)) from e
    tasks_path = iter_dir / "tasks.json"
    use_implementation = (
        caps.use_implementation_executor
        and tasks_path.exists()
        and (deps.single_completion is not None or deps.stream_completion is not None)
    )
    tasks_data = None
    if use_implementation:
        from gotg.tasks import load_tasks_file
        tasks_data = load_tasks_file(tasks_path)

    current_layer = iteration.get("current_layer", 0)

    return SessionSetup(
        agents=agents,
        iteration=iteration,
        iter_dir=iter_dir,
        model_config=model_config,
        history=history,
        policy=policy,
        deps=deps,
        log_path=log_path,
        debug_path=debug_path,
        use_implementation=use_implementation,
        tasks_data=tasks_data,
        current_layer=current_layer,
        fileguard=fileguard,
        approval_store=approval_store,
        worktree_map=worktree_map,
    )


def run_and_persist(setup: SessionSetup) -> Iterator:
    """Run engine/implementation generator AND persist events.

    Contract:
    - Only AppendMessage and AppendDebug are persisted (via persist_event)
    - Persistence happens BEFORE yielding (persist-then-emit)
    - If persistence raises, event is NOT yielded (hard guarantee)
    - All other event types are yielded without persistence
    - Phase routing (implementation vs discussion) is handled internally
    """
    if setup.use_implementation:
        try:
            setup.deps.validate(setup.policy, require_raw_completion=True)
        except ValueError as e:
            raise SessionSetupError(str(e)) from e
        from gotg.implementation import run_implementation
        gen = run_implementation(
            agents=setup.agents, tasks=setup.tasks_data,
            current_layer=setup.current_layer,
            iteration=setup.iteration, iter_dir=setup.iter_dir,
            model_config=setup.model_config, deps=setup.deps,
            history=setup.history, policy=setup.policy,
        )
    else:
        from gotg.engine import run_session
        gen = run_session(
            agents=setup.agents, iteration=setup.iteration,
            model_config=setup.model_config, deps=setup.deps,
            history=setup.history, policy=setup.policy,
        )

    for event in gen:
        if isinstance(event, (AppendMessage, AppendDebug)):
            persist_event(event, setup.log_path, setup.debug_path)
        yield event


def persist_event(event: object, log_path: Path, debug_path: Path) -> None:
    """Persist AppendMessage/AppendDebug events to disk. Other event types are no-ops."""
    if isinstance(event, AppendMessage):
        append_message(log_path, event.msg)
    elif isinstance(event, AppendDebug):
        append_debug(debug_path, event.entry)


def validate_iteration_for_run(iteration: dict, iter_dir: Path, agents: list[dict]) -> None:
    """Validate iteration is ready to run. Raises SessionSetupError."""
    if not iteration.get("description"):
        raise SessionSetupError("Iteration description is empty. Edit .team/iteration.json first.")
    if iteration.get("status") != "in-progress":
        raise SessionSetupError(
            f"Iteration status is '{iteration.get('status')}', expected 'in-progress'."
        )
    if len(agents) < 2:
        raise SessionSetupError("Need at least 2 agents in .team/team.json.")

    phase = iteration.get("phase", "refinement")
    from gotg.phases import get_phase_caps
    try:
        caps = get_phase_caps(phase)
    except ValueError as e:
        raise SessionSetupError(str(e)) from e
    if not caps.requires_tasks:
        return

    tasks_path = iter_dir / "tasks.json"
    if not tasks_path.exists():
        raise SessionSetupError(
            f"{phase} requires tasks.json. Run 'gotg advance' from planning first."
        )
    from gotg.tasks import load_tasks_file
    tasks = load_tasks_file(tasks_path)
    current_layer = iteration.get("current_layer")
    if caps.filter_tasks_by_layer and current_layer is not None:
        tasks = [t for t in tasks if t.get("layer") == current_layer]
    unassigned = [t["id"] for t in tasks if not t.get("assigned_to")]
    if unassigned:
        scope = (
            f"layer {current_layer} tasks"
            if caps.filter_tasks_by_layer and current_layer is not None
            else "all tasks"
        )
        raise SessionSetupError(
            f"{scope} must be assigned before starting {phase}. "
            f"Unassigned tasks: {', '.join(unassigned)}. "
            "Edit .team/iterations/<id>/tasks.json to assign agents."
        )


def build_file_infra(
    project_root: Path, file_access: dict | None, iter_dir: Path
) -> tuple:
    """Build FileGuard + ApprovalStore from config. Returns (fileguard, approval_store)."""
    if not file_access:
        return None, None
    from gotg.fileguard import FileGuard
    fileguard = FileGuard(project_root, file_access)
    approval_store = None
    if file_access.get("enable_approvals"):
        from gotg.approvals import ApprovalStore
        approval_store = ApprovalStore(iter_dir / "approvals.json")
    return fileguard, approval_store


def setup_worktrees(
    team_dir: Path,
    agents: list[dict],
    fileguard: object | None,
    layer_override: int | None,
    iteration: dict,
) -> tuple[dict | None, list[str]]:
    """Set up worktrees for agents if configured.

    Returns (worktree_map, warnings). Raises SessionSetupError on fatal errors.
    """
    from gotg.config import load_worktree_config
    worktree_config = load_worktree_config(team_dir)
    if not worktree_config or not worktree_config.get("enabled"):
        return None, []

    phase = iteration.get("phase", "refinement")
    from gotg.phases import get_phase_caps
    try:
        caps = get_phase_caps(phase)
    except ValueError as e:
        raise SessionSetupError(str(e)) from e
    if not caps.enable_worktrees:
        return None, []

    warnings: list[str] = []
    if not fileguard:
        warnings.append(
            "worktrees enabled but file_access not configured — worktrees require file tools."
        )
        return None, warnings

    from gotg.worktree import ensure_git_repo, create_worktree, ensure_gitignore_entries, WorktreeError

    project_root = team_dir.parent
    try:
        ensure_git_repo(project_root)
    except WorktreeError as e:
        raise SessionSetupError(str(e)) from e

    head_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_root, capture_output=True, text=True,
    )
    current_branch = head_result.stdout.strip()
    if current_branch != "main":
        raise SessionSetupError(
            f"HEAD is on '{current_branch}', expected 'main'. "
            "Worktrees branch from HEAD — switch to main first."
        )

    for w in ensure_gitignore_entries(project_root):
        warnings.append(w)

    layer = resolve_layer(layer_override, iteration)

    # For implementation phase, only create worktrees for agents with current-layer tasks
    agents_to_setup = agents
    if caps.filter_worktree_agents_by_tasks:
        tasks_path = team_dir.parent / ".team" / "iterations"
        # Find iter_dir from the team_dir layout
        from gotg.config import get_current_iteration
        try:
            _, iter_dir = get_current_iteration(team_dir)
            tasks_file = iter_dir / "tasks.json"
            if tasks_file.exists():
                from gotg.tasks import load_tasks_file as _load_tasks
                tasks_data = _load_tasks(tasks_file)
                layer_tasks = [t for t in tasks_data if t.get("layer") == layer]
                assigned_agents = {t.get("assigned_to") for t in layer_tasks if t.get("assigned_to")}
                if assigned_agents:
                    agents_to_setup = [a for a in agents if a["name"] in assigned_agents]
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError) as e:
            import sys
            print(f"Warning: could not filter agents by task assignment: {e}", file=sys.stderr)

    worktree_map = {}
    for agent in agents_to_setup:
        try:
            wt_path = create_worktree(project_root, agent["name"], layer)
            worktree_map[agent["name"]] = wt_path
        except WorktreeError as e:
            raise SessionSetupError(
                f"Error creating worktree for {agent['name']}: {e}"
            ) from e

    return worktree_map, warnings


def apply_and_inject(
    approval_store: object,
    fileguard: object,
    iteration: dict,
    log_path: Path,
    worktree_map: dict | None = None,
) -> list[dict]:
    """Apply approved writes and inject denial messages.

    Returns list of system message dicts (already persisted to log_path).
    Caller decides how to display them (print for CLI, post_message for TUI).
    """
    from gotg.approvals import apply_approved_writes

    messages: list[dict] = []

    # Route writes to agent worktrees when available
    fg_for_agent = None
    if worktree_map:
        fg_for_agent = (
            lambda name: fileguard.with_root(worktree_map[name])
            if name in worktree_map
            else fileguard
        )

    results = apply_approved_writes(
        approval_store, fileguard, fileguard_for_agent=fg_for_agent
    )
    for r in results:
        msg = {
            "from": "system",
            "iteration": iteration["id"],
            "content": (
                f"[file_write] APPROVED: {r['message']}"
                if r["success"]
                else f"[file_write] APPROVAL FAILED: {r['message']}"
            ),
        }
        append_message(log_path, msg)
        messages.append(msg)

    for req in approval_store.get_denied_uninjected():
        reason = req.get("denial_reason") or "No reason provided"
        msg = {
            "from": "system",
            "iteration": iteration["id"],
            "content": (
                f"[file_write] DENIED by PM: {req['path']} — {reason}. "
                f"(Originally requested by {req['requested_by']})"
            ),
        }
        append_message(log_path, msg)
        messages.append(msg)
        approval_store.mark_injected(req["id"])

    return messages


def load_diffs_for_review(
    team_dir: Path, iteration: dict, layer_override: int | None
) -> tuple[str | None, list[str]]:
    """Load diffs for code-review phase. Returns (diffs_str, warnings)."""
    if iteration.get("phase") != "code-review":
        return None, []

    from gotg.config import load_worktree_config
    worktree_config = load_worktree_config(team_dir)
    if not worktree_config or not worktree_config.get("enabled"):
        return None, ["code-review phase but worktrees not enabled. No diffs to load."]

    from gotg.worktree import format_diffs_for_prompt

    layer = resolve_layer(layer_override, iteration)
    diffs = format_diffs_for_prompt(team_dir.parent, layer)

    warnings: list[str] = []
    if not diffs:
        warnings.append(f"no branches found for layer {layer}. No diffs to review.")

    return diffs, warnings
