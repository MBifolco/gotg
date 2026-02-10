"""Integration tests for TUI live conversation streaming."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gotg.events import (
    AppendMessage,
    CoachAskedPM,
    PauseForApprovals,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
)
from gotg.tui.app import GotgApp
from gotg.tui.screens.chat import ChatScreen, SessionState
from gotg.tui.screens.home import HomeScreen
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.info_tile import InfoTile
from gotg.tui.widgets.message_list import MessageList, MessageWidget

from textual.widgets import DataTable, Input


# ── Fixtures ────────────────────────────────────────────────────


def _make_team_dir(tmp_path, iterations=None, grooming=None):
    """Create a minimal .team/ directory for TUI testing."""
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

    iters = [dict(it) for it in (iterations or [])]
    current = iters[0]["id"] if iters else "iter-1"
    clean_iters = []
    for it in iters:
        msgs = it.pop("_messages", [])
        clean_iters.append(it)
        it_dir = team_dir / "iterations" / it["id"]
        it_dir.mkdir(parents=True)
        log = it_dir / "conversation.jsonl"
        lines = [json.dumps(m) for m in msgs]
        log.write_text("\n".join(lines) + "\n" if lines else "")

    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": clean_iters,
        "current": current,
    }))

    for g in (grooming or []):
        g = dict(g)
        groom_dir = team_dir / "grooming" / g["slug"]
        groom_dir.mkdir(parents=True)
        msgs = g.pop("_messages", [])
        (groom_dir / "grooming.json").write_text(json.dumps(g))
        log = groom_dir / "conversation.jsonl"
        lines = [json.dumps(m) for m in msgs]
        log.write_text("\n".join(lines) + "\n" if lines else "")

    return team_dir


def _default_iteration():
    return {
        "id": "iter-1", "description": "Test task", "phase": "refinement",
        "status": "in-progress", "max_turns": 30,
        "_messages": [
            {"from": "agent-1", "content": "hello"},
            {"from": "agent-2", "content": "world"},
        ],
    }


def _make_session_started():
    return SessionStarted(
        iteration_id="iter-1", description="Test task", phase="refinement",
        current_layer=None, agents=["agent-1", "agent-2"], coach="coach",
        has_file_tools=False, writable_paths=None, worktree_count=0,
        turn=2, max_turns=30,
    )


# ── ChatScreen view mode ────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_view_mode_has_input(tmp_path):
    """ChatScreen in view mode has an Input widget."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)

        inp = app.screen.query_one("#chat-input", Input)
        assert inp is not None
        assert not inp.disabled


@pytest.mark.asyncio
async def test_chat_view_mode_has_action_bar_hidden(tmp_path):
    """ActionBar is hidden in view mode."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        bar = app.screen.query_one("#action-bar", ActionBar)
        assert "visible" not in bar.classes


# ── ChatScreen live streaming ────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_streams_messages(tmp_path):
    """Messages from engine events appear as MessageWidgets."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])

    def mock_run_session(**kwargs):
        yield _make_session_started()
        yield AppendMessage({"from": "agent-1", "content": "new message 1"})
        yield AppendMessage({"from": "agent-2", "content": "new message 2"})
        yield SessionComplete(total_turns=4)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.context.TeamContext") as mock_ctx_cls:
            _setup_mock_ctx(mock_ctx_cls, team_dir)
            with patch("gotg.engine.run_session", side_effect=mock_run_session):
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, ChatScreen)

                # Press R to run
                app.screen._start_session("run")
                # Wait for worker to complete
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        msg_list = app.screen.query_one("#message-list", MessageList)
        widgets = msg_list.query(MessageWidget)
        # 2 existing + 2 new = 4
        assert len(widgets) >= 4


