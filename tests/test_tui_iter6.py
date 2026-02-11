"""Tests for TUI iteration 6: helpers, modals, help overlay, HomeScreen enhancements."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gotg.tui.helpers import (
    count_jsonl_lines,
    format_size,
    get_selected_row_key,
    is_agent_turn,
    resolve_coach_name,
)


# ── helpers: count_jsonl_lines ────────────────────────────────


def test_count_jsonl_lines_normal(tmp_path):
    p = tmp_path / "test.jsonl"
    p.write_text('{"a":1}\n{"b":2}\n{"c":3}\n')
    assert count_jsonl_lines(p) == 3


def test_count_jsonl_lines_empty_file(tmp_path):
    p = tmp_path / "test.jsonl"
    p.write_text("")
    assert count_jsonl_lines(p) == 0


def test_count_jsonl_lines_nonexistent(tmp_path):
    p = tmp_path / "nope.jsonl"
    assert count_jsonl_lines(p) == 0


def test_count_jsonl_lines_blank_lines(tmp_path):
    p = tmp_path / "test.jsonl"
    p.write_text('{"a":1}\n\n{"b":2}\n  \n')
    assert count_jsonl_lines(p) == 2


# ── helpers: format_size ──────────────────────────────────────


def test_format_size_bytes():
    assert format_size(0) == "0B"
    assert format_size(512) == "512B"
    assert format_size(1023) == "1023B"


def test_format_size_kilobytes():
    assert format_size(1024) == "1.0K"
    assert format_size(2048) == "2.0K"


def test_format_size_megabytes():
    assert format_size(1024 * 1024) == "1.0M"
    assert format_size(3 * 1024 * 1024) == "3.0M"


# ── helpers: is_agent_turn ────────────────────────────────────


def test_is_agent_turn_agent():
    assert is_agent_turn({"from": "agent-1"}) is True


def test_is_agent_turn_human():
    assert is_agent_turn({"from": "human"}) is False


def test_is_agent_turn_system():
    assert is_agent_turn({"from": "system"}) is False


def test_is_agent_turn_coach():
    assert is_agent_turn({"from": "coach"}, coach_name="coach") is False


def test_is_agent_turn_coach_none():
    assert is_agent_turn({"from": "coach"}, coach_name=None) is True


# ── helpers: resolve_coach_name ───────────────────────────────


def test_resolve_coach_name_dict():
    assert resolve_coach_name({"name": "coach", "role": "Agile Coach"}) == "coach"


def test_resolve_coach_name_string():
    assert resolve_coach_name("my-coach") == "my-coach"


def test_resolve_coach_name_none():
    assert resolve_coach_name(None) is None


# ── helpers: get_selected_row_key ─────────────────────────────


@pytest.mark.asyncio
async def test_get_selected_row_key_returns_key():
    """get_selected_row_key returns the string key of the cursor row."""
    from textual.app import App
    from textual.widgets import DataTable

    class TestApp(App):
        def compose(self):
            yield DataTable(id="t", cursor_type="row")

        def on_mount(self):
            t = self.query_one("#t", DataTable)
            t.add_column("Name")
            t.add_row("Alice", key="alice")
            t.add_row("Bob", key="bob")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        t = app.query_one("#t", DataTable)
        assert get_selected_row_key(t) == "alice"


@pytest.mark.asyncio
async def test_get_selected_row_key_empty_table():
    from textual.app import App
    from textual.widgets import DataTable

    class TestApp(App):
        def compose(self):
            yield DataTable(id="t", cursor_type="row")

        def on_mount(self):
            self.query_one("#t", DataTable).add_column("Name")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        t = app.query_one("#t", DataTable)
        assert get_selected_row_key(t) is None


# ── config: create_iteration ──────────────────────────────────


def test_create_iteration(tmp_path):
    from gotg.config import create_iteration
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [], "current": None,
    }))

    result = create_iteration(team_dir, "iter-1", description="Build feature X")
    assert result["id"] == "iter-1"
    assert result["description"] == "Build feature X"
    assert result["status"] == "pending"
    assert result["phase"] == "refinement"

    # Check file was written
    data = json.loads((team_dir / "iteration.json").read_text())
    assert len(data["iterations"]) == 1
    assert data["current"] == "iter-1"

    # Check directory and log created
    assert (team_dir / "iterations" / "iter-1" / "conversation.jsonl").exists()


def test_create_iteration_duplicate_raises(tmp_path):
    from gotg.config import create_iteration
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [{"id": "iter-1", "description": "x"}], "current": "iter-1",
    }))

    with pytest.raises(ValueError, match="already exists"):
        create_iteration(team_dir, "iter-1")


def test_create_iteration_no_set_current(tmp_path):
    from gotg.config import create_iteration
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [{"id": "iter-1"}], "current": "iter-1",
    }))

    create_iteration(team_dir, "iter-2", set_current=False)
    data = json.loads((team_dir / "iteration.json").read_text())
    assert data["current"] == "iter-1"  # unchanged


# ── modals: TextInputModal ────────────────────────────────────


@pytest.mark.asyncio
async def test_text_input_modal_submit():
    """TextInputModal dismisses with value on Enter."""
    from textual.app import App
    from gotg.tui.modals.text_input import TextInputModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                TextInputModal("Enter name:", placeholder="Name..."),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        # Type text and submit
        app.screen.query_one("#modal-input").value = "test-value"
        await pilot.press("enter")
        await pilot.pause()

    assert results == ["test-value"]


@pytest.mark.asyncio
async def test_text_input_modal_cancel():
    """TextInputModal dismisses with None on Escape."""
    from textual.app import App
    from gotg.tui.modals.text_input import TextInputModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                TextInputModal("Enter name:"),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert results == [None]


@pytest.mark.asyncio
async def test_text_input_modal_empty_no_submit():
    """TextInputModal does not dismiss on Enter with empty input."""
    from textual.app import App
    from textual.widgets import Input
    from gotg.tui.modals.text_input import TextInputModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                TextInputModal("Enter name:"),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        # Press enter with empty input
        await pilot.press("enter")
        await pilot.pause()

    # Should NOT have dismissed
    assert results == []


# ── modals: ConfirmModal ──────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_modal_yes():
    """ConfirmModal dismisses with True on Y."""
    from textual.app import App
    from gotg.tui.modals.confirm import ConfirmModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                ConfirmModal("Delete this?"),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

    assert results == [True]


@pytest.mark.asyncio
async def test_confirm_modal_no():
    """ConfirmModal dismisses with False on N."""
    from textual.app import App
    from gotg.tui.modals.confirm import ConfirmModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                ConfirmModal("Delete this?"),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

    assert results == [False]


@pytest.mark.asyncio
async def test_confirm_modal_escape():
    """ConfirmModal dismisses with False on Escape."""
    from textual.app import App
    from gotg.tui.modals.confirm import ConfirmModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                ConfirmModal("Delete this?"),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert results == [False]


# ── help: collect_bindings ────────────────────────────────────


def test_collect_bindings_from_screen():
    from gotg.tui.screens.help import collect_bindings
    from textual.binding import Binding

    class FakeScreen:
        BINDINGS = [
            Binding("r", "refresh", "Refresh"),
            Binding("q", "quit", "Quit"),
        ]
        app = None

    bindings = collect_bindings(FakeScreen())
    keys = [k for k, _ in bindings]
    assert "r" in keys
    assert "q" in keys


def test_collect_bindings_format_key():
    from gotg.tui.screens.help import _format_key
    assert _format_key("escape") == "Esc"
    assert _format_key("question_mark") == "?"
    assert _format_key("r") == "r"


# ── help: HelpScreen integration ─────────────────────────────


@pytest.mark.asyncio
async def test_help_screen_opens_and_closes(tmp_path):
    """? key opens help, Escape closes it."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.home import HomeScreen
    from gotg.tui.screens.help import HelpScreen

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)

        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


