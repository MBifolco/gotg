import json
from pathlib import Path

import pytest

from gotg.config import load_model_config, load_agents, load_iteration


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
