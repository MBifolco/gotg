"""Integration tests for ChatScreen code-review workflow."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gotg.events import (
    PhaseCompleteSignaled,
    SessionStarted,
)
from gotg.tui.app import GotgApp
from gotg.tui.screens.chat import ChatScreen, SessionState, PauseReason
from gotg.tui.screens.review import ReviewScreen
from gotg.tui.widgets.action_bar import ActionBar


# ── Fixtures ────────────────────────────────────────────────────


def _make_team_dir(tmp_path, phase="code-review"):
    """Create a minimal .team/ directory for ChatScreen code-review tests."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()

    team_json = {
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "coach": {"name": "coach", "role": "Agile Coach"},
        "model": {"provider": "ollama", "model": "test"},
    }
    (team_dir / "team.json").write_text(json.dumps(team_json))

    it_dir = team_dir / "iterations" / "iter-1"
    it_dir.mkdir(parents=True)
    (it_dir / "conversation.jsonl").write_text(
        json.dumps({"from": "agent-1", "content": "hello"}) + "\n"
    )

    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [{
            "id": "iter-1", "description": "Test task", "phase": phase,
            "status": "in-progress", "max_turns": 30, "current_layer": 0,
        }],
        "current": "iter-1",
    }))

    return team_dir


def _make_session_started(phase="code-review"):
    return SessionStarted(
        iteration_id="iter-1", description="Test task", phase=phase,
        current_layer=0, agents=["agent-1", "agent-2"], coach="coach",
        has_file_tools=False, writable_paths=None, worktree_count=0,
        turn=1, max_turns=30,
    )


def _setup_mock_ctx(mock_ctx_cls, team_dir):
    """Configure TeamContext mock."""
    mock_ctx = MagicMock()
    mock_ctx.team_dir = team_dir
    mock_ctx.project_root = team_dir.parent
    mock_ctx.agents = [
        {"name": "agent-1", "role": "Software Engineer"},
        {"name": "agent-2", "role": "Software Engineer"},
    ]
    mock_ctx.coach = {"name": "coach", "role": "Agile Coach"}
    mock_ctx.file_access = None
    mock_ctx.worktree_config = None

    iter_data = json.loads((team_dir / "iteration.json").read_text())
    current_id = iter_data.get("current", "iter-1")
    iteration = next(
        (it for it in iter_data.get("iterations", []) if it["id"] == current_id),
        {"id": current_id, "description": "test", "status": "in-progress",
         "max_turns": 30, "phase": "code-review", "current_layer": 0},
    )
    iter_dir = team_dir / "iterations" / current_id
    mock_ctx.iteration_store.get_current.return_value = (iteration, iter_dir)
    mock_ctx.model_config = {"provider": "ollama", "model": "test"}

    mock_ctx_cls.from_team_dir.return_value = mock_ctx
    return mock_ctx


# ── PhaseCompleteSignaled code-review specific ──────────────────


@pytest.mark.asyncio
async def test_code_review_phase_complete_shows_d_hint(tmp_path):
    """PhaseCompleteSignaled(phase='code-review') shows D keybinding, not P."""
    team_dir = _make_team_dir(tmp_path, phase="code-review")

    def mock_run_session(**kwargs):
        yield _make_session_started(phase="code-review")
        yield PhaseCompleteSignaled(phase="code-review")

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.context.TeamContext") as mock_ctx_cls:
            _setup_mock_ctx(mock_ctx_cls, team_dir)
            with patch("gotg.engine.run_session", side_effect=mock_run_session):
                await pilot.press("enter")
                await pilot.pause()

                app.screen._start_session("run")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        assert app.screen.session_state == SessionState.PAUSED
        assert app.screen._pause_reason == PauseReason.PHASE_COMPLETE

        bar = app.screen.query_one("#action-bar", ActionBar)
        content = str(bar._Static__content)
        assert "D" in content
        # Should mention "diffs" or "merge", not "advance"
        assert "diffs" in content.lower() or "merge" in content.lower() or "review" in content.lower()


@pytest.mark.asyncio
async def test_non_code_review_phase_complete_shows_p_hint(tmp_path):
    """PhaseCompleteSignaled for non-code-review phase shows P, not D."""
    team_dir = _make_team_dir(tmp_path, phase="refinement")

    def mock_run_session(**kwargs):
        yield _make_session_started(phase="refinement")
        yield PhaseCompleteSignaled(phase="refinement")

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.context.TeamContext") as mock_ctx_cls:
            _setup_mock_ctx(mock_ctx_cls, team_dir)
            with patch("gotg.engine.run_session", side_effect=mock_run_session):
                await pilot.press("enter")
                await pilot.pause()

                app.screen._start_session("run")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        bar = app.screen.query_one("#action-bar", ActionBar)
        content = str(bar._Static__content)
        assert "P" in content


# ── D keybinding guards ───────────────────────────────────────


@pytest.mark.asyncio
async def test_d_opens_review_screen_in_code_review(tmp_path):
    """Pressing D when paused at code-review phase complete opens ReviewScreen."""
    team_dir = _make_team_dir(tmp_path, phase="code-review")

    def mock_run_session(**kwargs):
        yield _make_session_started(phase="code-review")
        yield PhaseCompleteSignaled(phase="code-review")

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.context.TeamContext") as mock_ctx_cls:
            _setup_mock_ctx(mock_ctx_cls, team_dir)
            with patch("gotg.engine.run_session", side_effect=mock_run_session):
                await pilot.press("enter")
                await pilot.pause()

                app.screen._start_session("run")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        assert app.screen.session_state == SessionState.PAUSED

        from gotg.session import ReviewResult, BranchReview
        review_result = ReviewResult(
            layer=0,
            branches=[BranchReview(
                branch="agent-1/layer-0", merged=False, empty=False,
                stat="1 file", diff="+code", files_changed=1, insertions=1, deletions=0,
            )],
            total_files=1, total_insertions=1, total_deletions=0,
        )

        with patch("gotg.context.TeamContext") as mock_ctx_cls:
            _setup_mock_ctx(mock_ctx_cls, team_dir)
            with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
                await pilot.press("d")
                await pilot.pause()
                await pilot.pause()

        assert isinstance(app.screen, ReviewScreen)


@pytest.mark.asyncio
async def test_d_noop_when_not_code_review(tmp_path):
    """Pressing D when paused at non-code-review phase does nothing."""
    team_dir = _make_team_dir(tmp_path, phase="refinement")

    def mock_run_session(**kwargs):
        yield _make_session_started(phase="refinement")
        yield PhaseCompleteSignaled(phase="refinement")

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.context.TeamContext") as mock_ctx_cls:
            _setup_mock_ctx(mock_ctx_cls, team_dir)
            with patch("gotg.engine.run_session", side_effect=mock_run_session):
                await pilot.press("enter")
                await pilot.pause()

                app.screen._start_session("run")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        assert app.screen.session_state == SessionState.PAUSED

        # D should be a no-op — metadata phase is "refinement"
        await pilot.press("d")
        await pilot.pause()

        assert isinstance(app.screen, ChatScreen)


@pytest.mark.asyncio
async def test_d_noop_when_viewing(tmp_path):
    """Pressing D in VIEWING state does nothing."""
    team_dir = _make_team_dir(tmp_path, phase="code-review")
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ChatScreen)
        assert app.screen.session_state == SessionState.VIEWING

        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)
