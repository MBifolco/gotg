import json

import pytest

from gotg.scaffold import init_project


def test_init_creates_team_directory(tmp_path):
    init_project(tmp_path)
    assert (tmp_path / ".team").is_dir()


def test_init_creates_agents_directory(tmp_path):
    init_project(tmp_path)
    assert (tmp_path / ".team" / "agents").is_dir()


def test_init_creates_model_json(tmp_path):
    init_project(tmp_path)
    config = json.loads((tmp_path / ".team" / "model.json").read_text())
    assert config["provider"] == "ollama"
    assert config["base_url"] == "http://localhost:11434"
    assert config["model"] == "qwen2.5-coder:7b"


def test_init_creates_two_agent_configs(tmp_path):
    init_project(tmp_path)
    agents_dir = tmp_path / ".team" / "agents"
    agent_files = sorted(agents_dir.glob("*.json"))
    assert len(agent_files) == 2

    a1 = json.loads(agent_files[0].read_text())
    a2 = json.loads(agent_files[1].read_text())
    assert a1["name"] == "agent-1"
    assert a2["name"] == "agent-2"
    assert a1["role"] == "Software Engineer"
    assert "system_prompt" not in a1  # default comes from code, not config


def test_init_creates_iteration_json(tmp_path):
    init_project(tmp_path)
    iteration = json.loads((tmp_path / ".team" / "iteration.json").read_text())
    assert iteration["id"] == "iter-1"
    assert iteration["description"] == ""
    assert iteration["status"] == "pending"
    assert iteration["max_turns"] == 10


def test_init_creates_empty_conversation_log(tmp_path):
    init_project(tmp_path)
    log = tmp_path / ".team" / "conversation.jsonl"
    assert log.exists()
    assert log.read_text() == ""


def test_init_refuses_if_team_exists(tmp_path):
    (tmp_path / ".team").mkdir()
    with pytest.raises(SystemExit):
        init_project(tmp_path)


def test_init_does_not_touch_existing_files(tmp_path):
    existing = tmp_path / "mycode.py"
    existing.write_text("print('hello')")
    init_project(tmp_path)
    assert existing.read_text() == "print('hello')"


def test_default_system_prompt_mentions_pushback():
    """The default system prompt should tell agents not to just agree."""
    from gotg.scaffold import DEFAULT_SYSTEM_PROMPT
    prompt = DEFAULT_SYSTEM_PROMPT.lower()
    assert "agree" in prompt
