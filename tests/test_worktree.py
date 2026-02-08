import subprocess
from pathlib import Path

import pytest

from gotg.worktree import (
    WorktreeError,
    WORKTREE_BASE,
    worktree_dir_name,
    branch_name,
    get_worktree_path,
    ensure_git_repo,
    ensure_gitignore_entries,
    create_worktree,
    commit_worktree,
    is_worktree_dirty,
    remove_worktree,
    list_active_worktrees,
    cleanup_layer_worktrees,
    diff_branch,
    list_layer_branches,
    is_branch_merged,
    is_merge_in_progress,
    merge_branch,
    abort_merge,
)


@pytest.fixture
def git_project(tmp_path):
    """Create a minimal git repo with initial commit."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "README.md").write_text("init")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    return tmp_path


# --- Naming helpers ---

def test_worktree_dir_name():
    assert worktree_dir_name("agent-1", 0) == "agent-1-layer-0"
    assert worktree_dir_name("agent-2", 3) == "agent-2-layer-3"


def test_branch_name():
    assert branch_name("agent-1", 0) == "agent-1/layer-0"
    assert branch_name("agent-2", 1) == "agent-2/layer-1"


def test_get_worktree_path(tmp_path):
    result = get_worktree_path(tmp_path, "agent-1", 0)
    assert result == tmp_path / WORKTREE_BASE / "agent-1-layer-0"


# --- ensure_git_repo ---

def test_ensure_git_repo_success(git_project):
    ensure_git_repo(git_project)  # should not raise


def test_ensure_git_repo_not_git(tmp_path):
    with pytest.raises(WorktreeError, match="Not a git repository"):
        ensure_git_repo(tmp_path)


# --- ensure_gitignore_entries ---

def test_ensure_gitignore_creates_file(tmp_path):
    ensure_gitignore_entries(tmp_path)
    content = (tmp_path / ".gitignore").read_text()
    assert "/.worktrees/" in content
    assert "/.team/" in content
    assert ".env" in content


def test_ensure_gitignore_appends(tmp_path):
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    ensure_gitignore_entries(tmp_path)
    content = (tmp_path / ".gitignore").read_text()
    assert "*.pyc" in content
    assert "/.worktrees/" in content
    assert "/.team/" in content


def test_ensure_gitignore_idempotent(tmp_path):
    ensure_gitignore_entries(tmp_path)
    ensure_gitignore_entries(tmp_path)
    content = (tmp_path / ".gitignore").read_text()
    assert content.count("/.worktrees/") == 1
    assert content.count("/.team/") == 1
    assert content.count(".env") == 1


def test_ensure_gitignore_no_trailing_newline(tmp_path):
    """Existing .gitignore without trailing newline gets newline before entry."""
    (tmp_path / ".gitignore").write_text("*.pyc")
    ensure_gitignore_entries(tmp_path)
    content = (tmp_path / ".gitignore").read_text()
    assert "*.pyc\n/.worktrees/" in content


def test_ensure_gitignore_warns_tracked_team(git_project):
    """Warns if .team/ is tracked by git."""
    (git_project / ".team").mkdir()
    (git_project / ".team" / "team.json").write_text("{}")
    subprocess.run(["git", "add", "-A"], cwd=git_project, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add team"], cwd=git_project, capture_output=True, check=True)
    warnings = ensure_gitignore_entries(git_project)
    assert any(".team" in w and "git rm" in w for w in warnings)


def test_ensure_gitignore_no_warning_untracked(git_project):
    """No warning when .team/ exists but is not tracked."""
    warnings = ensure_gitignore_entries(git_project)
    assert len(warnings) == 0


# --- create_worktree ---

def test_create_worktree_creates_dir(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    assert wt.exists()
    assert wt.is_dir()
    assert wt == git_project / WORKTREE_BASE / "agent-1-layer-0"


def test_create_worktree_creates_branch(git_project):
    create_worktree(git_project, "agent-1", 0)
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "agent-1/layer-0"],
        cwd=git_project, capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_create_worktree_contains_project_files(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    assert (wt / "README.md").read_text() == "init"
    assert (wt / "src" / "main.py").read_text() == "print('hello')"


def test_create_worktree_idempotent(git_project):
    wt1 = create_worktree(git_project, "agent-1", 0)
    wt2 = create_worktree(git_project, "agent-1", 0)
    assert wt1 == wt2


def test_create_worktree_two_agents_isolated(git_project):
    wt1 = create_worktree(git_project, "agent-1", 0)
    wt2 = create_worktree(git_project, "agent-2", 0)
    assert wt1 != wt2
    # Write in one, verify other is unaffected
    (wt1 / "src" / "agent1.py").write_text("agent 1 code")
    assert not (wt2 / "src" / "agent1.py").exists()


def test_create_worktree_branch_exists_no_worktree(git_project):
    """Case 3: branch exists but worktree was removed — attach existing branch."""
    wt = create_worktree(git_project, "agent-1", 0)
    # Write a file and commit so branch has history
    (wt / "new_file.txt").write_text("from branch")
    commit_worktree(wt, "add file")
    # Remove worktree but keep branch
    remove_worktree(git_project, wt)
    assert not wt.exists()
    # Re-create should attach existing branch
    wt2 = create_worktree(git_project, "agent-1", 0)
    assert wt2.exists()
    assert (wt2 / "new_file.txt").read_text() == "from branch"


def test_create_worktree_orphan_dir_cleaned_up(git_project):
    """Case 4: directory exists but git doesn't know about it — clean up and recreate."""
    wt_path = get_worktree_path(git_project, "agent-1", 0)
    wt_path.mkdir(parents=True)
    (wt_path / "orphan.txt").write_text("stale")
    # create_worktree should remove orphan dir and create properly
    wt = create_worktree(git_project, "agent-1", 0)
    assert wt.exists()
    assert not (wt / "orphan.txt").exists()
    assert (wt / "README.md").exists()


