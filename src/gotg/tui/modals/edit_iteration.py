"""Multi-field modal for editing iteration properties."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from gotg.config import ITERATION_STATUSES


_STATUS_OPTIONS = [(s, s) for s in ITERATION_STATUSES]


class EditIterationModal(ModalScreen[dict | None]):
    """Edit iteration description, max_turns, and status.

    Dismisses with {"description": str, "max_turns": int, "status": str}
    or None on cancel.
    """

    DEFAULT_CSS = """
    EditIterationModal {
        align: center middle;
    }
    EditIterationModal > Vertical {
        width: 64;
        max-height: 22;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    EditIterationModal > Vertical > Label {
        margin: 0 0 0 0;
    }
    EditIterationModal > Vertical > .field-label {
        margin: 1 0 0 0;
        text-style: bold;
    }
    EditIterationModal > Vertical > .hint {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    EditIterationModal > Vertical > Horizontal {
        height: auto;
        align: center middle;
        margin: 1 0 0 0;
    }
    EditIterationModal > Vertical > Horizontal > Button {
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "submit", "Save", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, iteration: dict) -> None:
        super().__init__()
        self._iteration = iteration

    def compose(self):
        it = self._iteration
        with Vertical():
            yield Label(f"Edit {it.get('id', 'iteration')}")
            yield Label("Description", classes="field-label")
            yield Input(
                value=it.get("description", "") or it.get("title", ""),
                placeholder="What should the team build?",
                id="edit-desc",
            )
            yield Label("Max turns", classes="field-label")
            yield Input(
                value=str(it.get("max_turns", 30)),
                placeholder="30",
                id="edit-max-turns",
            )
            yield Label("Status", classes="field-label")
            yield Select(
                _STATUS_OPTIONS,
                value=it.get("status", "pending"),
                allow_blank=False,
                id="edit-status",
            )
            with Horizontal():
                yield Button("Save (Ctrl+S)", id="btn-save", variant="success")
                yield Button("Cancel (Esc)", id="btn-cancel")
            yield Label("Tab=next field  Ctrl+S=save  Escape=cancel", classes="hint")

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
        desc = self.query_one("#edit-desc", Input).value.strip()
        max_turns_raw = self.query_one("#edit-max-turns", Input).value.strip()
        status = self.query_one("#edit-status", Select).value

        if not desc:
            self.notify("Description is required.", severity="warning")
            return

        try:
            max_turns = int(max_turns_raw)
            if max_turns < 1:
                raise ValueError
        except (ValueError, TypeError):
            self.notify("Max turns must be a positive integer.", severity="warning")
            return

        self.dismiss({"description": desc, "max_turns": max_turns, "status": str(status)})
