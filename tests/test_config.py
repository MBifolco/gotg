import json
from pathlib import Path

import pytest

from gotg.config import load_model_config, load_agents, load_iteration, read_dotenv, ensure_dotenv_key


@pytest.fixture
def team_dir(tmp_path):
    """Create a minimal .team/ directory structure."""
    team = tmp_path / ".team"
    team.mkdir()
    agents_dir = team / "agents"
    agents_dir.mkdir()

    (team / "model.json").write_text(json.dumps({
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "qwen2.5-coder:7b",
    }))

    (agents_dir / "agent-1.json").write_text(json.dumps({
        "name": "agent-1",
        "system_prompt": "You are an engineer.",
    }))

    (agents_dir / "agent-2.json").write_text(json.dumps({
        "name": "agent-2",
        "system_prompt": "You are an engineer.",
    }))

    (team / "iteration.json").write_text(json.dumps({
        "id": "iter-1",
        "description": "Design a todo app",
        "status": "in-progress",
        "max_turns": 10,
    }))

    return team


def test_load_model_config(team_dir):
    config = load_model_config(team_dir)
    assert config["provider"] == "ollama"
    assert config["base_url"] == "http://localhost:11434"
    assert config["model"] == "qwen2.5-coder:7b"


def test_load_agents_returns_sorted(team_dir):
    agents = load_agents(team_dir)
    assert len(agents) == 2
    assert agents[0]["name"] == "agent-1"
    assert agents[1]["name"] == "agent-2"


def test_load_agents_ignores_non_json(team_dir):
    (team_dir / "agents" / "notes.txt").write_text("not an agent")
    agents = load_agents(team_dir)
    assert len(agents) == 2


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
    (team / "model.json").write_text("{invalid json")
    with pytest.raises(json.JSONDecodeError):
        load_model_config(team)


def test_load_iteration_invalid_json(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "iteration.json").write_text("")
    with pytest.raises(json.JSONDecodeError):
        load_iteration(team)


def test_load_agents_empty_directory(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "agents").mkdir()
    agents = load_agents(team)
    assert agents == []


def test_load_agents_preserves_all_fields(tmp_path):
    """Extra fields in agent config should be preserved (forward compat)."""
    team = tmp_path / ".team"
    team.mkdir()
    agents_dir = team / "agents"
    agents_dir.mkdir()
    (agents_dir / "agent-1.json").write_text(json.dumps({
        "name": "agent-1",
        "system_prompt": "hi",
        "custom_field": "some value",
    }))
    agents = load_agents(team)
    assert agents[0]["custom_field"] == "some value"


def test_load_model_config_preserves_extra_fields(tmp_path):
    """api_key and other future fields should be preserved."""
    team = tmp_path / ".team"
    team.mkdir()
    (team / "model.json").write_text(json.dumps({
        "provider": "openai",
        "base_url": "https://api.openai.com",
        "model": "gpt-4o",
        "api_key": "sk-test",
    }))
    config = load_model_config(team)
    assert config["api_key"] == "sk-test"


def test_load_model_config_resolves_env_var_api_key(tmp_path, monkeypatch):
    """api_key starting with $ should resolve from environment."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-123")
    team = tmp_path / ".team"
    team.mkdir()
    (team / "model.json").write_text(json.dumps({
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5-20250929",
        "api_key": "$ANTHROPIC_API_KEY",
    }))
    config = load_model_config(team)
    assert config["api_key"] == "sk-ant-secret-123"


def test_load_model_config_env_var_missing_raises(tmp_path, monkeypatch):
    """Missing env var should raise a clear error."""
    monkeypatch.delenv("NONEXISTENT_KEY_VAR", raising=False)
    team = tmp_path / ".team"
    team.mkdir()
    (team / "model.json").write_text(json.dumps({
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "m",
        "api_key": "$NONEXISTENT_KEY_VAR",
    }))
    with pytest.raises(SystemExit):
        load_model_config(team)


def test_load_model_config_literal_api_key_not_resolved(tmp_path):
    """api_key without $ prefix should be used as-is."""
    team = tmp_path / ".team"
    team.mkdir()
    (team / "model.json").write_text(json.dumps({
        "provider": "openai",
        "base_url": "https://api.openai.com",
        "model": "m",
        "api_key": "sk-literal-key",
    }))
    config = load_model_config(team)
    assert config["api_key"] == "sk-literal-key"


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
    (team / "model.json").write_text(json.dumps({
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "m",
        "api_key": "$ANTHROPIC_API_KEY",
    }))
    # Write .env in project root (parent of .team/)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-from-dotenv\n")
    config = load_model_config(team)
    assert config["api_key"] == "sk-from-dotenv"


def test_load_model_config_dotenv_takes_priority_over_env(tmp_path, monkeypatch):
    """.env file should take priority over os.environ."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-environ")
    team = tmp_path / ".team"
    team.mkdir()
    (team / "model.json").write_text(json.dumps({
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "m",
        "api_key": "$ANTHROPIC_API_KEY",
    }))
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-from-dotenv\n")
    config = load_model_config(team)
    assert config["api_key"] == "sk-from-dotenv"


def test_load_model_config_falls_back_to_environ(tmp_path, monkeypatch):
    """If .env doesn't have the key, fall back to os.environ."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-environ")
    team = tmp_path / ".team"
    team.mkdir()
    (team / "model.json").write_text(json.dumps({
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "m",
        "api_key": "$ANTHROPIC_API_KEY",
    }))
    # .env exists but has a different key
    (tmp_path / ".env").write_text("OTHER_KEY=something\n")
    config = load_model_config(team)
    assert config["api_key"] == "sk-from-environ"
