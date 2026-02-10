"""Action bar widget for session pause states."""

from __future__ import annotations

from rich.markup import escape
from textual.widgets import Static


class ActionBar(Static):
    """Contextual action bar shown when session pauses or completes."""

    DEFAULT_CSS = """
    ActionBar {
        display: none;
        height: auto;
        max-height: 4;
        background: $surface;
        border-top: solid $warning;
        padding: 0 1;
    }
    ActionBar.visible {
        display: block;
    }
    """

    def show(self, text: str) -> None:
        """Show the action bar with the given text."""
        self.update(escape(text))
        self.add_class("visible")

    def hide(self) -> None:
        """Hide the action bar."""
        self.remove_class("visible")
        self.update("")
