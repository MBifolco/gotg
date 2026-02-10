"""Conversation message display widgets."""

from __future__ import annotations

from rich.markup import escape
from textual.containers import VerticalScroll
from textual.widgets import Static

_KNOWN_SENDERS = frozenset({"agent-1", "agent-2", "human", "system", "coach"})


class MessageWidget(Static):
    """Single conversation message with speaker-colored styling."""

    def __init__(self, msg: dict) -> None:
        sender = msg["from"]
        content = msg.get("content", "")
        css_class = f"msg-{sender}" if sender in _KNOWN_SENDERS else "msg-default"

        if msg.get("phase_boundary"):
            css_class = "phase-boundary"

        if msg.get("pass_turn"):
            css_class = "msg-pass"

        markup = f"[bold]{escape(sender)}[/bold] {escape(content)}"
        super().__init__(markup, classes=css_class)


class MessageList(VerticalScroll):
    """Scrollable list of conversation messages."""

    def load_messages(self, messages: list[dict]) -> None:
        self.remove_children()
        if not messages:
            self.mount(Static("No messages yet.", classes="msg-empty"))
            return
        for msg in messages:
            self.mount(MessageWidget(msg))
        self.scroll_end(animate=False)

    def append_message(self, msg: dict) -> None:
        """Append a single message for streaming. Removes empty placeholder, auto-scrolls."""
        for e in self.query(".msg-empty"):
            e.remove()
        self.mount(MessageWidget(msg))
        self.scroll_end(animate=False)
