"""TUI subpackage for gotg. Requires textual (optional dependency)."""

from __future__ import annotations

from pathlib import Path


def run_app(team_dir: Path) -> None:
    """Launch the TUI application."""
    from gotg.tui.app import GotgApp

    app = GotgApp(team_dir)
    app.run()
