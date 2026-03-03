import json
import pytest
from pathlib import Path

from gotg.policy import SessionPolicy, iteration_policy, grooming_policy, _format_iteration_plan
from gotg.prompts import AGENT_TOOLS, COACH_TOOLS
from gotg.tools import FILE_TOOLS, READ_ONLY_FILE_TOOLS


# --- Helpers ---

AGENTS = [
    {"name": "agent-1", "role": "Software Engineer"},
    {"name": "agent-2", "role": "Software Engineer"},
]

ITERATION = {
    "id": "iter-1",
    "description": "Build a thing",
    "phase": "refinement",
    "max_turns": 10,
}

COACH = {"name": "coach", "role": "Agile Coach"}


def _make_iter_dir(tmp_path):
    """Create a minimal iteration directory with empty conversation log."""
    iter_dir = tmp_path / ".team" / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    return iter_dir


# --- SessionPolicy dataclass tests ---


def test_session_policy_creation():
    p = SessionPolicy(
        max_turns=5, coach=COACH, coach_cadence=2,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=tuple(AGENT_TOOLS), coach_tools=tuple(COACH_TOOLS),
        groomed_summary="summary", tasks_summary="tasks",
        diffs_summary=None, kickoff_text="kick",
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
    )
    assert p.max_turns == 5
    assert p.coach == COACH
    assert p.coach_cadence == 2
    assert isinstance(p.agent_tools, tuple)
    assert isinstance(p.coach_tools, tuple)
    assert p.groomed_summary == "summary"
    assert p.kickoff_text == "kick"


def test_session_policy_frozen():
    p = SessionPolicy(
        max_turns=5, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=tuple(AGENT_TOOLS), coach_tools=None,
        groomed_summary=None, tasks_summary=None,
        diffs_summary=None, kickoff_text=None,
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
    )
    with pytest.raises(AttributeError):
        p.max_turns = 99


# --- iteration_policy factory tests ---


