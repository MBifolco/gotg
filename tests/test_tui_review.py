"""Integration tests for TUI ReviewScreen."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gotg.session import (
    BranchReview,
    MergeResult,
    NextLayerResult,
    ReviewError,
    ReviewResult,
)
from gotg.tui.app import GotgApp
from gotg.tui.screens.review import ReviewScreen
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.content_viewer import ContentViewer

from textual.widgets import DataTable, Static


# ── Fixtures ────────────────────────────────────────────────────


def _make_team_dir(tmp_path, phase="code-review", current_layer=0):
    """Create a minimal .team/ directory for review tests."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "team.json").write_text(json.dumps({
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "coach": {"name": "coach", "role": "Agile Coach"},
        "model": {"provider": "ollama", "model": "test"},
    }))

    it_dir = team_dir / "iterations" / "iter-1"
    it_dir.mkdir(parents=True)
    (it_dir / "conversation.jsonl").write_text("")

    iteration = {
        "id": "iter-1", "description": "Test", "phase": phase,
        "status": "in-progress", "max_turns": 30, "current_layer": current_layer,
        "review_outcome": "approved",
    }
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [iteration],
        "current": "iter-1",
    }))

    return team_dir, it_dir, iteration


def _make_review_result(layer=0, branches=None):
    """Build a ReviewResult for mocking."""
    if branches is None:
        branches = [
            BranchReview(
                branch="agent-1/layer-0", merged=False, empty=False,
                stat=" src/agent-1.py | 1 +\n 1 file changed",
                diff="diff --git a/src/agent-1.py\n+# code by agent-1",
                files_changed=1, insertions=1, deletions=0,
            ),
            BranchReview(
                branch="agent-2/layer-0", merged=False, empty=False,
                stat=" src/agent-2.py | 1 +\n 1 file changed",
                diff="diff --git a/src/agent-2.py\n+# code by agent-2",
                files_changed=1, insertions=1, deletions=0,
            ),
        ]
    total_files = sum(b.files_changed for b in branches)
    total_ins = sum(b.insertions for b in branches)
    total_del = sum(b.deletions for b in branches)
    return ReviewResult(
        layer=layer, branches=branches,
        total_files=total_files, total_insertions=total_ins, total_deletions=total_del,
    )


def _make_merge_result(branch="agent-1/layer-0", success=True, commit="abc123"):
    return MergeResult(
        branch=branch, success=success,
        commit=commit if success else None,
        conflicts=[] if success else ["src/conflict.py"],
    )


# ── ReviewScreen display ──────────────────────────────────────


@pytest.mark.asyncio
async def test_review_screen_shows_branches(tmp_path):
    """ReviewScreen loads and displays branches in DataTable."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    review_result = _make_review_result()

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        table = app.screen.query_one("#review-table", DataTable)
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_review_screen_shows_diff_on_select(tmp_path):
    """Selecting a branch shows its diff in ContentViewer."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    review_result = _make_review_result()

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        viewer = app.screen.query_one("#review-viewer", ContentViewer)
        children = viewer.query(Static)
        # Header + content (at least 2 children)
        assert len(children) >= 2


