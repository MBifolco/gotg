import sys
from pathlib import Path

import gotg.cli as _cli
from gotg.config import IterationStore


def cmd_review(args):
    """Show diffs of agent branches against main."""
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.session import ReviewError, load_review_branches

    iteration, _ = IterationStore(team_dir).get_current()

    if args.branch:
        # Specific branch — bypass layer discovery, diff just this branch
        from gotg.worktree import (
            WorktreeError, diff_branch, ensure_git_repo, is_branch_merged,
        )
        project_root = team_dir.parent
        try:
            ensure_git_repo(project_root)
        except WorktreeError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)

        merged = is_branch_merged(project_root, args.branch)
        label = " [merged]" if merged else ""
        print(f"=== {args.branch}{label} ===")
        try:
            result = diff_branch(project_root, args.branch)
        except WorktreeError as e:
            print(f"Error: {e}")
            print()
            print("---")
            print(f"1 branch(es), 0 file(s) changed, +0 -0 lines")
            return
        if result["empty"]:
            print("(no changes)")
        else:
            print(result["stat"].rstrip())
            if not args.stat_only:
                print()
                print(result["diff"].rstrip())
        print()
        print("---")
        print(f"1 branch(es), {result['files_changed']} file(s) changed, +{result['insertions']} -{result['deletions']} lines")
        return

    # Normal case — load all branches for layer
    try:
        review = load_review_branches(team_dir, iteration, args.layer)
    except ReviewError as e:
        print(f"{e}")
        return

    for br in review.branches:
        label = " [merged]" if br.merged else ""
        print(f"=== {br.branch}{label} ===")
        if br.empty:
            print("(no changes)")
        else:
            print(br.stat.rstrip())
            if not args.stat_only:
                print()
                print(br.diff.rstrip())
        print()

    print("---")
    print(
        f"Layer {review.layer}: {len(review.branches)} branch(es), "
        f"{review.total_files} file(s) changed, "
        f"+{review.total_insertions} -{review.total_deletions} lines"
    )


def cmd_merge(args):
    """Merge an agent branch into main."""
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.worktree import WorktreeError, abort_merge, ensure_git_repo

    project_root = team_dir.parent
    try:
        ensure_git_repo(project_root)
    except WorktreeError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    if args.abort:
        try:
            abort_merge(project_root)
            print("Merge aborted.")
        except WorktreeError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)
        return

    from gotg.session import ReviewError, merge_branches
    from gotg.worktree import is_branch_merged

    iteration, _ = IterationStore(team_dir).get_current()
    layer = args.layer if args.layer is not None else iteration.get("current_layer", 0)
    is_all = args.branch == "all"

    # Single branch: check if already merged before calling merge_branches
    if not is_all and is_branch_merged(project_root, args.branch):
        print(f"Branch '{args.branch}' is already merged into main.")
        return

    branches = None if is_all else [args.branch]

    try:
        results = merge_branches(
            project_root, layer, branches=branches,
            force=args.force, on_progress=lambda msg: print(msg),
        )
    except ReviewError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    merged_count = sum(1 for r in results if r.success)
    for r in results:
        if r.success:
            if is_all:
                print(f"  Merged: {r.commit}")
            else:
                print(f"Merged {r.branch} into main: {r.commit}")
        else:
            print(f"\nCONFLICT merging {r.branch}:" if is_all else f"CONFLICT merging {r.branch}:")
            for f in r.conflicts:
                print(f"  {f}")
            if is_all:
                print(f"\nMerged {merged_count}/{merged_count + len([x for x in results if not x.success])} branches before conflict.")
                print("Resolve conflicts and commit, then run 'gotg merge all' again,")
                print("or run 'gotg merge --abort' to undo.")
            else:
                print("\nResolve conflicts and commit, or run 'gotg merge --abort' to undo.")
            return

    if is_all:
        print(f"\n{merged_count} branch(es) merged into main.")


def cmd_worktrees(args):
    """List active git worktrees."""
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.worktree import ensure_git_repo, list_active_worktrees, is_worktree_dirty, WorktreeError

    project_root = team_dir.parent
    try:
        ensure_git_repo(project_root)
    except WorktreeError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    worktrees = list_active_worktrees(project_root)
    if not worktrees:
        print("No active worktrees.")
        return

    print("Active worktrees:")
    for wt in worktrees:
        wt_path = Path(wt["path"])
        status = "[dirty]" if is_worktree_dirty(wt_path) else "[clean]"
        branch = wt.get("branch", "unknown")
        rel_path = wt_path.relative_to(project_root) if wt_path.is_relative_to(project_root) else wt_path
        print(f"  {branch:<30} {rel_path}/  {status}")


def cmd_commit_worktrees(args):
    """Commit all dirty worktrees."""
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.worktree import ensure_git_repo, list_active_worktrees, commit_worktree, WorktreeError

    project_root = team_dir.parent
    try:
        ensure_git_repo(project_root)
    except WorktreeError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    worktrees = list_active_worktrees(project_root)
    if not worktrees:
        print("No active worktrees.")
        return

    message = args.message or "Agent implementation work"
    committed = 0
    for wt in worktrees:
        wt_path = Path(wt["path"])
        branch = wt.get("branch", "unknown")
        try:
            commit_hash = commit_worktree(wt_path, message)
            if commit_hash:
                print(f"{branch}: committed {commit_hash}")
                committed += 1
            else:
                print(f"{branch}: nothing to commit")
        except WorktreeError as e:
            print(f"{branch}: error — {e}", file=sys.stderr)

    if committed:
        print(f"\n{committed} worktree(s) committed.")
