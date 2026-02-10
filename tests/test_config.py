import json
from pathlib import Path

import pytest

from gotg.config import (
    load_model_config, load_agents, load_coach, load_iteration,
    load_file_access, read_dotenv, ensure_dotenv_key,
    get_iteration_dir, get_current_iteration, save_model_config,
    save_iteration_phase, save_iteration_fields, PHASE_ORDER,
)


def _write_team_json(team_dir, model=None, agents=None):
    """Helper to write team.json with given model/agents."""
    default_agents = [
        {"name": "agent-1", "system_prompt": "You are an engineer."},
        {"name": "agent-2", "system_prompt": "You are an engineer."},
    ]
    (team_dir / "team.json").write_text(json.dumps({
        "model": model or {
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:7b",
        },
        "agents": default_agents if agents is None else agents,
    }, indent=2))


def _write_iteration_json(team_dir, iterations=None, current="iter-1"):
    """Helper to write list-format iteration.json."""
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": iterations or [
            {
                "id": "iter-1",
                "title": "Test Task",
                "description": "Design a todo app",
                "status": "in-progress",
                "max_turns": 10,
            }
        ],
        "current": current,
    }, indent=2))


@pytest.fixture
def team_dir(tmp_path):
    """Create a minimal .team/ directory structure (new format)."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    return team


def test_load_model_config(team_dir):
    config = load_model_config(team_dir)
    assert config["provider"] == "ollama"
    assert config["base_url"] == "http://localhost:11434"
    assert config["model"] == "qwen2.5-coder:7b"


def test_load_agents_returns_list(team_dir):
    agents = load_agents(team_dir)
    assert len(agents) == 2
    assert agents[0]["name"] == "agent-1"
    assert agents[1]["name"] == "agent-2"


def test_load_iteration(team_dir):
    iteration = load_iteration(team_dir)
    assert iteration["id"] == "iter-1"
    assert iteration["description"] == "Design a todo app"
    assert iteration["status"] == "in-progress"
    assert iteration["max_turns"] == 10


def test_load_model_config_missing_file(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    with pytest.raises(FileNotFoundError):
        load_model_config(team)


# --- edge cases ---

def test_load_model_config_invalid_json(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text("{invalid json")
    with pytest.raises(json.JSONDecodeError):
        load_model_config(team)


def test_load_iteration_invalid_json(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "iteration.json").write_text("")
    with pytest.raises(json.JSONDecodeError):
        load_iteration(team)


def test_load_agents_empty_list(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team, agents=[])
    agents = load_agents(team)
    assert agents == []


def test_load_agents_preserves_all_fields(tmp_path):
    """Extra fields in agent config should be preserved (forward compat)."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team, agents=[
        {"name": "agent-1", "system_prompt": "hi", "custom_field": "some value"},
    ])
    agents = load_agents(team)
    assert agents[0]["custom_field"] == "some value"


def test_load_model_config_preserves_extra_fields(tmp_path):
    """api_key and other future fields should be preserved."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team, model={
        "provider": "openai",
        "base_url": "https://api.openai.com",
        "model": "gpt-4o",
        "api_key": "sk-test",
    })
    config = load_model_config(team)
    assert config["api_key"] == "sk-test"


def test_load_model_config_resolves_env_var_api_key(tmp_path, monkeypatch):
    """api_key starting with $ should resolve from environment."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-123")
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team, model={
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5-20250929",
        "api_key": "$ANTHROPIC_API_KEY",
    })
    config = load_model_config(team)
    assert config["api_key"] == "sk-ant-secret-123"


def test_load_model_config_env_var_missing_raises(tmp_path, monkeypatch):
    """Missing env var should raise a clear error."""
    monkeypatch.delenv("NONEXISTENT_KEY_VAR", raising=False)
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team, model={
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "m",
        "api_key": "$NONEXISTENT_KEY_VAR",
    })
    with pytest.raises(SystemExit):
        load_model_config(team)


