import json
import subprocess

import pytest

from gotg.scaffold import init_project


@pytest.fixture
def git_project(tmp_path):
    """Create a minimal git repo."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
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
    assert "/.worktrees/" in content


def test_init_appends_to_existing_gitignore(git_project):
    (git_project / ".gitignore").write_text("*.pyc\n")
    init_project(git_project)
    content = (git_project / ".gitignore").read_text()
    assert "*.pyc" in content
    assert "/.team/" in content
    assert ".env" in content


def test_init_commits_gitignore(git_project):
    """init_project should commit .gitignore so it doesn't block merges later."""
    init_project(git_project)
    result = subprocess.run(
        ["git", "log", "--oneline", "--", ".gitignore"],
        cwd=git_project, capture_output=True, text=True,
    )
    assert "gotg" in result.stdout.lower()


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


def test_coach_notes_extraction_prompt_exists():
    from gotg.scaffold import COACH_NOTES_EXTRACTION_PROMPT
    assert len(COACH_NOTES_EXTRACTION_PROMPT) > 0


def test_coach_notes_extraction_prompt_has_placeholders():
    from gotg.scaffold import COACH_NOTES_EXTRACTION_PROMPT
    assert "{tasks_json}" in COACH_NOTES_EXTRACTION_PROMPT
    assert "{conversation}" in COACH_NOTES_EXTRACTION_PROMPT


def test_phase_prompts_has_pre_code_review_key():
    from gotg.scaffold import PHASE_PROMPTS
    assert "pre-code-review" in PHASE_PROMPTS


def test_pre_code_review_prompt_mentions_implementation():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["pre-code-review"].lower()
    assert "implement" in prompt


def test_pre_code_review_prompt_mentions_layer_by_layer():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["pre-code-review"].lower()
    assert "layer by layer" in prompt
    assert "layer 0" in prompt


def test_pre_code_review_prompt_discourages_full_code():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["pre-code-review"].lower()
    assert "full implementations" in prompt


def test_coach_facilitation_prompts_dict_exists():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    assert isinstance(COACH_FACILITATION_PROMPTS, dict)
    assert "grooming" in COACH_FACILITATION_PROMPTS
    assert "planning" in COACH_FACILITATION_PROMPTS
    assert "pre-code-review" in COACH_FACILITATION_PROMPTS
    assert "implementation" in COACH_FACILITATION_PROMPTS


def test_coach_facilitation_prompts_grooming_is_default():
    from gotg.scaffold import COACH_FACILITATION_PROMPT, COACH_FACILITATION_PROMPTS
    assert COACH_FACILITATION_PROMPTS["grooming"] is COACH_FACILITATION_PROMPT


def test_coach_facilitation_planning_mentions_scope_coverage():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["planning"].lower()
    assert "requirements" in prompt
    assert "groomed scope" in prompt


def test_coach_facilitation_pre_code_review_mentions_all_layers():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["pre-code-review"].lower()
    assert "all layers" in prompt


def test_coach_facilitation_pre_code_review_mentions_completion():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["pre-code-review"].lower()
    assert "signal completion" in prompt


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


# --- code-review phase prompts ---

def test_phase_prompts_has_code_review_key():
    from gotg.scaffold import PHASE_PROMPTS
    assert "code-review" in PHASE_PROMPTS


def test_code_review_prompt_mentions_diffs():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["code-review"].lower()
    assert "diffs" in prompt


def test_code_review_prompt_mentions_correctness():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["code-review"].lower()
    assert "correctness" in prompt


def test_code_review_prompt_mentions_consistency():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["code-review"].lower()
    assert "consistency" in prompt


def test_code_review_prompt_mentions_redirect():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["code-review"].lower()
    assert "decided earlier" in prompt


def test_code_review_prompt_discourages_replanning():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["code-review"].lower()
    assert "propose new tasks" in prompt


def test_coach_facilitation_prompts_has_code_review():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    assert "code-review" in COACH_FACILITATION_PROMPTS


