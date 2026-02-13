"""Tests for gotg.session — shared session helpers."""

import json
from pathlib import Path

from gotg.conversation import append_message as conv_append_message
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
    apply_and_inject,
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


# ── apply_and_inject ────────────────────────────────────────


def _make_approval_infra(tmp_path):
    """Create project dir, iter dir, fileguard, and approval store."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    iter_dir = tmp_path / "iter"
    iter_dir.mkdir()
    log_path = iter_dir / "conversation.jsonl"

    from gotg.approvals import ApprovalStore
    from gotg.fileguard import FileGuard

    file_access = {"writable_paths": ["**"], "enable_approvals": True}
    guard = FileGuard(project, file_access)
    store = ApprovalStore(iter_dir / "approvals.json")
    return project, iter_dir, log_path, guard, store


def test_apply_and_inject_applies_approved(tmp_path):
    """Approved writes get applied and system messages returned."""
    project, iter_dir, log_path, guard, store = _make_approval_infra(tmp_path)

    store.add_request("src/hello.py", "print('hi')", "agent-1", {})
    store.approve("a1")

    iteration = {"id": "iter-1"}
    messages = apply_and_inject(store, guard, iteration, log_path)

    assert len(messages) == 1
    assert "APPROVED" in messages[0]["content"]
    assert "src/hello.py" in messages[0]["content"]
    assert (project / "src" / "hello.py").read_text() == "print('hi')"
    # Verify persisted to log
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1


def test_apply_and_inject_injects_denials(tmp_path):
    """Denied requests get system messages and are marked injected."""
    _project, iter_dir, log_path, guard, store = _make_approval_infra(tmp_path)

    store.add_request("hack.py", "evil", "agent-1", {})
    store.deny("a1", "Not allowed")

    iteration = {"id": "iter-1"}
    messages = apply_and_inject(store, guard, iteration, log_path)

    assert len(messages) == 1
    assert "DENIED" in messages[0]["content"]
    assert "Not allowed" in messages[0]["content"]
    assert "agent-1" in messages[0]["content"]
    # Verify marked as injected
    reloaded = store._get("a1")
    assert reloaded.get("injected") is True


def test_apply_and_inject_noop_when_empty(tmp_path):
    """No messages when nothing to apply or inject."""
    _project, _iter_dir, log_path, guard, store = _make_approval_infra(tmp_path)

    iteration = {"id": "iter-1"}
    messages = apply_and_inject(store, guard, iteration, log_path)

    assert messages == []
    assert not log_path.exists()


def test_apply_and_inject_mixed(tmp_path):
    """Handles both approved and denied in same call."""
    project, iter_dir, log_path, guard, store = _make_approval_infra(tmp_path)

    store.add_request("src/good.py", "good code", "agent-1", {})
    store.add_request("src/bad.py", "bad code", "agent-2", {})
    store.approve("a1")
    store.deny("a2", "nope")

    iteration = {"id": "iter-1"}
    messages = apply_and_inject(store, guard, iteration, log_path)

    assert len(messages) == 2
    assert "APPROVED" in messages[0]["content"]
    assert "DENIED" in messages[1]["content"]
    assert (project / "src" / "good.py").read_text() == "good code"
    assert not (project / "src" / "bad.py").exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2


# ── validate_advance / advance_phase ──────────────────────────────

from gotg.session import PhaseAdvanceError, validate_advance, advance_phase, AdvanceResult


def test_validate_advance_success():
    iteration = {"phase": "refinement", "status": "in-progress"}
    current, next_ = validate_advance(iteration)
    assert current == "refinement"
    assert next_ == "planning"


def test_validate_advance_last_phase():
    iteration = {"phase": "code-review", "status": "in-progress"}
    with pytest.raises(PhaseAdvanceError, match="Cannot advance past"):
        validate_advance(iteration)


def test_validate_advance_unknown_phase():
    iteration = {"phase": "bogus", "status": "in-progress"}
    with pytest.raises(PhaseAdvanceError, match="Unknown phase"):
        validate_advance(iteration)


def test_validate_advance_wrong_status():
    iteration = {"phase": "refinement", "status": "pending"}
    with pytest.raises(PhaseAdvanceError, match="expected 'in-progress'"):
        validate_advance(iteration)


def _make_advance_team_dir(tmp_path, phase="refinement", with_coach=True):
    """Create a minimal .team dir for advance_phase tests."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()

    team_config = {
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "model": {"provider": "ollama", "model": "test", "base_url": "http://localhost:11434"},
    }
    if with_coach:
        team_config["coach"] = {"name": "coach", "role": "Agile Coach"}
    (team_dir / "team.json").write_text(json.dumps(team_config))

    iteration = {
        "id": "iter-1", "description": "test", "status": "in-progress",
        "phase": phase, "max_turns": 10,
    }
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [iteration],
        "current": "iter-1",
    }))

    iter_dir = team_dir / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    # Seed minimal conversation so advance guard passes
    (iter_dir / "conversation.jsonl").write_text(
        json.dumps({"from": "agent-1", "iteration": "iter-1", "content": "Ready."}) + "\n"
    )

    return team_dir, iter_dir, iteration


