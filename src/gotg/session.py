"""Shared session helpers used by both CLI and TUI."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from gotg.conversation import append_debug, append_message
from gotg.events import AppendDebug, AppendMessage


class SessionSetupError(Exception):
    """Raised when session setup fails. Caller decides how to display."""
    pass


class PhaseAdvanceError(Exception):
    """Raised when phase advance cannot proceed. Caller decides how to display."""
    pass


class ReviewError(Exception):
    """Raised when review/merge/next-layer cannot proceed. Caller decides how to display."""
    pass


@dataclass
class BranchReview:
    """Diff data for one agent branch."""
    branch: str
    merged: bool
    empty: bool
    stat: str
    diff: str
    files_changed: int
    insertions: int
    deletions: int


@dataclass
class ReviewResult:
    """Collection of branch diffs for a layer."""
    layer: int
    branches: list[BranchReview]
    total_files: int
    total_insertions: int
    total_deletions: int


@dataclass
class MergeResult:
    """Result of merging a single branch."""
    branch: str
    success: bool
    commit: str | None = None
    conflicts: list[str] = field(default_factory=list)


@dataclass
class NextLayerResult:
    """Result of next-layer advance."""
    from_layer: int
    to_layer: int | None
    all_done: bool
    boundary_msg: dict | None = None
    transition_msg: dict | None = None
    checkpoint_number: int | None = None
    task_count: int = 0
    removed_worktrees: list[str] = field(default_factory=list)


@dataclass
class AdvanceResult:
    """Result of a successful phase advance."""
    from_phase: str
    to_phase: str
    boundary_msg: dict
    transition_msg: dict
    checkpoint_number: int | None
    warnings: list[str] = field(default_factory=list)


class ResolutionStrategy(Enum):
    """How a conflict file was resolved."""
    OURS = "ours"
    THEIRS = "theirs"
    AI = "ai"


@dataclass
class ConflictFileInfo:
    """3-way merge content for a single conflicted file."""
    path: str
    base_content: str | None  # stage 1 — None for add/add conflicts
    ours_content: str         # stage 2 (main)
    theirs_content: str       # stage 3 (branch)
    working_content: str      # file on disk with conflict markers


@dataclass
class ConflictInfo:
    """All conflicted files for a merge-in-progress."""
    branch: str
    files: list[ConflictFileInfo]


@dataclass
class AiResolutionResult:
    """Successful AI-assisted conflict resolution."""
    path: str
    resolved_content: str
    explanation: str


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


def validate_advance(iteration: dict) -> tuple[str, str]:
    """Validate that advance is possible. Returns (current_phase, next_phase).

    Raises PhaseAdvanceError if advance cannot proceed.
    """
    from gotg.config import PHASE_ORDER

    if iteration.get("status") != "in-progress":
        raise PhaseAdvanceError(
            f"Iteration status is '{iteration.get('status')}', expected 'in-progress'."
        )

    current_phase = iteration.get("phase", "refinement")
    try:
        idx = PHASE_ORDER.index(current_phase)
    except ValueError:
        raise PhaseAdvanceError(f"Unknown phase '{current_phase}'.")

    if idx >= len(PHASE_ORDER) - 1:
        hint = " Run 'gotg next-layer' after merging." if current_phase == "code-review" else ""
        raise PhaseAdvanceError(f"Cannot advance past {current_phase}.{hint}")

    return current_phase, PHASE_ORDER[idx + 1]


def advance_phase(
    team_dir: Path,
    iteration: dict,
    iter_dir: Path,
    chat_call: Callable,
    on_progress: Callable[[str], None] | None = None,
) -> AdvanceResult:
    """Execute phase advance. Blocking (makes LLM calls).

    Args:
        team_dir: Path to .team/ directory.
        iteration: Current iteration dict.
        iter_dir: Path to iteration data directory.
        chat_call: The chat_completion callable for LLM extractions.
        on_progress: Optional callback for progress messages.

    Returns AdvanceResult. Raises PhaseAdvanceError on validation failure.
    """
    from gotg.checkpoint import create_checkpoint
    from gotg.config import (
        load_coach, load_model_config, load_worktree_config,
        save_iteration_fields, save_iteration_phase,
    )
    from gotg.conversation import read_phase_history
    from gotg.transitions import (
        auto_commit_layer_worktrees, build_transition_messages,
        extract_refinement_summary, extract_task_notes, extract_tasks,
    )

    def _progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    current_phase, next_phase = validate_advance(iteration)
    log_path = iter_dir / "conversation.jsonl"
    coach = load_coach(team_dir)
    coach_ran = False
    tasks_written = False
    warnings: list[str] = []

    # refinement → planning: extract summary
    if current_phase == "refinement" and next_phase == "planning" and coach:
        _progress("Summarizing refinement conversation...")
        model_config = load_model_config(team_dir)
        history = read_phase_history(log_path)
        summary = extract_refinement_summary(history, model_config, coach["name"], chat_call)
        summary_path = iter_dir / "refinement_summary.md"
        summary_path.write_text(summary + "\n")
        _progress(f"Wrote {summary_path}")
        coach_ran = True

    # planning → pre-code-review: extract tasks
    if current_phase == "planning" and next_phase == "pre-code-review" and coach:
        _progress("Extracting tasks from planning conversation...")
        model_config = load_model_config(team_dir)
        history = read_phase_history(log_path)
        tasks, raw_text, error = extract_tasks(history, model_config, coach["name"], chat_call)
        if tasks is not None:
            tasks_path = iter_dir / "tasks.json"
            tasks_path.write_text(json.dumps(tasks, indent=2) + "\n")
            _progress(f"Wrote {tasks_path}")
            tasks_written = True
        else:
            warnings.append(error)
            (iter_dir / "tasks_raw.txt").write_text(raw_text + "\n")
            warnings.append("Raw output saved to tasks_raw.txt for manual correction.")
        coach_ran = True

    # pre-code-review → implementation: set layer, extract notes
    if current_phase == "pre-code-review" and next_phase == "implementation":
        save_iteration_fields(team_dir, iteration["id"], current_layer=0)
        if coach:
            tasks_path = iter_dir / "tasks.json"
            if tasks_path.exists():
                _progress("Extracting task notes from pre-code-review...")
                model_config = load_model_config(team_dir)
                history = read_phase_history(log_path)
                tasks_data = json.loads(tasks_path.read_text())
                notes_map, raw_text, error = extract_task_notes(
                    history, tasks_data, model_config, coach["name"], chat_call,
                )
                if notes_map is not None:
                    for task in tasks_data:
                        if task["id"] in notes_map:
                            task["notes"] = notes_map[task["id"]]
                    tasks_path.write_text(json.dumps(tasks_data, indent=2) + "\n")
                    _progress(f"Updated {tasks_path} with task notes")
                    coach_ran = True
                else:
                    warnings.append(error)
                    (iter_dir / "notes_raw.txt").write_text(raw_text + "\n")
                    warnings.append("Raw output saved to notes_raw.txt for manual review.")

    # implementation → code-review: auto-commit worktrees
    if current_phase == "implementation" and next_phase == "code-review":
        worktree_config = load_worktree_config(team_dir)
        if worktree_config and worktree_config.get("enabled"):
            _progress("Auto-committing worktrees...")
            results = auto_commit_layer_worktrees(
                team_dir.parent, iteration.get("current_layer", 0)
            )
            for branch, commit_hash, err in results:
                if err:
                    warnings.append(f"Could not auto-commit {branch}: {err}")
                elif commit_hash:
                    _progress(f"Auto-committed {branch}: {commit_hash}")

    # Save phase change + boundary markers
    _progress("Saving phase change and creating checkpoint...")
    save_iteration_phase(team_dir, iteration["id"], next_phase)
    boundary_msg, transition_msg = build_transition_messages(
        iteration["id"], current_phase, next_phase, tasks_written, coach_ran,
    )
    append_message(log_path, boundary_msg)
    append_message(log_path, transition_msg)

    # Auto-checkpoint
    iteration["phase"] = next_phase
    checkpoint_number = None
    try:
        coach_name = coach["name"] if coach else "coach"
        checkpoint_number = create_checkpoint(
            iter_dir, iteration, trigger="auto", coach_name=coach_name
        )
    except Exception as e:
        warnings.append(f"Auto-checkpoint failed: {e}")

    return AdvanceResult(
        from_phase=current_phase,
        to_phase=next_phase,
        boundary_msg=boundary_msg,
        transition_msg=transition_msg,
        checkpoint_number=checkpoint_number,
        warnings=warnings,
    )


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


def load_review_branches(
    team_dir: Path,
    iteration: dict,
    layer_override: int | None = None,
) -> ReviewResult:
    """Load branch diffs for review. Raises ReviewError on failure."""
    from gotg.worktree import (
        WorktreeError, diff_branch, ensure_git_repo,
        is_branch_merged, list_layer_branches,
    )

    project_root = team_dir.parent
    try:
        ensure_git_repo(project_root)
    except WorktreeError as e:
        raise ReviewError(str(e)) from e

    layer = resolve_layer(layer_override, iteration)
    branches = list_layer_branches(project_root, layer)
    if not branches:
        raise ReviewError(f"No branches found for layer {layer}.")

    reviews: list[BranchReview] = []
    total_files = 0
    total_ins = 0
    total_del = 0

    for br in branches:
        merged = is_branch_merged(project_root, br)
        try:
            result = diff_branch(project_root, br)
        except WorktreeError:
            reviews.append(BranchReview(
                branch=br, merged=merged, empty=True,
                stat="", diff="", files_changed=0, insertions=0, deletions=0,
            ))
            continue
        reviews.append(BranchReview(
            branch=br,
            merged=merged,
            empty=result["empty"],
            stat=result["stat"],
            diff=result["diff"],
            files_changed=result["files_changed"],
            insertions=result["insertions"],
            deletions=result["deletions"],
        ))
        total_files += result["files_changed"]
        total_ins += result["insertions"]
        total_del += result["deletions"]

    return ReviewResult(
        layer=layer,
        branches=reviews,
        total_files=total_files,
        total_insertions=total_ins,
        total_deletions=total_del,
    )


def merge_branches(
    project_root: Path,
    layer: int,
    branches: list[str] | None = None,
    force: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> list[MergeResult]:
    """Merge branches into main. Stops on first conflict.

    Args:
        project_root: Git repository root.
        layer: Current layer number.
        branches: Specific branches to merge, or None to discover all unmerged.
        force: Skip dirty worktree checks.
        on_progress: Callback per branch.

    Returns list of MergeResult. Raises ReviewError for precondition failures.
    """
    from gotg.worktree import (
        WorktreeError, commit_worktree, is_branch_merged, is_merge_in_progress,
        is_worktree_dirty, list_active_worktrees, list_layer_branches,
        merge_branch,
    )

    if is_merge_in_progress(project_root):
        raise ReviewError(
            "A merge is already in progress. "
            "Resolve conflicts and commit, or run 'gotg merge --abort'."
        )

    # Verify HEAD is on main
    import subprocess as _sp
    _head = _sp.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_root, capture_output=True, text=True,
    ).stdout.strip()
    if _head != "main":
        raise ReviewError(
            f"HEAD is on '{_head}', expected 'main'. "
            "gotg requires the default branch to be named 'main'."
        )

    if is_worktree_dirty(project_root):
        raise ReviewError("uncommitted changes on main. Commit or stash before merging.")

    if branches is None:
        branches = list_layer_branches(project_root, layer)
        if not branches:
            raise ReviewError(f"No branches found for layer {layer}.")
        branches = [br for br in branches if not is_branch_merged(project_root, br)]
        if not branches:
            raise ReviewError(f"All branches in layer {layer} already merged.")

    # Auto-commit dirty worktrees before merging
    active_wts = list_active_worktrees(project_root)
    wt_by_branch = {wt.get("branch"): Path(wt["path"]) for wt in active_wts}
    for br in branches:
        if br in wt_by_branch and is_worktree_dirty(wt_by_branch[br]):
            if on_progress:
                on_progress(f"Auto-committing {br}...")
            try:
                commit_worktree(wt_by_branch[br], "Auto-commit before merge")
            except WorktreeError as e:
                raise ReviewError(
                    f"Failed to auto-commit {br}: {e}"
                )

    results: list[MergeResult] = []
    for br in branches:
        if on_progress:
            on_progress(f"Merging {br}...")
        try:
            result = merge_branch(project_root, br)
        except WorktreeError as e:
            results.append(MergeResult(branch=br, success=False, conflicts=[str(e)]))
            break
        if result["success"]:
            results.append(MergeResult(
                branch=br, success=True, commit=result["commit"],
            ))
        else:
            results.append(MergeResult(
                branch=br, success=False, conflicts=result.get("conflicts", []),
            ))
            break  # Stop on conflict

    return results


def validate_next_layer(
    team_dir: Path, iteration: dict, iter_dir: Path,
) -> tuple[int, int]:
    """Pre-flight check for next-layer advance. Returns (current_layer, next_layer).

    Raises ReviewError if advance cannot proceed.
    """
    if iteration.get("status") != "in-progress":
        raise ReviewError(
            f"Iteration status is '{iteration.get('status')}', expected 'in-progress'."
        )

    current_phase = iteration.get("phase", "refinement")
    if current_phase != "code-review":
        raise ReviewError(
            f"next-layer requires code-review phase, currently in '{current_phase}'."
        )

    current_layer = iteration.get("current_layer", 0)
    next_layer = current_layer + 1

    from gotg.config import load_worktree_config
    worktree_config = load_worktree_config(team_dir)
    if worktree_config and worktree_config.get("enabled"):
        from gotg.worktree import (
            WorktreeError, ensure_git_repo, is_branch_merged,
            is_worktree_dirty, list_active_worktrees, list_layer_branches,
        )

        project_root = team_dir.parent
        try:
            ensure_git_repo(project_root)
        except WorktreeError as e:
            raise ReviewError(str(e)) from e

        # Verify HEAD is on main
        head_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root, capture_output=True, text=True,
        )
        current_branch = head_result.stdout.strip()
        if current_branch != "main":
            raise ReviewError(
                f"HEAD is on '{current_branch}', expected 'main'. "
                "Switch to main before running next-layer."
            )

        # Verify all layer branches merged
        layer_branches = list_layer_branches(project_root, current_layer)
        unmerged = [br for br in layer_branches if not is_branch_merged(project_root, br)]
        if unmerged:
            raise ReviewError(
                f"Unmerged branches for layer {current_layer}: {', '.join(unmerged)}. "
                "Merge all branches before advancing."
            )

        # Block on dirty worktrees
        layer_suffix = f"/layer-{current_layer}"
        for wt in list_active_worktrees(project_root):
            branch = wt.get("branch", "")
            if branch.endswith(layer_suffix) and is_worktree_dirty(Path(wt["path"])):
                raise ReviewError(
                    f"Dirty worktree for {branch}. "
                    "Commit or discard changes before advancing."
                )

    return current_layer, next_layer


def advance_next_layer(
    team_dir: Path,
    iteration: dict,
    iter_dir: Path,
    on_progress: Callable[[str], None] | None = None,
) -> NextLayerResult:
    """Advance to next layer after code-review. Raises ReviewError on failure."""
    from gotg.checkpoint import create_checkpoint
    from gotg.config import load_coach, load_worktree_config, save_iteration_fields
    from gotg.conversation import append_message as conv_append_message

    def _progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    current_layer, next_layer = validate_next_layer(team_dir, iteration, iter_dir)
    removed_worktrees: list[str] = []

    # Clean up current layer worktrees
    worktree_config = load_worktree_config(team_dir)
    if worktree_config and worktree_config.get("enabled"):
        from gotg.worktree import cleanup_layer_worktrees
        _progress(f"Cleaning up layer {current_layer} worktrees...")
        try:
            removed = cleanup_layer_worktrees(team_dir.parent, current_layer)
            removed_worktrees.extend(removed)
        except Exception as e:
            _progress(f"Warning: worktree cleanup failed: {e}")

    # Check tasks.json for next layer
    tasks_path = iter_dir / "tasks.json"
    if not tasks_path.exists():
        raise ReviewError("tasks.json not found.")
    tasks = json.loads(tasks_path.read_text())

    # Recompute layers if any task is missing the stored layer field
    if any("layer" not in t for t in tasks):
        from gotg.tasks import compute_layers
        try:
            layers = compute_layers(tasks)
            for t in tasks:
                t["layer"] = layers[t["id"]]
        except (ValueError, KeyError) as e:
            _progress(f"Warning: could not compute layers: {e}")

    next_layer_tasks = [t for t in tasks if t.get("layer") == next_layer]
    if not next_layer_tasks:
        return NextLayerResult(
            from_layer=current_layer,
            to_layer=None,
            all_done=True,
        )

    # Advance to next layer
    _progress(f"Advancing to layer {next_layer}...")
    save_iteration_fields(
        team_dir, iteration["id"], phase="implementation", current_layer=next_layer,
    )

    # Log transition with boundary marker
    log_path = iter_dir / "conversation.jsonl"
    boundary_msg = {
        "from": "system",
        "iteration": iteration["id"],
        "content": "--- HISTORY BOUNDARY ---",
        "phase_boundary": True,
        "from_phase": "code-review",
        "to_phase": "implementation",
        "layer": next_layer,
    }
    conv_append_message(log_path, boundary_msg)
    transition_msg = {
        "from": "system",
        "iteration": iteration["id"],
        "content": (
            f"--- Layer {current_layer} complete. "
            f"Advancing to layer {next_layer} (implementation) ---"
        ),
    }
    conv_append_message(log_path, transition_msg)

    # Auto-checkpoint
    iteration["phase"] = "implementation"
    iteration["current_layer"] = next_layer
    checkpoint_number = None
    coach = load_coach(team_dir)
    try:
        coach_name = coach["name"] if coach else "coach"
        checkpoint_number = create_checkpoint(
            iter_dir, iteration, trigger="auto", coach_name=coach_name,
        )
    except Exception as e:
        _progress(f"Warning: auto-checkpoint failed: {e}")

    return NextLayerResult(
        from_layer=current_layer,
        to_layer=next_layer,
        all_done=False,
        boundary_msg=boundary_msg,
        transition_msg=transition_msg,
        checkpoint_number=checkpoint_number,
        task_count=len(next_layer_tasks),
        removed_worktrees=removed_worktrees,
    )


# ── Conflict resolution bridge functions ─────────────────────


def load_conflict_info(
    project_root: Path,
    branch: str,
    conflict_paths: list[str],
) -> ConflictInfo:
    """Load 3-way content for all conflicted files. Raises ReviewError."""
    from gotg.worktree import WorktreeError, get_conflict_stages

    files: list[ConflictFileInfo] = []
    for path in conflict_paths:
        try:
            stages = get_conflict_stages(project_root, path)
        except WorktreeError as e:
            raise ReviewError(f"Could not read conflict stages for {path}: {e}") from e
        files.append(ConflictFileInfo(
            path=path,
            base_content=stages["base"],
            ours_content=stages["ours"],
            theirs_content=stages["theirs"],
            working_content=stages["working"],
        ))
    return ConflictInfo(branch=branch, files=files)


def resolve_conflict_file(
    project_root: Path,
    file_path: str,
    strategy: ResolutionStrategy,
    content: str | None = None,
) -> None:
    """Resolve a single file using the given strategy. Raises ReviewError."""
    from gotg.worktree import (
        WorktreeError, resolve_conflict_content,
        resolve_conflict_ours, resolve_conflict_theirs,
    )

    try:
        if strategy == ResolutionStrategy.OURS:
            resolve_conflict_ours(project_root, file_path)
        elif strategy == ResolutionStrategy.THEIRS:
            resolve_conflict_theirs(project_root, file_path)
        elif strategy == ResolutionStrategy.AI:
            if content is None:
                raise ReviewError("AI resolution requires content.")
            resolve_conflict_content(project_root, file_path, content)
    except WorktreeError as e:
        raise ReviewError(f"Failed to resolve {file_path}: {e}") from e


def ai_resolve_conflict(
    file_path: str,
    branch: str,
    base_content: str | None,
    ours_content: str,
    theirs_content: str,
    task_context: str,
    model_config: dict,
    chat_call: Callable,
) -> AiResolutionResult:
    """LLM-assisted conflict resolution. Returns AiResolutionResult, raises ReviewError."""
    from gotg.transitions import resolve_merge_conflict

    try:
        resolved_content, explanation = resolve_merge_conflict(
            file_path, branch,
            base_content, ours_content, theirs_content,
            task_context, model_config, chat_call,
        )
    except ValueError as e:
        raise ReviewError(f"AI resolution failed for {file_path}: {e}") from e

    return AiResolutionResult(
        path=file_path,
        resolved_content=resolved_content,
        explanation=explanation,
    )


def finalize_merge(
    project_root: Path,
    branch: str,
) -> MergeResult:
    """Complete a merge after all conflicts are resolved. Raises ReviewError."""
    from gotg.worktree import WorktreeError, complete_merge

    try:
        commit_hash = complete_merge(project_root)
    except WorktreeError as e:
        raise ReviewError(f"Failed to complete merge of {branch}: {e}") from e

    return MergeResult(branch=branch, success=True, commit=commit_hash)