def test_coach_facilitation_code_review_mentions_concerns():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["code-review"].lower()
    assert "concerns" in prompt


def test_coach_facilitation_code_review_mentions_resolved():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["code-review"].lower()
    assert "resolved" in prompt


def test_coach_facilitation_code_review_blocks_early_completion():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["code-review"].lower()
    assert "do not" in prompt


def test_default_system_prompt_mentions_code_review():
    from gotg.scaffold import DEFAULT_SYSTEM_PROMPT
    assert "code-review" in DEFAULT_SYSTEM_PROMPT


# --- implementation phase prompts ---

def test_phase_prompts_has_implementation_key():
    from gotg.scaffold import PHASE_PROMPTS
    assert "implementation" in PHASE_PROMPTS


def test_implementation_prompt_mentions_file_tools():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["implementation"].lower()
    assert "file_read" in prompt
    assert "file_write" in prompt


def test_implementation_prompt_mentions_assigned_tasks():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["implementation"].lower()
    assert "assigned" in prompt


def test_implementation_prompt_mentions_tests():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["implementation"].lower()
    assert "test" in prompt


def test_implementation_prompt_mentions_redirect():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["implementation"].lower()
    assert "settled" in prompt


def test_implementation_prompt_discourages_cross_task():
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["implementation"].lower()
    assert "outside your assigned" in prompt or "different layer" in prompt


def test_coach_facilitation_prompts_has_implementation():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    assert "implementation" in COACH_FACILITATION_PROMPTS


def test_coach_facilitation_implementation_tracks_completion():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["implementation"].lower()
    assert "status" in prompt
    assert "complete" in prompt


def test_coach_facilitation_implementation_blocks_early_signal():
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    prompt = COACH_FACILITATION_PROMPTS["implementation"].lower()
    assert "do not signal" in prompt or "do not" in prompt


def test_default_system_prompt_mentions_implementation():
    from gotg.scaffold import DEFAULT_SYSTEM_PROMPT
    assert "implementation" in DEFAULT_SYSTEM_PROMPT


# --- conciseness norms ---

def test_default_system_prompt_mentions_conciseness():
    from gotg.scaffold import DEFAULT_SYSTEM_PROMPT
    assert "concise" in DEFAULT_SYSTEM_PROMPT.lower()


def test_default_system_prompt_discourages_checklists():
    from gotg.scaffold import DEFAULT_SYSTEM_PROMPT
    prompt = DEFAULT_SYSTEM_PROMPT.lower()
    assert "checkbox" in prompt or "checklists" in prompt


# --- implementation layer enforcement ---

def test_implementation_prompt_mentions_current_layer_template():
    """Implementation prompt should use {current_layer} placeholder."""
    from gotg.scaffold import PHASE_PROMPTS
    prompt = PHASE_PROMPTS["implementation"]
    assert "{current_layer}" in prompt


# --- PHASE_KICKOFF_MESSAGES ---

def test_phase_kickoff_messages_has_all_phases():
    from gotg.scaffold import PHASE_KICKOFF_MESSAGES
    for phase in ("grooming", "planning", "pre-code-review", "implementation", "code-review"):
        assert phase in PHASE_KICKOFF_MESSAGES


def test_phase_kickoff_messages_end_with_coach_line():
    from gotg.scaffold import PHASE_KICKOFF_MESSAGES
    for phase, msg in PHASE_KICKOFF_MESSAGES.items():
        assert msg.rstrip().endswith("The coach will facilitate from here."), (
            f"Phase {phase} kickoff doesn't end with coach facilitation line"
        )


# --- should_inject_kickoff ---

def test_should_inject_kickoff_empty_history():
    from gotg.scaffold import should_inject_kickoff
    assert should_inject_kickoff([], "grooming") is True


def test_should_inject_kickoff_after_phase_advance():
    from gotg.scaffold import should_inject_kickoff
    history = [
        {"from": "agent-1", "content": "hello"},
        {"from": "system", "content": "--- Phase advanced: grooming → planning ---"},
    ]
    assert should_inject_kickoff(history, "planning") is True


