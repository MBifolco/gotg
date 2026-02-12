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


class StreamingChatbox(Vertical):
    """In-progress streaming message — Static during streaming, Markdown after finalize."""

    DEFAULT_CSS = """
    StreamingChatbox {
        height: auto;
    }
    """

    def __init__(self, agent: str, css_class: str = "chatbox-default") -> None:
        super().__init__(classes=css_class)
        self.border_title = agent
        self._buffer: list[str] = []
        self._static = Static("", classes="chatbox-stream")

    def compose(self):
        yield self._static

    def append_text(self, text: str) -> None:
        self._buffer.append(text)
        self._static.update(escape("".join(self._buffer)))

    def finalize(self, full_content: str) -> None:
        """Replace streaming Static with Markdown. full_content is persisted text only."""
        self._static.remove()
        self.mount(Markdown(full_content, classes="chatbox-md"))


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
        self.call_after_refresh(self.scroll_end, animate=False)

    def _mount_before_spinner(self, widget) -> None:
        """Mount a widget, inserting before the loading spinner if present."""
        spinners = self.query(".ml-loading")
        if spinners:
            self.mount(widget, before=spinners.first())
        else:
            self.mount(widget)

    def append_message(self, msg: dict) -> None:
        """Append a single message. Only auto-scrolls if user is near the bottom."""
        for e in self.query(".msg-empty"):
            e.remove()
        self._mount_before_spinner(_make_widget(msg, self._agent_index))
        self._maybe_scroll()

    def append_coach_prompt(self, question: str) -> None:
        """Append a coach question as a visually distinct prompt."""
        self._mount_before_spinner(CoachPrompt(question))
        self._maybe_scroll()

    def _maybe_scroll(self) -> None:
        """Auto-scroll only if user is at or near the bottom."""
        if self.is_vertical_scroll_end or self.max_scroll_y == 0:
            # Defer until after layout so scroll target reflects new content
            self.call_after_refresh(self.scroll_end, animate=False)

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

    def begin_streaming(self, agent: str, css_class: str) -> StreamingChatbox:
        """Create and mount a StreamingChatbox, return it for incremental updates."""
        for e in self.query(".msg-empty"):
            e.remove()
        widget = StreamingChatbox(agent, css_class=css_class)
        self._mount_before_spinner(widget)
        self._maybe_scroll()
        return widget

    def finalize_streaming(self, widget: StreamingChatbox, content: str) -> None:
        """Swap streaming Static with Markdown rendering."""
        widget.finalize(content)
        self._maybe_scroll()
