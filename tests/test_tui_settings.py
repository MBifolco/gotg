"""Tests for TUI iteration 8: Settings screen."""

import json
from pathlib import Path

import pytest

from gotg.config import load_team_config, save_team_config


# ── Shared fixture ────────────────────────────────────────────


def _make_team_dir(tmp_path, *, include_file_access=True, include_worktrees=True):
    """Create a .team/ directory with full team.json for settings tests."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()

    config = {
        "model": {
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:7b",
        },
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "coach": {"name": "coach", "role": "Agile Coach"},
    }
    if include_file_access:
        config["file_access"] = {
            "writable_paths": ["src/**", "tests/**"],
            "protected_paths": [],
            "max_file_size_bytes": 1048576,
            "max_files_per_turn": 10,
            "enable_approvals": False,
        }
    if include_worktrees:
        config["worktrees"] = {"enabled": False}

    (team_dir / "team.json").write_text(json.dumps(config, indent=2) + "\n")

    # iteration.json (needed for GotgApp)
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [
            {"id": "iter-1", "description": "Test", "phase": "refinement",
             "status": "in-progress", "max_turns": 30},
        ],
        "current": "iter-1",
    }))
    iter_dir = team_dir / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    return team_dir


# ── Config: load_team_config / save_team_config ──────────────


def test_load_team_config(tmp_path):
    team_dir = _make_team_dir(tmp_path)
    config = load_team_config(team_dir)
    assert config["model"]["provider"] == "ollama"
    assert len(config["agents"]) == 2
    assert config["coach"]["name"] == "coach"
    assert config["file_access"]["enable_approvals"] is False


def test_save_team_config(tmp_path):
    team_dir = _make_team_dir(tmp_path)
    config = load_team_config(team_dir)
    config["model"]["model"] = "new-model"
    save_team_config(team_dir, config)
    reloaded = load_team_config(team_dir)
    assert reloaded["model"]["model"] == "new-model"


def test_save_team_config_trailing_newline(tmp_path):
    team_dir = _make_team_dir(tmp_path)
    config = load_team_config(team_dir)
    save_team_config(team_dir, config)
    raw = (team_dir / "team.json").read_text()
    assert raw.endswith("\n")
    assert not raw.endswith("\n\n")


# ── AgentEditModal ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_modal_submit():
    """AgentEditModal returns dict with name and role."""
    from textual.app import App
    from gotg.tui.modals.agent_edit import AgentEditModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                AgentEditModal(),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one("#agent-name").value = "agent-3"
        app.screen.query_one("#agent-role").value = "Tester"
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert results == [{"name": "agent-3", "role": "Tester"}]


@pytest.mark.asyncio
async def test_agent_modal_cancel():
    """AgentEditModal returns None on escape."""
    from textual.app import App
    from gotg.tui.modals.agent_edit import AgentEditModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                AgentEditModal(),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert results == [None]


@pytest.mark.asyncio
async def test_agent_modal_empty_name_stays_open():
    """AgentEditModal does not dismiss with empty name."""
    from textual.app import App
    from gotg.tui.modals.agent_edit import AgentEditModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                AgentEditModal(),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        # Leave name empty, try to save
        await pilot.press("ctrl+s")
        await pilot.pause()
        # Should still be on the modal
        assert isinstance(app.screen, AgentEditModal)
        assert results == []


@pytest.mark.asyncio
async def test_agent_modal_prefills_for_edit():
    """AgentEditModal pre-fills name and role when agent is passed."""
    from textual.app import App
    from textual.widgets import Input
    from gotg.tui.modals.agent_edit import AgentEditModal

    app = App()
    async with app.run_test() as pilot:
        app.push_screen(AgentEditModal(agent={"name": "bob", "role": "QA"}))
        await pilot.pause()
        await pilot.pause()
        assert app.screen.query_one("#agent-name", Input).value == "bob"
        assert app.screen.query_one("#agent-role", Input).value == "QA"


@pytest.mark.asyncio
async def test_agent_modal_default_role():
    """AgentEditModal defaults role to 'Software Engineer' when left blank."""
    from textual.app import App
    from gotg.tui.modals.agent_edit import AgentEditModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                AgentEditModal(),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one("#agent-name").value = "agent-x"
        # Leave role empty
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert results == [{"name": "agent-x", "role": "Software Engineer"}]


# ── SettingsScreen loading ───────────────────────────────────


@pytest.mark.asyncio
async def test_settings_loads_model_fields(tmp_path):
    """SettingsScreen populates model fields from team.json."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Select

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        assert app.screen.query_one("#set-provider", Select).value == "ollama"
        assert app.screen.query_one("#set-model-name", Select).value == "qwen2.5-coder:7b"
        assert app.screen.query_one("#set-base-url", Input).value == "http://localhost:11434"


@pytest.mark.asyncio
async def test_settings_loads_agents(tmp_path):
    """SettingsScreen populates agent table from team.json."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import DataTable

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        table = app.screen.query_one("#agent-table", DataTable)
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_settings_loads_switches(tmp_path):
    """SettingsScreen populates switch values from team.json."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        assert app.screen.query_one("#set-coach-enabled", Switch).value is True
        assert app.screen.query_one("#set-approvals", Switch).value is False
        assert app.screen.query_one("#set-worktrees", Switch).value is False
        assert app.screen.query_one("#set-streaming", Switch).value is False