# --- commit_worktree ---

def test_commit_worktree_with_changes(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "new.py").write_text("new code")
    commit_hash = commit_worktree(wt, "add new.py")
    assert commit_hash is not None
    assert len(commit_hash) >= 7


def test_commit_worktree_no_changes(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    assert commit_worktree(wt, "nothing") is None


def test_commit_worktree_visible_in_log(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")
    result = subprocess.run(
        ["git", "log", "--oneline", "-1", "agent-1/layer-0"],
        cwd=git_project, capture_output=True, text=True,
    )
    assert "add feature" in result.stdout


# --- is_worktree_dirty ---

def test_is_worktree_dirty_clean(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    assert is_worktree_dirty(wt) is False


def test_is_worktree_dirty_with_changes(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "dirty.txt").write_text("uncommitted")
    assert is_worktree_dirty(wt) is True


# --- remove_worktree ---

def test_remove_worktree_cleans_up(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    assert wt.exists()
    remove_worktree(git_project, wt)
    assert not wt.exists()


def test_remove_worktree_nonexistent(git_project):
    fake = git_project / WORKTREE_BASE / "nonexistent"
    with pytest.raises(WorktreeError):
        remove_worktree(git_project, fake)


# --- list_active_worktrees ---

def test_list_active_worktrees_empty(git_project):
    assert list_active_worktrees(git_project) == []


def test_list_active_worktrees_returns_worktrees(git_project):
    create_worktree(git_project, "agent-1", 0)
    create_worktree(git_project, "agent-2", 0)
    result = list_active_worktrees(git_project)
    assert len(result) == 2
    branches = {wt["branch"] for wt in result}
    assert "agent-1/layer-0" in branches
    assert "agent-2/layer-0" in branches


def test_list_active_worktrees_excludes_main(git_project):
    create_worktree(git_project, "agent-1", 0)
    result = list_active_worktrees(git_project)
    paths = [wt["path"] for wt in result]
    assert str(git_project.resolve()) not in paths


# --- cleanup_layer_worktrees ---

def test_cleanup_layer_worktrees_removes_all(git_project):
    create_worktree(git_project, "agent-1", 0)
    create_worktree(git_project, "agent-2", 0)
    removed = cleanup_layer_worktrees(git_project, 0)
    assert len(removed) == 2
    assert not (git_project / WORKTREE_BASE / "agent-1-layer-0").exists()
    assert not (git_project / WORKTREE_BASE / "agent-2-layer-0").exists()


def test_cleanup_layer_worktrees_preserves_other_layers(git_project):
    create_worktree(git_project, "agent-1", 0)
    create_worktree(git_project, "agent-1", 1)
    removed = cleanup_layer_worktrees(git_project, 0)
    assert len(removed) == 1
    assert (git_project / WORKTREE_BASE / "agent-1-layer-1").exists()


def test_cleanup_layer_worktrees_empty(git_project):
    removed = cleanup_layer_worktrees(git_project, 0)
    assert removed == []


# --- diff_branch ---

def test_diff_branch_with_changes(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "new.py").write_text("new code")
    commit_worktree(wt, "add new.py")
    result = diff_branch(git_project, "agent-1/layer-0")
    assert result["branch"] == "agent-1/layer-0"
    assert result["files_changed"] == 1
    assert result["insertions"] > 0
    assert result["empty"] is False
    assert "new.py" in result["stat"]
    assert "new code" in result["diff"]


def test_diff_branch_empty(git_project):
    create_worktree(git_project, "agent-1", 0)
    result = diff_branch(git_project, "agent-1/layer-0")
    assert result["empty"] is True
    assert result["files_changed"] == 0
    assert result["insertions"] == 0
    assert result["deletions"] == 0


def test_diff_branch_multiple_files(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "a.py").write_text("a")
    (wt / "src" / "b.py").write_text("b")
    commit_worktree(wt, "add two files")
    result = diff_branch(git_project, "agent-1/layer-0")
    assert result["files_changed"] == 2


def test_diff_branch_modified_existing(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "main.py").write_text("modified code")
    commit_worktree(wt, "modify main.py")
    result = diff_branch(git_project, "agent-1/layer-0")
    assert result["files_changed"] == 1
    assert result["deletions"] > 0
    assert result["insertions"] > 0


def test_diff_branch_nonexistent(git_project):
    with pytest.raises(WorktreeError, match="does not exist"):
        diff_branch(git_project, "nonexistent/branch")


# --- list_layer_branches ---

def test_list_layer_branches_filters_correctly(git_project):
    create_worktree(git_project, "agent-1", 0)
    create_worktree(git_project, "agent-2", 0)
    create_worktree(git_project, "agent-1", 1)
    result = list_layer_branches(git_project, 0)
    assert result == ["agent-1/layer-0", "agent-2/layer-0"]
    result1 = list_layer_branches(git_project, 1)
    assert result1 == ["agent-1/layer-1"]


def test_list_layer_branches_empty(git_project):
    assert list_layer_branches(git_project, 0) == []


def test_list_layer_branches_includes_removed_worktrees(git_project):
    """Branches persist after worktrees are removed."""
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "file.txt").write_text("data")
    commit_worktree(wt, "add file")
    remove_worktree(git_project, wt)
    result = list_layer_branches(git_project, 0)
    assert "agent-1/layer-0" in result


# --- is_branch_merged ---

def test_is_branch_merged_false_before_merge(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")
    assert is_branch_merged(git_project, "agent-1/layer-0") is False


def test_is_branch_merged_true_after_merge(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")
    merge_branch(git_project, "agent-1/layer-0")
    assert is_branch_merged(git_project, "agent-1/layer-0") is True


# --- is_merge_in_progress ---

def test_is_merge_in_progress_false_normally(git_project):
    assert is_merge_in_progress(git_project) is False


def test_is_merge_in_progress_true_during_conflict(git_project):
    """Create a conflict so merge pauses mid-way."""
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "main.py").write_text("agent version")
    commit_worktree(wt, "agent change")
    # Change the same file on main
    (git_project / "src" / "main.py").write_text("main version")
    subprocess.run(["git", "add", "-A"], cwd=git_project, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "main change"], cwd=git_project, capture_output=True, check=True)
    # This merge should conflict
    merge_branch(git_project, "agent-1/layer-0")
    assert is_merge_in_progress(git_project) is True
    # Clean up
    subprocess.run(["git", "merge", "--abort"], cwd=git_project, capture_output=True)


# --- merge_branch ---

def test_merge_branch_clean(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature code")
    commit_worktree(wt, "add feature")
    result = merge_branch(git_project, "agent-1/layer-0")
    assert result["success"] is True
    assert result["branch"] == "agent-1/layer-0"
    assert len(result["commit"]) >= 7
    # Verify main has the file
    assert (git_project / "src" / "feature.py").read_text() == "feature code"


def test_merge_branch_conflict(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "main.py").write_text("agent version")
    commit_worktree(wt, "agent change")
    # Change same file on main
    (git_project / "src" / "main.py").write_text("main version")
    subprocess.run(["git", "add", "-A"], cwd=git_project, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "main change"], cwd=git_project, capture_output=True, check=True)
    result = merge_branch(git_project, "agent-1/layer-0")
    assert result["success"] is False
    assert "src/main.py" in result["conflicts"]
    # Clean up
    subprocess.run(["git", "merge", "--abort"], cwd=git_project, capture_output=True)


def test_merge_branch_nonexistent(git_project):
    with pytest.raises(WorktreeError, match="does not exist"):
        merge_branch(git_project, "nonexistent/branch")


def test_merge_branch_creates_merge_commit(git_project):
    """--no-ff creates a merge commit even when fast-forward is possible."""
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")
    merge_branch(git_project, "agent-1/layer-0")
    # Check last commit message contains "Merge"
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=git_project, capture_output=True, text=True,
    )
    assert "Merge" in result.stdout


def test_merge_branch_not_on_main(git_project):
    """Raises WorktreeError when HEAD is not on main."""
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")
    # Checkout a different branch
    subprocess.run(["git", "checkout", "-b", "other"], cwd=git_project, capture_output=True, check=True)
    with pytest.raises(WorktreeError, match="expected 'main'"):
        merge_branch(git_project, "agent-1/layer-0")
    # Clean up — go back to main
    subprocess.run(["git", "checkout", "main"], cwd=git_project, capture_output=True)


# --- abort_merge ---

def test_abort_merge_restores_clean_state(git_project):
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "main.py").write_text("agent version")
    commit_worktree(wt, "agent change")
    (git_project / "src" / "main.py").write_text("main version")
    subprocess.run(["git", "add", "-A"], cwd=git_project, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "main change"], cwd=git_project, capture_output=True, check=True)
    merge_branch(git_project, "agent-1/layer-0")
    assert is_merge_in_progress(git_project) is True
    abort_merge(git_project)
    assert is_merge_in_progress(git_project) is False
    assert (git_project / "src" / "main.py").read_text() == "main version"


