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
from gotg.tui.helpers import get_selected_row_key


# ── Provider presets ─────────────────────────────────────────

PROVIDER_OPTIONS = [
    ("ollama", "ollama"),
    ("anthropic", "anthropic"),
    ("openai", "openai"),
]

PROVIDER_PRESETS = {
    "ollama": {"base_url": "http://localhost:11434", "api_key": ""},
    "anthropic": {"base_url": "https://api.anthropic.com", "api_key": "$ANTHROPIC_API_KEY"},
    "openai": {"base_url": "https://api.openai.com", "api_key": "$OPENAI_API_KEY"},
}

PROVIDER_MODELS: dict[str, list[tuple[str, str]]] = {
    "ollama": [
        ("qwen2.5-coder:7b", "qwen2.5-coder:7b"),
        ("qwen2.5-coder:14b", "qwen2.5-coder:14b"),
        ("qwen2.5-coder:32b", "qwen2.5-coder:32b"),
        ("llama3.2:8b", "llama3.2:8b"),
        ("deepseek-coder-v2:16b", "deepseek-coder-v2:16b"),
        ("codellama:13b", "codellama:13b"),
    ],
    "anthropic": [
        ("claude-sonnet-4-5-20250929", "claude-sonnet-4-5-20250929"),
        ("claude-opus-4-6", "claude-opus-4-6"),
        ("claude-haiku-4-5-20251001", "claude-haiku-4-5-20251001"),
    ],
    "openai": [
        ("gpt-4o", "gpt-4o"),
        ("gpt-4o-mini", "gpt-4o-mini"),
        ("o1", "o1"),
        ("o3-mini", "o3-mini"),
    ],
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
                PROVIDER_MODELS.get("ollama", []),
                allow_blank=True,
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

    def _refresh_agent_table(self) -> None:
        """Rebuild agent DataTable from self._agents."""
        table = self.query_one("#agent-table", DataTable)
        table.clear()
        for i, agent in enumerate(self._agents):
            table.add_row(agent["name"], agent.get("role", ""), key=str(i))

    def _update_coach_inputs(self, enabled: bool) -> None:
        """Enable or disable coach name/role inputs."""
        self.query_one("#set-coach-name", Input).disabled = not enabled
        self.query_one("#set-coach-role", Input).disabled = not enabled

    def _update_model_options(self, provider: str, current_model: str = "") -> None:
        """Update the model Select options for the given provider."""
        model_select = self.query_one("#set-model-name", Select)
        options = list(PROVIDER_MODELS.get(provider, []))
        # If current model isn't in the list, add it so it's selectable
        known_values = {v for _, v in options}
        if current_model and current_model not in known_values:
            options.insert(0, (current_model, current_model))
        model_select.set_options(options)
        if current_model:
            model_select.value = current_model
        elif options:
            model_select.value = options[0][1]

    # ── Provider preset ──────────────────────────────────────

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "set-provider":
            return
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

    # ── Coach toggle ─────────────────────────────────────────

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "set-coach-enabled":
            self._update_coach_inputs(event.value)

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
        model_name = str(model_select.value).strip() if model_select.value is not Select.BLANK else ""
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
            AgentEditModal(),
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
            AgentEditModal(agent=self._agents[idx]),
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