def test_load_model_config_literal_api_key_not_resolved(tmp_path):
    """api_key without $ prefix should be used as-is."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team, model={
        "provider": "openai",
        "base_url": "https://api.openai.com",
        "model": "m",
        "api_key": "sk-literal-key",
    })
    config = load_model_config(team)
    assert config["api_key"] == "sk-literal-key"


# --- get_iteration_dir ---

def test_get_iteration_dir(team_dir):
    path = get_iteration_dir(team_dir, "iter-1")
    assert path == team_dir / "iterations" / "iter-1"


def test_get_iteration_dir_custom_id(team_dir):
    path = get_iteration_dir(team_dir, "iter-2-auth")
    assert path == team_dir / "iterations" / "iter-2-auth"


# --- get_current_iteration ---

def test_get_current_iteration_returns_tuple(team_dir):
    iteration, iter_dir = get_current_iteration(team_dir)
    assert iteration["id"] == "iter-1"
    assert iteration["description"] == "Design a todo app"
    assert iter_dir == team_dir / "iterations" / "iter-1"


def test_get_current_iteration_missing_id_raises(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team, current="nonexistent")
    with pytest.raises(SystemExit):
        get_current_iteration(team)


# --- save_model_config ---

def test_save_model_config_updates_model(team_dir):
    save_model_config(team_dir, {
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5-20250929",
    })
    config = load_model_config(team_dir)
    assert config["provider"] == "anthropic"


def test_save_model_config_preserves_agents(team_dir):
    """Writing model config should not clobber agents."""
    save_model_config(team_dir, {
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "m",
    })
    agents = load_agents(team_dir)
    assert len(agents) == 2
    assert agents[0]["name"] == "agent-1"


# --- read_dotenv ---

def test_read_dotenv_basic(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("FOO=bar\nBAZ=qux\n")
    result = read_dotenv(dotenv)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_read_dotenv_missing_file(tmp_path):
    result = read_dotenv(tmp_path / ".env")
    assert result == {}


def test_read_dotenv_ignores_comments_and_blank_lines(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("# comment\n\nFOO=bar\n  # another comment\n")
    result = read_dotenv(dotenv)
    assert result == {"FOO": "bar"}


def test_read_dotenv_strips_quotes(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text('KEY1="double-quoted"\nKEY2=\'single-quoted\'\n')
    result = read_dotenv(dotenv)
    assert result["KEY1"] == "double-quoted"
    assert result["KEY2"] == "single-quoted"


def test_read_dotenv_empty_value(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("MY_KEY=\n")
    result = read_dotenv(dotenv)
    assert result == {"MY_KEY": ""}


def test_read_dotenv_value_with_equals(tmp_path):
    """Values containing = should be preserved."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("KEY=abc=def=ghi\n")
    result = read_dotenv(dotenv)
    assert result["KEY"] == "abc=def=ghi"


# --- ensure_dotenv_key ---

def test_ensure_dotenv_key_creates_file(tmp_path):
    dotenv = tmp_path / ".env"
    ensure_dotenv_key(dotenv, "ANTHROPIC_API_KEY")
    assert dotenv.exists()
    assert dotenv.read_text() == "ANTHROPIC_API_KEY=\n"