# ── HomeScreen: empty states ──────────────────────────────────


@pytest.mark.asyncio
async def test_home_empty_state_iterations(tmp_path):
    """Empty state visible when no iterations exist."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        empty = app.screen.query_one("#iter-empty")
        assert empty.display is True
        table = app.screen.query_one("#iter-table")
        assert table.display is False


@pytest.mark.asyncio
async def test_home_no_empty_state_with_iterations(tmp_path):
    """Empty state hidden when iterations exist."""
    iterations = [
        {"id": "iter-1", "description": "First", "phase": "refinement",
         "status": "in-progress", "max_turns": 30},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    from gotg.tui.app import GotgApp

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        empty = app.screen.query_one("#iter-empty")
        assert empty.display is False
        table = app.screen.query_one("#iter-table")
        assert table.display is True


# ── HomeScreen: Info tab ──────────────────────────────────────


@pytest.mark.asyncio
async def test_home_info_tab_shows_project_info(tmp_path):
    """Info tab displays model and agent info."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from textual.widgets import Static

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        info = app.screen.query_one("#info-content", Static)
        content = str(info._Static__content)
        assert "ollama" in content
        assert "agent-1" in content


# ── HomeScreen: N key — new iteration ─────────────────────────


@pytest.mark.asyncio
async def test_home_n_creates_iteration(tmp_path):
    """Pressing N opens TextInputModal, submitting creates iteration."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.modals.text_input import TextInputModal

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        # Press N — should open modal
        await pilot.press("n")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, TextInputModal)

        # Type description and submit
        app.screen.query_one("#modal-input").value = "Build a REST API"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        # Verify iteration was created
        data = json.loads((team_dir / "iteration.json").read_text())
        ids = [it["id"] for it in data["iterations"]]
        assert "iter-1" in ids
        created = next(it for it in data["iterations"] if it["id"] == "iter-1")
        assert created["description"] == "Build a REST API"


@pytest.mark.asyncio
async def test_home_n_cancel_does_nothing(tmp_path):
    """Pressing N then Escape creates no iteration."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.modals.text_input import TextInputModal

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("n")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, TextInputModal)

        await pilot.press("escape")
        await pilot.pause()

        data = json.loads((team_dir / "iteration.json").read_text())
        assert len(data["iterations"]) == 0


