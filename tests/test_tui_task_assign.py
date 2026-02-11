"""Integration tests for TUI TaskAssignScreen."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gotg.tui.app import GotgApp
from gotg.tui.screens.task_assign import TaskAssignScreen
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.content_viewer import ContentViewer

from textual.widgets import DataTable, Static


# ── Fixtures ────────────────────────────────────────────────────


AGENTS = [
    {"name": "agent-1", "role": "Software Engineer"},
    {"name": "agent-2", "role": "Software Engineer"},
]

SAMPLE_TASKS = [
    {
        "id": "task-a",
        "description": "Build the widget framework",
        "done_criteria": "Widget renders correctly",
        "depends_on": [],
        "assigned_to": None,
        "status": "pending",
        "layer": 0,
    },
    {
        "id": "task-b",
        "description": "Add styling system for widgets",
        "done_criteria": "Styles apply to all widgets",
        "depends_on": ["task-a"],
        "assigned_to": None,
        "status": "pending",
        "layer": 1,
    },
    {
        "id": "task-c",
        "description": "Write integration tests",
        "done_criteria": "All tests pass",
        "depends_on": ["task-a"],
        "assigned_to": None,
        "status": "pending",
        "layer": 1,
    },
]


def _make_team_dir(tmp_path, phase="pre-code-review"):
    """Create a minimal .team/ directory for task assign tests."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "team.json").write_text(json.dumps({
        "agents": AGENTS,
        "coach": {"name": "coach", "role": "Agile Coach"},
        "model": {"provider": "ollama", "model": "test"},
    }))

    it_dir = team_dir / "iterations" / "iter-1"
    it_dir.mkdir(parents=True)
    (it_dir / "conversation.jsonl").write_text("")

    iteration = {
        "id": "iter-1", "description": "Test", "phase": phase,
        "status": "in-progress", "max_turns": 30, "current_layer": 0,
    }
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [iteration],
        "current": "iter-1",
    }))

    return team_dir, it_dir, iteration


def _write_tasks(it_dir, tasks=None):
    """Write tasks.json to the iteration directory."""
    tasks = tasks if tasks is not None else SAMPLE_TASKS
    (it_dir / "tasks.json").write_text(json.dumps(tasks, indent=2))


# ── TaskAssignScreen display ────────────────────────────────────


@pytest.mark.asyncio
async def test_loads_tasks(tmp_path):
    """TaskAssignScreen loads tasks.json and populates DataTable."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    _write_tasks(it_dir)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(TaskAssignScreen(it_dir, AGENTS))
        await pilot.pause()

        table = app.screen.query_one("#task-table", DataTable)
        assert table.row_count == 3


@pytest.mark.asyncio
async def test_shows_detail(tmp_path):
    """Selecting a row shows task details in ContentViewer."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    _write_tasks(it_dir)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(TaskAssignScreen(it_dir, AGENTS))
        await pilot.pause()

        viewer = app.screen.query_one("#task-viewer", ContentViewer)
        children = viewer.query(Static)
        # Should have content showing task-a details
        assert len(children) >= 1


@pytest.mark.asyncio
async def test_no_tasks_file(tmp_path):
    """Screen handles missing tasks.json gracefully."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    # Don't write tasks.json

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(TaskAssignScreen(it_dir, AGENTS))
        await pilot.pause()

        bar = app.screen.query_one("#task-action-bar", ActionBar)
        content = str(bar._Static__content)
        assert "No tasks" in content


# ── Agent cycling ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cycle_agent(tmp_path):
    """Pressing 'a' cycles assignment through agents."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    _write_tasks(it_dir)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = TaskAssignScreen(it_dir, AGENTS)
        app.push_screen(screen)
        await pilot.pause()

        # Focus the table
        table = app.screen.query_one("#task-table", DataTable)
        table.focus()
        await pilot.pause()

        # First task starts unassigned (None)
        assert screen._tasks[0]["assigned_to"] is None

        # Press 'a' → assigns to agent-1
        await pilot.press("a")
        await pilot.pause()
        assert screen._tasks[0]["assigned_to"] == "agent-1"

        # Press 'a' again → assigns to agent-2
        await pilot.press("a")
        await pilot.pause()
        assert screen._tasks[0]["assigned_to"] == "agent-2"
        assert screen._dirty is True


