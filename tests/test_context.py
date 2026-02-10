import json
from pathlib import Path

import pytest

from gotg.config import IterationStore
from gotg.context import TeamContext
from gotg.conversation import ConversationStore


# --- Helpers ---

def _write_team_json(team_dir, model=None, agents=None, coach=None,
                     file_access=None, worktrees=None):
    """Write team.json with given sections."""
    data = {
        "model": model or {
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:7b",
        },
        "agents": agents or [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
    }
    if coach is not None:
        data["coach"] = coach
    if file_access is not None:
        data["file_access"] = file_access
    if worktrees is not None:
        data["worktrees"] = worktrees
    (team_dir / "team.json").write_text(json.dumps(data, indent=2))


def _write_iteration_json(team_dir, iterations=None, current="iter-1"):
    """Write list-format iteration.json."""
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": iterations or [
            {
                "id": "iter-1",
                "title": "Test Task",
                "description": "Design a todo app",
                "status": "in-progress",
                "phase": "refinement",
                "max_turns": 10,
            }
        ],
        "current": current,
    }, indent=2))


@pytest.fixture
def team_dir(tmp_path):
    """Create a minimal .team/ directory."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    return team


# --- TeamContext tests ---

def test_from_team_dir_loads_all_config(team_dir):
    _write_team_json(team_dir, coach={"name": "coach", "role": "Agile Coach"},
                     file_access={"writable_paths": ["src/**"]},
                     worktrees={"enabled": True})
    ctx = TeamContext.from_team_dir(team_dir)
    assert ctx.model_config["provider"] == "ollama"
    assert len(ctx.agents) == 2
    assert ctx.agents[0]["name"] == "agent-1"
    assert ctx.coach["name"] == "coach"
    assert ctx.file_access["writable_paths"] == ["src/**"]
    assert ctx.worktree_config["enabled"] is True
    assert ctx.team_dir == team_dir
    assert ctx.project_root == team_dir.parent


def test_from_team_dir_without_coach(team_dir):
    ctx = TeamContext.from_team_dir(team_dir)
    assert ctx.coach is None


def test_from_team_dir_without_file_access(team_dir):
    ctx = TeamContext.from_team_dir(team_dir)
    assert ctx.file_access is None


def test_from_team_dir_without_worktree_config(team_dir):
    ctx = TeamContext.from_team_dir(team_dir)
    assert ctx.worktree_config is None


def test_project_root_is_parent_of_team_dir(team_dir):
    ctx = TeamContext.from_team_dir(team_dir)
    assert ctx.project_root == team_dir.parent


def test_context_is_frozen(team_dir):
    ctx = TeamContext.from_team_dir(team_dir)
    with pytest.raises(AttributeError):
        ctx.agents = []


# --- IterationStore tests ---

def test_iteration_store_get_current(team_dir):
    store = IterationStore(team_dir)
    iteration, iter_dir = store.get_current()
    assert iteration["id"] == "iter-1"
    assert iteration["description"] == "Design a todo app"
    assert iter_dir == team_dir / "iterations" / "iter-1"


def test_iteration_store_load(team_dir):
    store = IterationStore(team_dir)
    iteration = store.load()
    assert iteration["id"] == "iter-1"
    assert iteration["phase"] == "refinement"


def test_iteration_store_save_fields(team_dir):
    store = IterationStore(team_dir)
    store.save_fields("iter-1", phase="planning", current_layer=1)
    iteration = store.load()
    assert iteration["phase"] == "planning"
    assert iteration["current_layer"] == 1


def test_iteration_store_save_phase(team_dir):
    store = IterationStore(team_dir)
    store.save_phase("iter-1", "implementation")
    iteration = store.load()
    assert iteration["phase"] == "implementation"


def test_iteration_store_get_dir(team_dir):
    store = IterationStore(team_dir)
    assert store.get_dir("iter-1") == team_dir / "iterations" / "iter-1"


def test_iteration_store_from_context(team_dir):
    ctx = TeamContext.from_team_dir(team_dir)
    iteration, iter_dir = ctx.iteration_store.get_current()
    assert iteration["id"] == "iter-1"
    assert iter_dir.name == "iter-1"


# --- ConversationStore tests ---

def test_conversation_store_read_full(tmp_path):
    log_path = tmp_path / "conversation.jsonl"
    log_path.write_text(
        json.dumps({"from": "agent-1", "iteration": "iter-1", "content": "hello"}) + "\n"
        + json.dumps({"from": "agent-2", "iteration": "iter-1", "content": "hi"}) + "\n"
    )
    store = ConversationStore(log_path)
    msgs = store.read_full()
    assert len(msgs) == 2
    assert msgs[0]["from"] == "agent-1"
    assert msgs[1]["content"] == "hi"


def test_conversation_store_append(tmp_path):
    log_path = tmp_path / "conversation.jsonl"
    store = ConversationStore(log_path)
    store.append({"from": "agent-1", "iteration": "iter-1", "content": "test"})
    msgs = store.read_full()
    assert len(msgs) == 1
    assert msgs[0]["content"] == "test"


def test_conversation_store_read_phase_history(tmp_path):
    log_path = tmp_path / "conversation.jsonl"
    lines = [
        json.dumps({"from": "agent-1", "iteration": "iter-1", "content": "old"}),
        json.dumps({"from": "system", "iteration": "iter-1", "content": "--- BOUNDARY ---", "phase_boundary": True}),
        json.dumps({"from": "agent-1", "iteration": "iter-1", "content": "new"}),
    ]
    log_path.write_text("\n".join(lines) + "\n")
    store = ConversationStore(log_path)
    history = store.read_phase_history()
    assert len(history) == 1
    assert history[0]["content"] == "new"


def test_conversation_store_append_debug(tmp_path):
    log_path = tmp_path / "conversation.jsonl"
    debug_path = tmp_path / "debug.jsonl"
    store = ConversationStore(log_path, debug_path=debug_path)
    store.append_debug({"turn": 0, "agent": "agent-1"})
    content = debug_path.read_text().strip()
    parsed = json.loads(content)
    assert parsed["turn"] == 0
    assert parsed["agent"] == "agent-1"


def test_conversation_store_append_debug_noop_without_path(tmp_path):
    log_path = tmp_path / "conversation.jsonl"
    store = ConversationStore(log_path)  # no debug_path
    store.append_debug({"turn": 0})  # should not raise
    # No debug file should exist
    assert not (tmp_path / "debug.jsonl").exists()
