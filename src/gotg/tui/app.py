"""Main TUI application."""

from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.binding import Binding

from gotg.tui.screens.home import HomeScreen


class GotgApp(App):
    """gotg Terminal User Interface."""

    CSS_PATH = "styles.tcss"
    TITLE = "gotg"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, team_dir: Path) -> None:
        super().__init__()
        self.team_dir = team_dir

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())
