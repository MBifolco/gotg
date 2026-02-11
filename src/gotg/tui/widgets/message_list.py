"""Conversation message display widgets."""

from __future__ import annotations

from rich.markup import escape
from textual.containers import Vertical, VerticalScroll
from textual.widgets import LoadingIndicator, Markdown, Static

# Fixed roles get dedicated CSS classes; agents get palette-based classes.
_FIXED_ROLES = {"human", "system", "coach"}

# Color palette for agents — assigned by discovery order.
_AGENT_PALETTE = ["agent-0", "agent-1", "agent-2", "agent-3"]


def _css_class_for(sender: str, agent_index: dict[str, int]) -> str:
    """Return the CSS class for a message sender.

    Fixed roles (human, system, coach) get 'chatbox-{role}'.
    Agent names get 'chatbox-agent-N' based on discovery order,
    cycling through the palette.
    """
    if sender in _FIXED_ROLES:
        return f"chatbox-{sender}"
    # Assign a palette index on first encounter
    if sender not in agent_index:
        agent_index[sender] = len(agent_index)
    idx = agent_index[sender] % len(_AGENT_PALETTE)
    return f"chatbox-{_AGENT_PALETTE[idx]}"


class Chatbox(Vertical):
    """Single conversation message with bordered container and markdown content."""

    DEFAULT_CSS = """
    Chatbox {
        height: auto;
    }
    """

    def __init__(self, msg: dict, css_class: str = "chatbox-default") -> None:
        super().__init__(classes=css_class)
        self.border_title = msg["from"]
        self._content = msg.get("content", "")

    def compose(self):
        yield Markdown(self._content, classes="chatbox-md")


# Backward compatibility alias for existing tests.
MessageWidget = Chatbox


class CoachPrompt(Static):
    """Coach question to the PM — visually distinct from chat messages."""

    def __init__(self, question: str) -> None:
        super().__init__(
            f"[bold]Coach asks:[/bold] {escape(question)}",
            classes="coach-prompt",
        )


class PhaseMarker(Static):
    """Phase boundary separator line."""

    def __init__(self, msg: dict) -> None:
        content = msg.get("content", "")
        super().__init__(f"[bold]{escape(content)}[/bold]", classes="phase-boundary")


def _make_widget(msg: dict, agent_index: dict[str, int]) -> Chatbox | Static:
    """Factory: choose the right widget type for a message."""
    if msg.get("phase_boundary"):
        return PhaseMarker(msg)
    if msg.get("pass_turn"):
        sender = msg.get("from", "")
        markup = f"[bold]{escape(sender)}[/bold] {escape(msg.get('content', ''))}"
        return Static(markup, classes="msg-pass")

    css_class = _css_class_for(msg["from"], agent_index)
    return Chatbox(msg, css_class=css_class)


class MessageList(VerticalScroll):
    """Scrollable list of conversation messages."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._agent_index: dict[str, int] = {}
        self._loading_visible = False

    def load_messages(self, messages: list[dict]) -> None:
        self.remove_children()
        self._agent_index.clear()
        self._loading_visible = False
        if not messages:
            self.mount(Static("No messages yet.", classes="msg-empty"))
            return
        for msg in messages:
            self.mount(_make_widget(msg, self._agent_index))
        self.scroll_end(animate=False)

    def append_message(self, msg: dict) -> None:
        """Append a single message. Only auto-scrolls if user is near the bottom."""
        for e in self.query(".msg-empty"):
            e.remove()
        self.mount(_make_widget(msg, self._agent_index))
        self._maybe_scroll()

    def append_coach_prompt(self, question: str) -> None:
        """Append a coach question as a visually distinct prompt."""
        self.mount(CoachPrompt(question))
        self._maybe_scroll()

    def _maybe_scroll(self) -> None:
        """Auto-scroll only if user is at or near the bottom."""
        if self.is_vertical_scroll_end or self.max_scroll_y == 0:
            self.scroll_end(animate=False)

    def show_loading(self) -> None:
        """Show a loading spinner at the bottom of the message list."""
        if self._loading_visible:
            return
        self._loading_visible = True
        self.mount(LoadingIndicator(classes="ml-loading"))
        self._maybe_scroll()

    def hide_loading(self) -> None:
        """Remove the loading spinner."""
        self._loading_visible = False
        for w in self.query(".ml-loading"):
            w.remove()
