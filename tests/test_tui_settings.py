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
        await pilot.press("ctrl+s")
        await pilot.pause()

    saved = json.loads((team_dir / "team.json").read_text())
    assert saved["model"]["model"] == "gpt-4o"
    assert saved["coach"]["name"] == "my-coach"
    assert saved["file_access"]["writable_paths"] == ["lib/**", "bin/**"]
    assert saved["worktrees"]["enabled"] is True


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
