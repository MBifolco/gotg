import json
import subprocess

import pytest

from gotg.scaffold import init_project


@pytest.fixture
def git_project(tmp_path):
    """Create a minimal git repo."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)
    return tmp_path


def test_init_requires_git_repo(tmp_path):
    with pytest.raises(SystemExit):
        init_project(tmp_path)


def test_init_creates_team_directory(git_project):
    init_project(git_project)
    assert (git_project / ".team").is_dir()


def test_init_creates_team_json(git_project):
    init_project(git_project)
    team_json = json.loads((git_project / ".team" / "team.json").read_text())
    assert "model" in team_json
    assert "agents" in team_json


def test_init_creates_team_json_model_section(git_project):
    init_project(git_project)
    team_json = json.loads((git_project / ".team" / "team.json").read_text())
    model = team_json["model"]
    assert model["provider"] == "ollama"
    assert model["base_url"] == "http://localhost:11434"
    assert model["model"] == "qwen2.5-coder:7b"


def test_init_creates_team_json_agents_section(git_project):
    init_project(git_project)
    team_json = json.loads((git_project / ".team" / "team.json").read_text())
    agents = team_json["agents"]
    assert len(agents) == 2
    assert agents[0]["name"] == "agent-1"
    assert agents[1]["name"] == "agent-2"
    assert agents[0]["role"] == "Software Engineer"
    assert "system_prompt" not in agents[0]


def test_init_creates_iteration_json_list_format(git_project):
    init_project(git_project)
    data = json.loads((git_project / ".team" / "iteration.json").read_text())
    assert data["current"] == "iter-1"
    assert len(data["iterations"]) == 1
    entry = data["iterations"][0]
    assert entry["id"] == "iter-1"
    assert entry["title"] == ""
    assert entry["description"] == ""
    assert entry["status"] == "pending"
    assert entry["phase"] == "grooming"
    assert entry["max_turns"] == 10


def test_init_creates_iterations_directory(git_project):
    init_project(git_project)
    assert (git_project / ".team" / "iterations" / "iter-1").is_dir()


def test_init_creates_empty_conversation_log(git_project):
    init_project(git_project)
    log = git_project / ".team" / "iterations" / "iter-1" / "conversation.jsonl"
    assert log.exists()
    assert log.read_text() == ""


def test_init_refuses_if_team_exists(git_project):
    (git_project / ".team").mkdir()
    with pytest.raises(SystemExit):
        init_project(git_project)


def test_init_does_not_touch_existing_files(git_project):
    existing = git_project / "mycode.py"
    existing.write_text("print('hello')")
    init_project(git_project)
    assert existing.read_text() == "print('hello')"


def test_init_creates_gitignore_with_team_and_env(git_project):
    init_project(git_project)
    content = (git_project / ".gitignore").read_text()
    assert "/.team/" in content
    assert ".env" in content


def test_init_appends_to_existing_gitignore(git_project):
    (git_project / ".gitignore").write_text("*.pyc\n")
    init_project(git_project)
    content = (git_project / ".gitignore").read_text()
    assert "*.pyc" in content
    assert "/.team/" in content
    assert ".env" in content


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


def test_init_creates_team_json_coach_section(git_project):
    init_project(git_project)
    team_json = json.loads((git_project / ".team" / "team.json").read_text())
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
    assert "signal_phase_complete" in COACH_FACILITATION_PROMPT
    assert "technical opinions" in COACH_FACILITATION_PROMPT.lower()


def test_coach_tools_exists():
    from gotg.scaffold import COACH_TOOLS
    assert isinstance(COACH_TOOLS, list)
    assert len(COACH_TOOLS) == 1
    tool = COACH_TOOLS[0]
    assert tool["name"] == "signal_phase_complete"
    assert "input_schema" in tool


def test_phase_prompts_has_planning_key():
    from gotg.scaffold import PHASE_PROMPTS
    assert "planning" in PHASE_PROMPTS


def test_planning_prompt_mentions_tasks():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["planning"].lower()
    assert "tasks" in prompt
    assert "independent" in prompt or "assignable" in prompt


def test_planning_prompt_mentions_redirect():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["planning"].lower()
    assert "grooming" in prompt


def test_coach_planning_prompt_exists():
    from gotg.scaffold import COACH_PLANNING_PROMPT
    assert isinstance(COACH_PLANNING_PROMPT, str)
    assert len(COACH_PLANNING_PROMPT) > 0
    assert "json" in COACH_PLANNING_PROMPT.lower()


def test_coach_planning_prompt_mentions_required_fields():
    from gotg.scaffold import COACH_PLANNING_PROMPT
    for field in ["id", "description", "done_criteria", "depends_on", "assigned_to", "status"]:
        assert field in COACH_PLANNING_PROMPT


def test_phase_prompts_has_pre_code_review_key():
    from gotg.scaffold import PHASE_PROMPTS
    assert "pre-code-review" in PHASE_PROMPTS


def test_pre_code_review_prompt_mentions_implementation():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["pre-code-review"].lower()
    assert "implement" in prompt


def test_pre_code_review_prompt_mentions_redirect():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["pre-code-review"].lower()
    assert "planning" in prompt


def test_pre_code_review_prompt_mentions_layer_by_layer():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["pre-code-review"].lower()
    assert "layer by layer" in prompt
    assert "layer 0" in prompt


def test_pre_code_review_prompt_discourages_full_code():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["pre-code-review"].lower()
    assert "code review phase after this" in prompt
    assert "don't write full implementations" in prompt or "write full implementations" in prompt


def test_pre_code_review_prompt_mentions_one_at_a_time():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["pre-code-review"].lower()
    assert "one task at a time" in prompt


def test_coach_facilitation_prompts_dict_exists():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    assert isinstance(COACH_FACILITATION_PROMPTS, dict)
    assert "grooming" in COACH_FACILITATION_PROMPTS
    assert "planning" in COACH_FACILITATION_PROMPTS
    assert "pre-code-review" in COACH_FACILITATION_PROMPTS


def test_coach_facilitation_prompts_grooming_is_default():
    from gotg.scaffold import COACH_FACILITATION_PROMPT, COACH_FACILITATION_PROMPTS
    assert COACH_FACILITATION_PROMPTS["grooming"] is COACH_FACILITATION_PROMPT


def test_coach_facilitation_planning_mentions_scope_coverage():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["planning"].lower()
    assert "requirements" in prompt
    assert "groomed scope" in prompt


def test_coach_facilitation_pre_code_review_mentions_all_tasks():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["pre-code-review"].lower()
    assert "all tasks" in prompt
    assert "every task id" in prompt


def test_coach_facilitation_pre_code_review_blocks_early_completion():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["pre-code-review"].lower()
    assert "do not signal" in prompt or "do not signal completion" in prompt


def test_init_creates_file_access_in_team_json(git_project):
    init_project(git_project)
    team_json = json.loads((git_project / ".team" / "team.json").read_text())
    assert "file_access" in team_json
    fa = team_json["file_access"]
    assert "writable_paths" in fa
    assert "src/**" in fa["writable_paths"]
    assert fa["max_file_size_bytes"] == 1048576
    assert fa["max_files_per_turn"] == 10
    assert fa["enable_approvals"] is False


def test_init_creates_worktrees_config_in_team_json(git_project):
    init_project(git_project)
    team_json = json.loads((git_project / ".team" / "team.json").read_text())
    assert "worktrees" in team_json
    assert team_json["worktrees"]["enabled"] is False