@pytest.mark.asyncio
async def test_settings_loads_streaming_enabled(tmp_path):
    """SettingsScreen loads streaming=true from team.json."""
    team_dir = _make_team_dir(tmp_path)
    config = json.loads((team_dir / "team.json").read_text())
    config["streaming"] = True
    (team_dir / "team.json").write_text(json.dumps(config, indent=2) + "\n")

    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        assert app.screen.query_one("#set-streaming", Switch).value is True


@pytest.mark.asyncio
async def test_settings_handles_missing_optional_sections(tmp_path):
    """SettingsScreen works when file_access and worktrees are missing."""
    team_dir = _make_team_dir(tmp_path, include_file_access=False, include_worktrees=False)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Should have defaults
        assert app.screen.query_one("#set-max-file-size", Input).value == "1048576"
        assert app.screen.query_one("#set-max-files-per-turn", Input).value == "10"
        assert app.screen.query_one("#set-worktrees", Switch).value is False


# ── SettingsScreen save ──────────────────────────────────────


@pytest.mark.asyncio
async def test_settings_save_model(tmp_path):
    """Ctrl+S saves model changes to disk."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Select

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#set-model-name", Select).value = "llama3.2:8b"
        await pilot.press("ctrl+s")
        await pilot.pause()

    saved = json.loads((team_dir / "team.json").read_text())
    assert saved["model"]["model"] == "llama3.2:8b"


@pytest.mark.asyncio
async def test_settings_save_all_sections(tmp_path):
    """Ctrl+S saves all sections to disk."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Select, Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Change provider to openai first so gpt-4o is in the list
        app.screen.query_one("#set-provider", Select).value = "openai"
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one("#set-model-name", Select).value = "gpt-4o"
        app.screen.query_one("#set-coach-name", Input).value = "my-coach"
        app.screen.query_one("#set-writable-paths", Input).value = "lib/**, bin/**"
        app.screen.query_one("#set-worktrees", Switch).value = True
        app.screen.query_one("#set-streaming", Switch).value = True
        await pilot.press("ctrl+s")
        await pilot.pause()

    saved = json.loads((team_dir / "team.json").read_text())
    assert saved["model"]["model"] == "gpt-4o"
    assert saved["coach"]["name"] == "my-coach"
    assert saved["file_access"]["writable_paths"] == ["lib/**", "bin/**"]
    assert saved["worktrees"]["enabled"] is True
    assert saved["streaming"] is True


@pytest.mark.asyncio
async def test_settings_validation_empty_model(tmp_path):
    """Ctrl+S with blank model name does not save."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Select

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#set-model-name", Select).value = Select.BLANK
        await pilot.press("ctrl+s")
        await pilot.pause()

        # Still on settings screen
        assert isinstance(app.screen, SettingsScreen)
        # Original value unchanged on disk
        saved = json.loads((team_dir / "team.json").read_text())
        assert saved["model"]["model"] == "qwen2.5-coder:7b"


@pytest.mark.asyncio
async def test_settings_blank_model_remains_valid_after_provider_change(tmp_path):
    """Blank model selection remains legal after model options are refreshed."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Select

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Force option rebuild path.
        app.screen.query_one("#set-provider", Select).value = "anthropic"
        await pilot.pause()
        await pilot.pause()

        # Regression contract: this assignment must never raise.
        app.screen.query_one("#set-model-name", Select).value = Select.BLANK
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, SettingsScreen)
        saved = json.loads((team_dir / "team.json").read_text())
        assert saved["model"]["model"] == "qwen2.5-coder:7b"


@pytest.mark.asyncio
async def test_settings_validation_invalid_file_size(tmp_path):
    """Ctrl+S with non-numeric max file size does not save."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#set-max-file-size", Input).value = "not-a-number"
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, SettingsScreen)


@pytest.mark.asyncio
async def test_settings_escape_goes_back(tmp_path):
    """Escape pops the settings screen."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from gotg.tui.screens.home import HomeScreen

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(app.screen, HomeScreen)


# ── Provider presets ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_change_fills_base_url(tmp_path):
    """Changing provider updates base_url."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Select

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Change provider from ollama to anthropic
        app.screen.query_one("#set-provider", Select).value = "anthropic"
        await pilot.pause()
        await pilot.pause()

        base_url = app.screen.query_one("#set-base-url", Input).value
        assert base_url == "https://api.anthropic.com"


@pytest.mark.asyncio
async def test_provider_change_updates_model_options(tmp_path):
    """Changing provider updates the model dropdown options."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen, PROVIDER_MODELS
    from textual.widgets import Select

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Initially ollama — model should be one of ollama models
        model_val = app.screen.query_one("#set-model-name", Select).value
        assert model_val == "qwen2.5-coder:7b"

        # Change to anthropic
        app.screen.query_one("#set-provider", Select).value = "anthropic"
        await pilot.pause()
        await pilot.pause()

        # Model should be set to first anthropic model
        model_val = app.screen.query_one("#set-model-name", Select).value
        anthropic_first = PROVIDER_MODELS["anthropic"][0][1]
        assert model_val == anthropic_first

        # Change to openai
        app.screen.query_one("#set-provider", Select).value = "openai"
        await pilot.pause()
        await pilot.pause()

        model_val = app.screen.query_one("#set-model-name", Select).value
        openai_first = PROVIDER_MODELS["openai"][0][1]
        assert model_val == openai_first