@pytest.mark.asyncio
async def test_chat_pause_for_approvals(tmp_path):
    """PauseForApprovals shows action bar."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])

    def mock_run_session(**kwargs):
        yield _make_session_started()
        yield PauseForApprovals(pending_count=3)

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
        bar = app.screen.query_one("#action-bar", ActionBar)
        assert "visible" in bar.classes


@pytest.mark.asyncio
async def test_chat_coach_asked_pm(tmp_path):
    """CoachAskedPM shows action bar with question."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])

    def mock_run_session(**kwargs):
        yield _make_session_started()
        yield CoachAskedPM(question="What should we focus on?")

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


@pytest.mark.asyncio
async def test_chat_phase_complete(tmp_path):
    """PhaseCompleteSignaled shows action bar."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])

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


@pytest.mark.asyncio
async def test_chat_session_complete(tmp_path):
    """SessionComplete sets state to COMPLETE."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])

    def mock_run_session(**kwargs):
        yield _make_session_started()
        yield SessionComplete(total_turns=10)

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

        assert app.screen.session_state == SessionState.COMPLETE
        bar = app.screen.query_one("#action-bar", ActionBar)
        assert "visible" in bar.classes


@pytest.mark.asyncio
async def test_chat_error_handling(tmp_path):
    """Worker errors set state back to VIEWING."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])

    app = GotgApp(team_dir)
    async with app.run_test(notifications=True) as pilot:
        await pilot.pause()

        with patch("gotg.context.TeamContext") as mock_ctx_cls:
            mock_ctx_cls.from_team_dir.side_effect = Exception("Connection failed")
            with patch("gotg.engine.run_session"):
                await pilot.press("enter")
                await pilot.pause()

                app.screen._start_session("run")
                await pilot.pause()
                await pilot.pause()
                await pilot.pause()

        assert app.screen.session_state == SessionState.VIEWING


# ── MessageList append ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_message_list_append(tmp_path):
    """append_message adds a single widget without clearing existing."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        msg_list = app.screen.query_one("#message-list", MessageList)
        initial_count = len(msg_list.query(MessageWidget))
        msg_list.append_message({"from": "agent-1", "content": "appended"})
        await pilot.pause()

        new_count = len(msg_list.query(MessageWidget))
        assert new_count == initial_count + 1


# ── ActionBar ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_action_bar_show_hide(tmp_path):
    """ActionBar visibility toggles correctly."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        bar = app.screen.query_one("#action-bar", ActionBar)
        assert "visible" not in bar.classes

        bar.show("Test message")
        await pilot.pause()
        assert "visible" in bar.classes

        bar.hide()
        await pilot.pause()
        assert "visible" not in bar.classes


# ── InfoTile live status ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_info_tile_live_status(tmp_path):
    """InfoTile live status updates correctly."""
    team_dir = _make_team_dir(tmp_path, iterations=[_default_iteration()])
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        info = app.screen.query_one("#info-tile", InfoTile)
        info.update_session_status("Running", 5)
        await pilot.pause()

        from textual.widgets import Static
        status = info.query_one("#live-status", Static)
        content = str(status._Static__content)
        assert "Running" in content
        assert "5" in content


# ── Mock helpers ─────────────────────────────────────────────────


def _setup_mock_ctx(mock_ctx_cls, team_dir):
    """Configure TeamContext mock for test sessions."""
    from unittest.mock import MagicMock
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

    # Mock iteration store
    iter_data = json.loads((team_dir / "iteration.json").read_text())
    current_id = iter_data.get("current", "iter-1")
    iteration = next(
        (it for it in iter_data.get("iterations", []) if it["id"] == current_id),
        {"id": current_id, "description": "test", "status": "in-progress", "max_turns": 30, "phase": "refinement"},
    )
    iter_dir = team_dir / "iterations" / current_id
    mock_ctx.iteration_store.get_current.return_value = (iteration, iter_dir)
    mock_ctx.model_config = {"provider": "ollama", "model": "test"}

    mock_ctx_cls.from_team_dir.return_value = mock_ctx
    return mock_ctx
