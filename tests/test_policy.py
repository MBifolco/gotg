import json
import pytest
from pathlib import Path

from gotg.policy import SessionPolicy, iteration_policy, grooming_policy
from gotg.prompts import AGENT_TOOLS, COACH_TOOLS
from gotg.tools import FILE_TOOLS


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
    p = grooming_policy(AGENTS, "Discuss feature X")
    assert p.coach is None
    assert p.coach_cadence is None
    assert p.stop_on_phase_complete is False
    assert p.stop_on_ask_pm is False
    assert p.coach_tools is None
    assert isinstance(p.agent_tools, tuple)
    assert p.max_turns == 30


def test_grooming_policy_max_turns():
    p = grooming_policy(AGENTS, "Discuss feature X", max_turns=50)
    assert p.max_turns == 50