def test_should_inject_kickoff_after_layer_advance():
    from gotg.scaffold import should_inject_kickoff
    history = [
        {"from": "agent-1", "content": "done"},
        {"from": "system", "content": "--- Layer advanced: 0 → 1 ---"},
    ]
    assert should_inject_kickoff(history, "implementation") is True


def test_should_inject_kickoff_false_mid_phase_resume():
    """Mid-phase resume (no transition in history) should not inject kickoff."""
    from gotg.scaffold import should_inject_kickoff
    history = [
        {"from": "agent-1", "content": "hello"},
        {"from": "agent-2", "content": "world"},
    ]
    assert should_inject_kickoff(history, "grooming") is False


def test_should_inject_kickoff_true_when_human_msg_after_advance():
    """Kickoff should inject even if human message landed after advance."""
    from gotg.scaffold import should_inject_kickoff
    history = [
        {"from": "system", "content": "--- Phase advanced: grooming → planning ---"},
        {"from": "human", "content": "focus on auth first"},
    ]
    assert should_inject_kickoff(history, "planning") is True


def test_should_inject_kickoff_false_when_kickoff_already_exists():
    """If kickoff was already injected after transition, don't inject again."""
    from gotg.scaffold import should_inject_kickoff
    history = [
        {"from": "system", "content": "--- Phase advanced: grooming → planning ---"},
        {"from": "system", "content": "--- Phase: planning ---\nGoal: break..."},
        {"from": "agent-1", "content": "Let me propose tasks"},
    ]
    assert should_inject_kickoff(history, "planning") is False


# --- format_phase_kickoff ---

def test_format_phase_kickoff_grooming_addresses_first_agent():
    from gotg.scaffold import format_phase_kickoff
    agents = [{"name": "alice"}, {"name": "bob"}]
    iteration = {"id": "iter-1", "description": "Build X"}
    result = format_phase_kickoff("grooming", agents, iteration)
    assert "alice" in result


def test_format_phase_kickoff_implementation_includes_layer():
    from gotg.scaffold import format_phase_kickoff
    agents = [{"name": "agent-1"}, {"name": "agent-2"}]
    iteration = {"id": "iter-1", "description": "Build X", "current_layer": 2}
    result = format_phase_kickoff("implementation", agents, iteration)
    assert "layer 2" in result


def test_format_phase_kickoff_unknown_phase_returns_empty():
    from gotg.scaffold import format_phase_kickoff
    agents = [{"name": "agent-1"}]
    iteration = {"id": "iter-1", "description": "Build X"}
    assert format_phase_kickoff("unknown-phase", agents, iteration) == ""


# --- format_agent_task_assignments ---

def test_format_agent_task_assignments_basic(tmp_path):
    from gotg.scaffold import format_agent_task_assignments
    iter_dir = tmp_path
    tasks = [
        {"id": "T1", "assigned_to": "agent-1", "layer": 0},
        {"id": "T2", "assigned_to": "agent-2", "layer": 0},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    agents = [{"name": "agent-1"}, {"name": "agent-2"}]
    result = format_agent_task_assignments(iter_dir, agents)
    assert "agent-1: T1" in result
    assert "agent-2: T2" in result


def test_format_agent_task_assignments_filters_by_layer(tmp_path):
    from gotg.scaffold import format_agent_task_assignments
    iter_dir = tmp_path
    tasks = [
        {"id": "T1", "assigned_to": "agent-1", "layer": 0},
        {"id": "T2", "assigned_to": "agent-1", "layer": 1},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    agents = [{"name": "agent-1"}]
    result = format_agent_task_assignments(iter_dir, agents, current_layer=0)
    assert "T1" in result
    assert "T2" not in result


def test_format_agent_task_assignments_no_file(tmp_path):
    from gotg.scaffold import format_agent_task_assignments
    agents = [{"name": "agent-1"}]
    assert format_agent_task_assignments(tmp_path, agents) == "No tasks assigned yet."
