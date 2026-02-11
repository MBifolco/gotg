"""Yes/No confirmation modal."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmModal(ModalScreen[bool]):
    """Modal with a question and Yes/No buttons. Dismisses with True or False."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > Vertical {
        width: 60;
        max-height: 12;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    ConfirmModal > Vertical > Label {
        margin: 0 0 1 0;
    }
    ConfirmModal > Vertical > Horizontal {
        height: auto;
        align: center middle;
    }
    ConfirmModal > Vertical > Horizontal > Button {
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("y", "yes", "Yes", show=False),
        Binding("n", "no", "No", show=False),
        Binding("escape", "no", "Cancel", show=False),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self):
        with Vertical():
            yield Label(self._question)
            with Horizontal():
                yield Button("Yes (Y)", id="btn-yes", variant="success")
                yield Button("No (N)", id="btn-no", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)
