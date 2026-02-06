import json

import pytest

from gotg.scaffold import init_project


def test_init_creates_team_directory(tmp_path):
    init_project(tmp_path)
    assert (tmp_path / ".team").is_dir()


def test_init_creates_team_json(tmp_path):
    init_project(tmp_path)
    team_json = json.loads((tmp_path / ".team" / "team.json").read_text())
    assert "model" in team_json
    assert "agents" in team_json


def test_init_creates_team_json_model_section(tmp_path):
    init_project(tmp_path)
    team_json = json.loads((tmp_path / ".team" / "team.json").read_text())
    model = team_json["model"]
    assert model["provider"] == "ollama"
    assert model["base_url"] == "http://localhost:11434"
    assert model["model"] == "qwen2.5-coder:7b"


def test_init_creates_team_json_agents_section(tmp_path):
    init_project(tmp_path)
    team_json = json.loads((tmp_path / ".team" / "team.json").read_text())
    agents = team_json["agents"]
    assert len(agents) == 2
    assert agents[0]["name"] == "agent-1"
    assert agents[1]["name"] == "agent-2"
    assert agents[0]["role"] == "Software Engineer"
    assert "system_prompt" not in agents[0]


def test_init_creates_iteration_json_list_format(tmp_path):
    init_project(tmp_path)
    data = json.loads((tmp_path / ".team" / "iteration.json").read_text())
    assert data["current"] == "iter-1"
    assert len(data["iterations"]) == 1
    entry = data["iterations"][0]
    assert entry["id"] == "iter-1"
    assert entry["title"] == ""
    assert entry["description"] == ""
    assert entry["status"] == "pending"
    assert entry["phase"] == "grooming"
    assert entry["max_turns"] == 10


def test_init_creates_iterations_directory(tmp_path):
    init_project(tmp_path)
    assert (tmp_path / ".team" / "iterations" / "iter-1").is_dir()


def test_init_creates_empty_conversation_log(tmp_path):
    init_project(tmp_path)
    log = tmp_path / ".team" / "iterations" / "iter-1" / "conversation.jsonl"
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


def test_default_system_prompt_mentions_phases():
    """The base prompt should explain the phase system."""
    from gotg.scaffold import DEFAULT_SYSTEM_PROMPT
    prompt = DEFAULT_SYSTEM_PROMPT.lower()
    assert "phases" in prompt
    assert "grooming" in prompt
    assert "planning" in prompt


def test_phase_prompts_has_grooming_key():
    from gotg.scaffold import PHASE_PROMPTS
    assert "grooming" in PHASE_PROMPTS


def test_grooming_prompt_mentions_scope():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["grooming"].lower()
    assert "scope" in prompt
    assert "requirements" in prompt


def test_grooming_prompt_mentions_redirect():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["grooming"].lower()
    assert "redirect" in prompt or "nail down the requirements" in prompt


def test_init_creates_team_json_coach_section(tmp_path):
    init_project(tmp_path)
    team_json = json.loads((tmp_path / ".team" / "team.json").read_text())
    coach = team_json["coach"]
    assert coach["name"] == "coach"
    assert coach["role"] == "Agile Coach"


def test_coach_grooming_prompt_exists():
    from gotg.scaffold import COACH_GROOMING_PROMPT
    assert isinstance(COACH_GROOMING_PROMPT, str)
    assert len(COACH_GROOMING_PROMPT) > 0
    assert "scope" in COACH_GROOMING_PROMPT.lower() or "summary" in COACH_GROOMING_PROMPT.lower()


def test_coach_facilitation_prompt_exists():
    from gotg.scaffold import COACH_FACILITATION_PROMPT
    assert isinstance(COACH_FACILITATION_PROMPT, str)
    assert len(COACH_FACILITATION_PROMPT) > 0
    assert "PHASE_COMPLETE" in COACH_FACILITATION_PROMPT
    assert "technical opinions" in COACH_FACILITATION_PROMPT.lower()
