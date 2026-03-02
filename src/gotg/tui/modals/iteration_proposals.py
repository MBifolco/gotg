"""Modal for reviewing and approving/rejecting iteration proposals from coach."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class IterationProposalModal(ModalScreen[str | None]):
    """Displays proposed iterations. Dismisses with 'approved', feedback string, or None."""

    DEFAULT_CSS = """
    IterationProposalModal {
        align: center middle;
    }
    IterationProposalModal > Vertical {
        width: 72;
        max-height: 80%;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    IterationProposalModal > Vertical > .proposal-title {
        text-style: bold;
        margin: 0 0 1 0;
    }
    IterationProposalModal > Vertical > VerticalScroll {
        height: auto;
        max-height: 20;
        margin: 0 0 1 0;
    }
    IterationProposalModal > Vertical > VerticalScroll > Label {
        width: 1fr;
    }
    IterationProposalModal > Vertical > .rationale {
        color: $text-muted;
        margin: 0 0 1 0;
        width: 1fr;
    }
    IterationProposalModal > Vertical > Horizontal {
        height: auto;
        align: center middle;
        margin: 1 0 0 0;
    }
    IterationProposalModal > Vertical > Horizontal > Button {
        margin: 0 2;
    }
    IterationProposalModal > Vertical > .hint {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        proposals: list[dict],
        rationale: str,
        batch_id: str,
    ) -> None:
        super().__init__()
        self._proposals = proposals
        self._rationale = rationale
        self._batch_id = batch_id
        self._feedback_mode = False

    def compose(self):
        with Vertical():
            yield Label(
                f"Coach proposes {len(self._proposals)} iteration(s)",
                classes="proposal-title",
            )
            with VerticalScroll():
                for i, p in enumerate(self._proposals, 1):
                    action = "NEW" if p.get("action") == "create" else f"UPDATE {p.get('iteration_id', '?')}"
                    yield Label(f"[bold]{i}. [{action}] {p.get('title', '')}[/bold]")
                    yield Label(f"  {p.get('description', '')}")
            if self._rationale:
                yield Label(f"Rationale: {self._rationale}", classes="rationale")
            yield Input(
                placeholder="Type feedback...",
                id="feedback-input",
            )
            with Horizontal():
                yield Button("Approve", id="btn-approve", variant="success")
                yield Button("Send Feedback", id="btn-feedback", variant="primary")
                yield Button("Dismiss (Esc)", id="btn-cancel")
            yield Label("Escape=dismiss", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#feedback-input", Input).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-approve":
            self.dismiss("approved")
        elif event.button.id == "btn-feedback":
            if self._feedback_mode:
                self._submit_feedback()
            else:
                self._feedback_mode = True
                inp = self.query_one("#feedback-input", Input)
                inp.display = True
                inp.focus()
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "feedback-input":
            self._submit_feedback()

    def _submit_feedback(self) -> None:
        text = self.query_one("#feedback-input", Input).value.strip()
        if text:
            self.dismiss(text)
        else:
            self.notify("Please enter feedback.", severity="warning")

    def action_cancel(self) -> None:
        self.dismiss(None)