@pytest.mark.asyncio
async def test_custom_model_preserved_on_load(tmp_path):
    """A custom model name not in presets is still shown in the Select."""
    team_dir = _make_team_dir(tmp_path)
    # Write a custom model name
    config = json.loads((team_dir / "team.json").read_text())
    config["model"]["model"] = "my-custom-finetuned-model"
    (team_dir / "team.json").write_text(json.dumps(config, indent=2) + "\n")

    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Select

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        model_val = app.screen.query_one("#set-model-name", Select).value
        assert model_val == "my-custom-finetuned-model"


# ── Coach toggle ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_coach_toggle_disables_inputs(tmp_path):
    """Turning off coach switch disables name/role inputs."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Coach is enabled by default
        assert app.screen.query_one("#set-coach-name", Input).disabled is False

        # Turn off coach
        app.screen.query_one("#set-coach-enabled", Switch).value = False
        await pilot.pause()

        assert app.screen.query_one("#set-coach-name", Input).disabled is True
        assert app.screen.query_one("#set-coach-role", Input).disabled is True


@pytest.mark.asyncio
async def test_coach_disabled_saves_no_coach(tmp_path):
    """Saving with coach disabled omits coach from team.json."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#set-coach-enabled", Switch).value = False
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

    saved = json.loads((team_dir / "team.json").read_text())
    assert "coach" not in saved


# ── Agent CRUD ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_agent(tmp_path):
    """A key opens AgentEditModal, submit adds row to table."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from gotg.tui.modals.agent_edit import AgentEditModal
    from textual.widgets import DataTable

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, AgentEditModal)

        app.screen.query_one("#agent-name").value = "agent-3"
        app.screen.query_one("#agent-role").value = "Tester"
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

        # Back on settings, table has 3 agents
        assert isinstance(app.screen, SettingsScreen)
        table = app.screen.query_one("#agent-table", DataTable)
        assert table.row_count == 3


@pytest.mark.asyncio
async def test_edit_agent(tmp_path):
    """E key opens AgentEditModal pre-filled, submit updates table."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from gotg.tui.modals.agent_edit import AgentEditModal
    from textual.widgets import DataTable, Input

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Focus the agent table and select first row
        table = app.screen.query_one("#agent-table", DataTable)
        table.focus()
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, AgentEditModal)

        # Verify pre-filled
        assert app.screen.query_one("#agent-name", Input).value == "agent-1"

        # Change role
        app.screen.query_one("#agent-role").value = "Tech Lead"
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

        # Verify updated in settings screen's internal list
        assert isinstance(app.screen, SettingsScreen)
        assert app.screen._agents[0]["role"] == "Tech Lead"


@pytest.mark.asyncio
async def test_remove_agent_confirm(tmp_path):
    """Delete key with 3+ agents opens ConfirmModal, confirm removes agent."""
    team_dir = _make_team_dir(tmp_path)
    # Add a third agent so we can remove one
    config = json.loads((team_dir / "team.json").read_text())
    config["agents"].append({"name": "agent-3", "role": "QA"})
    (team_dir / "team.json").write_text(json.dumps(config, indent=2))

    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from gotg.tui.modals.confirm import ConfirmModal
    from textual.widgets import DataTable

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        table = app.screen.query_one("#agent-table", DataTable)
        table.focus()
        await pilot.pause()

        assert table.row_count == 3

        await pilot.press("delete")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)

        await pilot.press("y")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, SettingsScreen)
        table = app.screen.query_one("#agent-table", DataTable)
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_remove_agent_cancel(tmp_path):
    """Cancel on ConfirmModal keeps the agent."""
    team_dir = _make_team_dir(tmp_path)
    config = json.loads((team_dir / "team.json").read_text())
    config["agents"].append({"name": "agent-3", "role": "QA"})
    (team_dir / "team.json").write_text(json.dumps(config, indent=2))

    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from gotg.tui.modals.confirm import ConfirmModal
    from textual.widgets import DataTable

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        table = app.screen.query_one("#agent-table", DataTable)
        table.focus()
        await pilot.pause()

        await pilot.press("delete")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)

        await pilot.press("n")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, SettingsScreen)
        table = app.screen.query_one("#agent-table", DataTable)
        assert table.row_count == 3


