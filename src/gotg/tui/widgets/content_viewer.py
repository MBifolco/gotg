"""Scrollable content viewer for file previews with syntax highlighting."""

from __future__ import annotations

from rich.markup import escape
from rich.syntax import Syntax
from textual.containers import VerticalScroll
from textual.widgets import Static

_LEXER_MAP = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "json": "json", "yaml": "yaml", "yml": "yaml",
    "md": "markdown", "toml": "toml", "sh": "bash",
    "css": "css", "html": "html", "sql": "sql",
    "rs": "rust", "go": "go", "rb": "ruby",
}


class ContentViewer(VerticalScroll):
    """Displays file content with syntax-aware formatting."""

    DEFAULT_CSS = """
    ContentViewer {
        border: solid $accent;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.mount(Static(
            "[dim]Select an approval to view file content[/dim]",
            classes="cv-placeholder",
        ))

    def show_content(self, path: str, content: str) -> None:
        """Display file content with a path header."""
        self.remove_children()
        self.mount(Static(f"[bold]{escape(path)}[/bold]", classes="cv-header"))

        ext = path.rsplit(".", 1)[-1] if "." in path else ""
        lexer = _LEXER_MAP.get(ext, "text")
        syntax = Syntax(content, lexer, theme="monokai", line_numbers=True)
        self.mount(Static(syntax, classes="cv-content"))
        self.scroll_home(animate=False)

    def clear_content(self) -> None:
        """Clear the viewer and show placeholder."""
        self.remove_children()
        self.mount(Static(
            "[dim]Select an approval to view file content[/dim]",
            classes="cv-placeholder",
        ))
