"""Unit tests for session.py review/merge/next-layer/conflict bridge functions."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from gotg.session import (
    AiResolutionResult,
    BranchReview,
    ConflictFileInfo,
    ConflictInfo,
    MergeResult,
    NextLayerResult,
    ResolutionStrategy,
    ReviewError,
    ReviewResult,
    ai_resolve_conflict,
    finalize_merge,
    load_conflict_info,
    load_review_branches,
    merge_branches,
    resolve_conflict_file,
    validate_next_layer,
    advance_next_layer,
)


# ── Helpers ────────────────────────────────────────────────────


def _git_init(path):
    """Initialize a git repo with initial commit."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, capture_output=True, check=True)
    (path / "src").mkdir()
    (path / "src" / "main.py").write_text("print('hello')")
    (path / ".gitignore").write_text("/.team/\n/.worktrees/\n.env\n")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True)


def _make_team_dir(tmp_path, phase="code-review", current_layer=0, tasks=None):
    """Create .team/ dir for review/merge/next-layer tests."""
    _git_init(tmp_path)

    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text(json.dumps({
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "coach": {"name": "coach", "role": "Agile Coach"},
        "model": {"provider": "ollama", "model": "test", "base_url": "http://localhost:11434"},
    }))

    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    if tasks is None:
        tasks = [
            {"id": "T1", "description": "Task 1", "layer": 0,
             "status": "done", "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
            {"id": "T2", "description": "Task 2", "layer": 1,
             "status": "todo", "assigned_to": "agent-1", "depends_on": ["T1"], "done_criteria": "done"},
        ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    iteration = {
        "id": "iter-1", "description": "Test", "status": "in-progress",
        "phase": phase, "max_turns": 10, "current_layer": current_layer,
    }
    (team / "iteration.json").write_text(json.dumps({
        "iterations": [iteration],
        "current": "iter-1",
    }))

    return team, iter_dir, iteration


def _create_branch_with_changes(tmp_path, agent_name, layer=0):
    """Create a worktree branch with committed changes."""
    from gotg.worktree import create_worktree, commit_worktree
    wt = create_worktree(tmp_path, agent_name, layer)
    (wt / "src" / f"{agent_name}.py").write_text(f"# code by {agent_name}")
    commit_worktree(wt, f"add {agent_name} code")
    return wt


# ── load_review_branches ──────────────────────────────────────


def test_load_review_branches_returns_branch_data(tmp_path):
    """Returns BranchReview list with diff data."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    _create_branch_with_changes(tmp_path, "agent-1", 0)

    result = load_review_branches(team, iteration)
    assert isinstance(result, ReviewResult)
    assert result.layer == 0
    assert len(result.branches) == 1
    assert result.branches[0].branch == "agent-1/layer-0"
    assert not result.branches[0].merged
    assert not result.branches[0].empty
    assert result.branches[0].files_changed >= 1
    assert "agent-1.py" in result.branches[0].stat


def test_load_review_branches_multiple_branches(tmp_path):
    """Returns data for all branches in the layer."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    _create_branch_with_changes(tmp_path, "agent-1", 0)
    _create_branch_with_changes(tmp_path, "agent-2", 0)

    result = load_review_branches(team, iteration)
    assert len(result.branches) == 2
    names = [b.branch for b in result.branches]
    assert "agent-1/layer-0" in names
    assert "agent-2/layer-0" in names
    assert result.total_files >= 2


def test_load_review_branches_shows_merged_status(tmp_path):
    """Merged branches are flagged correctly."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    _create_branch_with_changes(tmp_path, "agent-1", 0)

    # Merge the branch
    from gotg.worktree import merge_branch
    merge_branch(tmp_path, "agent-1/layer-0")

    result = load_review_branches(team, iteration)
    assert result.branches[0].merged is True


def test_load_review_branches_no_branches_raises(tmp_path):
    """Raises ReviewError when no branches found for layer."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    # No branches created

    with pytest.raises(ReviewError, match="No branches found"):
        load_review_branches(team, iteration)


def test_load_review_branches_not_git_repo_raises(tmp_path):
    """Raises ReviewError when not a git repo."""
    team = tmp_path / ".team"
    team.mkdir()
    iteration = {"current_layer": 0}

    with pytest.raises(ReviewError):
        load_review_branches(team, iteration)


def test_load_review_branches_respects_layer_override(tmp_path):
    """layer_override takes precedence over iteration state."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, current_layer=0)
    _create_branch_with_changes(tmp_path, "agent-1", 1)

    # Default layer=0 would find no branches, but override layer=1
    result = load_review_branches(team, iteration, layer_override=1)
    assert result.layer == 1
    assert len(result.branches) == 1


# ── merge_branches ────────────────────────────────────────────


def test_merge_single_branch_success(tmp_path):
    """Merge a single branch returns success with commit hash."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    _create_branch_with_changes(tmp_path, "agent-1", 0)

    results = merge_branches(tmp_path, layer=0, branches=["agent-1/layer-0"])
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].commit is not None
    assert results[0].branch == "agent-1/layer-0"

    # Verify file exists on main
    assert (tmp_path / "src" / "agent-1.py").exists()


def test_merge_all_branches(tmp_path):
    """Merge all unmerged branches for a layer."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    _create_branch_with_changes(tmp_path, "agent-1", 0)
    _create_branch_with_changes(tmp_path, "agent-2", 0)

    results = merge_branches(tmp_path, layer=0)
    assert len(results) == 2
    assert all(r.success for r in results)


def test_merge_stops_on_conflict(tmp_path):
    """Merge stops on first conflict, returns partial results."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    _create_branch_with_changes(tmp_path, "agent-1", 0)

    # Create a conflicting branch
    from gotg.worktree import create_worktree, commit_worktree
    wt2 = create_worktree(tmp_path, "agent-2", 0)
    # Write to same file as agent-1
    (wt2 / "src" / "agent-1.py").write_text("# conflicting code")
    commit_worktree(wt2, "conflicting change")

    # Merge agent-1 first so agent-2 conflicts
    merge_branches(tmp_path, layer=0, branches=["agent-1/layer-0"])

    # Now try merging agent-2 — conflict
    from gotg.worktree import abort_merge
    results = merge_branches(tmp_path, layer=0, branches=["agent-2/layer-0"])
    assert len(results) == 1
    assert results[0].success is False
    assert len(results[0].conflicts) >= 1

    # Clean up merge state
    abort_merge(tmp_path)


def test_merge_raises_on_merge_in_progress(tmp_path):
    """Raises ReviewError when a merge is already in progress."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    _create_branch_with_changes(tmp_path, "agent-1", 0)

    # Create conflict to leave merge in progress
    from gotg.worktree import create_worktree, commit_worktree
    wt2 = create_worktree(tmp_path, "agent-2", 0)
    (wt2 / "src" / "agent-1.py").write_text("# conflict")
    commit_worktree(wt2, "conflict")

    merge_branches(tmp_path, layer=0, branches=["agent-1/layer-0"])
    # Start conflicting merge manually
    subprocess.run(
        ["git", "merge", "--no-ff", "agent-2/layer-0"],
        cwd=tmp_path, capture_output=True,
    )

    with pytest.raises(ReviewError, match="merge is already in progress"):
        merge_branches(tmp_path, layer=0, branches=["agent-1/layer-0"])

    # Cleanup
    from gotg.worktree import abort_merge
    abort_merge(tmp_path)


def test_merge_raises_on_dirty_main(tmp_path):
    """Raises ReviewError when main has uncommitted changes."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    _create_branch_with_changes(tmp_path, "agent-1", 0)

    # Dirty the main worktree
    (tmp_path / "src" / "main.py").write_text("dirty")

    with pytest.raises(ReviewError, match="uncommitted changes on main"):
        merge_branches(tmp_path, layer=0, branches=["agent-1/layer-0"])


def test_merge_auto_commits_dirty_worktrees(tmp_path):
    """Dirty worktrees are auto-committed before merge (not rejected)."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    wt = _create_branch_with_changes(tmp_path, "agent-1", 0)

    # Dirty the worktree after initial commit (simulates code-review writes)
    (wt / "src" / "extra.py").write_text("# added during code review")

    progress_msgs = []
    results = merge_branches(
        tmp_path, layer=0, branches=["agent-1/layer-0"],
        on_progress=progress_msgs.append,
    )
    assert len(results) == 1
    assert results[0].success is True
    # Auto-commit progress message should appear
    assert any("Auto-committing" in m for m in progress_msgs)
    # File should be on main after merge
    assert (tmp_path / "src" / "extra.py").exists()


def test_merge_calls_on_progress(tmp_path):
    """on_progress callback is called per branch."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    _create_branch_with_changes(tmp_path, "agent-1", 0)

    progress_msgs = []
    merge_branches(
        tmp_path, layer=0, branches=["agent-1/layer-0"],
        on_progress=progress_msgs.append,
    )
    assert len(progress_msgs) >= 1
    assert "agent-1/layer-0" in progress_msgs[0]


def test_merge_skips_already_merged(tmp_path):
    """Discover mode skips already-merged branches."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    _create_branch_with_changes(tmp_path, "agent-1", 0)
    _create_branch_with_changes(tmp_path, "agent-2", 0)

    # Merge agent-1 first
    merge_branches(tmp_path, layer=0, branches=["agent-1/layer-0"])

    # Now merge all — should only merge agent-2
    results = merge_branches(tmp_path, layer=0)
    assert len(results) == 1
    assert results[0].branch == "agent-2/layer-0"


# ── validate_next_layer ───────────────────────────────────────


def test_validate_next_layer_success(tmp_path):
    """Returns (current_layer, next_layer) when valid."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    current, next_l = validate_next_layer(team, iteration, iter_dir)
    assert current == 0
    assert next_l == 1


def test_validate_next_layer_wrong_phase(tmp_path):
    """Raises ReviewError when not in implementation or code-review phase."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, phase="planning")
    with pytest.raises(ReviewError, match="implementation or code-review"):
        validate_next_layer(team, iteration, iter_dir)


def test_validate_next_layer_implementation_phase(tmp_path):
    """Accepts implementation phase for next-layer."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, phase="implementation")
    current, next_l = validate_next_layer(team, iteration, iter_dir)
    assert current == 0
    assert next_l == 1


def test_validate_next_layer_wrong_status(tmp_path):
    """Raises ReviewError when status is not in-progress."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    iteration["status"] = "done"
    with pytest.raises(ReviewError, match="in-progress"):
        validate_next_layer(team, iteration, iter_dir)


# ── advance_next_layer ────────────────────────────────────────


def test_advance_next_layer_success(tmp_path):
    """Advances to next layer, writes boundary + transition messages."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)

    result = advance_next_layer(team, iteration, iter_dir)
    assert isinstance(result, NextLayerResult)
    assert result.from_layer == 0
    assert result.to_layer == 1
    assert result.all_done is False
    assert result.task_count == 1
    assert result.boundary_msg is not None
    assert result.transition_msg is not None

    # Verify iteration.json updated
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "implementation"
    assert data["iterations"][0]["current_layer"] == 1

    # Verify conversation log has boundary + transition
    from gotg.conversation import read_log
    messages = read_log(iter_dir / "conversation.jsonl")
    assert len(messages) == 2
    assert messages[0].get("phase_boundary") is True
    assert "layer 1" in messages[1]["content"].lower()


def test_advance_next_layer_all_done(tmp_path):
    """Returns all_done=True when no more layers."""
    tasks = [
        {"id": "T1", "description": "Task 1", "layer": 0,
         "status": "done", "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
    ]
    team, iter_dir, iteration = _make_team_dir(tmp_path, tasks=tasks)

    result = advance_next_layer(team, iteration, iter_dir)
    assert result.all_done is True
    assert result.to_layer is None

    # Phase should NOT have changed
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "code-review"


def test_advance_next_layer_auto_checkpoints(tmp_path):
    """Creates an auto checkpoint on advance."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)

    result = advance_next_layer(team, iteration, iter_dir)
    assert result.checkpoint_number is not None

    cp_dir = iter_dir / "checkpoints"
    assert cp_dir.exists()
    assert len(list(cp_dir.iterdir())) >= 1


def test_advance_next_layer_calls_on_progress(tmp_path):
    """on_progress callback receives step messages."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)

    progress_msgs = []
    advance_next_layer(team, iteration, iter_dir, on_progress=progress_msgs.append)
    assert len(progress_msgs) >= 1
    assert any("layer" in m.lower() for m in progress_msgs)


def test_advance_next_layer_wrong_phase(tmp_path):
    """Raises ReviewError when not in implementation or code-review."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, phase="planning")
    with pytest.raises(ReviewError, match="implementation or code-review"):
        advance_next_layer(team, iteration, iter_dir)


# ── Conflict resolution helpers ───────────────────────────────


def _create_merge_conflict(tmp_path):
    """Create a merge conflict and return (project_root, branch_name, conflict_paths).

    Leaves the repo in conflict state (MERGE_HEAD exists).
    """
    # Create branch with changes
    subprocess.run(
        ["git", "checkout", "-b", "agent-1/layer-0"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    (tmp_path / "src" / "main.py").write_text("# branch version\nprint('from branch')")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "branch change"], cwd=tmp_path, capture_output=True, check=True)

    # Back to main, make conflicting change
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "src" / "main.py").write_text("# main version\nprint('from main')")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "main change"], cwd=tmp_path, capture_output=True, check=True)

    # Attempt merge — will conflict
    subprocess.run(
        ["git", "merge", "--no-ff", "agent-1/layer-0"],
        cwd=tmp_path, capture_output=True,
    )
    return tmp_path, "agent-1/layer-0", ["src/main.py"]


# ── load_conflict_info ────────────────────────────────────────


def test_load_conflict_info_returns_stages(tmp_path):
    """Loads 3-way content for all conflicted files."""
    team, _, _ = _make_team_dir(tmp_path)
    root, branch, paths = _create_merge_conflict(tmp_path)

    info = load_conflict_info(root, branch, paths)
    assert isinstance(info, ConflictInfo)
    assert info.branch == branch
    assert len(info.files) == 1
    f = info.files[0]
    assert f.path == "src/main.py"
    assert "from main" in f.ours_content
    assert "from branch" in f.theirs_content
    assert "<<<<<<" in f.working_content  # conflict markers

    # Clean up merge state
    from gotg.worktree import abort_merge
    abort_merge(root)


def test_load_conflict_info_base_none_for_add_add(tmp_path):
    """base_content is None for add/add conflicts."""
    team, _, _ = _make_team_dir(tmp_path)

    # Create add/add conflict
    subprocess.run(
        ["git", "checkout", "-b", "agent-1/layer-0"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    (tmp_path / "src" / "new.py").write_text("# branch version")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "branch add"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "src" / "new.py").write_text("# main version")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "main add"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "merge", "--no-ff", "agent-1/layer-0"],
        cwd=tmp_path, capture_output=True,
    )

    info = load_conflict_info(tmp_path, "agent-1/layer-0", ["src/new.py"])
    assert info.files[0].base_content is None

    from gotg.worktree import abort_merge
    abort_merge(tmp_path)


# ── resolve_conflict_file ─────────────────────────────────────


def test_resolve_conflict_file_ours(tmp_path):
    """Resolves with ours strategy."""
    team, _, _ = _make_team_dir(tmp_path)
    root, branch, paths = _create_merge_conflict(tmp_path)

    resolve_conflict_file(root, "src/main.py", ResolutionStrategy.OURS)
    content = (root / "src" / "main.py").read_text()
    assert "from main" in content

    from gotg.worktree import abort_merge
    abort_merge(root)


def test_resolve_conflict_file_theirs(tmp_path):
    """Resolves with theirs strategy."""
    team, _, _ = _make_team_dir(tmp_path)
    root, branch, paths = _create_merge_conflict(tmp_path)

    resolve_conflict_file(root, "src/main.py", ResolutionStrategy.THEIRS)
    content = (root / "src" / "main.py").read_text()
    assert "from branch" in content

    from gotg.worktree import abort_merge
    abort_merge(root)


def test_resolve_conflict_file_ai_requires_content(tmp_path):
    """AI strategy raises without content."""
    team, _, _ = _make_team_dir(tmp_path)
    root, branch, paths = _create_merge_conflict(tmp_path)

    with pytest.raises(ReviewError, match="requires content"):
        resolve_conflict_file(root, "src/main.py", ResolutionStrategy.AI)

    from gotg.worktree import abort_merge
    abort_merge(root)


def test_resolve_conflict_file_ai_with_content(tmp_path):
    """AI strategy writes content and stages."""
    team, _, _ = _make_team_dir(tmp_path)
    root, branch, paths = _create_merge_conflict(tmp_path)

    resolve_conflict_file(root, "src/main.py", ResolutionStrategy.AI, content="# merged")
    content = (root / "src" / "main.py").read_text()
    assert content == "# merged"

    from gotg.worktree import abort_merge
    abort_merge(root)


# ── ai_resolve_conflict ──────────────────────────────────────


def test_ai_resolve_conflict_success():
    """Returns AiResolutionResult on success."""
    import json as _json

    def mock_chat(**kwargs):
        return _json.dumps({"content": "resolved code", "explanation": "Combined both"})

    result = ai_resolve_conflict(
        "src/main.py", "agent-1/layer-0",
        base_content="original", ours_content="ours", theirs_content="theirs",
        task_context="Build feature X",
        model_config={"provider": "ollama", "base_url": "http://localhost:11434", "model": "test"},
        chat_call=mock_chat,
    )
    assert isinstance(result, AiResolutionResult)
    assert result.path == "src/main.py"
    assert result.resolved_content == "resolved code"
    assert result.explanation == "Combined both"


def test_ai_resolve_conflict_raises_on_bad_response():
    """Raises ReviewError when LLM returns unparseable response."""
    def mock_chat(**kwargs):
        return "I cannot resolve this conflict."

    with pytest.raises(ReviewError, match="AI resolution failed"):
        ai_resolve_conflict(
            "src/main.py", "agent-1/layer-0",
            None, "ours", "theirs", "ctx",
            {"provider": "ollama", "base_url": "http://localhost:11434", "model": "test"},
            mock_chat,
        )


# ── finalize_merge ────────────────────────────────────────────


def test_finalize_merge_success(tmp_path):
    """Returns MergeResult on successful completion."""
    team, _, _ = _make_team_dir(tmp_path)
    root, branch, paths = _create_merge_conflict(tmp_path)

    # Resolve the conflict first
    from gotg.worktree import resolve_conflict_ours
    resolve_conflict_ours(root, "src/main.py")

    result = finalize_merge(root, branch)
    assert isinstance(result, MergeResult)
    assert result.success is True
    assert result.commit is not None
    assert result.branch == branch


def test_finalize_merge_raises_with_unresolved(tmp_path):
    """Raises ReviewError when conflicts remain."""
    team, _, _ = _make_team_dir(tmp_path)
    root, branch, _ = _create_merge_conflict(tmp_path)

    with pytest.raises(ReviewError, match="Failed to complete merge"):
        finalize_merge(root, branch)

    from gotg.worktree import abort_merge
    abort_merge(root)
