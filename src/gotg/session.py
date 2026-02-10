"""Shared session helpers used by both CLI and TUI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gotg.conversation import append_debug, append_message
from gotg.events import AppendDebug, AppendMessage


class SessionSetupError(Exception):
    """Raised when session setup fails. Caller decides how to display."""
    pass


def persist_event(event: object, log_path: Path, debug_path: Path) -> None:
    """Persist AppendMessage/AppendDebug events to disk. Other event types are no-ops."""
    if isinstance(event, AppendMessage):
        append_message(log_path, event.msg)
    elif isinstance(event, AppendDebug):
        append_debug(debug_path, event.entry)


def resolve_layer(layer_override: int | None, iteration: dict) -> int:
    """Resolve current layer: explicit override > iteration state > 0."""
    if layer_override is not None:
        return layer_override
    return iteration.get("current_layer", 0)


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
    if phase not in ("pre-code-review", "implementation"):
        return

    tasks_path = iter_dir / "tasks.json"
    if not tasks_path.exists():
        raise SessionSetupError(
            f"{phase} requires tasks.json. Run 'gotg advance' from planning first."
        )
    tasks = json.loads(tasks_path.read_text())
    current_layer = iteration.get("current_layer")
    if phase == "implementation" and current_layer is not None:
        tasks = [t for t in tasks if t.get("layer") == current_layer]
    unassigned = [t["id"] for t in tasks if not t.get("assigned_to")]
    if unassigned:
        scope = (
            f"layer {current_layer} tasks"
            if phase == "implementation" and current_layer is not None
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
    if phase not in ("implementation", "code-review"):
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

    worktree_map = {}
    for agent in agents:
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
