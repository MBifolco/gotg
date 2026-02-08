import subprocess
from pathlib import Path


class WorktreeError(Exception):
    """Raised when a git worktree operation fails."""
    pass


WORKTREE_BASE = ".worktrees"


def worktree_dir_name(agent_name: str, layer: int) -> str:
    """Generate worktree directory name: agent-1-layer-0"""
    return f"{agent_name}-layer-{layer}"


def branch_name(agent_name: str, layer: int) -> str:
    """Generate branch name: agent-1/layer-0"""
    return f"{agent_name}/layer-{layer}"


def get_worktree_path(project_root: Path, agent_name: str, layer: int) -> Path:
    """Return worktree path (no git command, just path construction)."""
    return project_root / WORKTREE_BASE / worktree_dir_name(agent_name, layer)


def ensure_git_repo(project_root: Path) -> None:
    """Verify project is a git repo. Raises WorktreeError if not."""
    git_dir = project_root / ".git"
    if not git_dir.exists():
        raise WorktreeError(
            f"Not a git repository: {project_root}. "
            "Run 'git init' first."
        )


GITIGNORE_ENTRIES = [f"/{WORKTREE_BASE}/", "/.team/", ".env"]


def ensure_gitignore_entries(project_root: Path) -> list[str]:
    """Ensure .worktrees/, .team/, and .env are in .gitignore.

    Returns list of warning messages (e.g. if tracked files need manual untracking).
    """
    import subprocess as _sp

    gitignore = project_root / ".gitignore"
    warnings = []

    if gitignore.exists():
        content = gitignore.read_text()
    else:
        content = ""

    existing = {line.strip() for line in content.splitlines()}
    added = []
    for entry in GITIGNORE_ENTRIES:
        if entry not in existing:
            added.append(entry)

    if added:
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n".join(added) + "\n"
        gitignore.write_text(content)

    # Warn if any of these paths are currently tracked by git
    # Use `git ls-files -- path` (not --error-unmatch) to catch files *under*
    # directories like .team/team.json, since git doesn't track directories.
    for check_path in [".team", ".env"]:
        result = _sp.run(
            ["git", "ls-files", "--", check_path],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            warnings.append(
                f"'{check_path}' is tracked by git. "
                f"Run 'git rm -r --cached {check_path}' to untrack it."
            )

    return warnings


def _git(project_root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in the project root. Raises WorktreeError on failure."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise WorktreeError(e.stderr.strip() or str(e))


def _branch_exists(project_root: Path, branch: str) -> bool:
    """Check if a branch exists."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _is_known_worktree(project_root: Path, wt_path: Path) -> bool:
    """Check if a path is a registered git worktree."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    resolved = str(wt_path.resolve())
    for line in result.stdout.splitlines():
        if line.startswith("worktree ") and line[9:] == resolved:
            return True
    return False


def create_worktree(project_root: Path, agent_name: str, layer: int) -> Path:
    """Create branch + worktree. Returns worktree path.

    Idempotent: handles four cases:
    1. Worktree exists and git knows about it → return path
    2. Neither branch nor worktree exist → create both
    3. Branch exists but worktree doesn't → attach existing branch
    4. Directory exists but git doesn't know about it → remove and recreate
    """
    wt_path = get_worktree_path(project_root, agent_name, layer)
    branch = branch_name(agent_name, layer)

    if wt_path.exists():
        if _is_known_worktree(project_root, wt_path):
            return wt_path
        # Case 4: directory exists but git doesn't know about it — clean up
        import shutil
        shutil.rmtree(wt_path)

    if _branch_exists(project_root, branch):
        # Case 3: branch exists, attach it to new worktree
        _git(project_root, "worktree", "add", str(wt_path), branch)
    else:
        # Case 2: create both branch and worktree
        _git(project_root, "worktree", "add", "-b", branch, str(wt_path))

    return wt_path


def commit_worktree(worktree_path: Path, message: str) -> str | None:
    """Stage all changes and commit. Returns commit hash or None if clean."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        return None

    _git(worktree_path, "add", "-A")
    _git(worktree_path, "commit", "-m", message)
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def is_worktree_dirty(worktree_path: Path) -> bool:
    """Check if a worktree has uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def remove_worktree(project_root: Path, worktree_path: Path) -> None:
    """Remove a git worktree."""
    _git(project_root, "worktree", "remove", str(worktree_path), "--force")


def list_active_worktrees(project_root: Path) -> list[dict]:
    """Parse 'git worktree list --porcelain'. Returns list of dicts.

    Each dict: {"path": str, "branch": str, "head": str}
    Excludes the main worktree.
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    worktrees = []
    current = {}
    main_path = str(project_root.resolve())

    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current and current.get("path") != main_path:
                worktrees.append(current)
            current = {"path": line[9:]}
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            # "branch refs/heads/agent-1/layer-0" → "agent-1/layer-0"
            ref = line[7:]
            if ref.startswith("refs/heads/"):
                current["branch"] = ref[11:]
            else:
                current["branch"] = ref
        elif line == "":
            pass  # separator between entries

    # Don't forget last entry
    if current and current.get("path") != main_path:
        worktrees.append(current)

    return worktrees


SENSITIVE_PATHS = [".env", ".env.*", ".team/**"]


def diff_branch(project_root: Path, branch: str, exclude_paths: list[str] | None = None) -> dict:
    """Return diff of a branch against main (three-dot: changes since divergence).

    Args:
        exclude_paths: list of pathspec patterns to exclude (e.g. [".env", ".team/**"])

    Returns dict with keys:
        branch, stat, diff, files_changed, insertions, deletions, empty
    """
    if not _branch_exists(project_root, branch):
        raise WorktreeError(f"Branch '{branch}' does not exist.")

    # Build pathspec exclusions: -- ':!.env' ':!.team/**'
    excludes = []
    if exclude_paths:
        excludes = ["--"] + [f":!{p}" for p in exclude_paths]

    stat = _git(project_root, "diff", "--stat", f"main...{branch}", *excludes).stdout
    full_diff = _git(project_root, "diff", f"main...{branch}", *excludes).stdout
    numstat = _git(project_root, "diff", "--numstat", f"main...{branch}", *excludes).stdout

    files_changed = 0
    insertions = 0
    deletions = 0
    for line in numstat.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        files_changed += 1
        # Binary files show "-" for counts
        if parts[0] != "-":
            insertions += int(parts[0])
        if parts[1] != "-":
            deletions += int(parts[1])

    return {
        "branch": branch,
        "stat": stat,
        "diff": full_diff,
        "files_changed": files_changed,
        "insertions": insertions,
        "deletions": deletions,
        "empty": files_changed == 0,
    }


def list_layer_branches(project_root: Path, layer: int) -> list[str]:
    """List branches matching */layer-{N} pattern. Returns sorted list of branch names."""
    result = _git(
        project_root,
        "for-each-ref",
        f"--format=%(refname:short)",
        f"refs/heads/*/layer-{layer}",
    )
    branches = [line for line in result.stdout.strip().splitlines() if line]
    return sorted(branches)


def is_branch_merged(project_root: Path, branch: str) -> bool:
    """Check if branch is fully merged into current HEAD (main)."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", branch, "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_merge_in_progress(project_root: Path) -> bool:
    """Check if a merge is currently in progress."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "MERGE_HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    merge_head_path = Path(result.stdout.strip())
    if not merge_head_path.is_absolute():
        merge_head_path = project_root / merge_head_path
    return merge_head_path.exists()


def merge_branch(project_root: Path, branch: str) -> dict:
    """Merge a branch into main with --no-ff.

    Returns dict with keys: success, branch, commit (if success), conflicts (if not)
    Raises WorktreeError if not on main or branch doesn't exist.
    """
    # Verify HEAD is on main
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    current = result.stdout.strip()
    if current != "main":
        raise WorktreeError(
            f"HEAD is on '{current}', expected 'main'. "
            "gotg requires the default branch to be named 'main'."
        )

    if not _branch_exists(project_root, branch):
        raise WorktreeError(f"Branch '{branch}' does not exist.")

    merge_result = subprocess.run(
        ["git", "merge", "--no-ff", "-m", f"Merge {branch} into main", branch],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    if merge_result.returncode == 0:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        return {
            "success": True,
            "branch": branch,
            "commit": commit.stdout.strip(),
        }

    # Non-zero exit: conflict or hard error?
    if is_merge_in_progress(project_root):
        conflict_result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        conflicts = [f for f in conflict_result.stdout.strip().splitlines() if f]
        return {
            "success": False,
            "branch": branch,
            "conflicts": conflicts,
        }

    # Hard error (not a conflict)
    raise WorktreeError(merge_result.stderr.strip() or f"git merge failed (exit {merge_result.returncode})")


def abort_merge(project_root: Path) -> None:
    """Abort an in-progress merge. Raises WorktreeError if no merge in progress."""
    if not is_merge_in_progress(project_root):
        raise WorktreeError("No merge in progress.")
    _git(project_root, "merge", "--abort")


MAX_DIFF_CHARS = 50_000


def format_diffs_for_prompt(project_root: Path, layer: int) -> str | None:
    """Format diffs of all layer branches for injection into agent prompts.

    Returns formatted string with stat + diff per branch, or None if no branches.
    Per-branch budget: MAX_DIFF_CHARS / num_branches. Truncates with marker if exceeded.
    """
    branches = list_layer_branches(project_root, layer)
    if not branches:
        return None

    per_branch_budget = MAX_DIFF_CHARS // len(branches)
    parts = []
    total_files = 0
    total_ins = 0
    total_del = 0

    for br in branches:
        merged = is_branch_merged(project_root, br)
        label = f" [merged]" if merged else ""
        header = f"=== {br}{label} ==="

        try:
            result = diff_branch(project_root, br, exclude_paths=SENSITIVE_PATHS)
        except WorktreeError:
            parts.append(f"{header}\n(error reading diff)")
            continue

        if result["empty"]:
            parts.append(f"{header}\n(no changes)")
            continue

        total_files += result["files_changed"]
        total_ins += result["insertions"]
        total_del += result["deletions"]

        # Always include stat
        section = f"{header}\n{result['stat'].rstrip()}"

        # Add diff within budget
        diff_text = result["diff"].rstrip()
        if len(diff_text) <= per_branch_budget:
            section += f"\n\n{diff_text}"
        else:
            # Truncate: include as many lines as fit
            lines = diff_text.splitlines()
            truncated = []
            char_count = 0
            for line in lines:
                if char_count + len(line) + 1 > per_branch_budget:
                    break
                truncated.append(line)
                char_count += len(line) + 1
            omitted = len(lines) - len(truncated)
            section += f"\n\n" + "\n".join(truncated)
            section += f"\n... ({omitted} lines omitted)"

        parts.append(section)

    summary = f"Layer {layer}: {len(branches)} branch(es), {total_files} file(s) changed, +{total_ins} -{total_del} lines"
    parts.append(summary)

    result_text = "\n\n".join(parts)

    # Global cap: if total still exceeds MAX_DIFF_CHARS, fall back to stat-only
    if len(result_text) > MAX_DIFF_CHARS:
        stat_parts = []
        for br in branches:
            merged = is_branch_merged(project_root, br)
            label = f" [merged]" if merged else ""
            header = f"=== {br}{label} ==="
            try:
                res = diff_branch(project_root, br, exclude_paths=SENSITIVE_PATHS)
            except WorktreeError:
                stat_parts.append(f"{header}\n(error reading diff)")
                continue
            if res["empty"]:
                stat_parts.append(f"{header}\n(no changes)")
            else:
                stat_parts.append(f"{header}\n{res['stat'].rstrip()}")
        stat_parts.append(f"(Diffs truncated to stat-only — total exceeded {MAX_DIFF_CHARS} chars)")
        stat_parts.append(summary)
        return "\n\n".join(stat_parts)

    return result_text


def cleanup_layer_worktrees(project_root: Path, layer: int) -> list[str]:
    """Remove all worktrees for a given layer. Returns list of removed dir names."""
    suffix = f"-layer-{layer}"
    wt_base = project_root / WORKTREE_BASE
    removed = []

    if not wt_base.exists():
        return removed

    for entry in wt_base.iterdir():
        if entry.is_dir() and entry.name.endswith(suffix):
            try:
                remove_worktree(project_root, entry)
                removed.append(entry.name)
            except WorktreeError:
                pass  # already removed or not a worktree

    return removed
