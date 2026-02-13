"""Sidebar participant tiles with per-agent tool activity streams."""

from __future__ import annotations

from collections import deque
from typing import Iterable

from rich.markup import escape
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static


def _tool_line(tool_name: str, path: str, status: str, size: int | None) -> str:
    """Format one tool activity line for a participant tile."""
    base = tool_name if not path else f"{tool_name} {path}"
    if tool_name == "file_write" and size:
        base = f"{base} ({size}b)"
    if status == "error":
        return f"{base} FAIL"
    if status == "pending_approval":
        return f"{base} PENDING"
    return base


class ParticipantTile(Vertical):
    """Single participant tile with live status and tool history."""

    _ACTIVE_COLORS = ("$warning", "$success", "$primary")

    def __init__(self, name: str, role: str = "", max_items: int = 8) -> None:
        super().__init__(classes="participant-tile")
        self.border_title = name
        self._role = role
        self._lines: deque[str] = deque(maxlen=max_items)
        self._pulse_timer = None
        self._pulse_index = 0

    def compose(self):
        yield Static("", id="pt-role", classes="pt-role")
        yield Static("Status: idle", id="pt-status", classes="pt-status")
        yield Static("No tool activity yet.", id="pt-tools", classes="pt-tools")

    def on_mount(self) -> None:
        role = self._role.strip()
        role_text = role if role else "(no role set)"
        self.query_one("#pt-role", Static).update(escape(role_text))

    def set_status(self, status: str) -> None:
        """Update participant status line."""
        self.query_one("#pt-status", Static).update(f"Status: {escape(status)}")

    def start_pulse(self) -> None:
        """Start cycling the tile border color to indicate activity."""
        self.add_class("tile-active")
        if self._pulse_timer is None:
            self._pulse_index = 0
            self._pulse_timer = self.set_interval(0.6, self._pulse_tick)

    def stop_pulse(self) -> None:
        """Stop the activity pulse and reset border."""
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
            self._pulse_timer = None
        self.remove_class("tile-active", "tile-pulse-0", "tile-pulse-1", "tile-pulse-2")

    def _pulse_tick(self) -> None:
        """Cycle through pulse classes."""
        for i in range(3):
            self.remove_class(f"tile-pulse-{i}")
        self.add_class(f"tile-pulse-{self._pulse_index}")
        self._pulse_index = (self._pulse_index + 1) % 3

    def add_tool_event(
        self,
        tool_name: str,
        path: str,
        status: str,
        size: int | None,
    ) -> None:
        """Append one tool line for this participant."""
        self._lines.appendleft(_tool_line(tool_name, path, status, size))
        text = "\n".join(escape(line) for line in self._lines)
        self.query_one("#pt-tools", Static).update(text)
        self.set_status("using tools")


class ParticipantPanel(VerticalScroll):
    """Scrollable collection of participant tiles."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tiles: dict[str, ParticipantTile] = {}

    def load_participants(self, agents: Iterable, coach: str | dict | None) -> None:
        """Reset and populate tiles from session metadata."""
        self.remove_children()
        self._tiles.clear()

        for agent in agents:
            if isinstance(agent, dict):
                name = str(agent.get("name", "")).strip()
                role = str(agent.get("role", "")).strip()
            else:
                name = str(agent).strip()
                role = ""
            if name:
                self._mount_tile(name, role)

        if coach:
            if isinstance(coach, dict):
                coach_name = str(coach.get("name", "")).strip()
                coach_role = str(coach.get("role", "")).strip()
            else:
                coach_name = str(coach).strip()
                coach_role = "Coach"
            if coach_name:
                self._mount_tile(coach_name, coach_role or "Coach")

    def _mount_tile(self, name: str, role: str) -> ParticipantTile:
        tile = ParticipantTile(name, role)
        self.mount(tile)
        self._tiles[name] = tile
        return tile

    def ensure_participant(self, name: str) -> ParticipantTile:
        """Get/create a tile by participant name."""
        tile = self._tiles.get(name)
        if tile is not None:
            return tile
        return self._mount_tile(name, "")

    def mark_typing(self, name: str) -> None:
        tile = self.ensure_participant(name)
        tile.set_status("typing")
        tile.start_pulse()

    def mark_idle(self, name: str) -> None:
        tile = self.ensure_participant(name)
        tile.set_status("idle")
        tile.stop_pulse()

    def add_tool_progress(self, event) -> None:
        """Record a tool progress event in the acting participant's tile only."""
        tile = self.ensure_participant(event.agent)
        tile.add_tool_event(
            tool_name=event.tool_name,
            path=event.path,
            status=event.status,
            size=event.bytes,
        )
