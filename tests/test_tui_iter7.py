"""Tests for TUI iteration 7: iteration lifecycle completion."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gotg.config import ITERATION_STATUSES, switch_current_iteration


# ── Shared fixture ────────────────────────────────────────────


def _make_team_dir(tmp_path, iterations=None, grooming=None, phase="code-review",
                   current_layer=0):
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


# ── Config: ITERATION_STATUSES ────────────────────────────────


def test_iteration_statuses_values():
    assert "pending" in ITERATION_STATUSES
    assert "in-progress" in ITERATION_STATUSES
    assert "done" in ITERATION_STATUSES


# ── Config: switch_current_iteration ──────────────────────────


def test_switch_current_iteration(tmp_path):
    team_dir = _make_team_dir(tmp_path, iterations=[
        {"id": "iter-1", "description": "First", "phase": "refinement",
         "status": "in-progress", "max_turns": 30},
        {"id": "iter-2", "description": "Second", "phase": "refinement",
         "status": "pending", "max_turns": 30},
    ])

    # Current should be iter-1
    data = json.loads((team_dir / "iteration.json").read_text())
    assert data["current"] == "iter-1"

    # Switch to iter-2
    switch_current_iteration(team_dir, "iter-2")
    data = json.loads((team_dir / "iteration.json").read_text())
    assert data["current"] == "iter-2"


def test_switch_current_iteration_nonexistent(tmp_path):
    team_dir = _make_team_dir(tmp_path, iterations=[
        {"id": "iter-1", "description": "First", "phase": "refinement",
         "status": "in-progress", "max_turns": 30},
    ])
    with pytest.raises(ValueError, match="not found"):
        switch_current_iteration(team_dir, "iter-99")


# ── EditIterationModal ────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_modal_submit_returns_dict():
    """EditIterationModal returns dict with all fields on submit."""
    from textual.app import App
    from textual.widgets import Input
    from gotg.tui.modals.edit_iteration import EditIterationModal

    results = []
    iteration = {"id": "iter-1", "description": "Test", "max_turns": 30, "status": "in-progress"}

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                EditIterationModal(iteration),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()

        # Verify pre-filled values
        desc = app.screen.query_one("#edit-desc", Input)
        assert desc.value == "Test"
        max_turns = app.screen.query_one("#edit-max-turns", Input)
        assert max_turns.value == "30"

        # Submit with Ctrl+S
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert len(results) == 1
    assert results[0] == {"description": "Test", "max_turns": 30, "status": "in-progress"}


@pytest.mark.asyncio
async def test_edit_modal_cancel_returns_none():
    """EditIterationModal returns None on Escape."""
    from textual.app import App
    from gotg.tui.modals.edit_iteration import EditIterationModal

    results = []
    iteration = {"id": "iter-1", "description": "Test", "max_turns": 30, "status": "pending"}

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                EditIterationModal(iteration),
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
async def test_edit_modal_empty_desc_stays_open():
    """EditIterationModal does not dismiss when description is empty."""
    from textual.app import App
    from textual.widgets import Input
    from gotg.tui.modals.edit_iteration import EditIterationModal

    results = []
    iteration = {"id": "iter-1", "description": "Test", "max_turns": 30, "status": "pending"}

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                EditIterationModal(iteration),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()

        # Clear description
        app.screen.query_one("#edit-desc", Input).value = ""
        await pilot.press("ctrl+s")
        await pilot.pause()

    # Should NOT have dismissed
    assert results == []


@pytest.mark.asyncio
async def test_edit_modal_invalid_max_turns_stays_open():
    """EditIterationModal does not dismiss when max_turns is invalid."""
    from textual.app import App
    from textual.widgets import Input
    from gotg.tui.modals.edit_iteration import EditIterationModal

    results = []
    iteration = {"id": "iter-1", "description": "Test", "max_turns": 30, "status": "pending"}

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                EditIterationModal(iteration),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()

        # Set invalid max_turns
        app.screen.query_one("#edit-max-turns", Input).value = "not-a-number"
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert results == []


@pytest.mark.asyncio
async def test_edit_modal_button_save():
    """Clicking Save button submits the form."""
    from textual.app import App
    from textual.widgets import Button
    from gotg.tui.modals.edit_iteration import EditIterationModal

    results = []
    iteration = {"id": "iter-1", "description": "Test", "max_turns": 10, "status": "done"}

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                EditIterationModal(iteration),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()

        # Click Save button
        btn = app.screen.query_one("#btn-save", Button)
        await pilot.click(btn)
        await pilot.pause()

    assert len(results) == 1
    assert results[0]["max_turns"] == 10
    assert results[0]["status"] == "done"


# ── HomeScreen: E key → EditIterationModal ────────────────────


@pytest.mark.asyncio
async def test_home_e_opens_edit_modal(tmp_path):
    """E key opens EditIterationModal (not TextInputModal)."""
    iterations = [
        {"id": "iter-1", "description": "Original", "phase": "refinement",
         "status": "in-progress", "max_turns": 30},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    from gotg.tui.app import GotgApp
    from gotg.tui.modals.edit_iteration import EditIterationModal
    from textual.widgets import DataTable

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        table = app.screen.query_one("#iter-table", DataTable)
        table.focus()
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditIterationModal)


@pytest.mark.asyncio
async def test_home_e_submit_updates_all_fields(tmp_path):
    """Saving EditIterationModal updates description, max_turns, and status on disk."""
    iterations = [
        {"id": "iter-1", "description": "Original", "phase": "refinement",
         "status": "pending", "max_turns": 30},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    from gotg.tui.app import GotgApp
    from gotg.tui.modals.edit_iteration import EditIterationModal
    from textual.widgets import DataTable, Input, Select

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        table = app.screen.query_one("#iter-table", DataTable)
        table.focus()
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditIterationModal)

        # Update fields
        app.screen.query_one("#edit-desc", Input).value = "Updated desc"
        app.screen.query_one("#edit-max-turns", Input).value = "15"
        app.screen.query_one("#edit-status", Select).value = "in-progress"

        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

        # Verify on disk
        data = json.loads((team_dir / "iteration.json").read_text())
        it = data["iterations"][0]
        assert it["description"] == "Updated desc"
        assert it["max_turns"] == 15
        assert it["status"] == "in-progress"


# ── HomeScreen: R key → switch current ────────────────────────


@pytest.mark.asyncio
async def test_home_r_switches_current(tmp_path):
    """R on a non-current iteration switches the current pointer."""
    iterations = [
        {"id": "iter-1", "description": "First", "phase": "refinement",
         "status": "in-progress", "max_turns": 30},
        {"id": "iter-2", "description": "Second", "phase": "refinement",
         "status": "in-progress", "max_turns": 30},
    ]
    team_dir = _make_team_dir(tmp_path, iterations=iterations)
    from gotg.tui.app import GotgApp
    from textual.widgets import DataTable

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        table = app.screen.query_one("#iter-table", DataTable)
        table.focus()
        await pilot.pause()

        # Move cursor to iter-2 (second row)
        await pilot.press("down")
        await pilot.pause()

        # Press R — should switch current to iter-2
        await pilot.press("R")
        await pilot.pause()
        await pilot.pause()

        # Verify current switched on disk
        data = json.loads((team_dir / "iteration.json").read_text())
        assert data["current"] == "iter-2"


@pytest.mark.asyncio
async def test_home_r_on_non_current_pending_switches_and_prompts(tmp_path):
    """R on a non-current pending iteration switches current AND prompts for description."""
    iterations = [
        {"id": "iter-1", "description": "First", "phase": "refinement",
         "status": "in-progress", "max_turns": 30},
        {"id": "iter-2", "description": "", "phase": "refinement",
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

        # Move cursor to iter-2
        await pilot.press("down")
        await pilot.pause()

        await pilot.press("R")
        await pilot.pause()
        await pilot.pause()

        # Should have switched current
        data = json.loads((team_dir / "iteration.json").read_text())
        assert data["current"] == "iter-2"

        # Should have opened TextInputModal for description
        assert isinstance(app.screen, TextInputModal)


# ── ReviewScreen: F key mark-done ─────────────────────────────


@pytest.mark.asyncio
async def test_review_f_noop_when_not_all_done(tmp_path):
    """F key does nothing when _all_layers_done is False."""
    from gotg.session import BranchReview, ReviewResult
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.review import ReviewScreen

    team_dir, it_dir, iteration = _make_review_team_dir(tmp_path)
    review_result = ReviewResult(
        layer=0,
        branches=[BranchReview(
            branch="agent-1/layer-0", merged=False, empty=False,
            stat="1 file", diff="+code", files_changed=1, insertions=1, deletions=0,
        )],
        total_files=1, total_insertions=1, total_deletions=0,
    )

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir))
            await pilot.pause()
            await pilot.pause()

        # F should be a no-op (not all done)
        await pilot.press("f")
        await pilot.pause()

        # Still on ReviewScreen
        assert isinstance(app.screen, ReviewScreen)


@pytest.mark.asyncio
async def test_review_f_marks_done_when_all_layers_complete(tmp_path):
    """F key marks iteration as done and pops screen when all_done."""
    from gotg.session import BranchReview, NextLayerResult, ReviewResult
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.review import ReviewScreen

    team_dir, it_dir, iteration = _make_review_team_dir(tmp_path)
    all_merged = [
        BranchReview(
            branch="agent-1/layer-0", merged=True, empty=False,
            stat="", diff="", files_changed=1, insertions=1, deletions=0,
        ),
    ]
    review_result = ReviewResult(
        layer=0, branches=all_merged,
        total_files=1, total_insertions=1, total_deletions=0,
    )
    done_result = NextLayerResult(
        from_layer=0, to_layer=None, all_done=True, task_count=0,
    )

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir))
            await pilot.pause()
            await pilot.pause()

        # Trigger next-layer to get all_done=True
        with patch("gotg.tui.screens.review.advance_next_layer", return_value=done_result):
            await pilot.press("n")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

        # Should still be on ReviewScreen with all_layers_done set
        assert isinstance(app.screen, ReviewScreen)
        assert app.screen._all_layers_done is True

        # Now press F to mark done
        await pilot.press("f")
        await pilot.pause()
        await pilot.pause()

        # Should have popped back
        assert not isinstance(app.screen, ReviewScreen)

        # Verify status on disk
        data = json.loads((team_dir / "iteration.json").read_text())
        assert data["iterations"][0]["status"] == "done"


@pytest.mark.asyncio
async def test_review_all_done_action_bar_shows_f_hint(tmp_path):
    """Action bar includes F key hint when all layers are complete."""
    from gotg.session import BranchReview, NextLayerResult, ReviewResult
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.review import ReviewScreen
    from gotg.tui.widgets.action_bar import ActionBar

    team_dir, it_dir, iteration = _make_review_team_dir(tmp_path)
    all_merged = [
        BranchReview(
            branch="agent-1/layer-0", merged=True, empty=False,
            stat="", diff="", files_changed=1, insertions=1, deletions=0,
        ),
    ]
    review_result = ReviewResult(
        layer=0, branches=all_merged,
        total_files=1, total_insertions=1, total_deletions=0,
    )
    done_result = NextLayerResult(
        from_layer=0, to_layer=None, all_done=True, task_count=0,
    )

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        with patch("gotg.tui.screens.review.load_review_branches", return_value=review_result):
            app.push_screen(ReviewScreen(team_dir, iteration, it_dir))
            await pilot.pause()
            await pilot.pause()

        with patch("gotg.tui.screens.review.advance_next_layer", return_value=done_result):
            await pilot.press("n")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

        bar = app.screen.query_one("#review-action-bar", ActionBar)
        content = str(bar._Static__content)
        assert "F" in content
        assert "done" in content.lower() or "mark" in content.lower()


# ── Review test helper ────────────────────────────────────────


def _make_review_team_dir(tmp_path, phase="code-review", current_layer=0):
    """Create .team/ dir for ReviewScreen tests. Returns (team_dir, it_dir, iteration)."""
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

    iteration = {
        "id": "iter-1", "description": "Test", "phase": phase,
        "status": "in-progress", "max_turns": 30, "current_layer": current_layer,
    }
    it_dir = team_dir / "iterations" / "iter-1"
    it_dir.mkdir(parents=True)
    (it_dir / "conversation.jsonl").write_text("")

    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [iteration],
        "current": "iter-1",
    }))

    return team_dir, it_dir, iteration