def test_advance_refinement_to_planning(tmp_path):
    """advance_phase writes refinement_summary.md and returns correct result."""
    team_dir, iter_dir, iteration = _make_advance_team_dir(tmp_path, phase="refinement")
    log_path = iter_dir / "conversation.jsonl"
    conv_append_message(log_path, {"from": "agent-1", "content": "We need auth."})

    mock_chat = lambda **kwargs: "## Summary\nAuth system."
    result = advance_phase(team_dir, iteration, iter_dir, chat_call=mock_chat)

    assert result.from_phase == "refinement"
    assert result.to_phase == "planning"
    assert (iter_dir / "refinement_summary.md").exists()
    assert "Auth system" in (iter_dir / "refinement_summary.md").read_text()
    assert result.checkpoint_number is not None
    assert len(result.warnings) == 0


def test_advance_planning_bad_json(tmp_path):
    """Bad JSON from LLM produces warnings but advance succeeds."""
    team_dir, iter_dir, iteration = _make_advance_team_dir(tmp_path, phase="planning")
    log_path = iter_dir / "conversation.jsonl"
    conv_append_message(log_path, {"from": "agent-1", "content": "Task plan here."})

    mock_chat = lambda **kwargs: "not valid json at all"
    result = advance_phase(team_dir, iteration, iter_dir, chat_call=mock_chat)

    assert result.from_phase == "planning"
    assert result.to_phase == "pre-code-review"
    assert len(result.warnings) > 0
    assert (iter_dir / "tasks_raw.txt").exists()
    assert not (iter_dir / "tasks.json").exists()


def test_advance_on_progress_called(tmp_path):
    """on_progress callback receives step messages."""
    team_dir, iter_dir, iteration = _make_advance_team_dir(tmp_path, phase="refinement")
    log_path = iter_dir / "conversation.jsonl"
    conv_append_message(log_path, {"from": "agent-1", "content": "stuff"})

    progress_msgs = []
    mock_chat = lambda **kwargs: "summary"
    result = advance_phase(
        team_dir, iteration, iter_dir, chat_call=mock_chat,
        on_progress=progress_msgs.append,
    )

    assert len(progress_msgs) >= 2  # at least extraction msg + checkpoint msg
    assert any("refinement" in m.lower() or "summariz" in m.lower() for m in progress_msgs)


def test_advance_without_coach_skips_extraction(tmp_path):
    """No coach → no extraction, but advance still works."""
    team_dir, iter_dir, iteration = _make_advance_team_dir(
        tmp_path, phase="refinement", with_coach=False
    )

    mock_chat = lambda **kwargs: "should not be called"
    result = advance_phase(team_dir, iteration, iter_dir, chat_call=mock_chat)

    assert result.from_phase == "refinement"
    assert result.to_phase == "planning"
    assert not (iter_dir / "refinement_summary.md").exists()
    assert result.checkpoint_number is not None