@pytest.mark.asyncio
async def test_remove_last_two_agents_blocked(tmp_path):
    """Cannot remove agent when only 2 remain."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import DataTable

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        table = app.screen.query_one("#agent-table", DataTable)
        table.focus()
        await pilot.pause()
        assert table.row_count == 2

        await pilot.press("delete")
        await pilot.pause()
        await pilot.pause()

        # Should still be on settings (no confirm modal)
        assert isinstance(app.screen, SettingsScreen)
        assert table.row_count == 2


# ── HomeScreen integration ───────────────────────────────────


@pytest.mark.asyncio
async def test_home_s_opens_settings(tmp_path):
    """S key from HomeScreen opens SettingsScreen."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, SettingsScreen)


# ── providers.py unit tests ──────────────────────────────────


def test_provider_runtime_config_no_ui_metadata():
    """provider_runtime_config returns only runtime keys (no models/default_model)."""
    from gotg.providers import provider_runtime_config

    config = provider_runtime_config("anthropic")
    assert "provider" in config
    assert "model" in config
    assert "base_url" in config
    assert "models" not in config
    assert "default_model" not in config
    assert config["provider"] == "anthropic"
    assert config["model"] == "claude-sonnet-4-6"
    assert config["api_key"] == "$ANTHROPIC_API_KEY"


def test_provider_runtime_config_custom_model():
    """provider_runtime_config accepts a custom model override."""
    from gotg.providers import provider_runtime_config

    config = provider_runtime_config("openai", "gpt-4o-mini")
    assert config["model"] == "gpt-4o-mini"


def test_provider_runtime_config_ollama_no_api_key():
    """Ollama has no api_key (empty string), so it's omitted from config."""
    from gotg.providers import provider_runtime_config

    config = provider_runtime_config("ollama")
    assert "api_key" not in config


def test_provider_runtime_config_gemini():
    """Gemini provider returns correct runtime config."""
    from gotg.providers import provider_runtime_config

    config = provider_runtime_config("gemini")
    assert config["provider"] == "gemini"
    assert config["model"] == "gemini-2.5-flash"
    assert config["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert config["api_key"] == "$GEMINI_API_KEY"


def test_build_model_override_cross_provider_error():
    """Cross-provider override without base_url returns error string."""
    from gotg.providers import build_model_override

    result = build_model_override(
        provider="openai", model="gpt-4o", base_url="", api_key="$OPENAI_API_KEY",
        team_provider="anthropic", team_base_url="https://api.anthropic.com",
        team_api_key="$ANTHROPIC_API_KEY",
    )
    assert isinstance(result, str)
    assert "Base URL" in result


def test_build_model_override_cross_provider_persists_api_key():
    """Cross-provider override always persists api_key."""
    from gotg.providers import build_model_override

    result = build_model_override(
        provider="openai", model="gpt-4o",
        base_url="https://api.openai.com", api_key="",
        team_provider="anthropic", team_base_url="https://api.anthropic.com",
        team_api_key="$ANTHROPIC_API_KEY",
    )
    assert isinstance(result, dict)
    assert result["api_key"] == ""
    assert result["base_url"] == "https://api.openai.com"


def test_build_model_override_same_provider_minimal():
    """Same-provider override with matching fields omits base_url/api_key."""
    from gotg.providers import build_model_override

    result = build_model_override(
        provider="anthropic", model="claude-opus-4-6",
        base_url="https://api.anthropic.com", api_key="$ANTHROPIC_API_KEY",
        team_provider="anthropic", team_base_url="https://api.anthropic.com",
        team_api_key="$ANTHROPIC_API_KEY",
    )
    assert isinstance(result, dict)
    assert result == {"provider": "anthropic", "model": "claude-opus-4-6"}


def test_build_model_override_same_provider_explicit_clear():
    """Same-provider override persists api_key when it differs (even empty)."""
    from gotg.providers import build_model_override

    result = build_model_override(
        provider="openai", model="gpt-4o-mini",
        base_url="https://api.openai.com", api_key="",
        team_provider="openai", team_base_url="https://api.openai.com",
        team_api_key="$OPENAI_API_KEY",
    )
    assert isinstance(result, dict)
    assert result["api_key"] == ""
    assert "base_url" not in result  # matching, so omitted


def test_build_model_override_missing_model():
    """build_model_override returns error when model is empty."""
    from gotg.providers import build_model_override

    result = build_model_override(
        provider="anthropic", model="",
        base_url="https://api.anthropic.com", api_key="$ANTHROPIC_API_KEY",
        team_provider="anthropic", team_base_url="https://api.anthropic.com",
        team_api_key="$ANTHROPIC_API_KEY",
    )
    assert isinstance(result, str)
    assert "Model name" in result


# ── AgentEditModal model override ────────────────────────────


@pytest.mark.asyncio
async def test_agent_override_on_returns_model():
    """AgentEditModal with override fields produces model dict in result."""
    from textual.app import App
    from gotg.tui.modals.agent_edit import AgentEditModal

    results = []
    team_model = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "base_url": "https://api.anthropic.com",
        "api_key": "$ANTHROPIC_API_KEY",
    }

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                AgentEditModal(team_model=team_model),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one("#agent-name").value = "agent-x"
        # Toggle override ON
        app.screen.query_one("#agent-model-override").value = True
        await pilot.pause()
        # Change model name
        app.screen.query_one("#agent-model-name").value = "claude-opus-4-6"
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert len(results) == 1
    assert "model" in results[0]
    assert results[0]["model"]["provider"] == "anthropic"
    assert results[0]["model"]["model"] == "claude-opus-4-6"


