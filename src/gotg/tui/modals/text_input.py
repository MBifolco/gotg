"""Single-field text input modal."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class TextInputModal(ModalScreen[str | None]):
    """Modal with a single text input. Dismisses with the value or None on cancel."""

    DEFAULT_CSS = """
    TextInputModal {
        align: center middle;
    }
    TextInputModal > Vertical {
        width: 60;
        max-height: 12;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    TextInputModal > Vertical > Label {
        margin: 0 0 1 0;
    }
    TextInputModal > Vertical > .hint {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        title: str,
        placeholder: str = "",
        initial: str = "",
    ) -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._initial = initial

    def compose(self):
        with Vertical():
            yield Label(self._title)
            yield Input(
                placeholder=self._placeholder,
                value=self._initial,
                id="modal-input",
            )
            yield Label("Enter=submit  Escape=cancel", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#modal-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
