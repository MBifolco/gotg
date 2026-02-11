"""Tests for TUI iteration 9: Markdown message rendering."""

import json
from pathlib import Path

import pytest

from gotg.tui.widgets.message_list import (
    Chatbox,
    MessageWidget,
    PhaseMarker,
    MessageList,
    _css_class_for,
)


# ── CSS class assignment ─────────────────────────────────────


def test_css_class_for_fixed_roles():
    """Fixed roles get dedicated chatbox-{role} classes."""
    idx = {}
    assert _css_class_for("human", idx) == "chatbox-human"
    assert _css_class_for("system", idx) == "chatbox-system"
    assert _css_class_for("coach", idx) == "chatbox-coach"


def test_css_class_for_agents_by_discovery_order():
    """Agents get palette-indexed classes based on first-seen order."""
    idx = {}
    assert _css_class_for("agent-1", idx) == "chatbox-agent-0"
    assert _css_class_for("agent-2", idx) == "chatbox-agent-1"
    # Repeat returns same class
    assert _css_class_for("agent-1", idx) == "chatbox-agent-0"


def test_css_class_for_custom_agent_names():
    """Custom agent names get palette classes, not hardcoded ones."""
    idx = {}
    assert _css_class_for("alice", idx) == "chatbox-agent-0"
    assert _css_class_for("bob", idx) == "chatbox-agent-1"
    assert _css_class_for("charlie", idx) == "chatbox-agent-2"
    assert _css_class_for("dave", idx) == "chatbox-agent-3"
    # Wraps around
    assert _css_class_for("eve", idx) == "chatbox-agent-0"


def test_message_widget_is_chatbox_alias():
    """MessageWidget is an alias for Chatbox (backward compat)."""
    assert MessageWidget is Chatbox


# ── Chatbox widget ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_chatbox_border_title_is_sender():
    """Chatbox sets border_title to the sender name."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.load_messages([{"from": "agent-1", "content": "hello"}])
        await pilot.pause()

        chatboxes = ml.query(Chatbox)
        assert len(chatboxes) == 1
        assert chatboxes[0].border_title == "agent-1"


@pytest.mark.asyncio
async def test_chatbox_contains_markdown_widget():
    """Chatbox contains a Markdown widget for content rendering."""
    from textual.app import App
    from textual.widgets import Markdown

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.load_messages([{"from": "agent-1", "content": "# Hello\n\nWorld"}])
        await pilot.pause()

        chatboxes = ml.query(Chatbox)
        assert len(chatboxes) == 1
        md_widgets = chatboxes[0].query(Markdown)
        assert len(md_widgets) == 1


@pytest.mark.asyncio
async def test_chatbox_css_class_by_role():
    """Chatboxes get role-appropriate CSS classes."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.load_messages([
            {"from": "agent-1", "content": "hi"},
            {"from": "human", "content": "hello"},
            {"from": "coach", "content": "nice"},
        ])
        await pilot.pause()

        chatboxes = list(ml.query(Chatbox))
        assert len(chatboxes) == 3
        assert "chatbox-agent-0" in chatboxes[0].classes
        assert "chatbox-human" in chatboxes[1].classes
        assert "chatbox-coach" in chatboxes[2].classes


# ── PhaseMarker ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_phase_boundary_uses_phase_marker():
    """Phase boundary messages use PhaseMarker (Static), not Chatbox."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.load_messages([
            {"from": "system", "content": "--- Phase: planning ---", "phase_boundary": True},
        ])
        await pilot.pause()

        chatboxes = ml.query(Chatbox)
        assert len(chatboxes) == 0
        markers = ml.query(".phase-boundary")
        assert len(markers) == 1


@pytest.mark.asyncio
async def test_pass_turn_uses_static():
    """Pass turn messages use Static, not Chatbox."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.load_messages([
            {"from": "agent-1", "content": "(pass)", "pass_turn": True},
        ])
        await pilot.pause()

        chatboxes = ml.query(Chatbox)
        assert len(chatboxes) == 0
        passes = ml.query(".msg-pass")
        assert len(passes) == 1


# ── Mixed message types ──────────────────────────────────────


@pytest.mark.asyncio
async def test_message_list_mixed_types():
    """Load messages with different types creates correct widget mix."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.load_messages([
            {"from": "agent-1", "content": "hello"},
            {"from": "system", "content": "--- boundary ---", "phase_boundary": True},
            {"from": "agent-2", "content": "world"},
            {"from": "agent-1", "content": "(pass)", "pass_turn": True},
            {"from": "human", "content": "input"},
        ])
        await pilot.pause()

        chatboxes = ml.query(Chatbox)
        assert len(chatboxes) == 3  # agent-1, agent-2, human
        markers = ml.query(".phase-boundary")
        assert len(markers) == 1
        passes = ml.query(".msg-pass")
        assert len(passes) == 1
        total_children = len(list(ml.children))
        assert total_children == 5


# ── Long content ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chatbox_long_content_no_crash():
    """A message with 1000 lines doesn't crash."""
    from textual.app import App

    long_content = "# Big Message\n\n" + "\n".join(
        f"Line {i}: some content here" for i in range(1000)
    )

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.load_messages([{"from": "agent-1", "content": long_content}])
        await pilot.pause()

        chatboxes = ml.query(Chatbox)
        assert len(chatboxes) == 1


# ── Markdown content rendering ───────────────────────────────


@pytest.mark.asyncio
async def test_chatbox_renders_code_fence():
    """A message with a code fence renders a MarkdownFence widget."""
    from textual.app import App
    from textual.widgets._markdown import MarkdownFence

    content = "Here is some code:\n\n```python\nprint('hello')\n```\n"

    class TestApp(App):
        def compose(self):
            yield MessageList(id="ml")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        ml = app.query_one("#ml", MessageList)
        ml.load_messages([{"from": "agent-1", "content": content}])
        await pilot.pause()
        await pilot.pause()

        chatboxes = ml.query(Chatbox)
        assert len(chatboxes) == 1
        fences = chatboxes[0].query(MarkdownFence)
        assert len(fences) >= 1