@pytest.mark.asyncio
async def test_agent_override_off_no_model():
    """AgentEditModal without override does not include model key."""
    from textual.app import App
    from gotg.tui.modals.agent_edit import AgentEditModal

    results = []

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                AgentEditModal(),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one("#agent-name").value = "agent-y"
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert len(results) == 1
    assert "model" not in results[0]


@pytest.mark.asyncio
async def test_agent_cross_provider_validation():
    """Agent cross-provider override with empty base_url shows warning, stays open."""
    from textual.app import App
    from textual.widgets import Switch, Input, Select
    from gotg.tui.modals.agent_edit import AgentEditModal

    results = []
    team_model = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "base_url": "https://api.anthropic.com",
        "api_key": "$ANTHROPIC_API_KEY",
    }

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                AgentEditModal(team_model=team_model),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one("#agent-name").value = "agent-z"
        app.screen.query_one("#agent-model-override", Switch).value = True
        await pilot.pause()
        # Change provider to openai (cross-provider)
        app.screen.query_one("#agent-provider", Select).value = "openai"
        await pilot.pause()
        # Clear base_url to trigger validation error
        app.screen.query_one("#agent-base-url", Input).value = ""
        await pilot.press("ctrl+s")
        await pilot.pause()

        # Should still be on modal (not dismissed)
        assert isinstance(app.screen, AgentEditModal)
        assert results == []


@pytest.mark.asyncio
async def test_agent_same_provider_minimal():
    """Same-provider override with matching base_url/api_key returns minimal dict."""
    from textual.app import App
    from textual.widgets import Switch
    from gotg.tui.modals.agent_edit import AgentEditModal

    results = []
    team_model = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "base_url": "https://api.anthropic.com",
        "api_key": "$ANTHROPIC_API_KEY",
    }

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                AgentEditModal(team_model=team_model),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one("#agent-name").value = "agent-minimal"
        app.screen.query_one("#agent-model-override", Switch).value = True
        await pilot.pause()
        # Change only the model name, keep base_url and api_key same as team
        app.screen.query_one("#agent-model-name").value = "claude-opus-4-6"
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert len(results) == 1
    model = results[0]["model"]
    assert model == {"provider": "anthropic", "model": "claude-opus-4-6"}
    assert "base_url" not in model
    assert "api_key" not in model


@pytest.mark.asyncio
async def test_agent_same_provider_explicit_clear():
    """Same-provider override with cleared api_key persists empty string."""
    from textual.app import App
    from textual.widgets import Switch, Input
    from gotg.tui.modals.agent_edit import AgentEditModal

    results = []
    team_model = {
        "provider": "openai",
        "model": "gpt-4o",
        "base_url": "https://api.openai.com",
        "api_key": "$OPENAI_API_KEY",
    }

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                AgentEditModal(team_model=team_model),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        app.screen.query_one("#agent-name").value = "agent-clear"
        app.screen.query_one("#agent-model-override", Switch).value = True
        await pilot.pause()
        # Clear api_key (differs from team's $OPENAI_API_KEY)
        app.screen.query_one("#agent-api-key", Input).value = ""
        app.screen.query_one("#agent-model-name").value = "gpt-4o-mini"
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert len(results) == 1
    model = results[0]["model"]
    assert model["api_key"] == ""
    assert "base_url" not in model  # same as team, omitted


@pytest.mark.asyncio
async def test_agent_toggle_on_seeds_from_team_model():
    """Toggle override ON auto-fills from team_model, not provider defaults."""
    from textual.app import App
    from textual.widgets import Switch, Input, Select
    from gotg.tui.modals.agent_edit import AgentEditModal

    team_model = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "base_url": "https://api.anthropic.com",
        "api_key": "$ANTHROPIC_API_KEY",
    }

    app = App()
    async with app.run_test() as pilot:
        app.push_screen(AgentEditModal(team_model=team_model))
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#agent-model-override", Switch).value = True
        await pilot.pause()

        assert str(app.screen.query_one("#agent-provider", Select).value) == "anthropic"
        assert str(app.screen.query_one("#agent-model-name", Select).value) == "claude-sonnet-4-5-20250929"
        assert app.screen.query_one("#agent-base-url", Input).value == "https://api.anthropic.com"
        assert app.screen.query_one("#agent-api-key", Input).value == "$ANTHROPIC_API_KEY"


@pytest.mark.asyncio
async def test_agent_toggle_on_seeds_custom_team_values():
    """Toggle override ON with custom team values that differ from provider defaults."""
    from textual.app import App
    from textual.widgets import Switch, Input, Select
    from gotg.tui.modals.agent_edit import AgentEditModal

    team_model = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "base_url": "https://custom-proxy.example.com",
        "api_key": "sk-custom-key-123",
    }

    app = App()
    async with app.run_test() as pilot:
        app.push_screen(AgentEditModal(team_model=team_model))
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#agent-model-override", Switch).value = True
        await pilot.pause()

        # Fields should show the custom team values, not provider defaults
        assert app.screen.query_one("#agent-base-url", Input).value == "https://custom-proxy.example.com"
        assert app.screen.query_one("#agent-api-key", Input).value == "sk-custom-key-123"
        assert str(app.screen.query_one("#agent-model-name", Select).value) == "claude-sonnet-4-5-20250929"