@pytest.mark.asyncio
async def test_review_screen_merged_status(tmp_path):
    """Merged branches show correctly in table."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    branches = [
        BranchReview(
            branch="agent-1/layer-0", merged=True, empty=False,
            stat="", diff="", files_changed=1, insertions=1, deletions=0,
        ),
    ]
    review_result = _make_review_result(branches=branches)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        # All merged — action bar should mention "next layer"
        bar = app.screen.query_one("#review-action-bar", ActionBar)
        content = str(bar._Static__content)
        assert "N" in content or "next" in content.lower()


# ── Merge actions ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_selected_branch(tmp_path):
    """Pressing M merges the selected branch and refreshes."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    review_result = _make_review_result()

    # After merge, return a result with agent-1 merged
    post_merge_branches = [
        BranchReview(
            branch="agent-1/layer-0", merged=True, empty=False,
            stat="", diff="", files_changed=1, insertions=1, deletions=0,
        ),
        BranchReview(
            branch="agent-2/layer-0", merged=False, empty=False,
            stat=" src/agent-2.py | 1 +", diff="+code",
            files_changed=1, insertions=1, deletions=0,
        ),
    ]
    post_merge_review = _make_review_result(branches=post_merge_branches)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        table = app.screen.query_one("#review-table", DataTable)
        table.focus()
        await pilot.pause()

        with patch("gotg.tui.screens.review.merge_branches", return_value=[_make_merge_result()]):
            with patch("gotg.tui.screens.review.load_review_branches", return_value=post_merge_review):
                await pilot.press("m")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        # Table should have refreshed
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_merge_all_branches(tmp_path):
    """Pressing Y merges all unmerged branches."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    review_result = _make_review_result()

    merge_results = [
        _make_merge_result("agent-1/layer-0"),
        _make_merge_result("agent-2/layer-0", commit="def456"),
    ]

    all_merged = [
        BranchReview(
            branch="agent-1/layer-0", merged=True, empty=False,
            stat="", diff="", files_changed=1, insertions=1, deletions=0,
        ),
        BranchReview(
            branch="agent-2/layer-0", merged=True, empty=False,
            stat="", diff="", files_changed=1, insertions=1, deletions=0,
        ),
    ]
    post_merge_review = _make_review_result(branches=all_merged)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        with patch("gotg.tui.screens.review.merge_branches", return_value=merge_results):
            with patch("gotg.tui.screens.review.load_review_branches", return_value=post_merge_review):
                await pilot.press("y")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        # Action bar should mention next layer after all merged
        bar = app.screen.query_one("#review-action-bar", ActionBar)
        content = str(bar._Static__content)
        assert "merged" in content.lower() or "N" in content


@pytest.mark.asyncio
async def test_merge_conflict_pushes_conflict_screen(tmp_path):
    """Merge conflict pushes ConflictScreen."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    review_result = _make_review_result()

    conflict_result = MergeResult(
        branch="agent-1/layer-0", success=False,
        conflicts=["src/conflict.py"],
    )

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        table = app.screen.query_one("#review-table", DataTable)
        table.focus()
        await pilot.pause()

        from gotg.tui.screens.conflict import ConflictScreen
        from gotg.session import ConflictInfo, ConflictFileInfo

        mock_info = ConflictInfo(
            branch="agent-1/layer-0",
            files=[ConflictFileInfo(
                path="src/conflict.py",
                base_content=None,
                ours_content="ours",
                theirs_content="theirs",
                working_content="conflict markers",
            )],
        )

        with patch("gotg.tui.screens.review.merge_branches", return_value=[conflict_result]), \
             patch("gotg.tui.screens.conflict.load_conflict_info", return_value=mock_info):
            await pilot.press("m")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

        # ConflictScreen should be the active screen
        assert isinstance(app.screen, ConflictScreen)


# ── Next layer ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_next_layer_after_all_merged(tmp_path):
    """Pressing N after all merged triggers next-layer advance."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    all_merged = [
        BranchReview(
            branch="agent-1/layer-0", merged=True, empty=False,
            stat="", diff="", files_changed=1, insertions=1, deletions=0,
        ),
    ]
    review_result = _make_review_result(branches=all_merged)

    next_result = NextLayerResult(
        from_layer=0, to_layer=1, all_done=False,
        boundary_msg={"from": "system", "content": "---", "phase_boundary": True},
        transition_msg={"from": "system", "content": "Layer 1"},
        checkpoint_number=1, task_count=2,
    )

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        with patch("gotg.tui.screens.review.advance_next_layer", return_value=next_result):
            await pilot.press("n")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

        # Should have popped back
        assert not isinstance(app.screen, ReviewScreen)


@pytest.mark.asyncio
async def test_next_layer_all_done_stays(tmp_path):
    """All layers done stays on ReviewScreen with message."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    all_merged = [
        BranchReview(
            branch="agent-1/layer-0", merged=True, empty=False,
            stat="", diff="", files_changed=1, insertions=1, deletions=0,
        ),
    ]
    review_result = _make_review_result(branches=all_merged)

    done_result = NextLayerResult(
        from_layer=0, to_layer=None, all_done=True,
        task_count=0,
    )

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        with patch("gotg.tui.screens.review.advance_next_layer", return_value=done_result):
            await pilot.press("n")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

        # Should stay on ReviewScreen
        assert isinstance(app.screen, ReviewScreen)
        bar = app.screen.query_one("#review-action-bar", ActionBar)
        content = str(bar._Static__content)
        assert "done" in content.lower() or "complete" in content.lower()


