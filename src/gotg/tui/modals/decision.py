"""Decision modal for structured coach questions with selectable options."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, RadioButton, RadioSet


_NONE_LABEL = "None of these, send a message"


class DecisionModal(ModalScreen[str | None]):
    """Modal with radio options + optional message. Dismisses with formatted response."""

    DEFAULT_CSS = """
    DecisionModal {
        align: center middle;
    }
    DecisionModal > Vertical {
        width: 64;
        max-height: 80%;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
        overflow-y: auto;
    }
    DecisionModal > Vertical > .decision-question {
        width: 100%;
        margin: 0 0 1 0;
    }
    DecisionModal > Vertical > Label {
        margin: 0 0 1 0;
    }
    DecisionModal > Vertical > RadioSet {
        height: auto;
        margin: 0 0 1 0;
    }
    DecisionModal > Vertical > .hint {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    DecisionModal > Vertical > Horizontal {
        height: auto;
        align: center middle;
        margin: 1 0 0 0;
    }
    DecisionModal > Vertical > Horizontal > Button {
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, question: str, options: tuple[str, ...]) -> None:
        super().__init__()
        self._question = question
        self._options = options
        self._selected_index: int | None = None

    def compose(self):
        with Vertical():
            yield Label(f"[bold]Coach asks:[/bold] {self._question}", classes="decision-question")
            with RadioSet(id="decision-radios"):
                for opt in self._options:
                    yield RadioButton(opt)
                yield RadioButton(_NONE_LABEL)
            yield Checkbox("Also send a message", id="cb-message")
            yield Input(
                placeholder="Your message...",
                id="decision-input",
                disabled=True,
            )
            with Horizontal():
                yield Button("Submit", id="btn-submit", variant="success")
                yield Button("Cancel (Esc)", id="btn-cancel")
            yield Label("Tab=navigate  Enter=submit  Escape=cancel", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#decision-input", Input).display = False

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self._selected_index = event.radio_set.pressed_index
        is_none = self._selected_index == len(self._options)

        cb = self.query_one("#cb-message", Checkbox)
        inp = self.query_one("#decision-input", Input)

        if is_none:
            cb.value = True
            cb.disabled = True
            inp.display = True
            inp.disabled = False
            inp.focus()
        else:
            cb.disabled = False
            if not cb.value:
                inp.display = False
                inp.disabled = True

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id != "cb-message":
            return
        inp = self.query_one("#decision-input", Input)
        if event.value:
            inp.display = True
            inp.disabled = False
            inp.focus()
        else:
            inp.display = False
            inp.disabled = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit":
            self._do_submit()
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "decision-input":
            self._do_submit()

    def _do_submit(self) -> None:
        if self._selected_index is None:
            self.notify("Please select an option.", severity="warning")
            return

        is_none = self._selected_index == len(self._options)
        message = self.query_one("#decision-input", Input).value.strip()

        if is_none and not message:
            self.notify("Please enter a message.", severity="warning")
            return

        if is_none:
            self.dismiss(f"Message: {message}")
        else:
            selected_text = self._options[self._selected_index]
            if message:
                self.dismiss(f"Selected: {selected_text}\n\nMessage: {message}")
            else:
                self.dismiss(f"Selected: {selected_text}")

    def action_cancel(self) -> None:
        self.dismiss(None)
