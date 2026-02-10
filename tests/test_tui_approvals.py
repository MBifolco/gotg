"""Integration tests for TUI ApprovalScreen."""

import json
from pathlib import Path

import pytest

from gotg.approvals import ApprovalStore
from gotg.tui.app import GotgApp
from gotg.tui.screens.approval import ApprovalScreen
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.content_viewer import ContentViewer

from textual.widgets import DataTable, Input, Static


# ── Fixtures ────────────────────────────────────────────────────


def _make_team_dir(tmp_path):
    """Create a minimal .team/ directory."""
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
    (it_dir / "conversation.jsonl").write_text("")
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [{"id": "iter-1", "description": "test", "phase": "refinement", "status": "in-progress", "max_turns": 30}],
        "current": "iter-1",
    }))
    return team_dir


def _make_store(path, requests=None):
    """Create an ApprovalStore with pre-populated requests."""
    store = ApprovalStore(path)
    for req in (requests or []):
        store.add_request(
            req.get("path", "file.txt"),
            req.get("content", "content"),
            req.get("agent", "agent-1"),
            {},
        )
        if req.get("status") == "approved":
            store.approve(store._data["requests"][-1]["id"])
        elif req.get("status") == "denied":
            store.deny(store._data["requests"][-1]["id"], req.get("reason", ""))
    return store


# ── ApprovalScreen display ──────────────────────────────────────


@pytest.mark.asyncio
async def test_approval_screen_shows_pending(tmp_path):
    """ApprovalScreen displays pending requests in DataTable."""
    approvals_path = tmp_path / "approvals.json"
    _make_store(approvals_path, [
        {"path": "src/foo.py", "content": "print('foo')", "agent": "agent-1"},
        {"path": "src/bar.py", "content": "print('bar')", "agent": "agent-2"},
    ])

    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ApprovalScreen(approvals_path))
        await pilot.pause()

        table = app.screen.query_one("#approval-table", DataTable)
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_approval_screen_shows_all_statuses(tmp_path):
    """ApprovalScreen shows pending, approved, and denied requests."""
    approvals_path = tmp_path / "approvals.json"
    _make_store(approvals_path, [
        {"path": "pending.py", "content": "p"},
        {"path": "approved.py", "content": "a", "status": "approved"},
        {"path": "denied.py", "content": "d", "status": "denied", "reason": "nope"},
    ])

    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ApprovalScreen(approvals_path))
        await pilot.pause()

        table = app.screen.query_one("#approval-table", DataTable)
        assert table.row_count == 3


@pytest.mark.asyncio
async def test_approval_screen_content_viewer(tmp_path):
    """ContentViewer shows content of first request on load."""
    approvals_path = tmp_path / "approvals.json"
    _make_store(approvals_path, [
        {"path": "hello.py", "content": "print('hello world')", "agent": "agent-1"},
    ])

    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ApprovalScreen(approvals_path))
        await pilot.pause()

        viewer = app.screen.query_one("#content-viewer", ContentViewer)
        # Should have children (header + content)
        children = viewer.query(Static)
        assert len(children) >= 2


# ── Approve actions ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_selected(tmp_path):
    """Pressing A approves the selected pending request."""
    approvals_path = tmp_path / "approvals.json"
    _make_store(approvals_path, [
        {"path": "file.py", "content": "x", "agent": "agent-1"},
    ])

    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ApprovalScreen(approvals_path))
        await pilot.pause()

        # Focus the table and approve
        app.screen.query_one("#approval-table", DataTable).focus()
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        # Verify approved in store
        store = ApprovalStore(approvals_path)
        assert len(store.get_pending()) == 0


@pytest.mark.asyncio
async def test_approve_all(tmp_path):
    """Pressing Y approves all pending requests."""
    approvals_path = tmp_path / "approvals.json"
    _make_store(approvals_path, [
        {"path": "f1.py", "content": "a", "agent": "agent-1"},
        {"path": "f2.py", "content": "b", "agent": "agent-2"},
    ])

    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ApprovalScreen(approvals_path))
        await pilot.pause()

        app.screen.query_one("#approval-table", DataTable).focus()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        store = ApprovalStore(approvals_path)
        assert len(store.get_pending()) == 0


# ── Deny flow ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deny_with_reason(tmp_path):
    """Deny flow: D opens input, Enter submits denial with reason."""
    approvals_path = tmp_path / "approvals.json"
    _make_store(approvals_path, [
        {"path": "bad.py", "content": "evil", "agent": "agent-1"},
    ])

    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ApprovalScreen(approvals_path))
        await pilot.pause()

        app.screen.query_one("#approval-table", DataTable).focus()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        # Denial input should be visible
        denial_input = app.screen.query_one("#denial-input", Input)
        assert denial_input.display is True

        # Type reason and submit
        denial_input.value = "security risk"
        await pilot.press("enter")
        await pilot.pause()

        store = ApprovalStore(approvals_path)
        denied = [r for r in store._data["requests"] if r["status"] == "denied"]
        assert len(denied) == 1
        assert denied[0]["denial_reason"] == "security risk"


@pytest.mark.asyncio
async def test_deny_cancel_with_escape(tmp_path):
    """Escape during deny flow cancels without denying."""
    approvals_path = tmp_path / "approvals.json"
    _make_store(approvals_path, [
        {"path": "file.py", "content": "x", "agent": "agent-1"},
    ])

    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ApprovalScreen(approvals_path))
        await pilot.pause()

        app.screen.query_one("#approval-table", DataTable).focus()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        # Escape cancels the deny
        await pilot.press("escape")
        await pilot.pause()

        # Still on ApprovalScreen, request still pending
        assert isinstance(app.screen, ApprovalScreen)
        store = ApprovalStore(approvals_path)
        assert len(store.get_pending()) == 1


# ── Focus guard ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_focus_guard_blocks_actions_during_deny(tmp_path):
    """Actions a/y are no-ops while deny input is visible."""
    approvals_path = tmp_path / "approvals.json"
    _make_store(approvals_path, [
        {"path": "f1.py", "content": "a", "agent": "agent-1"},
        {"path": "f2.py", "content": "b", "agent": "agent-2"},
    ])

    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ApprovalScreen(approvals_path))
        await pilot.pause()

        app.screen.query_one("#approval-table", DataTable).focus()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        # While in deny mode, pressing 'a' and 'y' should be no-ops
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        # Cancel the deny
        await pilot.press("escape")
        await pilot.pause()

        # Both requests still pending
        store = ApprovalStore(approvals_path)
        assert len(store.get_pending()) == 2


# ── Navigation ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escape_pops_screen(tmp_path):
    """Escape returns to previous screen."""
    approvals_path = tmp_path / "approvals.json"
    _make_store(approvals_path, [
        {"path": "f.py", "content": "x", "agent": "agent-1"},
    ])

    team_dir = _make_team_dir(tmp_path)
    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ApprovalScreen(approvals_path))
        await pilot.pause()
        assert isinstance(app.screen, ApprovalScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ApprovalScreen)
