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
    for check_path in [".team", ".env"]:
        result = _sp.run(
            ["git", "ls-files", "--error-unmatch", check_path],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
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
