"""Static metadata display for the chat sidebar."""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape
from textual.containers import Vertical
from textual.widgets import Static

from gotg.tui.data import relative_time


class InfoTile(Vertical):
    """Displays iteration or grooming session metadata."""

    def load_metadata(self, metadata: dict, data_dir: Path) -> None:
        self.remove_children()

        # Title / ID
        title = metadata.get("id") or metadata.get("slug", "")
        self.mount(Static(f"[bold]{escape(str(title))}[/bold]", classes="info-title"))

        # Description / Topic
        desc = metadata.get("description") or metadata.get("topic", "")
        if desc:
            self.mount(Static(escape(desc), classes="info-desc"))

        # Phase
        phase = metadata.get("phase")
        if phase:
            self.mount(Static(f"Phase: {escape(phase)}", classes="info-field"))

        # Layer
        layer = metadata.get("current_layer")
        if layer is not None:
            self.mount(Static(f"Layer: {layer}", classes="info-field"))

        # Status
        status = metadata.get("status")
        if status:
            self.mount(Static(f"Status: {escape(status)}", classes="info-field"))

        # Message count
        msg_count = metadata.get("message_count", 0)
        self.mount(Static(f"Messages: {msg_count}", classes="info-field"))

        # Max turns
        max_turns = metadata.get("max_turns")
        if max_turns is not None:
            self.mount(Static(f"Max turns: {max_turns}", classes="info-field"))

        # Last activity
        log_path = data_dir / "conversation.jsonl"
        mtime = log_path.stat().st_mtime if log_path.exists() else None
        ts = relative_time(mtime)
        if ts:
            self.mount(Static(f"Last activity: {ts}", classes="info-field"))

        # Agents
        agents = metadata.get("agents", [])
        if agents:
            names = ", ".join(
                a if isinstance(a, str) else a.get("name", "?") for a in agents
            )
            self.mount(Static(f"Agents: {escape(names)}", classes="info-field"))

        # Coach
        coach = metadata.get("coach")
        if coach:
            name = coach if isinstance(coach, str) else coach.get("name", "coach")
            self.mount(Static(f"Coach: {escape(name)}", classes="info-field"))

        # Live session status (hidden by default, updated during running sessions)
        self.mount(Static("", id="live-status", classes="info-field"))

    def update_phase(self, phase: str) -> None:
        """Update just the phase field without re-composing."""
        for child in self.children:
            if isinstance(child, Static):
                content = str(child._Static__content)
                if content.startswith("Phase:"):
                    child.update(f"Phase: {escape(phase)}")
                    return

    def update_session_status(self, state_text: str, turn: int | None = None) -> None:
        """Update the live session status indicator."""
        status = self.query_one("#live-status", Static)
        if turn is not None:
            status.update(f"Session: {state_text} (turn {turn})")
        else:
            status.update(f"Session: {state_text}" if state_text else "")
