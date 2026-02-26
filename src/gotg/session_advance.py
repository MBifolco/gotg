"""Phase transitions and layer progression."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from gotg.conversation import ConversationStore
from gotg.session_types import (
    AdvanceResult,
    NextLayerResult,
    PhaseAdvanceError,
    ReviewError,
)

__all__ = [
    "validate_advance",
    "advance_phase",
    "validate_next_layer",
    "advance_next_layer",
]


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
    from gotg.transitions import (
        auto_commit_layer_worktrees, build_phase_skeleton, build_transition_messages,
        extract_refinement_summary, extract_task_notes, extract_tasks,
    )

    def _progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    current_phase, next_phase = validate_advance(iteration)
    log_path = iter_dir / "conversation.jsonl"
    store = ConversationStore(log_path)

    # Guard: refuse to advance if no conversation happened in this phase
    phase_history = store.read_phase_history()
    agent_messages = [m for m in phase_history if m.get("from") not in ("system", "human")]
    if not agent_messages:
        raise PhaseAdvanceError(
            f"No conversation in {current_phase} phase. Run 'gotg run' first."
        )

    coach = load_coach(team_dir)
    coach_ran = False
    tasks_written = False
    warnings: list[str] = []

    # refinement → planning: extract summary
    if current_phase == "refinement" and next_phase == "planning" and coach:
        _progress("Summarizing refinement conversation...")
        model_config = load_model_config(team_dir)
        history = store.read_phase_history()
        summary = extract_refinement_summary(history, model_config, coach["name"], chat_call)
        summary_path = iter_dir / "refinement_summary.md"
        summary_path.write_text(summary + "\n")
        _progress(f"Wrote {summary_path}")
        coach_ran = True

    # planning → pre-code-review: extract tasks
    if current_phase == "planning" and next_phase == "pre-code-review" and coach:
        _progress("Extracting tasks from planning conversation...")
        model_config = load_model_config(team_dir)
        history = store.read_phase_history()
        summary_path = iter_dir / "refinement_summary.md"
        ref_summary = summary_path.read_text().strip() if summary_path.exists() else None
        tasks, raw_text, error = extract_tasks(
            history, model_config, coach["name"], chat_call,
            refinement_summary=ref_summary,
        )
        if tasks is not None:
            tasks_path = iter_dir / "tasks.json"
            from gotg.tasks import save_tasks_file
            save_tasks_file(tasks_path, tasks)
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
                history = store.read_phase_history()
                from gotg.tasks import load_tasks_file, save_tasks_file
                tasks_data = load_tasks_file(tasks_path)
                notes_map, raw_text, error = extract_task_notes(
                    history, tasks_data, model_config, coach["name"], chat_call,
                )
                if notes_map is not None:
                    for task in tasks_data:
                        if task["id"] in notes_map:
                            task["notes"] = notes_map[task["id"]]
                    save_tasks_file(tasks_path, tasks_data)
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

    # Capture phase history BEFORE writing boundary markers —
    # read_phase_history returns messages after the last boundary,
    # so it must be called while the current phase's content is still "last".
    history_for_skeleton = store.read_phase_history()
    coach_name_for_skeleton = coach["name"] if coach else "coach"

    # Save phase change + boundary markers
    _progress("Saving phase change and creating checkpoint...")
    save_iteration_phase(team_dir, iteration["id"], next_phase)
    boundary_msg, transition_msg = build_transition_messages(
        iteration["id"], current_phase, next_phase, tasks_written, coach_ran,
    )
    store.append(boundary_msg)
    store.append(transition_msg)

    # Compute and accumulate phase skeleton from pre-boundary history
    skeleton_path = iter_dir / "phase_skeleton.md"
    existing_skeleton = skeleton_path.read_text().strip() if skeleton_path.exists() else ""
    new_skeleton = build_phase_skeleton(
        history_for_skeleton, current_phase, coach_name_for_skeleton,
    )
    accumulated = (existing_skeleton + "\n\n" + new_skeleton).strip()
    skeleton_path.write_text(accumulated + "\n")

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
    from gotg.phases import get_phase_caps
    try:
        caps = get_phase_caps(current_phase)
    except ValueError as e:
        raise ReviewError(str(e)) from e
    if not caps.supports_next_layer:
        raise ReviewError(
            f"next-layer requires implementation or code-review phase, currently in '{current_phase}'."
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
    """Advance to next layer after implementation/code-review. Raises ReviewError on failure."""
    from gotg.checkpoint import create_checkpoint
    from gotg.config import load_coach, load_worktree_config, save_iteration_fields

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
    from gotg.tasks import load_tasks_file
    tasks = load_tasks_file(tasks_path)

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
    from_phase = iteration.get("phase", "implementation")
    log_path = iter_dir / "conversation.jsonl"
    store = ConversationStore(log_path)
    boundary_msg = {
        "from": "system",
        "iteration": iteration["id"],
        "content": "--- HISTORY BOUNDARY ---",
        "phase_boundary": True,
        "from_phase": from_phase,
        "to_phase": "implementation",
        "layer": next_layer,
    }
    store.append(boundary_msg)
    transition_msg = {
        "from": "system",
        "iteration": iteration["id"],
        "content": (
            f"--- Layer {current_layer} complete. "
            f"Advancing to layer {next_layer} (implementation) ---"
        ),
    }
    store.append(transition_msg)

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