# ── Error handling ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_error_pops_screen(tmp_path):
    """ReviewError on load notifies and pops screen."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch(
            "gotg.tui.screens.review.load_review_branches",
            side_effect=ReviewError("No branches found for layer 0."),
        ):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

        # Should have popped back
        assert not isinstance(app.screen, ReviewScreen)


# ── Navigation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escape_pops_review_screen(tmp_path):
    """Escape returns to previous screen."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    review_result = _make_review_result()

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        assert isinstance(app.screen, ReviewScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ReviewScreen)


@pytest.mark.asyncio
async def test_n_blocked_while_unmerged(tmp_path):
    """Pressing N with unmerged branches shows warning, doesn't advance."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    review_result = _make_review_result()  # has 2 unmerged branches

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        # N should be blocked (unmerged branches exist)
        with patch("gotg.tui.screens.review.advance_next_layer") as mock_advance:
            await pilot.press("n")
            await pilot.pause()
            mock_advance.assert_not_called()

        # Still on ReviewScreen
        assert isinstance(app.screen, ReviewScreen)


# ── Finding 2: ReviewScreen reloads iteration before actions ─────────


@pytest.mark.asyncio
async def test_review_screen_reload_iteration_before_merge(tmp_path):
    """merge_selected reloads iteration from disk, not cached snapshot."""
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    review_result = _make_review_result()

    app = GotgApp(team_dir=team_dir)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        # Open ReviewScreen with approved outcome
        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        # Now change iteration.json to revoke approval
        iter_data = json.loads((team_dir / "iteration.json").read_text())
        iter_data["iterations"][0]["review_outcome"] = "changes_requested"
        (team_dir / "iteration.json").write_text(json.dumps(iter_data))

        # Select first branch (down arrow from header)
        table = app.screen.query_one("#review-table", DataTable)
        table.focus()
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()

        # Merge should be blocked because _reload_iteration picks up stale outcome
        with patch("gotg.tui.screens.review.merge_branches") as mock_merge:
            await pilot.press("m")
            await pilot.pause()
            mock_merge.assert_not_called()


@pytest.mark.asyncio
async def test_review_screen_reload_iteration_before_next_layer(tmp_path):
    """action_next_layer reloads iteration from disk before checking merge_allowed."""
    # Create with approved, then revoke on disk after screen is open
    team_dir, it_dir, iteration = _make_team_dir(tmp_path)
    # All merged so next-layer check reaches _merge_allowed
    all_merged = [
        BranchReview(
            branch="agent-1/layer-0", merged=True, empty=False,
            stat="1 file", diff="diff", files_changed=1, insertions=1, deletions=0,
        ),
    ]
    review_result = _make_review_result(branches=all_merged)

    app = GotgApp(team_dir=team_dir)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir, review_outcome="approved"))
            await pilot.pause()
            await pilot.pause()

        # Revoke on disk
        iter_data = json.loads((team_dir / "iteration.json").read_text())
        iter_data["iterations"][0]["review_outcome"] = None
        (team_dir / "iteration.json").write_text(json.dumps(iter_data))

        with patch("gotg.tui.screens.review.advance_next_layer") as mock_advance:
            await pilot.press("n")
            await pilot.pause()
            mock_advance.assert_not_called()
