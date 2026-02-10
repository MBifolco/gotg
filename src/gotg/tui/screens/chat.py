"""Read-only conversation viewer."""

from __future__ import annotations

from pathlib import Path

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from gotg.conversation import read_log
from gotg.tui.widgets.info_tile import InfoTile
from gotg.tui.widgets.message_list import MessageList


class ChatScreen(Screen):
    """Displays a conversation log with metadata sidebar."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("home", "scroll_top", "Top"),
        Binding("end", "scroll_bottom", "Bottom"),
    ]

    def __init__(self, data_dir: Path, metadata: dict) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.metadata = metadata

    def compose(self):
        yield Header()
        with Horizontal(id="chat-layout"):
            with Vertical(id="chat-main"):
                yield MessageList(id="message-list")
            with Vertical(id="chat-sidebar"):
                yield InfoTile(id="info-tile")
        yield Footer()

    def on_mount(self) -> None:
        log_path = self.data_dir / "conversation.jsonl"
        messages = read_log(log_path) if log_path.exists() else []

        msg_list = self.query_one("#message-list", MessageList)
        msg_list.load_messages(messages)

        # Enrich metadata with message count for the info tile
        enriched = {**self.metadata, "message_count": len(messages)}
        info = self.query_one("#info-tile", InfoTile)
        info.load_metadata(enriched, self.data_dir)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_scroll_top(self) -> None:
        msg_list = self.query_one("#message-list", MessageList)
        msg_list.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        msg_list = self.query_one("#message-list", MessageList)
        msg_list.scroll_end(animate=False)
