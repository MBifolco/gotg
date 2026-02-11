"""Integration tests for TUI phase advance."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gotg.events import (
    AdvanceComplete,
    AdvanceError,
    AdvanceProgress,
    AppendMessage,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
)
from gotg.session import AdvanceResult
from gotg.tui.app import GotgApp
from gotg.tui.screens.chat import ChatScreen, SessionState, PauseReason
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.info_tile import InfoTile
from gotg.tui.widgets.message_list import MessageList, MessageWidget



# ── Fixtures ────────────────────────────────────────────────────


def _make_team_dir(tmp_path, phase="refinement"):
    """Create a minimal .team/ directory for TUI advance testing."""
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
        + json.dumps({"from": "agent-2", "content": "world"}) + "\n"
    )

    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [{
            "id": "iter-1", "description": "Test task", "phase": phase,
            "status": "in-progress", "max_turns": 30,
        }],
        "current": "iter-1",
    }))

    return team_dir


def _make_session_started():
    return SessionStarted(
        iteration_id="iter-1", description="Test task", phase="refinement",
        current_layer=None, agents=["agent-1", "agent-2"], coach="coach",
        has_file_tools=False, writable_paths=None, worktree_count=0,
        turn=2, max_turns=30,
    )


def _setup_mock_ctx(mock_ctx_cls, team_dir):
    """Configure TeamContext mock for test sessions."""
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
         "max_turns": 30, "phase": "refinement"},
    )
    iter_dir = team_dir / "iterations" / current_id
    mock_ctx.iteration_store.get_current.return_value = (iteration, iter_dir)
    mock_ctx.model_config = {"provider": "ollama", "model": "test"}

    mock_ctx_cls.from_team_dir.return_value = mock_ctx
    return mock_ctx


def _make_advance_result(from_phase="refinement", to_phase="planning"):
    return AdvanceResult(
        from_phase=from_phase,
        to_phase=to_phase,
        boundary_msg={"from": "system", "content": "--- boundary ---", "phase_boundary": True},
        transition_msg={"from": "system", "content": f"Phase: {from_phase} -> {to_phase}"},
        checkpoint_number=1,
        warnings=[],
    )


# ── Phase advance from PAUSED state ─────────────────────────────


@pytest.mark.asyncio
async def test_advance_from_phase_complete(tmp_path):
    """Pressing P when paused at phase complete runs advance and transitions to VIEWING."""
    team_dir = _make_team_dir(tmp_path)

    def mock_run_session(**kwargs):
        yield _make_session_started()
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
        assert app.screen._pause_reason == PauseReason.PHASE_COMPLETE

        # Now press P to advance
        with patch("gotg.context.TeamContext") as mock_ctx_cls:
            _setup_mock_ctx(mock_ctx_cls, team_dir)
            with patch("gotg.session.advance_phase", return_value=_make_advance_result()):
                await pilot.press("p")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        assert app.screen.session_state == SessionState.VIEWING

        # Verify transition messages appear (Chatbox + PhaseMarker + Static children)
        msg_list = app.screen.query_one("#message-list", MessageList)
        children = list(msg_list.children)
        assert len(children) >= 4  # 2 existing + boundary + transition


@pytest.mark.asyncio
async def test_advance_error_returns_to_paused(tmp_path):
    """Advance error puts state back to PAUSED."""
    team_dir = _make_team_dir(tmp_path)

    def mock_run_session(**kwargs):
        yield _make_session_started()
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

        # Advance fails with PhaseAdvanceError
        from gotg.session import PhaseAdvanceError
        with patch("gotg.context.TeamContext") as mock_ctx_cls:
            _setup_mock_ctx(mock_ctx_cls, team_dir)
            with patch("gotg.session.advance_phase", side_effect=PhaseAdvanceError("Cannot advance past code-review.")):
                await pilot.press("p")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        assert app.screen.session_state == SessionState.PAUSED
        bar = app.screen.query_one("#action-bar", ActionBar)
        assert "visible" in bar.classes


@pytest.mark.asyncio
async def test_p_ignored_in_wrong_states(tmp_path):
    """P key does nothing when not paused at phase complete."""
    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ChatScreen)
        assert app.screen.session_state == SessionState.VIEWING

        # Press P in VIEWING state — nothing should happen
        await pilot.press("p")
        await pilot.pause()
        assert app.screen.session_state == SessionState.VIEWING


@pytest.mark.asyncio
async def test_advance_updates_metadata_phase(tmp_path):
    """After advance, metadata phase is updated for display."""
    team_dir = _make_team_dir(tmp_path)

    def mock_run_session(**kwargs):
        yield _make_session_started()
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

        with patch("gotg.context.TeamContext") as mock_ctx_cls:
            _setup_mock_ctx(mock_ctx_cls, team_dir)
            with patch("gotg.session.advance_phase", return_value=_make_advance_result()):
                await pilot.press("p")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        assert app.screen.metadata["phase"] == "planning"


@pytest.mark.asyncio
async def test_phase_complete_action_bar_mentions_p(tmp_path):
    """PhaseCompleteSignaled action bar text includes P keybinding."""
    team_dir = _make_team_dir(tmp_path)

    def mock_run_session(**kwargs):
        yield _make_session_started()
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
        assert "visible" in bar.classes
        content = str(bar._Static__content)
        assert "P" in content
