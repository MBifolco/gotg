"""Review, merge, and conflict resolution bridge functions."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from gotg.session_types import (
    AiResolutionResult,
    BranchReview,
    ConflictFileInfo,
    ConflictInfo,
    MergeResult,
    ResolutionStrategy,
    ReviewError,
    ReviewResult,
    resolve_layer,
)

__all__ = [
    "load_review_branches",
    "merge_branches",
    "load_conflict_info",
    "resolve_conflict_file",
    "ai_resolve_conflict",
    "finalize_merge",
]


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

    if is_worktree_dirty(project_root, include_untracked=False):
        raise ReviewError("uncommitted changes on main. Commit or stash before merging.")

    # Auto-commit dirty worktrees before checking merge status
    active_wts = list_active_worktrees(project_root)
    wt_by_branch = {wt.get("branch"): Path(wt["path"]) for wt in active_wts}

    if branches is None:
        all_layer_branches = list_layer_branches(project_root, layer)
        if not all_layer_branches:
            raise ReviewError(f"No branches found for layer {layer}.")

        # Auto-commit before filtering — otherwise branches with only
        # untracked files appear "merged" (same commit as main)
        for br in all_layer_branches:
            if br in wt_by_branch and is_worktree_dirty(wt_by_branch[br]):
                if on_progress:
                    on_progress(f"Auto-committing {br}...")
                try:
                    commit_worktree(wt_by_branch[br], "Auto-commit before merge")
                except WorktreeError as e:
                    raise ReviewError(f"Failed to auto-commit {br}: {e}")

        branches = [br for br in all_layer_branches if not is_branch_merged(project_root, br)]
        if not branches:
            raise ReviewError(f"All branches in layer {layer} already merged.")
    else:
        # Explicit branch list — auto-commit those specific branches
        for br in branches:
            if br in wt_by_branch and is_worktree_dirty(wt_by_branch[br]):
                if on_progress:
                    on_progress(f"Auto-committing {br}...")
                try:
                    commit_worktree(wt_by_branch[br], "Auto-commit before merge")
                except WorktreeError as e:
                    raise ReviewError(f"Failed to auto-commit {br}: {e}")

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