@pytest.mark.asyncio
async def test_coach_toggle_on_seeds_custom_team_values(tmp_path):
    """Toggle coach override ON with custom global form values that differ from provider defaults."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Select, Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Change the global form to custom values
        app.screen.query_one("#set-base-url", Input).value = "https://custom-proxy.example.com"
        app.screen.query_one("#set-api-key", Input).value = "sk-custom-key-456"
        await pilot.pause()

        # Toggle coach override ON
        app.screen.query_one("#set-coach-model-override", Switch).value = True
        await pilot.pause()

        # Coach fields should show the custom team form values, not provider defaults
        assert app.screen.query_one("#set-coach-base-url", Input).value == "https://custom-proxy.example.com"
        assert app.screen.query_one("#set-coach-api-key", Input).value == "sk-custom-key-456"
        assert app.screen.query_one("#set-coach-model-name", Input).value == "qwen2.5-coder:7b"


@pytest.mark.asyncio
async def test_coach_disabled_hides_override_row(tmp_path):
    """Coach switch OFF hides the entire Custom model row, not just the switch."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Coach is enabled, override row should be visible
        assert app.screen.query_one("#coach-model-override-row").display is True

        # Disable coach
        app.screen.query_one("#set-coach-enabled", Switch).value = False
        await pilot.pause()

        # Entire row container should be hidden
        assert app.screen.query_one("#coach-model-override-row").display is False


@pytest.mark.asyncio
async def test_agent_provider_change_autofills():
    """Changing agent provider updates base_url, api_key, and model name."""
    from textual.app import App
    from textual.widgets import Switch, Input, Select
    from gotg.tui.modals.agent_edit import AgentEditModal

    team_model = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "base_url": "https://api.anthropic.com",
        "api_key": "$ANTHROPIC_API_KEY",
    }

    app = App()
    async with app.run_test() as pilot:
        app.push_screen(AgentEditModal(team_model=team_model))
        await pilot.pause()
        await pilot.pause()

        # Turn on override
        app.screen.query_one("#agent-model-override", Switch).value = True
        await pilot.pause()

        # Change provider to openai
        app.screen.query_one("#agent-provider", Select).value = "openai"
        await pilot.pause()

        assert app.screen.query_one("#agent-base-url", Input).value == "https://api.openai.com"
        assert app.screen.query_one("#agent-api-key", Input).value == "$OPENAI_API_KEY"
        assert str(app.screen.query_one("#agent-model-name", Select).value) == "gpt-4.1-mini"


@pytest.mark.asyncio
async def test_agent_provider_change_preserves_custom_model():
    """Changing agent provider does not overwrite a custom model name."""
    from textual.app import App
    from textual.widgets import Switch, Input, Select
    from gotg.tui.modals.agent_edit import AgentEditModal

    team_model = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "base_url": "https://api.anthropic.com",
        "api_key": "$ANTHROPIC_API_KEY",
    }

    app = App()
    async with app.run_test() as pilot:
        app.push_screen(AgentEditModal(team_model=team_model))
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#agent-model-override", Switch).value = True
        await pilot.pause()

        # Pick a non-default model (user's deliberate choice)
        app.screen.query_one("#agent-model-name", Select).value = "claude-opus-4-6"

        # Change provider
        app.screen.query_one("#agent-provider", Select).value = "openai"
        await pilot.pause()

        # User's choice should be preserved (not replaced with openai default)
        assert str(app.screen.query_one("#agent-model-name", Select).value) == "claude-opus-4-6"


@pytest.mark.asyncio
async def test_agent_loaded_custom_override_provider_change():
    """Loading custom override model, then changing provider preserves custom name."""
    from textual.app import App
    from textual.widgets import Input, Select
    from gotg.tui.modals.agent_edit import AgentEditModal

    team_model = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5-20250929",
        "base_url": "https://api.anthropic.com",
        "api_key": "$ANTHROPIC_API_KEY",
    }
    agent = {
        "name": "agent-1",
        "role": "SE",
        "model": {"provider": "openai", "model": "my-finetuned-gpt",
                   "base_url": "https://api.openai.com", "api_key": "$OPENAI_API_KEY"},
    }

    app = App()
    async with app.run_test() as pilot:
        app.push_screen(AgentEditModal(agent=agent, team_model=team_model))
        await pilot.pause()
        await pilot.pause()

        # Model should be loaded
        assert str(app.screen.query_one("#agent-model-name", Select).value) == "my-finetuned-gpt"

        # Change provider to anthropic
        app.screen.query_one("#agent-provider", Select).value = "anthropic"
        await pilot.pause()

        # Custom model name should NOT be replaced
        assert str(app.screen.query_one("#agent-model-name", Select).value) == "my-finetuned-gpt"


