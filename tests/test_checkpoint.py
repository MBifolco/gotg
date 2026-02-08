import json
from pathlib import Path

import pytest

from gotg.checkpoint import (
    CHECKPOINT_EXCLUDE,
    _iter_files,
    _next_checkpoint_number,
    _count_agent_turns,
    create_checkpoint,
    list_checkpoints,
    restore_checkpoint,
)


@pytest.fixture
def iter_dir(tmp_path):
    """Create a minimal iteration directory."""
    d = tmp_path / "iter-1"
    d.mkdir()
    return d


def _write_conversation(iter_dir, messages):
    """Write messages to conversation.jsonl."""
    path = iter_dir / "conversation.jsonl"
    path.write_text("\n".join(json.dumps(m) for m in messages) + "\n")


def _sample_iteration(**overrides):
    """Return a sample iteration dict."""
    base = {
        "id": "iter-1",
        "phase": "grooming",
        "status": "in-progress",
        "max_turns": 10,
        "description": "Test iteration",
    }
    base.update(overrides)
    return base


# --- _iter_files ---

def test_iter_files_returns_all_files(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    (iter_dir / "groomed.md").write_text("summary")
    result = _iter_files(iter_dir)
    assert "conversation.jsonl" in result
    assert "groomed.md" in result


def test_iter_files_excludes_debug_jsonl(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    (iter_dir / "debug.jsonl").touch()
    result = _iter_files(iter_dir)
    assert "conversation.jsonl" in result
    assert "debug.jsonl" not in result


def test_iter_files_excludes_checkpoints_dir(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    (iter_dir / "checkpoints").mkdir()
    result = _iter_files(iter_dir)
    assert "checkpoints" not in result


def test_iter_files_empty_dir(iter_dir):
    result = _iter_files(iter_dir)
    assert result == []


def test_iter_files_does_not_recurse(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    sub = iter_dir / "subdir"
    sub.mkdir()
    (sub / "nested.txt").touch()
    result = _iter_files(iter_dir)
    assert "nested.txt" not in result


def test_iter_files_returns_sorted(iter_dir):
    (iter_dir / "tasks.json").touch()
    (iter_dir / "conversation.jsonl").touch()
    (iter_dir / "groomed.md").touch()
    result = _iter_files(iter_dir)
    assert result == sorted(result)


# --- _next_checkpoint_number ---

def test_next_checkpoint_number_no_checkpoints(iter_dir):
    assert _next_checkpoint_number(iter_dir) == 1


def test_next_checkpoint_number_no_checkpoints_dir(iter_dir):
    # checkpoints/ doesn't exist at all
    assert _next_checkpoint_number(iter_dir) == 1


def test_next_checkpoint_number_with_existing(iter_dir):
    (iter_dir / "checkpoints" / "1").mkdir(parents=True)
    (iter_dir / "checkpoints" / "2").mkdir()
    assert _next_checkpoint_number(iter_dir) == 3


def test_next_checkpoint_number_gaps(iter_dir):
    (iter_dir / "checkpoints" / "1").mkdir(parents=True)
    (iter_dir / "checkpoints" / "5").mkdir()
    assert _next_checkpoint_number(iter_dir) == 6


def test_next_checkpoint_number_ignores_non_numeric(iter_dir):
    (iter_dir / "checkpoints" / "1").mkdir(parents=True)
    (iter_dir / "checkpoints" / "temp").mkdir()
    assert _next_checkpoint_number(iter_dir) == 2


# --- _count_agent_turns ---

def test_count_agent_turns_empty(iter_dir):
    assert _count_agent_turns(iter_dir) == 0


def test_count_agent_turns_no_conversation_file(iter_dir):
    assert _count_agent_turns(iter_dir) == 0


def test_count_agent_turns_counts_only_agents(iter_dir):
    _write_conversation(iter_dir, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
        {"from": "human", "iteration": "iter-1", "content": "question"},
        {"from": "agent-2", "iteration": "iter-1", "content": "response"},
        {"from": "coach", "iteration": "iter-1", "content": "summary"},
        {"from": "system", "iteration": "iter-1", "content": "transition"},
        {"from": "agent-1", "iteration": "iter-1", "content": "more"},
    ])
    assert _count_agent_turns(iter_dir) == 3


def test_count_agent_turns_custom_coach_name(iter_dir):
    """Coach with a renamed name should still be excluded from agent turn count."""
    _write_conversation(iter_dir, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
        {"from": "scrum-master", "iteration": "iter-1", "content": "facilitation"},
        {"from": "agent-2", "iteration": "iter-1", "content": "response"},
    ])
    # Default coach_name="coach" would count "scrum-master" as agent turn
    assert _count_agent_turns(iter_dir) == 3
    # With correct coach_name, scrum-master is excluded
    assert _count_agent_turns(iter_dir, coach_name="scrum-master") == 2


# --- create_checkpoint ---

def test_create_checkpoint_returns_number(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    number = create_checkpoint(iter_dir, _sample_iteration())
    assert number == 1


def test_create_checkpoint_creates_directory(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    create_checkpoint(iter_dir, _sample_iteration())
    assert (iter_dir / "checkpoints" / "1").is_dir()


def test_create_checkpoint_copies_files(iter_dir):
    (iter_dir / "conversation.jsonl").write_text('{"from":"a","content":"hi"}\n')
    (iter_dir / "groomed.md").write_text("summary")
    create_checkpoint(iter_dir, _sample_iteration())
    cp = iter_dir / "checkpoints" / "1"
    assert (cp / "conversation.jsonl").read_text() == '{"from":"a","content":"hi"}\n'
    assert (cp / "groomed.md").read_text() == "summary"


def test_create_checkpoint_skips_missing_files(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    # groomed.md doesn't exist — should not error
    number = create_checkpoint(iter_dir, _sample_iteration())
    cp = iter_dir / "checkpoints" / str(number)
    assert not (cp / "groomed.md").exists()


def test_create_checkpoint_excludes_debug(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    (iter_dir / "debug.jsonl").write_text("debug data")
    create_checkpoint(iter_dir, _sample_iteration())
    cp = iter_dir / "checkpoints" / "1"
    assert not (cp / "debug.jsonl").exists()


def test_create_checkpoint_writes_state_json(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    iteration = _sample_iteration(phase="planning", max_turns=20)
    create_checkpoint(iter_dir, iteration, description="test save", trigger="manual")
    state = json.loads((iter_dir / "checkpoints" / "1" / "state.json").read_text())
    assert state["number"] == 1
    assert state["phase"] == "planning"
    assert state["status"] == "in-progress"
    assert state["max_turns"] == 20
    assert state["description"] == "test save"
    assert state["trigger"] == "manual"
    assert "timestamp" in state


def test_create_checkpoint_auto_description(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    create_checkpoint(iter_dir, _sample_iteration(), trigger="auto")
    state = json.loads((iter_dir / "checkpoints" / "1" / "state.json").read_text())
    assert state["description"] == "Auto after auto"


def test_create_checkpoint_increments(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    iteration = _sample_iteration()
    n1 = create_checkpoint(iter_dir, iteration)
    n2 = create_checkpoint(iter_dir, iteration)
    n3 = create_checkpoint(iter_dir, iteration)
    assert (n1, n2, n3) == (1, 2, 3)


def test_create_checkpoint_state_has_turn_count(iter_dir):
    _write_conversation(iter_dir, [
        {"from": "agent-1", "iteration": "iter-1", "content": "a"},
        {"from": "agent-2", "iteration": "iter-1", "content": "b"},
        {"from": "coach", "iteration": "iter-1", "content": "c"},
    ])
    create_checkpoint(iter_dir, _sample_iteration())
    state = json.loads((iter_dir / "checkpoints" / "1" / "state.json").read_text())
    assert state["turn_count"] == 2  # only agent turns


# --- Safety net: discovery covers unknown artifacts ---

def test_create_checkpoint_includes_unknown_artifacts(iter_dir):
    """New artifact files are automatically backed up without code changes."""
    (iter_dir / "conversation.jsonl").touch()
    (iter_dir / "groomed.md").write_text("scope")
    (iter_dir / "tasks.json").write_text("[]")
    (iter_dir / "new_artifact.txt").write_text("future data")
    (iter_dir / "debug.jsonl").write_text("excluded")

    create_checkpoint(iter_dir, _sample_iteration())
    cp = iter_dir / "checkpoints" / "1"
    assert (cp / "new_artifact.txt").exists()
    assert (cp / "new_artifact.txt").read_text() == "future data"
    assert not (cp / "debug.jsonl").exists()


# --- list_checkpoints ---

def test_list_checkpoints_empty(iter_dir):
    assert list_checkpoints(iter_dir) == []


def test_list_checkpoints_no_checkpoints_dir(iter_dir):
    assert list_checkpoints(iter_dir) == []


def test_list_checkpoints_returns_sorted(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    iteration = _sample_iteration()
    create_checkpoint(iter_dir, iteration, description="first")
    iteration["phase"] = "planning"
    create_checkpoint(iter_dir, iteration, description="second")
    result = list_checkpoints(iter_dir)
    assert len(result) == 2
    assert result[0]["number"] == 1
    assert result[0]["description"] == "first"
    assert result[1]["number"] == 2
    assert result[1]["description"] == "second"


def test_list_checkpoints_skips_missing_state_json(iter_dir):
    (iter_dir / "checkpoints" / "1").mkdir(parents=True)
    # No state.json — should be skipped
    result = list_checkpoints(iter_dir)
    assert result == []


# --- restore_checkpoint ---

def test_restore_checkpoint_copies_files_back(iter_dir):
    original = '{"from":"agent-1","iteration":"iter-1","content":"original"}\n'
    (iter_dir / "conversation.jsonl").write_text(original)
    create_checkpoint(iter_dir, _sample_iteration())

    # Modify current state
    (iter_dir / "conversation.jsonl").write_text('{"from":"agent-1","iteration":"iter-1","content":"modified"}\n')

    restore_checkpoint(iter_dir, 1)
    assert (iter_dir / "conversation.jsonl").read_text() == original


def test_restore_checkpoint_removes_files_not_in_checkpoint(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    create_checkpoint(iter_dir, _sample_iteration())

    # Add a new file after checkpoint
    (iter_dir / "tasks.json").write_text("[]")

    restore_checkpoint(iter_dir, 1)
    assert not (iter_dir / "tasks.json").exists()


def test_restore_checkpoint_returns_state(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    iteration = _sample_iteration(phase="planning", max_turns=20)
    create_checkpoint(iter_dir, iteration)

    state = restore_checkpoint(iter_dir, 1)
    assert state["phase"] == "planning"
    assert state["max_turns"] == 20


def test_restore_checkpoint_invalid_number(iter_dir):
    with pytest.raises(ValueError, match="does not exist"):
        restore_checkpoint(iter_dir, 99)


def test_restore_checkpoint_preserves_checkpoints_dir(iter_dir):
    (iter_dir / "conversation.jsonl").touch()
    create_checkpoint(iter_dir, _sample_iteration())
    create_checkpoint(iter_dir, _sample_iteration())

    restore_checkpoint(iter_dir, 1)
    # Both checkpoints should still exist
    assert (iter_dir / "checkpoints" / "1").exists()
    assert (iter_dir / "checkpoints" / "2").exists()
