"""Integration tests for the TUI using Textual's Pilot."""

import json
import pytest
from pathlib import Path

from gotg.tui.app import GotgApp
from gotg.tui.screens.home import HomeScreen
from gotg.tui.screens.chat import ChatScreen
from gotg.tui.widgets.message_list import MessageList, MessageWidget
from gotg.tui.widgets.info_tile import InfoTile

from textual.widgets import DataTable, Static


# ── Fixtures ────────────────────────────────────────────────────


def _make_team_dir(tmp_path, iterations=None, grooming=None):
    """Create a minimal .team/ directory for TUI testing."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()

    # team.json
    team_json = {
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "coach": {"name": "coach", "role": "Agile Coach"},
        "model": {"provider": "ollama", "model": "test"},
    }
    (team_dir / "team.json").write_text(json.dumps(team_json))

    # iteration.json
    iters = [dict(it) for it in (iterations or [])]  # shallow copy
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

    # Create grooming sessions
    for g in (grooming or []):
        g = dict(g)  # shallow copy
        groom_dir = team_dir / "grooming" / g["slug"]
        groom_dir.mkdir(parents=True)
        msgs = g.pop("_messages", [])
        (groom_dir / "grooming.json").write_text(json.dumps(g))
        log = groom_dir / "conversation.jsonl"
        lines = [json.dumps(m) for m in msgs]
        log.write_text("\n".join(lines) + "\n" if lines else "")

    return team_dir


# ── App launch ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_app_launches_with_home_screen(tmp_path):
    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_app_quit_with_q(tmp_path):
    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")


# ── Home screen ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_home_shows_iterations(tmp_path):
    iterations = [
        {"id": "iter-1", "description": "First task", "phase": "refinement",
         "status": "in-progress", "max_turns": 30,
         "_messages": [
             {"from": "agent-1", "content": "hello"},
             {"from": "agent-2", "content": "hi"},
         ]},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#iter-table", DataTable)
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_home_shows_multiple_iterations(tmp_path):
    iterations = [
        {"id": "iter-1", "description": "First", "phase": "planning",
         "status": "complete", "max_turns": 10},
        {"id": "iter-2", "description": "Second", "phase": "refinement",
         "status": "in-progress", "max_turns": 20},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#iter-table", DataTable)
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_home_shows_grooming_sessions(tmp_path):
    grooming = [
        {"slug": "error-handling", "topic": "Error handling", "coach": False,
         "max_turns": 30, "status": "active",
         "_messages": [{"from": "agent-1", "content": "test"}]},
    ]
    team_dir = _make_team_dir(tmp_path, grooming=grooming)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#groom-table", DataTable)
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_home_empty_tables(tmp_path):
    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        iter_table = app.screen.query_one("#iter-table", DataTable)
        groom_table = app.screen.query_one("#groom-table", DataTable)
        assert iter_table.row_count == 0
        assert groom_table.row_count == 0


@pytest.mark.asyncio
async def test_home_refresh(tmp_path):
    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#iter-table", DataTable)
        assert table.row_count == 0

        # Add an iteration to disk
        data = json.loads((team_dir / "iteration.json").read_text())
        data["iterations"].append(
            {"id": "iter-1", "description": "New", "phase": "refinement",
             "status": "in-progress", "max_turns": 10}
        )
        (team_dir / "iteration.json").write_text(json.dumps(data))
        it_dir = team_dir / "iterations" / "iter-1"
        it_dir.mkdir(parents=True)
        (it_dir / "conversation.jsonl").touch()

        await pilot.press("r")
        await pilot.pause()
        assert table.row_count == 1


# ── Chat screen navigation ──────────────────────────────────────


@pytest.mark.asyncio
async def test_navigate_to_chat_and_back(tmp_path):
    iterations = [
        {"id": "iter-1", "description": "Test task", "phase": "refinement",
         "status": "in-progress", "max_turns": 30,
         "_messages": [
             {"from": "agent-1", "content": "hello world"},
             {"from": "agent-2", "content": "greetings"},
         ]},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_chat_shows_messages(tmp_path):
    iterations = [
        {"id": "iter-1", "description": "Test", "phase": "refinement",
         "status": "in-progress", "max_turns": 30,
         "_messages": [
             {"from": "agent-1", "content": "first message"},
             {"from": "agent-2", "content": "second message"},
             {"from": "coach", "content": "coach message"},
         ]},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)

        msg_list = app.screen.query_one("#message-list", MessageList)
        widgets = msg_list.query(MessageWidget)
        assert len(widgets) == 3


@pytest.mark.asyncio
async def test_chat_empty_conversation(tmp_path):
    iterations = [
        {"id": "iter-1", "description": "Empty", "phase": "refinement",
         "status": "pending", "max_turns": 10},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)

        msg_list = app.screen.query_one("#message-list", MessageList)
        widgets = msg_list.query(MessageWidget)
        assert len(widgets) == 0
        empty = msg_list.query(".msg-empty")
        assert len(empty) == 1


@pytest.mark.asyncio
async def test_chat_info_tile_present(tmp_path):
    iterations = [
        {"id": "iter-1", "description": "Build something", "phase": "planning",
         "status": "in-progress", "max_turns": 30,
         "_messages": [{"from": "agent-1", "content": "hello"}]},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)

        info = app.screen.query_one("#info-tile", InfoTile)
        children = info.query(Static)
        assert len(children) > 0


@pytest.mark.asyncio
async def test_chat_phase_boundary_styling(tmp_path):
    iterations = [
        {"id": "iter-1", "description": "Test", "phase": "planning",
         "status": "in-progress", "max_turns": 30,
         "_messages": [
             {"from": "agent-1", "content": "discussion"},
             {"from": "system", "content": "--- HISTORY BOUNDARY ---",
              "phase_boundary": True, "from_phase": "refinement", "to_phase": "planning"},
             {"from": "agent-1", "content": "planning now"},
         ]},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)

        msg_list = app.screen.query_one("#message-list", MessageList)
        boundary = msg_list.query(".phase-boundary")
        assert len(boundary) == 1


# ── cmd_ui CLI registration ─────────────────────────────────────


def test_cmd_ui_no_team_dir(tmp_path, monkeypatch):
    """cmd_ui exits with error when no .team/ directory exists."""
    monkeypatch.chdir(tmp_path)
    from gotg.cli import cmd_ui
    with pytest.raises(SystemExit):
        cmd_ui(type("Args", (), {})())
