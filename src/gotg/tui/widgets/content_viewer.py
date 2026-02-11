"""Scrollable content viewer for file previews with syntax highlighting."""

from __future__ import annotations

import re

from rich.markup import escape
from rich.syntax import Syntax
from textual.containers import VerticalScroll
from textual.widgets import Collapsible, Static

_LEXER_MAP = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "json": "json", "yaml": "yaml", "yml": "yaml",
    "md": "markdown", "toml": "toml", "sh": "bash",
    "css": "css", "html": "html", "sql": "sql",
    "rs": "rust", "go": "go", "rb": "ruby",
}


def parse_diff_files(content: str) -> list[tuple[str, str]]:
    """Parse unified diff into (filename, diff_section) pairs.

    Splits on 'diff --git' boundaries.  Returns empty list if the content
    isn't a standard unified diff (e.g. stat-only output).
    """
    parts = re.split(r"(?=^diff --git )", content, flags=re.MULTILINE)
    files: list[tuple[str, str]] = []
    for part in parts:
        part = part.strip()
        if not part.startswith("diff --git "):
            continue
        m = re.match(r"diff --git a/.+? b/(.+)", part.split("\n")[0])
        filename = m.group(1) if m else "(unknown file)"
        files.append((filename, part))
    return files


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

    def show_diff(self, title: str, content: str) -> None:
        """Display diff content organized by file with collapsible sections."""
        self.remove_children()
        self.mount(Static(f"[bold]{escape(title)}[/bold]", classes="cv-header"))

        files = parse_diff_files(content)
        if not files:
            # Not a unified diff (e.g. stat-only) — show as-is
            syntax = Syntax(content, "diff", theme="monokai", line_numbers=False)
            self.mount(Static(syntax, classes="cv-content"))
        else:
            for i, (filename, diff_section) in enumerate(files):
                syntax = Syntax(
                    diff_section, "diff", theme="monokai", line_numbers=False,
                )
                self.mount(Collapsible(
                    Static(syntax, classes="cv-content"),
                    title=filename,
                    collapsed=i > 0,
                    classes="cv-diff-file",
                ))

        self.scroll_home(animate=False)

    def clear_content(self) -> None:
        """Clear the viewer and show placeholder."""
        self.remove_children()
        self.mount(Static(
            "[dim]Select an approval to view file content[/dim]",
            classes="cv-placeholder",
        ))
