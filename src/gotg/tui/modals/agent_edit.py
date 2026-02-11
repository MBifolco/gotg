"""Modal for adding or editing an agent (name + role)."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class AgentEditModal(ModalScreen[dict | None]):
    """Add or edit an agent.

    Dismisses with {"name": str, "role": str} or None on cancel.
    """

    DEFAULT_CSS = """
    AgentEditModal {
        align: center middle;
    }
    AgentEditModal > Vertical {
        width: 60;
        max-height: 16;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    AgentEditModal > Vertical > Label {
        margin: 0 0 0 0;
    }
    AgentEditModal > Vertical > .field-label {
        margin: 1 0 0 0;
        text-style: bold;
    }
    AgentEditModal > Vertical > .hint {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    AgentEditModal > Vertical > Horizontal {
        height: auto;
        align: center middle;
        margin: 1 0 0 0;
    }
    AgentEditModal > Vertical > Horizontal > Button {
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "submit", "Save", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, agent: dict | None = None) -> None:
        super().__init__()
        self._agent = agent or {}

    def compose(self):
        title = "Edit Agent" if self._agent.get("name") else "Add Agent"
        with Vertical():
            yield Label(title)
            yield Label("Name", classes="field-label")
            yield Input(
                value=self._agent.get("name", ""),
                placeholder="agent-3",
                id="agent-name",
            )
            yield Label("Role", classes="field-label")
            yield Input(
                value=self._agent.get("role", ""),
                placeholder="Software Engineer",
                id="agent-role",
            )
            with Horizontal():
                yield Button("Save (Ctrl+S)", id="btn-save", variant="success")
                yield Button("Cancel (Esc)", id="btn-cancel")
            yield Label("Ctrl+S=save  Escape=cancel", classes="hint")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self._do_submit()
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def action_submit(self) -> None:
        self._do_submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _do_submit(self) -> None:
        name = self.query_one("#agent-name", Input).value.strip()
        role = self.query_one("#agent-role", Input).value.strip()

        if not name:
            self.notify("Agent name is required.", severity="warning")
            return

        self.dismiss({"name": name, "role": role or "Software Engineer"})
