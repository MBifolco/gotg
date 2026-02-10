import json
import time
from pathlib import Path

from gotg.tui.data import list_iterations, load_session_metadata, relative_time


# ── list_iterations ─────────────────────────────────────────────


def _write_iteration_json(team_dir, iterations, current="iter-1"):
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": iterations,
        "current": current,
    }))


def test_list_iterations_missing_file(tmp_path):
    assert list_iterations(tmp_path) == []


def test_list_iterations_empty_list(tmp_path):
    _write_iteration_json(tmp_path, [])
    assert list_iterations(tmp_path) == []


def test_list_iterations_single(tmp_path):
    it = {"id": "iter-1", "description": "Build a thing", "phase": "refinement", "status": "in-progress", "max_turns": 30}
    _write_iteration_json(tmp_path, [it])
    it_dir = tmp_path / "iterations" / "iter-1"
    it_dir.mkdir(parents=True)
    log = it_dir / "conversation.jsonl"
    log.write_text('{"from":"agent-1","content":"hello"}\n{"from":"agent-2","content":"hi"}\n')

    result = list_iterations(tmp_path)
    assert len(result) == 1
    assert result[0]["id"] == "iter-1"
    assert result[0]["is_current"] is True
    assert result[0]["message_count"] == 2
    assert result[0]["last_modified"] is not None
    assert result[0]["description"] == "Build a thing"


def test_list_iterations_multiple_with_current(tmp_path):
    iterations = [
        {"id": "iter-1", "description": "First", "phase": "planning", "status": "complete", "max_turns": 10},
        {"id": "iter-2", "description": "Second", "phase": "refinement", "status": "in-progress", "max_turns": 20},
    ]
    _write_iteration_json(tmp_path, iterations, current="iter-2")
    for it in iterations:
        d = tmp_path / "iterations" / it["id"]
        d.mkdir(parents=True)
        (d / "conversation.jsonl").touch()

    result = list_iterations(tmp_path)
    assert len(result) == 2
    assert result[0]["is_current"] is False
    assert result[1]["is_current"] is True


def test_list_iterations_missing_conversation_log(tmp_path):
    it = {"id": "iter-1", "description": "No log", "status": "pending", "max_turns": 10}
    _write_iteration_json(tmp_path, [it])
    (tmp_path / "iterations" / "iter-1").mkdir(parents=True)
    # No conversation.jsonl file

    result = list_iterations(tmp_path)
    assert result[0]["message_count"] == 0
    assert result[0]["last_modified"] is None


def test_list_iterations_empty_log(tmp_path):
    it = {"id": "iter-1", "description": "Empty", "status": "pending", "max_turns": 10}
    _write_iteration_json(tmp_path, [it])
    d = tmp_path / "iterations" / "iter-1"
    d.mkdir(parents=True)
    (d / "conversation.jsonl").write_text("\n\n")

    result = list_iterations(tmp_path)
    assert result[0]["message_count"] == 0


def test_list_iterations_preserves_extra_fields(tmp_path):
    it = {"id": "iter-1", "description": "X", "status": "in-progress", "max_turns": 10, "current_layer": 2, "title": "My Title"}
    _write_iteration_json(tmp_path, [it])
    (tmp_path / "iterations" / "iter-1").mkdir(parents=True)
    (tmp_path / "iterations" / "iter-1" / "conversation.jsonl").touch()

    result = list_iterations(tmp_path)
    assert result[0]["current_layer"] == 2
    assert result[0]["title"] == "My Title"


# ── load_session_metadata ───────────────────────────────────────


def test_load_session_metadata(tmp_path):
    team_json = {
        "agents": [{"name": "agent-1", "role": "Engineer"}],
        "coach": {"name": "coach", "role": "Agile Coach"},
        "model": {"provider": "ollama"},
    }
    (tmp_path / "team.json").write_text(json.dumps(team_json))

    meta = {"id": "iter-1", "description": "Test", "phase": "refinement"}
    result = load_session_metadata(tmp_path, meta)

    assert result["id"] == "iter-1"
    assert result["agents"] == [{"name": "agent-1", "role": "Engineer"}]
    assert result["coach"] == {"name": "coach", "role": "Agile Coach"}


def test_load_session_metadata_no_coach(tmp_path):
    team_json = {
        "agents": [{"name": "agent-1", "role": "Engineer"}],
        "model": {"provider": "ollama"},
    }
    (tmp_path / "team.json").write_text(json.dumps(team_json))

    meta = {"slug": "test-groom", "topic": "Explore errors"}
    result = load_session_metadata(tmp_path, meta)

    assert result["slug"] == "test-groom"
    assert result["coach"] is None


# ── relative_time ───────────────────────────────────────────────


def test_relative_time_none():
    assert relative_time(None) == ""


def test_relative_time_just_now():
    assert relative_time(time.time() - 10) == "just now"


def test_relative_time_minutes():
    assert relative_time(time.time() - 300) == "5m ago"


def test_relative_time_hours():
    assert relative_time(time.time() - 7200) == "2h ago"


def test_relative_time_days():
    assert relative_time(time.time() - 172800) == "2d ago"
