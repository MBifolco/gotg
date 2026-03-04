"""Modal for adding or editing an agent (name + role + optional model override)."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Switch

from gotg.providers import (
    PROVIDERS,
    build_model_override,
    provider_preset,
    provider_runtime_config,
    provider_select_options,
)
from gotg.tui.screens.settings import PROVIDER_MODELS


class AgentEditModal(ModalScreen[dict | None]):
    """Add or edit an agent.

    Dismisses with {"name": str, "role": str, "model"?: dict} or None on cancel.
    """

    DEFAULT_CSS = """
    AgentEditModal {
        align: center middle;
    }
    AgentEditModal > Vertical {
        width: 60;
        max-height: 42;
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
    AgentEditModal > Vertical > .switch-row {
        height: auto;
        margin: 1 0 0 0;
    }
    AgentEditModal > Vertical > .switch-row > Label {
        margin: 0 1 0 0;
    }
    AgentEditModal > Vertical > .switch-row > Switch {
        height: auto;
    }
    #agent-model-fields {
        height: auto;
    }
    #agent-model-fields > .field-label {
        margin: 1 0 0 0;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "submit", "Save", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self, agent: dict | None = None, team_model: dict | None = None
    ) -> None:
        super().__init__()
        self._agent = agent or {}
        self._team_model = team_model or provider_runtime_config("ollama")
        self._last_autofilled_model: str = ""
        # Consumed-event guards: skip the first deferred event from load
        self._skip_switch_event: bool = False
        self._skip_provider_event: str | None = None

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
            with Horizontal(classes="switch-row"):
                yield Label("Custom model")
                yield Switch(id="agent-model-override", value=False)
            with Vertical(id="agent-model-fields"):
                yield Label("Provider", classes="field-label")
                yield Select(
                    provider_select_options(),
                    value="ollama",
                    allow_blank=False,
                    id="agent-provider",
                )
                yield Label("Model name", classes="field-label")
                yield Select(
                    [("", Select.BLANK)],
                    allow_blank=False,
                    id="agent-model-name",
                )
                yield Label("Base URL", classes="field-label")
                yield Input(id="agent-base-url", placeholder="http://localhost:11434")
                yield Label("API key reference", classes="field-label")
                yield Input(id="agent-api-key", placeholder="$API_KEY or leave blank")
            with Horizontal():
                yield Button("Save (Ctrl+S)", id="btn-save", variant="success")
                yield Button("Cancel (Esc)", id="btn-cancel")
            yield Label("Ctrl+S=save  Escape=cancel", classes="hint")

    def _update_model_options(self, provider: str, current_model: str = "") -> None:
        """Update the model Select options for the given provider."""
        model_select = self.query_one("#agent-model-name", Select)
        options = list(PROVIDER_MODELS.get(provider, []))
        known_values = {v for _, v in options}
        if current_model and current_model not in known_values:
            options.insert(0, (current_model, current_model))
        options = [("", Select.BLANK), *options]
        model_select.set_options(options)
        if current_model:
            model_select.value = current_model
        elif len(options) > 1:
            model_select.value = options[1][1]
        else:
            model_select.value = Select.BLANK

    def _get_model_name(self) -> str:
        """Read the current model name from the Select widget."""
        sel = self.query_one("#agent-model-name", Select)
        if sel.value in (None, Select.BLANK, ""):
            return ""
        return str(sel.value).strip()

    def on_mount(self) -> None:
        # Hide model fields by default
        self.query_one("#agent-model-fields").display = False

        # Load existing model override if present
        agent_model = self._agent.get("model")
        if agent_model:
            effective = {**self._team_model, **agent_model}
            agent_provider = effective.get("provider", "ollama")
            # Set consumed-event guards before setting values
            self._skip_switch_event = True
            self._skip_provider_event = agent_provider
            self.query_one("#agent-model-override", Switch).value = True
            self.query_one("#agent-model-fields").display = True
            self.query_one("#agent-provider", Select).value = agent_provider
            self._update_model_options(agent_provider, effective.get("model", ""))
            self.query_one("#agent-base-url", Input).value = effective.get("base_url", "")
            self.query_one("#agent-api-key", Input).value = effective.get("api_key", "")
            self._last_autofilled_model = PROVIDERS.get(
                agent_provider, {}
            ).get("default_model", "")

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id != "agent-model-override":
            return
        if self._skip_switch_event:
            self._skip_switch_event = False
            return
        if event.value:
            self.query_one("#agent-model-fields").display = True
            provider = self._team_model.get("provider", "ollama")
            # Guard: the provider set below queues a deferred Select.Changed
            self._skip_provider_event = provider
            self.query_one("#agent-provider", Select).value = provider
            team_model_name = self._team_model.get("model", "")
            self._update_model_options(provider, team_model_name)
            self.query_one("#agent-base-url", Input).value = self._team_model.get(
                "base_url", ""
            )
            self.query_one("#agent-api-key", Input).value = self._team_model.get(
                "api_key", ""
            )
            self._last_autofilled_model = team_model_name
        else:
            self.query_one("#agent-model-fields").display = False

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "agent-provider":
            return
        provider = str(event.value)
        if self._skip_provider_event is not None:
            expected = self._skip_provider_event
            self._skip_provider_event = None
            if provider == expected:
                return
        preset = provider_preset(provider)
        self.query_one("#agent-base-url", Input).value = preset["base_url"]
        self.query_one("#agent-api-key", Input).value = preset["api_key"]
        # Stale-model logic
        current_model = self._get_model_name()
        default_model = PROVIDERS.get(provider, {}).get("default_model", "")
        if not current_model or current_model == self._last_autofilled_model:
            self._update_model_options(provider, default_model)
        else:
            self._update_model_options(provider, current_model)
        self._last_autofilled_model = default_model

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

        result: dict = {"name": name, "role": role or "Software Engineer"}

        override_on = self.query_one("#agent-model-override", Switch).value
        if override_on:
            override = build_model_override(
                provider=str(self.query_one("#agent-provider", Select).value),
                model=self._get_model_name(),
                base_url=self.query_one("#agent-base-url", Input).value.strip(),
                api_key=self.query_one("#agent-api-key", Input).value.strip(),
                team_provider=self._team_model.get("provider", ""),
                team_base_url=self._team_model.get("base_url", ""),
                team_api_key=self._team_model.get("api_key", ""),
            )
            if isinstance(override, str):
                self.notify(override, severity="warning")
                return
            result["model"] = override

        self.dismiss(result)