def test_abort_merge_no_merge_in_progress(git_project):
    with pytest.raises(WorktreeError, match="No merge in progress"):
        abort_merge(git_project)


# --- format_diffs_for_prompt ---

def test_format_diffs_for_prompt_with_changes(git_project):
    """Branches with changes produce a string with diff content."""
    from gotg.worktree import format_diffs_for_prompt
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature code")
    commit_worktree(wt, "add feature")

    result = format_diffs_for_prompt(git_project, 0)
    assert result is not None
    assert "agent-1/layer-0" in result
    assert "feature.py" in result
    assert "feature code" in result


def test_format_diffs_for_prompt_empty_branches(git_project):
    """Branches with no changes show '(no changes)'."""
    from gotg.worktree import format_diffs_for_prompt
    create_worktree(git_project, "agent-1", 0)
    # No changes committed to worktree, but branch exists

    result = format_diffs_for_prompt(git_project, 0)
    assert result is not None
    assert "(no changes)" in result


def test_format_diffs_for_prompt_no_branches(git_project):
    """No branches for layer returns None."""
    from gotg.worktree import format_diffs_for_prompt
    result = format_diffs_for_prompt(git_project, 0)
    assert result is None


def test_format_diffs_for_prompt_includes_stat(git_project):
    """Output includes stat lines."""
    from gotg.worktree import format_diffs_for_prompt
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature code")
    commit_worktree(wt, "add feature")

    result = format_diffs_for_prompt(git_project, 0)
    assert "1 file changed" in result


