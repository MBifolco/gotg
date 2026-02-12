"""Tests for the ConflictScreen TUI component."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

textual = pytest.importorskip("textual")

from textual.app import App

from gotg.session import (
    AiResolutionResult,
    ConflictFileInfo,
    ConflictInfo,
    MergeResult,
    ResolutionStrategy,
    ReviewError,
)
from gotg.tui.screens.conflict import ConflictScreen, _State
from gotg.tui.widgets.action_bar import ActionBar


# ── Helpers ──────────────────────────────────────────────────


def _make_app(screen):
    class TestApp(App):
        CSS_PATH = None

        def on_mount(self):
            self.push_screen(screen)

    return TestApp()


def _bar_text(bar):
    return str(bar._Static__content)


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def conflict_info():
    return ConflictInfo(
        branch="agent-1/layer-0",
        files=[
            ConflictFileInfo(
                path="src/main.py",
                base_content="original",
                ours_content="# main version",
                theirs_content="# branch version",
                working_content="<<<<<<< HEAD\n# main\n=======\n# branch\n>>>>>>> agent-1",
            ),
        ],
    )


# ── Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conflict_screen_loads_and_shows_table(conflict_info):
    """ConflictScreen shows conflict files in table after load."""
    screen = ConflictScreen(
        Path("/fake"), "agent-1/layer-0", ["src/main.py"],
        Path("/fake/.team"), "task context",
    )

    with patch("gotg.tui.screens.conflict.load_conflict_info", return_value=conflict_info):
        app = _make_app(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

            assert screen._state == _State.BROWSING
            assert len(screen._file_map) == 1
            assert "src/main.py" in screen._file_map

            bar = screen.query_one("#conflict-action-bar", ActionBar)
            assert "1/1 unresolved" in _bar_text(bar)


@pytest.mark.asyncio
async def test_conflict_screen_resolve_ours(conflict_info):
    """Pressing O resolves selected file with ours strategy."""
    screen = ConflictScreen(
        Path("/fake"), "agent-1/layer-0", ["src/main.py"],
        Path("/fake/.team"), "task context",
    )

    with patch("gotg.tui.screens.conflict.load_conflict_info", return_value=conflict_info), \
         patch("gotg.tui.screens.conflict.resolve_conflict_file") as mock_resolve:
        app = _make_app(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

            await pilot.press("o")
            await pilot.pause()

            mock_resolve.assert_called_once_with(
                Path("/fake"), "src/main.py", ResolutionStrategy.OURS,
            )
            assert screen._resolutions["src/main.py"] == ResolutionStrategy.OURS

            bar = screen.query_one("#conflict-action-bar", ActionBar)
            assert "All 1 file(s) resolved" in _bar_text(bar)


@pytest.mark.asyncio
async def test_conflict_screen_resolve_theirs(conflict_info):
    """Pressing T resolves selected file with theirs strategy."""
    screen = ConflictScreen(
        Path("/fake"), "agent-1/layer-0", ["src/main.py"],
        Path("/fake/.team"), "task context",
    )

    with patch("gotg.tui.screens.conflict.load_conflict_info", return_value=conflict_info), \
         patch("gotg.tui.screens.conflict.resolve_conflict_file") as mock_resolve:
        app = _make_app(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

            await pilot.press("t")
            await pilot.pause()

            mock_resolve.assert_called_once_with(
                Path("/fake"), "src/main.py", ResolutionStrategy.THEIRS,
            )
            assert screen._resolutions["src/main.py"] == ResolutionStrategy.THEIRS


@pytest.mark.asyncio
async def test_conflict_screen_ai_resolve_preview(conflict_info):
    """AI resolve shows preview, accept applies."""
    screen = ConflictScreen(
        Path("/fake"), "agent-1/layer-0", ["src/main.py"],
        Path("/fake/.team"), "task context",
    )

    ai_result = AiResolutionResult(
        path="src/main.py",
        resolved_content="# merged",
        explanation="Combined both changes",
    )

    with patch("gotg.tui.screens.conflict.load_conflict_info", return_value=conflict_info), \
         patch("gotg.tui.screens.conflict.ai_resolve_conflict", return_value=ai_result), \
         patch("gotg.tui.screens.conflict.resolve_conflict_file") as mock_resolve, \
         patch("gotg.config.load_model_config", return_value={"provider": "ollama", "model": "test", "base_url": "http://x"}), \
         patch("gotg.model.chat_completion"):
        app = _make_app(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

            await pilot.press("a")
            # Wait for worker
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            assert screen._state == _State.AI_PREVIEW
            assert screen._ai_result == ai_result

            # Accept
            await pilot.press("y")
            await pilot.pause()

            mock_resolve.assert_called_once_with(
                Path("/fake"), "src/main.py",
                ResolutionStrategy.AI, content="# merged",
            )
            assert screen._state == _State.BROWSING
            assert screen._resolutions["src/main.py"] == ResolutionStrategy.AI


@pytest.mark.asyncio
async def test_conflict_screen_ai_reject(conflict_info):
    """Pressing N during AI preview returns to browsing."""
    screen = ConflictScreen(
        Path("/fake"), "agent-1/layer-0", ["src/main.py"],
        Path("/fake/.team"), "task context",
    )

    ai_result = AiResolutionResult(
        path="src/main.py", resolved_content="# merged", explanation="ok",
    )

    with patch("gotg.tui.screens.conflict.load_conflict_info", return_value=conflict_info), \
         patch("gotg.tui.screens.conflict.ai_resolve_conflict", return_value=ai_result), \
         patch("gotg.config.load_model_config", return_value={"provider": "ollama", "model": "test", "base_url": "http://x"}), \
         patch("gotg.model.chat_completion"):
        app = _make_app(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            assert screen._state == _State.AI_PREVIEW

            await pilot.press("n")
            await pilot.pause()

            assert screen._state == _State.BROWSING
            assert screen._ai_result is None
            assert "src/main.py" not in screen._resolutions


@pytest.mark.asyncio
async def test_conflict_screen_complete_merge(conflict_info):
    """C completes merge after all files resolved."""
    screen = ConflictScreen(
        Path("/fake"), "agent-1/layer-0", ["src/main.py"],
        Path("/fake/.team"), "task context",
    )

    merge_result = MergeResult(branch="agent-1/layer-0", success=True, commit="abc1234")

    dismissed = []

    with patch("gotg.tui.screens.conflict.load_conflict_info", return_value=conflict_info), \
         patch("gotg.tui.screens.conflict.resolve_conflict_file"), \
         patch("gotg.tui.screens.conflict.finalize_merge", return_value=merge_result):
        app = _make_app(screen)
        screen.dismiss = lambda result=None: dismissed.append(result)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

            # Resolve first
            await pilot.press("o")
            await pilot.pause()

            # Complete merge
            await pilot.press("c")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            assert len(dismissed) == 1
            assert dismissed[0] == merge_result


@pytest.mark.asyncio
async def test_conflict_screen_complete_blocked_when_unresolved(conflict_info):
    """C is blocked when files remain unresolved."""
    screen = ConflictScreen(
        Path("/fake"), "agent-1/layer-0", ["src/main.py"],
        Path("/fake/.team"), "task context",
    )

    with patch("gotg.tui.screens.conflict.load_conflict_info", return_value=conflict_info):
        app = _make_app(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

            # Try to complete without resolving
            await pilot.press("c")
            await pilot.pause()

            # Should still be browsing
            assert screen._state == _State.BROWSING
            assert len(screen._resolutions) == 0


@pytest.mark.asyncio
async def test_conflict_screen_skip_already_resolved(conflict_info):
    """O/T/A are no-ops on already-resolved files."""
    screen = ConflictScreen(
        Path("/fake"), "agent-1/layer-0", ["src/main.py"],
        Path("/fake/.team"), "task context",
    )

    with patch("gotg.tui.screens.conflict.load_conflict_info", return_value=conflict_info), \
         patch("gotg.tui.screens.conflict.resolve_conflict_file") as mock_resolve:
        app = _make_app(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()

            # Resolve with ours
            await pilot.press("o")
            await pilot.pause()
            assert mock_resolve.call_count == 1

            # Try again — should be no-op
            await pilot.press("o")
            await pilot.pause()
            assert mock_resolve.call_count == 1

            await pilot.press("t")
            await pilot.pause()
            assert mock_resolve.call_count == 1


@pytest.mark.asyncio
async def test_conflict_screen_load_error():
    """Error during load pops the screen."""
    screen = ConflictScreen(
        Path("/fake"), "agent-1/layer-0", ["src/main.py"],
        Path("/fake/.team"), "task context",
    )

    popped = []

    with patch(
        "gotg.tui.screens.conflict.load_conflict_info",
        side_effect=ReviewError("Stage read failed"),
    ):
        app = _make_app(screen)
        original_pop = app.pop_screen
        app.pop_screen = lambda: popped.append(True)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            assert len(popped) == 1
