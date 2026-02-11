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
        Binding("question_mark", "show_help", "Help"),
    ]

    def __init__(self, team_dir: Path) -> None:
        super().__init__()
        self.team_dir = team_dir

    def action_show_help(self) -> None:
        from gotg.tui.screens.help import HelpScreen, collect_bindings
        screen = self.screen
        screen_name = type(screen).__name__
        bindings = collect_bindings(screen)
        self.push_screen(HelpScreen(screen_name, bindings))

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())