def test_iteration_policy_default_max_turns(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.max_turns == ITERATION["max_turns"]


def test_iteration_policy_max_turns_override(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[], max_turns_override=99)
    assert p.max_turns == 99


def test_iteration_policy_with_coach(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[], coach=COACH)
    assert p.coach == COACH
    assert p.coach_cadence == len(AGENTS)
    assert p.coach_tools is not None
    assert isinstance(p.coach_tools, tuple)
    assert len(p.coach_tools) > 0


def test_iteration_policy_without_coach(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.coach is None
    assert p.coach_cadence is None
    assert p.coach_tools is None


def test_iteration_policy_loads_groomed_md(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    (iter_dir / "refinement_summary.md").write_text("# Scope\nDo the thing\n")
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.groomed_summary == "# Scope\nDo the thing"


def test_iteration_policy_loads_tasks_json(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    tasks = [
        {"id": "T1", "description": "task one", "depends_on": [],
         "done_criteria": "done", "assigned_to": "agent-1"},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.tasks_summary is not None
    assert "T1" in p.tasks_summary


def test_iteration_policy_no_artifacts(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.groomed_summary is None
    assert p.tasks_summary is None


def test_iteration_policy_with_fileguard(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)

    class FakeGuard:
        writable_paths = ["src/**"]
        protected_paths = []
        max_files_per_turn = 10
        max_file_size_bytes = 1048576
        enable_approvals = False

    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[], fileguard=FakeGuard())
    assert isinstance(p.agent_tools, tuple)
    assert len(p.agent_tools) > len(AGENT_TOOLS)


def test_iteration_policy_without_fileguard(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.agent_tools == tuple(AGENT_TOOLS)


def test_iteration_policy_stop_conditions(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.stop_on_phase_complete is True
    assert p.stop_on_ask_pm is True


# --- grooming_policy tests (minimal — Codex constraint 4) ---


def test_grooming_policy_defaults():
    p = grooming_policy(AGENTS, "Discuss feature X", history=[])
    assert p.coach is None
    assert p.coach_cadence is None
    assert p.stop_on_phase_complete is False
    assert p.stop_on_ask_pm is False
    assert p.coach_tools is None
    assert isinstance(p.agent_tools, tuple)
    assert p.max_turns == 30
    assert p.system_supplement is not None
    assert "GROOMING" in p.system_supplement
    assert p.coach_system_prompt is None
    assert p.kickoff_text is not None
    assert "Discuss feature X" in p.kickoff_text


def test_grooming_policy_max_turns():
    p = grooming_policy(AGENTS, "Discuss feature X", history=[], max_turns=50)
    assert p.max_turns == 50


def test_grooming_policy_with_coach():
    p = grooming_policy(AGENTS, "Discuss feature X", history=[], coach=COACH)
    assert p.coach == COACH
    assert p.coach_cadence == len(AGENTS)
    assert p.stop_on_ask_pm is True
    assert p.stop_on_phase_complete is False
    assert p.coach_tools is not None
    # Coach should have ask_pm but NOT signal_phase_complete
    tool_names = {t["name"] for t in p.coach_tools}
    assert "ask_pm" in tool_names
    assert "signal_phase_complete" not in tool_names
    assert p.coach_system_prompt is not None
    assert "grooming" in p.coach_system_prompt.lower()


def test_grooming_policy_kickoff_includes_topic():
    p = grooming_policy(AGENTS, "How to handle errors", history=[])
    assert "How to handle errors" in p.kickoff_text
    assert "agent-1" in p.kickoff_text


def test_grooming_policy_no_kickoff_with_history():
    history = [{"from": "system", "content": "existing message"}]
    p = grooming_policy(AGENTS, "Some topic", history=history)
    assert p.kickoff_text is None


# --- Implementation layer filtering ---


def test_iteration_policy_implementation_filters_tasks_by_layer(tmp_path):
    """Implementation phase passes current_layer to format_tasks_summary."""
    iter_dir = _make_iter_dir(tmp_path)
    tasks = [
        {"id": "a", "depends_on": [], "description": "Do A",
         "done_criteria": "A done", "assigned_to": "agent-1", "status": "pending", "layer": 0},
        {"id": "b", "depends_on": ["a"], "description": "Do B",
         "done_criteria": "B done", "assigned_to": "agent-2", "status": "pending", "layer": 1},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    iteration = {
        "id": "iter-1", "description": "Build a thing",
        "phase": "implementation", "max_turns": 10, "current_layer": 0,
    }
    p = iteration_policy(AGENTS, iteration, iter_dir, history=[])
    assert "**a**" in p.tasks_summary
    assert "**b**" not in p.tasks_summary


def test_iteration_policy_non_implementation_shows_all_tasks(tmp_path):
    """Non-implementation phases show all tasks (no layer filtering)."""
    iter_dir = _make_iter_dir(tmp_path)
    tasks = [
        {"id": "a", "depends_on": [], "description": "Do A",
         "done_criteria": "A done", "assigned_to": "agent-1", "status": "pending", "layer": 0},
        {"id": "b", "depends_on": ["a"], "description": "Do B",
         "done_criteria": "B done", "assigned_to": "agent-2", "status": "pending", "layer": 1},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    iteration = {
        "id": "iter-1", "description": "Build a thing",
        "phase": "pre-code-review", "max_turns": 10,
    }
    p = iteration_policy(AGENTS, iteration, iter_dir, history=[])
    assert "**a**" in p.tasks_summary
    assert "**b**" in p.tasks_summary


def test_iteration_policy_loads_phase_skeleton(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    skeleton_path = iter_dir / "phase_skeleton.md"
    skeleton_path.write_text("## REFINEMENT phase\nDecisions:\n- agreed on X\n")
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.phase_skeleton is not None
    assert "REFINEMENT" in p.phase_skeleton


def test_iteration_policy_no_skeleton_file(tmp_path):
    iter_dir = _make_iter_dir(tmp_path)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.phase_skeleton is None


# --- _format_iteration_plan tests ---


def test_format_iteration_plan_single_iteration():
    """Single iteration returns None (no plan needed)."""
    result = _format_iteration_plan("iter-1", [
        {"id": "iter-1", "title": "Do the thing", "status": "in-progress"},
    ])
    assert result is None


def test_format_iteration_plan_multiple_iterations():
    """Multiple iterations formatted with >> marker on current."""
    result = _format_iteration_plan("iter-2", [
        {"id": "iter-1", "title": "First thing", "status": "done"},
        {"id": "iter-2", "title": "Second thing", "status": "in-progress"},
        {"id": "iter-3", "title": "Third thing", "status": "pending"},
    ])
    assert result is not None
    lines = result.split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("   ")  # not current
    assert "iter-1" in lines[0]
    assert "[done]" in lines[0]
    assert lines[1].startswith(">> ")  # current
    assert "iter-2" in lines[1]
    assert "[in-progress]" in lines[1]
    assert lines[2].startswith("   ")
    assert "iter-3" in lines[2]


def test_format_iteration_plan_uses_description_fallback():
    """Falls back to description[:80] when title is missing."""
    result = _format_iteration_plan("iter-1", [
        {"id": "iter-1", "description": "A long description here", "status": "in-progress"},
        {"id": "iter-2", "description": "Another desc", "status": "pending"},
    ])
    assert "A long description here" in result


def test_format_iteration_plan_empty_list():
    """Empty list returns None."""
    result = _format_iteration_plan("iter-1", [])
    assert result is None


# --- iteration_policy iteration_plan tests ---


def _make_iter_dir_with_iteration_json(tmp_path, iterations):
    """Create iter_dir and iteration.json with the given iterations list."""
    team_dir = tmp_path / ".team"
    iter_dir = team_dir / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    data = {
        "schema_version": 1,
        "iterations": iterations,
        "current": "iter-1",
    }
    (team_dir / "iteration.json").write_text(json.dumps(data))
    return iter_dir


def test_iteration_policy_loads_iteration_plan(tmp_path):
    iterations = [
        {"id": "iter-1", "title": "First", "description": "Build", "status": "in-progress",
         "phase": "refinement", "max_turns": 10},
        {"id": "iter-2", "title": "Second", "description": "Polish", "status": "pending",
         "phase": "refinement", "max_turns": 10},
    ]
    iter_dir = _make_iter_dir_with_iteration_json(tmp_path, iterations)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.iteration_plan is not None
    assert ">> iter-1" in p.iteration_plan
    assert "iter-2" in p.iteration_plan


def test_iteration_policy_no_plan_for_single_iteration(tmp_path):
    iterations = [
        {"id": "iter-1", "title": "Only one", "description": "Build", "status": "in-progress",
         "phase": "refinement", "max_turns": 10},
    ]
    iter_dir = _make_iter_dir_with_iteration_json(tmp_path, iterations)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.iteration_plan is None


def test_iteration_policy_no_plan_when_no_iteration_json(tmp_path):
    """No iteration.json → gracefully None (try/except in policy)."""
    iter_dir = _make_iter_dir(tmp_path)
    p = iteration_policy(AGENTS, ITERATION, iter_dir, history=[])
    assert p.iteration_plan is None


def test_iteration_policy_code_review_gets_read_only_tools(tmp_path):
    """Code-review agents get read-only file tools (no file_write)."""
    iter_dir = _make_iter_dir(tmp_path)

    class FakeGuard:
        writable_paths = ["src/**"]
        protected_paths = []
        max_files_per_turn = 10
        max_file_size_bytes = 1048576
        enable_approvals = False

    code_review_iter = {**ITERATION, "phase": "code-review"}
    p = iteration_policy(AGENTS, code_review_iter, iter_dir, history=[], fileguard=FakeGuard())
    tool_names = {t["name"] for t in p.agent_tools}
    assert "file_read" in tool_names
    assert "file_list" in tool_names
    assert "file_write" not in tool_names


def test_iteration_policy_implementation_gets_full_tools(tmp_path):
    """Implementation agents get full file tools (including file_write)."""
    iter_dir = _make_iter_dir(tmp_path)

    class FakeGuard:
        writable_paths = ["src/**"]
        protected_paths = []
        max_files_per_turn = 10
        max_file_size_bytes = 1048576
        enable_approvals = False

    impl_iter = {**ITERATION, "phase": "implementation"}
    p = iteration_policy(AGENTS, impl_iter, iter_dir, history=[], fileguard=FakeGuard())
    tool_names = {t["name"] for t in p.agent_tools}
    assert "file_read" in tool_names
    assert "file_list" in tool_names
    assert "file_write" in tool_names


def test_approval_tools_included_when_approvals_enabled(tmp_path):
    """When approvals + approval_store are set, destructive tools are included."""
    iter_dir = _make_iter_dir(tmp_path)

    class FakeGuard:
        writable_paths = ["src/**"]
        protected_paths = []
        max_files_per_turn = 10
        max_file_size_bytes = 1048576
        enable_approvals = True

    class FakeStore:
        pass

    impl_iter = {**ITERATION, "phase": "implementation"}
    p = iteration_policy(AGENTS, impl_iter, iter_dir, history=[],
                         fileguard=FakeGuard(), approval_store=FakeStore())
    tool_names = {t["name"] for t in p.agent_tools}
    assert "file_delete" in tool_names
    assert "file_rename" in tool_names


def test_approval_tools_not_included_without_approvals(tmp_path):
    """Without approvals, destructive tools are absent."""
    iter_dir = _make_iter_dir(tmp_path)

    class FakeGuard:
        writable_paths = ["src/**"]
        protected_paths = []
        max_files_per_turn = 10
        max_file_size_bytes = 1048576
        enable_approvals = False

    impl_iter = {**ITERATION, "phase": "implementation"}
    p = iteration_policy(AGENTS, impl_iter, iter_dir, history=[], fileguard=FakeGuard())
    tool_names = {t["name"] for t in p.agent_tools}
    assert "file_delete" not in tool_names
    assert "file_rename" not in tool_names


def test_approval_tools_not_in_code_review(tmp_path):
    """Code review phase uses read-only tools — no destructive tools."""
    iter_dir = _make_iter_dir(tmp_path)

    class FakeGuard:
        writable_paths = ["src/**"]
        protected_paths = []
        max_files_per_turn = 10
        max_file_size_bytes = 1048576
        enable_approvals = True

    class FakeStore:
        pass

    review_iter = {**ITERATION, "phase": "code-review"}
    p = iteration_policy(AGENTS, review_iter, iter_dir, history=[],
                         fileguard=FakeGuard(), approval_store=FakeStore())
    tool_names = {t["name"] for t in p.agent_tools}
    assert "file_delete" not in tool_names
    assert "file_rename" not in tool_names
    assert "file_write" not in tool_names  # code-review is read-only


def test_grooming_never_gets_destructive_tools():
    """Grooming policy never includes destructive file tools."""
    from gotg.policy import grooming_policy
    p = grooming_policy(AGENTS, "test topic", history=[])
    tool_names = {t["name"] for t in p.agent_tools}
    assert "file_delete" not in tool_names
    assert "file_rename" not in tool_names