@pytest.mark.asyncio
async def test_cycle_wraps_to_unassigned(tmp_path):
    """Cycling past the last agent returns to unassigned (None)."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    _write_tasks(it_dir)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = TaskAssignScreen(it_dir, AGENTS)
        app.push_screen(screen)
        await pilot.pause()

        table = app.screen.query_one("#task-table", DataTable)
        table.focus()
        await pilot.pause()

        # Cycle through: None → agent-1 → agent-2 → None
        await pilot.press("a")  # agent-1
        await pilot.press("a")  # agent-2
        await pilot.press("a")  # None
        await pilot.pause()
        assert screen._tasks[0]["assigned_to"] is None


# ── Auto-assign ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_assign_round_robin(tmp_path):
    """Shift+A distributes tasks evenly across agents."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    _write_tasks(it_dir)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = TaskAssignScreen(it_dir, AGENTS)
        app.push_screen(screen)
        await pilot.pause()

        table = app.screen.query_one("#task-table", DataTable)
        table.focus()
        await pilot.pause()

        await pilot.press("A")
        await pilot.pause()

        # 3 tasks, 2 agents: agent-1, agent-2, agent-1
        assert screen._tasks[0]["assigned_to"] == "agent-1"
        assert screen._tasks[1]["assigned_to"] == "agent-2"
        assert screen._tasks[2]["assigned_to"] == "agent-1"
        assert screen._dirty is True


# ── Save ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_writes_json(tmp_path):
    """Ctrl+S persists updated tasks to tasks.json."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    _write_tasks(it_dir)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = TaskAssignScreen(it_dir, AGENTS)
        app.push_screen(screen)
        await pilot.pause()

        table = app.screen.query_one("#task-table", DataTable)
        table.focus()
        await pilot.pause()

        # Auto-assign
        await pilot.press("A")
        await pilot.pause()

        # Save
        await pilot.press("ctrl+s")
        await pilot.pause()

        # Verify file was updated
        saved = json.loads((it_dir / "tasks.json").read_text())
        assert saved[0]["assigned_to"] == "agent-1"
        assert saved[1]["assigned_to"] == "agent-2"
        assert saved[2]["assigned_to"] == "agent-1"


# ── Navigation ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escape_clean_pops(tmp_path):
    """Escape without changes pops screen immediately."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    _write_tasks(it_dir)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = TaskAssignScreen(it_dir, AGENTS)
        app.push_screen(screen)
        await pilot.pause()

        assert isinstance(app.screen, TaskAssignScreen)

        await pilot.press("escape")
        await pilot.pause()

        # Should have popped back
        assert not isinstance(app.screen, TaskAssignScreen)


@pytest.mark.asyncio
async def test_escape_dirty_confirms(tmp_path):
    """Escape with unsaved changes shows ConfirmModal."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    _write_tasks(it_dir)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = TaskAssignScreen(it_dir, AGENTS)
        app.push_screen(screen)
        await pilot.pause()

        table = app.screen.query_one("#task-table", DataTable)
        table.focus()
        await pilot.pause()

        # Make a change
        await pilot.press("a")
        await pilot.pause()
        assert screen._dirty is True

        # Try to leave
        await pilot.press("escape")
        await pilot.pause()

        # ConfirmModal should be on top now
        from gotg.tui.modals.confirm import ConfirmModal
        assert isinstance(app.screen, ConfirmModal)


# ── Action bar status ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_action_bar_shows_unassigned_count(tmp_path):
    """Action bar shows count of unassigned tasks."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    _write_tasks(it_dir)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(TaskAssignScreen(it_dir, AGENTS))
        await pilot.pause()

        bar = app.screen.query_one("#task-action-bar", ActionBar)
        content = str(bar._Static__content)
        assert "3/3 unassigned" in content


@pytest.mark.asyncio
async def test_action_bar_after_auto_assign(tmp_path):
    """Action bar updates to show all assigned after auto-assign."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    _write_tasks(it_dir)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = TaskAssignScreen(it_dir, AGENTS)
        app.push_screen(screen)
        await pilot.pause()

        table = app.screen.query_one("#task-table", DataTable)
        table.focus()
        await pilot.pause()

        await pilot.press("A")
        await pilot.pause()

        bar = app.screen.query_one("#task-action-bar", ActionBar)
        content = str(bar._Static__content)
        assert "All 3 tasks assigned" in content


# ── Layers computed on the fly ──────────────────────────────────


@pytest.mark.asyncio
async def test_computes_layers_if_missing(tmp_path):
    """Tasks without layer field get layers computed automatically."""
    team_dir, it_dir, _ = _make_team_dir(tmp_path)
    tasks = [
        {
            "id": "root",
            "description": "Root task",
            "done_criteria": "Done",
            "depends_on": [],
            "assigned_to": None,
            "status": "pending",
        },
        {
            "id": "child",
            "description": "Child task",
            "done_criteria": "Done",
            "depends_on": ["root"],
            "assigned_to": None,
            "status": "pending",
        },
    ]
    _write_tasks(it_dir, tasks)

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = TaskAssignScreen(it_dir, AGENTS)
        app.push_screen(screen)
        await pilot.pause()

        # Layers should have been computed
        assert screen._tasks[0].get("layer") == 0
        assert screen._tasks[1].get("layer") == 1
