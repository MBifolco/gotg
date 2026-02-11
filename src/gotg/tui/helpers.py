"""Shared TUI utilities — small helpers used across multiple screens."""

from __future__ import annotations

from pathlib import Path

from textual.widgets import DataTable


def count_jsonl_lines(path: Path) -> int:
    """Count non-blank lines in a JSONL file."""
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def get_selected_row_key(table: DataTable) -> str | None:
    """Return the string key of the selected row, or None if nothing is selected."""
    if table.row_count == 0:
        return None
    row_idx = table.cursor_row
    if row_idx is None:
        return None
    return table.ordered_rows[row_idx].key.value


def format_size(size_bytes: int) -> str:
    """Format byte count as a human-readable string (e.g. 1.2K, 3.4M)."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}K"
    return f"{size_bytes / (1024 * 1024):.1f}M"


def is_agent_turn(msg: dict, coach_name: str | None = None) -> bool:
    """Return True if a message is an agent turn (not human/system/coach)."""
    sender = msg.get("from", "")
    if sender in ("human", "system"):
        return False
    if coach_name and sender == coach_name:
        return False
    return True


def resolve_coach_name(coach: dict | str | None) -> str | None:
    """Extract the coach name string from various metadata shapes."""
    if coach is None:
        return None
    if isinstance(coach, str):
        return coach
    return coach.get("name", "coach")