def test_ensure_dotenv_key_appends_to_existing(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("EXISTING=value\n")
    ensure_dotenv_key(dotenv, "NEW_KEY")
    content = dotenv.read_text()
    assert "EXISTING=value" in content
    assert "NEW_KEY=" in content


def test_ensure_dotenv_key_does_not_duplicate(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("ANTHROPIC_API_KEY=sk-abc\n")
    ensure_dotenv_key(dotenv, "ANTHROPIC_API_KEY")
    content = dotenv.read_text()
    assert content.count("ANTHROPIC_API_KEY") == 1


def test_ensure_dotenv_key_handles_no_trailing_newline(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("EXISTING=value")  # no trailing newline
    ensure_dotenv_key(dotenv, "NEW_KEY")
    content = dotenv.read_text()
    assert "EXISTING=value\n" in content
    assert "NEW_KEY=\n" in content


# --- load_model_config with .env ---

def test_load_model_config_resolves_from_dotenv(tmp_path, monkeypatch):
    """api_key $VAR should resolve from .env file."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team, model={
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "m",
        "api_key": "$ANTHROPIC_API_KEY",
    })
    # Write .env in project root (parent of .team/)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-from-dotenv\n")
    config = load_model_config(team)
    assert config["api_key"] == "sk-from-dotenv"


def test_load_model_config_dotenv_takes_priority_over_env(tmp_path, monkeypatch):
    """.env file should take priority over os.environ."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-environ")
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team, model={
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "m",
        "api_key": "$ANTHROPIC_API_KEY",
    })
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-from-dotenv\n")
    config = load_model_config(team)
    assert config["api_key"] == "sk-from-dotenv"


def test_load_model_config_falls_back_to_environ(tmp_path, monkeypatch):
    """If .env doesn't have the key, fall back to os.environ."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-environ")
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team, model={
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "m",
        "api_key": "$ANTHROPIC_API_KEY",
    })
    # .env exists but has a different key
    (tmp_path / ".env").write_text("OTHER_KEY=something\n")
    config = load_model_config(team)
    assert config["api_key"] == "sk-from-environ"


# --- save_iteration_phase ---

def test_save_iteration_phase_updates_phase(team_dir):
    save_iteration_phase(team_dir, "iter-1", "planning")
    iteration = load_iteration(team_dir)
    assert iteration["phase"] == "planning"


def test_save_iteration_phase_preserves_other_fields(team_dir):
    save_iteration_phase(team_dir, "iter-1", "planning")
    iteration = load_iteration(team_dir)
    assert iteration["description"] == "Design a todo app"
    assert iteration["status"] == "in-progress"
    assert iteration["max_turns"] == 10


def test_save_iteration_phase_missing_id_raises(team_dir):
    with pytest.raises(SystemExit):
        save_iteration_phase(team_dir, "nonexistent", "planning")


# --- PHASE_ORDER ---

def test_phase_order_has_five_phases():
    assert PHASE_ORDER == ["refinement", "planning", "pre-code-review", "implementation", "code-review"]


def test_phase_order_includes_implementation():
    assert "implementation" in PHASE_ORDER


def test_phase_order_implementation_before_code_review():
    assert PHASE_ORDER.index("implementation") < PHASE_ORDER.index("code-review")


# --- load_coach ---

def test_load_coach_returns_coach_config(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    # Add coach to team.json
    team_config = json.loads((team / "team.json").read_text())
    team_config["coach"] = {"name": "coach", "role": "Agile Coach"}
    (team / "team.json").write_text(json.dumps(team_config, indent=2))
    coach = load_coach(team)
    assert coach["name"] == "coach"
    assert coach["role"] == "Agile Coach"


def test_load_coach_returns_none_when_missing(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    coach = load_coach(team)
    assert coach is None


def test_load_coach_preserves_fields(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    team_config = json.loads((team / "team.json").read_text())
    team_config["coach"] = {"name": "coach", "role": "Agile Coach", "custom": "value"}
    (team / "team.json").write_text(json.dumps(team_config, indent=2))
    coach = load_coach(team)
    assert coach["custom"] == "value"


# --- save_iteration_fields ---

def test_save_iteration_fields_updates_multiple(team_dir):
    save_iteration_fields(team_dir, "iter-1", phase="planning", max_turns=20)
    iteration = load_iteration(team_dir)
    assert iteration["phase"] == "planning"
    assert iteration["max_turns"] == 20


def test_save_iteration_fields_preserves_other_fields(team_dir):
    save_iteration_fields(team_dir, "iter-1", phase="planning")
    iteration = load_iteration(team_dir)
    assert iteration["description"] == "Design a todo app"
    assert iteration["status"] == "in-progress"


def test_save_iteration_fields_missing_id_raises(team_dir):
    with pytest.raises(SystemExit):
        save_iteration_fields(team_dir, "nonexistent", phase="planning")


# --- load_file_access ---

def test_backward_compat_grooming_phase(team_dir):
    """Old iteration.json with phase='grooming' should normalize to 'refinement'."""
    _write_iteration_json(team_dir, iterations=[
        {
            "id": "iter-1",
            "title": "Test Task",
            "description": "Design a todo app",
            "status": "in-progress",
            "phase": "grooming",
            "max_turns": 10,
        }
    ])
    iteration = load_iteration(team_dir)
    assert iteration["phase"] == "refinement"


def test_load_file_access_returns_config(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [],
        "file_access": {
            "writable_paths": ["src/**", "tests/**"],
            "max_file_size_bytes": 500000,
            "max_files_per_turn": 5,
        },
    }
    (team / "team.json").write_text(json.dumps(team_config))
    result = load_file_access(team)
    assert result is not None
    assert result["writable_paths"] == ["src/**", "tests/**"]
    assert result["max_file_size_bytes"] == 500000


def test_load_file_access_returns_none_when_absent(team_dir):
    result = load_file_access(team_dir)
    assert result is None
