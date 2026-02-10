"""Tests for gotg.session — shared session helpers."""

import json
from pathlib import Path

from gotg.events import (
    AppendDebug,
    AppendMessage,
    PauseForApprovals,
    SessionComplete,
    SessionStarted,
)
import pytest

from gotg.session import (
    SessionSetupError,
    build_file_infra,
    load_diffs_for_review,
    persist_event,
    resolve_layer,
    setup_worktrees,
    validate_iteration_for_run,
)


# ── persist_event ────────────────────────────────────────────


def test_persist_event_append_message(tmp_path):
    log = tmp_path / "conversation.jsonl"
    debug = tmp_path / "debug.jsonl"
    msg = {"from": "agent-1", "content": "hello"}
    persist_event(AppendMessage(msg), log, debug)
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["content"] == "hello"
    assert not debug.exists()


def test_persist_event_append_debug(tmp_path):
    log = tmp_path / "conversation.jsonl"
    debug = tmp_path / "debug.jsonl"
    entry = {"turn": 1, "agent": "agent-1"}
    persist_event(AppendDebug(entry), log, debug)
    lines = debug.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["turn"] == 1
    assert not log.exists()


def test_persist_event_noop_for_session_started(tmp_path):
    log = tmp_path / "conversation.jsonl"
    debug = tmp_path / "debug.jsonl"
    event = SessionStarted(
        iteration_id="iter-1", description="test", phase="refinement",
        current_layer=None, agents=["a1"], coach=None, has_file_tools=False,
        writable_paths=None, worktree_count=0, turn=0, max_turns=30,
    )
    persist_event(event, log, debug)
    assert not log.exists()
    assert not debug.exists()


def test_persist_event_noop_for_session_complete(tmp_path):
    log = tmp_path / "conversation.jsonl"
    debug = tmp_path / "debug.jsonl"
    persist_event(SessionComplete(total_turns=5), log, debug)
    assert not log.exists()
    assert not debug.exists()


def test_persist_event_noop_for_pause(tmp_path):
    log = tmp_path / "conversation.jsonl"
    debug = tmp_path / "debug.jsonl"
    persist_event(PauseForApprovals(pending_count=3), log, debug)
    assert not log.exists()
    assert not debug.exists()


def test_persist_event_multiple_messages(tmp_path):
    log = tmp_path / "conversation.jsonl"
    debug = tmp_path / "debug.jsonl"
    persist_event(AppendMessage({"from": "a1", "content": "first"}), log, debug)
    persist_event(AppendMessage({"from": "a2", "content": "second"}), log, debug)
    persist_event(AppendDebug({"turn": 1}), log, debug)
    log_lines = log.read_text().strip().splitlines()
    debug_lines = debug.read_text().strip().splitlines()
    assert len(log_lines) == 2
    assert len(debug_lines) == 1


# ── resolve_layer ────────────────────────────────────────────


def test_resolve_layer_override_wins():
    assert resolve_layer(5, {"current_layer": 2}) == 5


def test_resolve_layer_from_iteration():
    assert resolve_layer(None, {"current_layer": 3}) == 3


def test_resolve_layer_default_zero():
    assert resolve_layer(None, {}) == 0


# ── validate_iteration_for_run ───────────────────────────────


def _agents(n=2):
    return [{"name": f"agent-{i+1}", "role": "SE"} for i in range(n)]


def test_validate_raises_on_empty_description(tmp_path):
    iteration = {"id": "i", "description": "", "status": "in-progress", "phase": "refinement"}
    with pytest.raises(SessionSetupError, match="description is empty"):
        validate_iteration_for_run(iteration, tmp_path, _agents())


def test_validate_raises_on_wrong_status(tmp_path):
    iteration = {"id": "i", "description": "d", "status": "complete", "phase": "refinement"}
    with pytest.raises(SessionSetupError, match="complete"):
        validate_iteration_for_run(iteration, tmp_path, _agents())


def test_validate_raises_on_too_few_agents(tmp_path):
    iteration = {"id": "i", "description": "d", "status": "in-progress", "phase": "refinement"}
    with pytest.raises(SessionSetupError, match="at least 2"):
        validate_iteration_for_run(iteration, tmp_path, _agents(1))


def test_validate_passes_for_refinement(tmp_path):
    iteration = {"id": "i", "description": "d", "status": "in-progress", "phase": "refinement"}
    validate_iteration_for_run(iteration, tmp_path, _agents())  # should not raise


def test_validate_raises_missing_tasks_json(tmp_path):
    iteration = {"id": "i", "description": "d", "status": "in-progress", "phase": "pre-code-review"}
    with pytest.raises(SessionSetupError, match="tasks.json"):
        validate_iteration_for_run(iteration, tmp_path, _agents())


# ── build_file_infra ─────────────────────────────────────────


def test_build_file_infra_no_config(tmp_path):
    fg, store = build_file_infra(tmp_path, None, tmp_path)
    assert fg is None
    assert store is None


def test_build_file_infra_with_config(tmp_path):
    file_access = {"writable_paths": ["src/**"]}
    fg, store = build_file_infra(tmp_path, file_access, tmp_path)
    assert fg is not None
    assert store is None  # enable_approvals not set


def test_build_file_infra_with_approvals(tmp_path):
    file_access = {"writable_paths": ["src/**"], "enable_approvals": True}
    fg, store = build_file_infra(tmp_path, file_access, tmp_path)
    assert fg is not None
    assert store is not None


# ── setup_worktrees ──────────────────────────────────────────


def test_setup_worktrees_disabled(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text(json.dumps({"model": {}, "agents": []}))
    result, warnings = setup_worktrees(team, [], None, None, {"phase": "implementation"})
    assert result is None
    assert warnings == []


def test_setup_worktrees_skips_refinement(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text(json.dumps({
        "model": {}, "agents": [], "worktrees": {"enabled": True},
    }))
    result, warnings = setup_worktrees(team, [], None, None, {"phase": "refinement"})
    assert result is None


def test_setup_worktrees_warns_no_fileguard(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text(json.dumps({
        "model": {}, "agents": [], "worktrees": {"enabled": True},
    }))
    result, warnings = setup_worktrees(team, [], None, None, {"phase": "implementation"})
    assert result is None
    assert any("file tools" in w for w in warnings)


# ── load_diffs_for_review ────────────────────────────────────


def test_load_diffs_noop_for_refinement(tmp_path):
    diffs, warnings = load_diffs_for_review(tmp_path, {"phase": "refinement"}, None)
    assert diffs is None
    assert warnings == []


def test_load_diffs_warns_no_worktrees(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text(json.dumps({"model": {}, "agents": []}))
    diffs, warnings = load_diffs_for_review(team, {"phase": "code-review"}, None)
    assert diffs is None
    assert any("worktrees not enabled" in w for w in warnings)