@pytest.mark.asyncio
async def test_agent_minimal_override_round_trip():
    """Existing minimal override round-trips without adding explicit clears."""
    from textual.app import App
    from textual.widgets import Switch
    from gotg.tui.modals.agent_edit import AgentEditModal

    results = []
    team_model = {
        "provider": "openai",
        "model": "gpt-4o",
        "base_url": "https://api.openai.com",
        "api_key": "$OPENAI_API_KEY",
    }
    agent = {
        "name": "agent-1",
        "role": "SE",
        "model": {"provider": "openai", "model": "gpt-4o-mini"},
    }

    class TestApp(App):
        def on_mount(self):
            self.push_screen(
                AgentEditModal(agent=agent, team_model=team_model),
                callback=lambda r: results.append(r),
            )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()

        # Verify override is ON and fields show inherited values
        assert app.screen.query_one("#agent-model-override", Switch).value is True
        # Save without changes
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert len(results) == 1
    # Should stay minimal — no base_url or api_key added
    assert results[0]["model"] == {"provider": "openai", "model": "gpt-4o-mini"}


# ── Agent table Model column ────────────────────────────────


@pytest.mark.asyncio
async def test_agent_table_model_column(tmp_path):
    """Agent table shows override model name or '(default)'."""
    team_dir = _make_team_dir(tmp_path)
    config = json.loads((team_dir / "team.json").read_text())
    config["agents"][0]["model"] = {"provider": "openai", "model": "gpt-4o-mini",
                                     "base_url": "https://api.openai.com"}
    (team_dir / "team.json").write_text(json.dumps(config, indent=2) + "\n")

    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import DataTable

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        table = app.screen.query_one("#agent-table", DataTable)
        # First agent has override, second doesn't
        row0 = table.get_row(table.ordered_rows[0].key)
        row1 = table.get_row(table.ordered_rows[1].key)
        assert row0[2] == "gpt-4o-mini"
        assert row1[2] == "(default)"


# ── Coach override in SettingsScreen ─────────────────────────


@pytest.mark.asyncio
async def test_coach_override_save_load(tmp_path):
    """Enable coach + custom model → save → reload → fields populated."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Select, Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Enable coach override
        app.screen.query_one("#set-coach-model-override", Switch).value = True
        await pilot.pause()
        # Change coach provider to openai
        app.screen.query_one("#set-coach-provider", Select).value = "openai"
        await pilot.pause()
        app.screen.query_one("#set-coach-model-name", Input).value = "gpt-4o-mini"

        await pilot.press("ctrl+s")
        await pilot.pause()

    # Verify saved
    saved = json.loads((team_dir / "team.json").read_text())
    assert "model" in saved["coach"]
    assert saved["coach"]["model"]["provider"] == "openai"
    assert saved["coach"]["model"]["model"] == "gpt-4o-mini"

    # Reload and verify
    app2 = GotgApp(team_dir)
    async with app2.run_test() as pilot:
        await pilot.pause()
        app2.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        assert app2.screen.query_one("#set-coach-model-override", Switch).value is True
        assert app2.screen.query_one("#set-coach-model-name", Input).value == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_coach_override_off_no_model(tmp_path):
    """Coach enabled, custom model off → no model in saved coach."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Coach override switch should be off by default
        assert app.screen.query_one("#set-coach-model-override", Switch).value is False

        await pilot.press("ctrl+s")
        await pilot.pause()

    saved = json.loads((team_dir / "team.json").read_text())
    assert "model" not in saved["coach"]


@pytest.mark.asyncio
async def test_coach_disabled_hides_override(tmp_path):
    """Coach switch OFF hides override controls."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # First enable override
        app.screen.query_one("#set-coach-model-override", Switch).value = True
        await pilot.pause()
        assert app.screen.query_one("#coach-model-fields").display is True

        # Disable coach entirely
        app.screen.query_one("#set-coach-enabled", Switch).value = False
        await pilot.pause()

        # Override switch should be forced off and hidden
        assert app.screen.query_one("#set-coach-model-override", Switch).value is False
        assert app.screen.query_one("#coach-model-fields").display is False


@pytest.mark.asyncio
async def test_coach_toggle_on_seeds_from_form(tmp_path):
    """Toggle coach override ON auto-fills from current team model form state."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Select, Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        # Toggle coach override ON — should seed from team model (ollama defaults)
        app.screen.query_one("#set-coach-model-override", Switch).value = True
        await pilot.pause()

        assert str(app.screen.query_one("#set-coach-provider", Select).value) == "ollama"
        assert app.screen.query_one("#set-coach-model-name", Input).value == "qwen2.5-coder:7b"
        assert app.screen.query_one("#set-coach-base-url", Input).value == "http://localhost:11434"