def test_format_diffs_for_prompt_summary_line(git_project):
    """Output ends with 'Layer N:' summary."""
    from gotg.worktree import format_diffs_for_prompt
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature code")
    commit_worktree(wt, "add feature")

    result = format_diffs_for_prompt(git_project, 0)
    assert "Layer 0:" in result
    assert "branch(es)" in result


def test_format_diffs_for_prompt_large_diff_truncates(git_project):
    """Diff exceeding budget gets truncated — per-branch or global stat-only."""
    from gotg.worktree import format_diffs_for_prompt, MAX_DIFF_CHARS
    wt = create_worktree(git_project, "agent-1", 0)
    # Generate a large file that exceeds the budget
    large_content = "\n".join(f"line {i} = 'x' * 100  # padding" for i in range(2000))
    (wt / "src" / "big.py").write_text(large_content)
    commit_worktree(wt, "add big file")

    result = format_diffs_for_prompt(git_project, 0)
    assert result is not None
    # Either per-branch truncation or global stat-only fallback
    assert "omitted" in result or "stat-only" in result
    # Global cap: result should not exceed MAX_DIFF_CHARS
    assert len(result) <= MAX_DIFF_CHARS


# --- diff_branch exclude_paths ---

def test_diff_branch_exclude_paths(git_project):
    """exclude_paths should filter specified files from diff output."""
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature code")
    (wt / ".env.local").write_text("SECRET=abc")
    commit_worktree(wt, "add feature and env")

    # Without exclusion, .env.local appears
    result = diff_branch(git_project, "agent-1/layer-0")
    assert ".env.local" in result["diff"]

    # With exclusion, .env.local is filtered out
    result = diff_branch(git_project, "agent-1/layer-0", exclude_paths=[".env.*"])
    assert ".env.local" not in result["diff"]
    assert "feature.py" in result["diff"]


def test_diff_branch_exclude_paths_none(git_project):
    """exclude_paths=None should not filter anything."""
    wt = create_worktree(git_project, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature code")
    commit_worktree(wt, "add feature")

    result = diff_branch(git_project, "agent-1/layer-0", exclude_paths=None)
    assert "feature.py" in result["diff"]


# --- ensure_gitignore_entries tracked detection ---

def test_ensure_gitignore_entries_warns_tracked_files_under_dir(tmp_path):
    """Warns when files under .team/ are tracked (not just .team itself)."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    # Create and track a file under .team/
    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text("{}")
    subprocess.run(["git", "add", ".team/team.json"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    warnings = ensure_gitignore_entries(tmp_path)
    team_warnings = [w for w in warnings if ".team" in w]
    assert len(team_warnings) == 1
    assert "tracked by git" in team_warnings[0]