# ── HomeScreen: E key — edit iteration ────────────────────────


@pytest.mark.asyncio
async def test_home_e_edits_iteration(tmp_path):
    """Pressing E opens EditIterationModal with current values, saving updates them."""
    iterations = [
        {"id": "iter-1", "description": "Original desc", "phase": "refinement",
         "status": "in-progress", "max_turns": 30},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    from gotg.tui.app import GotgApp
    from gotg.tui.modals.edit_iteration import EditIterationModal
    from textual.widgets import DataTable, Input

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        # Focus table and press E
        table = app.screen.query_one("#iter-table", DataTable)
        table.focus()
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditIterationModal)

        # Verify initial values are pre-filled
        desc_input = app.screen.query_one("#edit-desc", Input)
        assert desc_input.value == "Original desc"

        # Update description and save via Ctrl+S
        desc_input.value = "Updated description"
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

        # Verify update on disk
        data = json.loads((team_dir / "iteration.json").read_text())
        assert data["iterations"][0]["description"] == "Updated description"


# ── HomeScreen: on_screen_resume refresh ──────────────────────


@pytest.mark.asyncio
async def test_home_refreshes_on_screen_resume(tmp_path):
    """HomeScreen reloads data when returning from pushed screen."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.home import HomeScreen
    from gotg.tui.screens.help import HelpScreen

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#iter-table")
        assert table.row_count == 0

        # Add iteration to disk while on help screen
        await pilot.press("question_mark")
        await pilot.pause()

        data = json.loads((team_dir / "iteration.json").read_text())
        data["iterations"].append(
            {"id": "iter-1", "description": "New", "phase": "refinement",
             "status": "in-progress", "max_turns": 10}
        )
        (team_dir / "iteration.json").write_text(json.dumps(data))
        it_dir = team_dir / "iterations" / "iter-1"
        it_dir.mkdir(parents=True)
        (it_dir / "conversation.jsonl").touch()

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.screen.query_one("#iter-table").row_count == 1


# ── HomeScreen: start pending iteration ───────────────────────


@pytest.mark.asyncio
async def test_run_pending_with_description_starts(tmp_path):
    """R on a pending iteration with description sets status and starts."""
    iterations = [
        {"id": "iter-1", "description": "Has description", "phase": "refinement",
         "status": "pending", "max_turns": 30},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.chat import ChatScreen
    from textual.widgets import DataTable

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        table = app.screen.query_one("#iter-table", DataTable)
        table.focus()
        await pilot.pause()

        await pilot.press("R")
        await pilot.pause()
        await pilot.pause()

        # Should have pushed ChatScreen (not modal)
        assert isinstance(app.screen, ChatScreen)

        # Status should have been updated
        data = json.loads((team_dir / "iteration.json").read_text())
        assert data["iterations"][0]["status"] == "in-progress"


@pytest.mark.asyncio
async def test_run_pending_without_description_prompts(tmp_path):
    """R on a pending iteration without description opens TextInputModal."""
    iterations = [
        {"id": "iter-1", "description": "", "phase": "refinement",
         "status": "pending", "max_turns": 30},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    from gotg.tui.app import GotgApp
    from gotg.tui.modals.text_input import TextInputModal
    from textual.widgets import DataTable

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        table = app.screen.query_one("#iter-table", DataTable)
        table.focus()
        await pilot.pause()

        await pilot.press("R")
        await pilot.pause()
        await pilot.pause()

        # Should show TextInputModal
        assert isinstance(app.screen, TextInputModal)


# ── Shared fixture ────────────────────────────────────────────


def _make_team_dir(tmp_path, iterations=None, grooming=None):
    """Create a minimal .team/ directory for testing."""
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
