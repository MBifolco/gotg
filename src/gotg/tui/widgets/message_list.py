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
        # True while a deferred scroll-to-end is pending after a layout change.
        # Lets turn transitions keep following output even if the next message
        # arrives before the refresh callback runs.
        self._follow_until_refresh = False
        # Scheduled call_later handle for clearing _follow_until_refresh.
        # Each virtual_size change resets the timer, so the flag stays alive
        # while Markdown subtrees are still settling.
        self._settle_timer = None
        # True while a streaming chatbox is active and user was at the bottom
        # when streaming started.  Prevents the _is_near_bottom() threshold
        # check from losing the scroll as content grows faster than layout
        # recalculations during streaming.
        self._streaming_auto_scroll = False

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
        should_scroll = self._should_follow_output()
        for e in self.query(".msg-empty"):
            e.remove()
        self._mount_before_spinner(_make_widget(msg, self._agent_index))
        self._maybe_scroll(should_scroll)

    def append_coach_prompt(self, question: str) -> None:
        """Append a coach question as a visually distinct prompt."""
        should_scroll = self._should_follow_output()
        self._mount_before_spinner(CoachPrompt(question))
        self._maybe_scroll(should_scroll)

    def pin_to_bottom(self) -> None:
        """Schedule a scroll-to-bottom after the next layout refresh.

        Call this after layout-affecting changes outside the MessageList
        (e.g. ActionBar appearing/disappearing) that shrink/grow the
        viewport without changing the message content.
        """
        self._follow_until_refresh = True
        self.call_after_refresh(self._deferred_scroll_end)

    def _is_near_bottom(self, threshold: int = 2) -> bool:
        """Return True if the viewport is close enough to the bottom to follow output."""
        if self.max_scroll_y == 0:
            return True
        return (self.max_scroll_y - self.scroll_y) <= threshold

    def _should_follow_output(self) -> bool:
        """Return whether output should stay pinned to the bottom."""
        return self._is_near_bottom() or self._follow_until_refresh or self._streaming_auto_scroll

    def _deferred_scroll_end(self) -> None:
        """Finalize deferred bottom pinning once layout is refreshed."""
        self.scroll_end(animate=False)
        # Don't clear _follow_until_refresh here — let the settle timer
        # handle it so Markdown rendering that spans multiple frames
        # stays pinned.
        self._start_settle_timer()

    def _start_settle_timer(self) -> None:
        """Start (or restart) a timer that clears _follow_until_refresh.

        Each call resets the timer.  As long as virtual_size keeps
        changing (Markdown still rendering), the timer keeps resetting
        and the flag stays alive.
        """
        if self._settle_timer is not None:
            self._settle_timer.stop()
        self._settle_timer = self.set_timer(0.3, self._settle_complete)

    def _settle_complete(self) -> None:
        """Content has stopped growing — safe to release the follow lock."""
        self._follow_until_refresh = False
        self._settle_timer = None

    def watch_virtual_size(self, size) -> None:
        """React to content height changes (e.g. Markdown subtree rendering).

        virtual_size is a Reactive that fires whenever child widget
        heights change.  max_scroll_y is a computed property and can't
        be watched, so this is the reliable hook for keeping the scroll
        pinned while content is still settling.
        """
        if self._follow_until_refresh or self._streaming_auto_scroll:
            self.scroll_end(animate=False)
            # Reset settle timer — content is still changing
            if self._follow_until_refresh and self._settle_timer is not None:
                self._start_settle_timer()

    def _maybe_scroll(self, should_scroll: bool | None = None) -> None:
        """Auto-scroll when the user was near the bottom before content changed."""
        if should_scroll is None:
            should_scroll = self._should_follow_output()
        if should_scroll:
            # Immediate scroll keeps streaming turn-to-turn transitions from lagging
            # when the next widget mounts before the deferred refresh callback runs.
            self.scroll_end(animate=False)
            # Defer until after layout so scroll target reflects new content
            self._follow_until_refresh = True
            self.call_after_refresh(self._deferred_scroll_end)

    def show_loading(self) -> None:
        """Show a loading spinner at the bottom of the message list."""
        if self._loading_visible:
            return
        should_scroll = self._should_follow_output()
        self._loading_visible = True
        self.mount(LoadingIndicator(classes="ml-loading"))
        self._maybe_scroll(should_scroll)

    def hide_loading(self) -> None:
        """Remove the loading spinner."""
        should_scroll = self._should_follow_output()
        self._loading_visible = False
        for w in self.query(".ml-loading"):
            w.remove()
        # If user was following output, keep them pinned to the bottom after
        # spinner height is removed (prevents turn-transition scroll drift).
        self._maybe_scroll(should_scroll)

    def begin_streaming(self, agent: str, css_class: str) -> StreamingChatbox:
        """Create and mount a StreamingChatbox, return it for incremental updates."""
        should_scroll = self._should_follow_output()
        # Lock in scroll intent for the entire streaming session so that
        # rapid Static.update() calls can't outrun layout recalculations
        # and trip _is_near_bottom()'s threshold check.
        self._streaming_auto_scroll = should_scroll
        for e in self.query(".msg-empty"):
            e.remove()
        widget = StreamingChatbox(agent, css_class=css_class)
        self._mount_before_spinner(widget)
        self._maybe_scroll(should_scroll)
        return widget

    def append_stream_delta(self, widget: StreamingChatbox, text: str) -> None:
        """Append streaming text and keep following output if user was near bottom."""
        widget.append_text(text)
        if self._streaming_auto_scroll:
            self.scroll_end(animate=False)

    def finalize_streaming(self, widget: StreamingChatbox, content: str) -> None:
        """Swap streaming Static with Markdown rendering."""
        should_scroll = self._streaming_auto_scroll or self._should_follow_output()
        self._streaming_auto_scroll = False
        widget.finalize(content)
        self._maybe_scroll(should_scroll)
