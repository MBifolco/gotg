"""Settings screen for editing team.json configuration."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Switch,
)

from gotg.config import load_team_config, save_team_config
from gotg.providers import (
    PROVIDERS,
    build_model_override,
    provider_preset,
    provider_select_options,
)
from gotg.tui.helpers import get_selected_row_key


# ── Provider presets (re-exports for backward compat) ────────

PROVIDER_OPTIONS = provider_select_options()

PROVIDER_PRESETS = {k: provider_preset(k) for k in PROVIDERS}

PROVIDER_MODELS: dict[str, list[tuple[str, str]]] = {
    k: [(m, m) for m in v["models"]] for k, v in PROVIDERS.items()
}


# ── SettingsScreen ───────────────────────────────────────────


class SettingsScreen(Screen):
    """Edit team.json configuration."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("escape", "go_back", "Back"),
        Binding("a", "add_agent", "Add Agent", show=False),
        Binding("e", "edit_agent", "Edit Agent", show=False),
        Binding("delete", "remove_agent", "Remove Agent", show=False),
        Binding("backspace", "remove_agent", "Remove Agent", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._agents: list[dict] = []
        self._loaded_provider: str | None = None
        self._coach_last_autofilled_model: str = ""
        # Consumed-event guards for coach model override load
        self._skip_coach_switch_event: bool = False
        self._skip_coach_provider_event: str | None = None

    def compose(self):
        yield Header()
        with VerticalScroll(id="settings-scroll"):
            # ── Model ──
            yield Label("Model", classes="settings-section")
            yield Label("Provider", classes="field-label")
            yield Select(
                PROVIDER_OPTIONS,
                value="ollama",
                allow_blank=False,
                id="set-provider",
            )
            yield Label("Model name", classes="field-label")
            yield Select(
                [("", Select.BLANK), *PROVIDER_MODELS.get("ollama", [])],
                allow_blank=False,
                id="set-model-name",
            )
            yield Label("Base URL", classes="field-label")
            yield Input(id="set-base-url", placeholder="http://localhost:11434")
            yield Label("API key reference", classes="field-label")
            yield Input(id="set-api-key", placeholder="$ANTHROPIC_API_KEY or leave blank")

            # ── Agents ──
            yield Label("Agents", classes="settings-section")
            yield DataTable(id="agent-table", cursor_type="row")
            with Horizontal(classes="button-row"):
                yield Button("Add (A)", id="btn-add-agent")
                yield Button("Edit (E)", id="btn-edit-agent")
                yield Button("Remove (Del)", id="btn-remove-agent")

            # ── Coach ──
            yield Label("Coach", classes="settings-section")
            with Horizontal(classes="switch-row"):
                yield Label("Enabled")
                yield Switch(id="set-coach-enabled", value=True)
            yield Label("Name", classes="field-label")
            yield Input(id="set-coach-name", placeholder="coach")
            yield Label("Role", classes="field-label")
            yield Input(id="set-coach-role", placeholder="Agile Coach")
            with Horizontal(classes="switch-row", id="coach-model-override-row"):
                yield Label("Custom model")
                yield Switch(id="set-coach-model-override", value=False)
            with Vertical(id="coach-model-fields"):
                yield Label("Provider", classes="field-label")
                yield Select(
                    PROVIDER_OPTIONS,
                    value="ollama",
                    allow_blank=False,
                    id="set-coach-provider",
                )
                yield Label("Model name", classes="field-label")
                yield Input(id="set-coach-model-name", placeholder="model name")
                yield Label("Base URL", classes="field-label")
                yield Input(id="set-coach-base-url", placeholder="http://localhost:11434")
                yield Label("API key reference", classes="field-label")
                yield Input(id="set-coach-api-key", placeholder="$API_KEY or leave blank")

            # ── File Access ──
            yield Label("File Access", classes="settings-section")
            yield Label("Writable paths (comma-separated)", classes="field-label")
            yield Input(id="set-writable-paths", placeholder="src/**, tests/**, docs/**")
            yield Label("Protected paths (comma-separated)", classes="field-label")
            yield Input(id="set-protected-paths", placeholder="")
            yield Label("Max file size (bytes)", classes="field-label")
            yield Input(id="set-max-file-size", placeholder="1048576")
            yield Label("Max files per turn", classes="field-label")
            yield Input(id="set-max-files-per-turn", placeholder="10")
            with Horizontal(classes="switch-row"):
                yield Label("Enable approvals")
                yield Switch(id="set-approvals", value=False)

            # ── Worktrees ──
            yield Label("Worktrees", classes="settings-section")
            with Horizontal(classes="switch-row"):
                yield Label("Enabled")
                yield Switch(id="set-worktrees", value=False)

            # ── Streaming ──
            yield Label("Streaming", classes="settings-section")
            with Horizontal(classes="switch-row"):
                yield Label("Enabled")
                yield Switch(id="set-streaming", value=False)

            yield Label(
                "Ctrl+S=save  Escape=back  A=add agent  E=edit agent  Del=remove",
                classes="hint",
            )
        yield Footer()

    def on_mount(self) -> None:
        # Set up agent table columns
        table = self.query_one("#agent-table", DataTable)
        table.add_column("Name", key="name")
        table.add_column("Role", key="role")
        table.add_column("Model", key="model")

        # Hide coach model fields by default
        self.query_one("#coach-model-fields").display = False

        self._load_config()

    def _load_config(self) -> None:
        """Load team.json and populate all widgets."""
        try:
            config = load_team_config(self.app.team_dir)
        except (FileNotFoundError, KeyError):
            self.notify("Could not load team.json", severity="error")
            return

        # Model
        model = config.get("model", {})
        provider = model.get("provider", "ollama")
        self._loaded_provider = provider
        self.query_one("#set-provider", Select).value = provider
        self._update_model_options(provider, model.get("model", ""))
        self.query_one("#set-base-url", Input).value = model.get("base_url", "")
        self.query_one("#set-api-key", Input).value = model.get("api_key", "")

        # Agents
        self._agents = [dict(a) for a in config.get("agents", [])]
        self._refresh_agent_table()

        # Coach
        coach = config.get("coach")
        coach_enabled = coach is not None
        self.query_one("#set-coach-enabled", Switch).value = coach_enabled
        if coach:
            self.query_one("#set-coach-name", Input).value = coach.get("name", "")
            self.query_one("#set-coach-role", Input).value = coach.get("role", "")
        self._update_coach_inputs(coach_enabled)

        # Coach model override
        if coach and coach.get("model"):
            current_team = self._current_team_model()
            effective = {**current_team, **coach["model"]}
            coach_provider = effective.get("provider", "ollama")
            # Set consumed-event guards before setting values
            self._skip_coach_switch_event = True
            self._skip_coach_provider_event = coach_provider
            self.query_one("#set-coach-model-override", Switch).value = True
            self.query_one("#coach-model-fields").display = True
            self.query_one("#set-coach-provider", Select).value = coach_provider
            self.query_one("#set-coach-model-name", Input).value = effective.get("model", "")
            self.query_one("#set-coach-base-url", Input).value = effective.get("base_url", "")
            self.query_one("#set-coach-api-key", Input).value = effective.get("api_key", "")
            self._coach_last_autofilled_model = PROVIDERS.get(
                coach_provider, {}
            ).get("default_model", "")
        else:
            self.query_one("#set-coach-model-override", Switch).value = False
            self.query_one("#coach-model-fields").display = False
            self._coach_last_autofilled_model = ""

        # File access
        fa = config.get("file_access") or {}
        writable = fa.get("writable_paths", [])
        protected = fa.get("protected_paths", [])
        self.query_one("#set-writable-paths", Input).value = ", ".join(writable)
        self.query_one("#set-protected-paths", Input).value = ", ".join(protected)
        self.query_one("#set-max-file-size", Input).value = str(
            fa.get("max_file_size_bytes", 1048576)
        )
        self.query_one("#set-max-files-per-turn", Input).value = str(
            fa.get("max_files_per_turn", 10)
        )
        self.query_one("#set-approvals", Switch).value = fa.get(
            "enable_approvals", False
        )

        # Worktrees
        wt = config.get("worktrees") or {}
        self.query_one("#set-worktrees", Switch).value = wt.get("enabled", False)

        # Streaming
        self.query_one("#set-streaming", Switch).value = bool(config.get("streaming", False))

    def _current_team_model(self) -> dict:
        """Read live team model state from form widgets."""
        model_select = self.query_one("#set-model-name", Select)
        model_val = (
            str(model_select.value)
            if model_select.value not in (None, Select.BLANK)
            else ""
        )
        return {
            "provider": str(self.query_one("#set-provider", Select).value),
            "model": model_val,
            "base_url": self.query_one("#set-base-url", Input).value.strip(),
            "api_key": self.query_one("#set-api-key", Input).value.strip(),
        }

    def _refresh_agent_table(self) -> None:
        """Rebuild agent DataTable from self._agents."""
        table = self.query_one("#agent-table", DataTable)
        table.clear()
        for i, agent in enumerate(self._agents):
            model_display = agent.get("model", {}).get("model", "(default)")
            table.add_row(agent["name"], agent.get("role", ""), model_display, key=str(i))

    def _update_coach_inputs(self, enabled: bool) -> None:
        """Enable or disable coach name/role inputs."""
        self.query_one("#set-coach-name", Input).disabled = not enabled
        self.query_one("#set-coach-role", Input).disabled = not enabled
        if not enabled:
            # Force coach model override off and hide entire row + fields
            self.query_one("#set-coach-model-override", Switch).value = False
            self.query_one("#coach-model-override-row").display = False
            self.query_one("#coach-model-fields").display = False
        else:
            self.query_one("#coach-model-override-row").display = True

    def _update_model_options(self, provider: str, current_model: str = "") -> None:
        """Update the model Select options for the given provider."""
        model_select = self.query_one("#set-model-name", Select)
        options = list(PROVIDER_MODELS.get(provider, []))
        # If current model isn't in the list, add it so it's selectable
        known_values = {v for _, v in options}
        if current_model and current_model not in known_values:
            options.insert(0, (current_model, current_model))
        # Keep blank model selection as a concrete option value so tests and
        # validation work across Textual versions.
        options = [("", Select.BLANK), *options]
        model_select.set_options(options)
        if current_model:
            model_select.value = current_model
        elif len(options) > 1:
            model_select.value = options[1][1]
        else:
            model_select.value = Select.BLANK

    # ── Provider preset ──────────────────────────────────────

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "set-provider":
            provider = str(event.value)
            # Skip auto-fill on initial mount
            if self._loaded_provider is not None and provider == self._loaded_provider:
                self._loaded_provider = None  # Allow future changes
                return
            self._loaded_provider = None
            preset = PROVIDER_PRESETS.get(provider, {})
            if "base_url" in preset:
                self.query_one("#set-base-url", Input).value = preset["base_url"]
            if "api_key" in preset:
                self.query_one("#set-api-key", Input).value = preset["api_key"]
            self._update_model_options(provider)
        elif event.select.id == "set-coach-provider":
            provider = str(event.value)
            if self._skip_coach_provider_event is not None:
                expected = self._skip_coach_provider_event
                self._skip_coach_provider_event = None
                if provider == expected:
                    return
            preset = provider_preset(provider)
            self.query_one("#set-coach-base-url", Input).value = preset["base_url"]
            self.query_one("#set-coach-api-key", Input).value = preset["api_key"]
            # Stale-model logic
            current_model = self.query_one("#set-coach-model-name", Input).value.strip()
            default_model = PROVIDERS.get(provider, {}).get("default_model", "")
            if not current_model or current_model == self._coach_last_autofilled_model:
                self.query_one("#set-coach-model-name", Input).value = default_model
            self._coach_last_autofilled_model = default_model

    # ── Coach toggle ─────────────────────────────────────────

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "set-coach-enabled":
            self._update_coach_inputs(event.value)
        elif event.switch.id == "set-coach-model-override":
            if self._skip_coach_switch_event:
                self._skip_coach_switch_event = False
                return
            if event.value:
                self.query_one("#coach-model-fields").display = True
                team = self._current_team_model()
                # Guard: the provider set below queues a deferred Select.Changed
                self._skip_coach_provider_event = team["provider"]
                self.query_one("#set-coach-provider", Select).value = team["provider"]
                self.query_one("#set-coach-model-name", Input).value = team.get("model", "")
                self.query_one("#set-coach-base-url", Input).value = team.get("base_url", "")
                self.query_one("#set-coach-api-key", Input).value = team.get("api_key", "")
                self._coach_last_autofilled_model = team.get("model", "")
            else:
                self.query_one("#coach-model-fields").display = False

    # ── Button handlers ──────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add-agent":
            self.action_add_agent()
        elif event.button.id == "btn-edit-agent":
            self.action_edit_agent()
        elif event.button.id == "btn-remove-agent":
            self.action_remove_agent()

    # ── Save ─────────────────────────────────────────────────

    def action_save(self) -> None:
        """Validate and save all settings to team.json."""
        model_select = self.query_one("#set-model-name", Select)
        model_name = (
            str(model_select.value).strip()
            if model_select.value not in (None, Select.BLANK, "")
            else ""
        )
        if not model_name:
            self.notify("Model name is required.", severity="warning")
            return

        if len(self._agents) < 2:
            self.notify("At least 2 agents are required.", severity="warning")
            return

        # Build model config
        provider = str(self.query_one("#set-provider", Select).value)
        model = {
            "provider": provider,
            "base_url": self.query_one("#set-base-url", Input).value.strip(),
            "model": model_name,
        }
        api_key = self.query_one("#set-api-key", Input).value.strip()
        if api_key:
            model["api_key"] = api_key

        # Build coach config
        coach_enabled = self.query_one("#set-coach-enabled", Switch).value
        coach = None
        if coach_enabled:
            coach_name = self.query_one("#set-coach-name", Input).value.strip()
            coach_role = self.query_one("#set-coach-role", Input).value.strip()
            coach = {
                "name": coach_name or "coach",
                "role": coach_role or "Agile Coach",
            }

            # Coach model override
            coach_override_on = self.query_one("#set-coach-model-override", Switch).value
            if coach_override_on:
                team = self._current_team_model()
                override = build_model_override(
                    provider=str(self.query_one("#set-coach-provider", Select).value),
                    model=self.query_one("#set-coach-model-name", Input).value.strip(),
                    base_url=self.query_one("#set-coach-base-url", Input).value.strip(),
                    api_key=self.query_one("#set-coach-api-key", Input).value.strip(),
                    team_provider=team["provider"],
                    team_base_url=team["base_url"],
                    team_api_key=team["api_key"],
                )
                if isinstance(override, str):
                    self.notify(override, severity="warning")
                    return
                coach["model"] = override

        # Build file access config
        writable_raw = self.query_one("#set-writable-paths", Input).value.strip()
        protected_raw = self.query_one("#set-protected-paths", Input).value.strip()
        writable_paths = [p.strip() for p in writable_raw.split(",") if p.strip()] if writable_raw else []
        protected_paths = [p.strip() for p in protected_raw.split(",") if p.strip()] if protected_raw else []

        max_file_size_raw = self.query_one("#set-max-file-size", Input).value.strip()
        max_files_raw = self.query_one("#set-max-files-per-turn", Input).value.strip()
        try:
            max_file_size = int(max_file_size_raw) if max_file_size_raw else 1048576
            if max_file_size < 1:
                raise ValueError
        except (ValueError, TypeError):
            self.notify("Max file size must be a positive integer.", severity="warning")
            return
        try:
            max_files = int(max_files_raw) if max_files_raw else 10
            if max_files < 1:
                raise ValueError
        except (ValueError, TypeError):
            self.notify("Max files per turn must be a positive integer.", severity="warning")
            return

        file_access = {
            "writable_paths": writable_paths,
            "protected_paths": protected_paths,
            "max_file_size_bytes": max_file_size,
            "max_files_per_turn": max_files,
            "enable_approvals": self.query_one("#set-approvals", Switch).value,
        }

        # Build worktrees config
        worktrees = {
            "enabled": self.query_one("#set-worktrees", Switch).value,
        }

        # Streaming
        streaming = self.query_one("#set-streaming", Switch).value

        # Assemble and save
        config: dict = {
            "model": model,
            "agents": self._agents,
            "file_access": file_access,
            "worktrees": worktrees,
            "streaming": streaming,
        }
        if coach is not None:
            config["coach"] = coach

        save_team_config(self.app.team_dir, config)
        self.notify("Settings saved.")

    # ── Navigation ───────────────────────────────────────────

    def action_go_back(self) -> None:
        self.app.pop_screen()

    # ── Agent CRUD ───────────────────────────────────────────

    def action_add_agent(self) -> None:
        from gotg.tui.modals.agent_edit import AgentEditModal

        self.app.push_screen(
            AgentEditModal(team_model=self._current_team_model()),
            callback=self._on_agent_added,
        )

    def _on_agent_added(self, result: dict | None) -> None:
        if result is None:
            return
        self._agents.append(result)
        self._refresh_agent_table()

    def action_edit_agent(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        key_str = get_selected_row_key(table)
        if key_str is None:
            return
        idx = int(key_str)
        if idx >= len(self._agents):
            return

        from gotg.tui.modals.agent_edit import AgentEditModal

        self.app.push_screen(
            AgentEditModal(agent=self._agents[idx], team_model=self._current_team_model()),
            callback=lambda result: self._on_agent_edited(result, idx),
        )

    def _on_agent_edited(self, result: dict | None, idx: int) -> None:
        if result is None:
            return
        self._agents[idx] = result
        self._refresh_agent_table()

    def action_remove_agent(self) -> None:
        if len(self._agents) <= 2:
            self.notify("At least 2 agents are required.", severity="warning")
            return

        table = self.query_one("#agent-table", DataTable)
        key_str = get_selected_row_key(table)
        if key_str is None:
            return
        idx = int(key_str)
        if idx >= len(self._agents):
            return

        agent_name = self._agents[idx]["name"]

        from gotg.tui.modals.confirm import ConfirmModal

        self.app.push_screen(
            ConfirmModal(f"Remove agent '{agent_name}'?"),
            callback=lambda confirmed: self._on_agent_removed(confirmed, idx),
        )

    def _on_agent_removed(self, confirmed: bool, idx: int) -> None:
        if not confirmed:
            return
        if idx < len(self._agents):
            self._agents.pop(idx)
            self._refresh_agent_table()
