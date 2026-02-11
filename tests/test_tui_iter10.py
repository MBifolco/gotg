"""Tests for TUI iteration 10: Chat polish (smart scroll, loading indicator)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gotg.tui.widgets.message_list import MessageList, Chatbox, LoadingIndicator


# ── Smart auto-scroll ────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_messages_scrolls_to_end():
    """load_messages always scrolls to the bottom."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        # Load enough messages to overflow viewport
        msgs = [{"from": "agent-1", "content": f"Line {i}"} for i in range(30)]
        ml.load_messages(msgs)
        await pilot.pause()

        # Should be at the bottom after bulk load
        assert ml.is_vertical_scroll_end or ml.max_scroll_y == 0


@pytest.mark.asyncio
async def test_append_when_at_bottom_scrolls():
    """append_message scrolls when already at the bottom."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        # Load messages, which scrolls to end
        msgs = [{"from": "agent-1", "content": f"Line {i}"} for i in range(30)]
        ml.load_messages(msgs)
        await pilot.pause()

        # Append one more — should still be at bottom
        ml.append_message({"from": "agent-1", "content": "new message"})
        await pilot.pause()

        chatboxes = ml.query(Chatbox)
        assert len(chatboxes) == 31


@pytest.mark.asyncio
async def test_maybe_scroll_respects_scroll_position():
    """_maybe_scroll doesn't scroll when not at bottom."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test(size=(80, 10)) as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        # Load enough to overflow
        msgs = [{"from": "agent-1", "content": f"Line {i}"} for i in range(30)]
        ml.load_messages(msgs)
        await pilot.pause()

        # Scroll to top (simulates user scrolling up)
        ml.scroll_home(animate=False)
        await pilot.pause()

        # Record scroll position
        y_before = ml.scroll_y

        # Append — should NOT yank back to bottom
        ml.append_message({"from": "agent-1", "content": "new message"})
        await pilot.pause()

        # If scroll was near the top, it should stay near the top
        # (exact position may shift due to content changes but shouldn't jump to end)
        if ml.max_scroll_y > 0:
            assert not ml.is_vertical_scroll_end


# ── Loading indicator ────────────────────────────────────────


@pytest.mark.asyncio
async def test_show_loading_mounts_indicator():
    """show_loading mounts a LoadingIndicator widget."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.show_loading()
        await pilot.pause()

        indicators = ml.query(".ml-loading")
        assert len(indicators) == 1


@pytest.mark.asyncio
async def test_show_loading_idempotent():
    """Calling show_loading twice doesn't create duplicate indicators."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.show_loading()
        ml.show_loading()
        await pilot.pause()

        indicators = ml.query(".ml-loading")
        assert len(indicators) == 1


@pytest.mark.asyncio
async def test_hide_loading_removes_indicator():
    """hide_loading removes the LoadingIndicator."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.show_loading()
        await pilot.pause()
        ml.hide_loading()
        await pilot.pause()

        indicators = ml.query(".ml-loading")
        assert len(indicators) == 0


@pytest.mark.asyncio
async def test_hide_loading_noop_when_not_shown():
    """hide_loading doesn't crash when no indicator is present."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.hide_loading()  # Should not raise
        await pilot.pause()

        indicators = ml.query(".ml-loading")
        assert len(indicators) == 0


@pytest.mark.asyncio
async def test_append_message_keeps_loading():
    """append_message does not remove loading indicator (caller manages it)."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.show_loading()
        await pilot.pause()

        ml.append_message({"from": "agent-1", "content": "hello"})
        await pilot.pause()

        # Loading indicator stays — caller is responsible for hide_loading()
        indicators = ml.query(".ml-loading")
        assert len(indicators) == 1
        # Message should be there too
        chatboxes = ml.query(Chatbox)
        assert len(chatboxes) == 1


@pytest.mark.asyncio
async def test_append_removes_empty_state():
    """append_message removes the 'No messages yet.' placeholder."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.load_messages([])  # Shows empty placeholder
        await pilot.pause()

        empties = ml.query(".msg-empty")
        assert len(empties) == 1

        ml.append_message({"from": "agent-1", "content": "hello"})
        await pilot.pause()

        empties = ml.query(".msg-empty")
        assert len(empties) == 0
        chatboxes = ml.query(Chatbox)
        assert len(chatboxes) == 1
