"""Context-sensitive help overlay showing keybindings for the current screen."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static


class HelpScreen(ModalScreen[None]):
    """Shows keybindings for the screen underneath."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > Vertical {
        width: 70;
        max-height: 80%;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    HelpScreen > Vertical > .help-title {
        text-style: bold;
        margin: 0 0 1 0;
    }
    HelpScreen > Vertical > .help-hint {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    HelpScreen > Vertical > VerticalScroll {
        height: 1fr;
    }
    .help-row {
        margin: 0;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("question_mark", "close", "Close", show=False),
    ]

    def __init__(self, screen_name: str, bindings: list[tuple[str, str]]) -> None:
        super().__init__()
        self._screen_name = screen_name
        self._help_bindings = bindings

    def compose(self):
        with Vertical():
            yield Label(f"Help — {self._screen_name}", classes="help-title")
            with VerticalScroll():
                for key, description in self._help_bindings:
                    yield Static(
                        f"  [bold]{key:<16}[/bold] {description}",
                        classes="help-row",
                    )
            yield Label("Press ? or Escape to close", classes="help-hint")

    def action_close(self) -> None:
        self.dismiss(None)


def collect_bindings(screen) -> list[tuple[str, str]]:
    """Collect human-readable bindings from a screen and its app.

    Returns a list of (key, description) tuples for all non-hidden bindings,
    plus hidden bindings that have descriptions.
    """
    result = []
    seen_keys: set[str] = set()

    # Screen bindings first (more specific)
    for binding in getattr(screen, "BINDINGS", []):
        if isinstance(binding, Binding):
            key, desc = binding.key, binding.description
        elif isinstance(binding, tuple):
            key = binding[0]
            desc = binding[2] if len(binding) > 2 else binding[1]
        else:
            continue
        if desc and key not in seen_keys:
            result.append((_format_key(key), desc))
            seen_keys.add(key)

    # App bindings (less specific, shown after)
    app = getattr(screen, "app", None)
    if app:
        for binding in getattr(app, "BINDINGS", []):
            if isinstance(binding, Binding):
                key, desc = binding.key, binding.description
            elif isinstance(binding, tuple):
                key = binding[0]
                desc = binding[2] if len(binding) > 2 else binding[1]
            else:
                continue
            if desc and key not in seen_keys:
                result.append((_format_key(key), desc))
                seen_keys.add(key)

    # Always include ? at the end
    if "question_mark" not in seen_keys and "?" not in seen_keys:
        result.append(("?", "Help"))

    return result


def _format_key(key: str) -> str:
    """Convert Textual key names to readable labels."""
    mapping = {
        "escape": "Esc",
        "question_mark": "?",
        "home": "Home",
        "end": "End",
    }
    return mapping.get(key, key)