@pytest.mark.asyncio
async def test_coach_provider_change_autofills(tmp_path):
    """Changing coach provider updates base_url, api_key, and model name."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Select, Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#set-coach-model-override", Switch).value = True
        await pilot.pause()

        # Change provider to anthropic
        app.screen.query_one("#set-coach-provider", Select).value = "anthropic"
        await pilot.pause()

        assert app.screen.query_one("#set-coach-base-url", Input).value == "https://api.anthropic.com"
        assert app.screen.query_one("#set-coach-api-key", Input).value == "$ANTHROPIC_API_KEY"
        assert app.screen.query_one("#set-coach-model-name", Input).value == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_coach_provider_change_preserves_custom_model(tmp_path):
    """Changing coach provider does not overwrite a custom model name."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Select, Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        app.screen.query_one("#set-coach-model-override", Switch).value = True
        await pilot.pause()

        # Type custom model
        app.screen.query_one("#set-coach-model-name", Input).value = "my-custom-coach-model"

        # Change provider
        app.screen.query_one("#set-coach-provider", Select).value = "anthropic"
        await pilot.pause()

        assert app.screen.query_one("#set-coach-model-name", Input).value == "my-custom-coach-model"


@pytest.mark.asyncio
async def test_coach_loaded_custom_override_provider_change(tmp_path):
    """Loading custom coach override model, then changing provider preserves custom name."""
    team_dir = _make_team_dir(tmp_path)
    config = json.loads((team_dir / "team.json").read_text())
    config["coach"]["model"] = {
        "provider": "openai", "model": "my-coach-ft",
        "base_url": "https://api.openai.com", "api_key": "$OPENAI_API_KEY",
    }
    (team_dir / "team.json").write_text(json.dumps(config, indent=2) + "\n")

    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Input, Select, Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        assert app.screen.query_one("#set-coach-model-override", Switch).value is True
        assert app.screen.query_one("#set-coach-model-name", Input).value == "my-coach-ft"

        # Change provider to anthropic
        app.screen.query_one("#set-coach-provider", Select).value = "anthropic"
        await pilot.pause()

        # Custom model name preserved
        assert app.screen.query_one("#set-coach-model-name", Input).value == "my-coach-ft"


@pytest.mark.asyncio
async def test_coach_minimal_override_round_trip(tmp_path):
    """Existing minimal coach override round-trips without adding explicit clears."""
    team_dir = _make_team_dir(tmp_path)
    config = json.loads((team_dir / "team.json").read_text())
    config["coach"]["model"] = {"provider": "ollama", "model": "llama3.2:8b"}
    (team_dir / "team.json").write_text(json.dumps(config, indent=2) + "\n")

    from gotg.tui.app import GotgApp
    from gotg.tui.screens.settings import SettingsScreen
    from textual.widgets import Switch

    app = GotgApp(team_dir)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        await pilot.pause()

        assert app.screen.query_one("#set-coach-model-override", Switch).value is True

        # Save without changes
        await pilot.press("ctrl+s")
        await pilot.pause()

    saved = json.loads((team_dir / "team.json").read_text())
    # Should stay minimal
    assert saved["coach"]["model"] == {"provider": "ollama", "model": "llama3.2:8b"}


# ── E2E resolver tests ──────────────────────────────────────


def test_e2e_resolver_cross_provider(tmp_path):
    """Save cross-provider override → TeamContext resolver returns correct config."""
    team_dir = _make_team_dir(tmp_path)
    # Write .env with both keys
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=test-ant-key\nOPENAI_API_KEY=test-oai-key\n"
    )
    config = json.loads((team_dir / "team.json").read_text())
    config["model"]["api_key"] = "$ANTHROPIC_API_KEY"
    config["agents"][0]["model"] = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com",
        "api_key": "$OPENAI_API_KEY",
    }
    (team_dir / "team.json").write_text(json.dumps(config, indent=2) + "\n")

    from gotg.context import TeamContext

    ctx = TeamContext.from_team_dir(team_dir)
    # agent-1 should get openai config
    a1_config = ctx.model_resolver("agent-1")
    assert a1_config["provider"] == "openai"
    assert a1_config["model"] == "gpt-4o-mini"
    assert a1_config["base_url"] == "https://api.openai.com"
    assert a1_config["api_key"] == "test-oai-key"

    # agent-2 should get team default
    a2_config = ctx.model_resolver("agent-2")
    assert a2_config["provider"] == "ollama"


def test_e2e_resolver_same_provider_clear(tmp_path):
    """Save same-provider override clearing api_key → resolver has empty key."""
    team_dir = _make_team_dir(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=test-key\n")
    config = json.loads((team_dir / "team.json").read_text())
    config["model"]["provider"] = "anthropic"
    config["model"]["base_url"] = "https://api.anthropic.com"
    config["model"]["api_key"] = "$ANTHROPIC_API_KEY"
    config["model"]["model"] = "claude-sonnet-4-5-20250929"
    config["agents"][0]["model"] = {
        "provider": "anthropic",
        "model": "claude-opus-4-6",
        "api_key": "",
    }
    (team_dir / "team.json").write_text(json.dumps(config, indent=2) + "\n")

    from gotg.context import TeamContext

    ctx = TeamContext.from_team_dir(team_dir)
    a1_config = ctx.model_resolver("agent-1")
    assert a1_config["provider"] == "anthropic"
    assert a1_config["model"] == "claude-opus-4-6"
    # api_key should be empty (explicitly cleared), not inherited
    assert a1_config["api_key"] == ""
