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


def test_validate_raises_domain_error_for_unknown_phase(tmp_path):
    """A typo'd phase in iteration.json produces SessionSetupError, not raw ValueError."""
    iteration = {"id": "i", "description": "d", "status": "in-progress", "phase": "bogus"}
    with pytest.raises(SessionSetupError, match="Unknown phase 'bogus'"):
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


def test_setup_worktrees_unknown_phase(tmp_path):
    """A typo'd phase with worktrees enabled produces SessionSetupError."""
    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text(json.dumps({
        "model": {}, "agents": [], "worktrees": {"enabled": True},
    }))
    with pytest.raises(SessionSetupError, match="Unknown phase 'bogus'"):
        setup_worktrees(team, [], None, None, {"phase": "bogus"})


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


# ── SessionSetup / prepare_session / run_and_persist ──

from unittest.mock import patch, MagicMock
from gotg.engine import SessionDeps
from gotg.events import SessionComplete, TextDelta
from gotg.session import SessionSetup, prepare_session, run_and_persist


def _make_deps(**overrides):
    """Build a minimal SessionDeps with no-op callables."""
    defaults = dict(
        agent_completion=lambda **kw: {"content": "ok", "operations": []},
        coach_completion=lambda **kw: "ok",
        single_completion=lambda **kw: MagicMock(),
        stream_completion=lambda **kw: MagicMock(),
    )
    defaults.update(overrides)
    return SessionDeps(**defaults)


def _make_iter_dir(tmp_path, phase="refinement", with_tasks=False):
    """Create a minimal iteration directory for prepare_session tests."""
    iter_dir = tmp_path / "iter"
    iter_dir.mkdir()
    (iter_dir / "conversation.jsonl").touch()
    if with_tasks:
        tasks = [
            {"id": "t1", "title": "Task 1", "description": "Do stuff",
             "done_criteria": "It works", "assigned_to": "agent-1",
             "depends_on": [], "layer": 0},
        ]
        (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    return iter_dir


def test_prepare_session_basic(tmp_path):
    """prepare_session returns SessionSetup with correct fields for refinement."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}]
    iteration = {"id": "iter-1", "description": "test", "status": "in-progress",
                 "phase": "refinement", "max_turns": 10}
    deps = _make_deps()

    setup = prepare_session(iter_dir, agents, iteration, {"provider": "test"}, deps)

    assert isinstance(setup, SessionSetup)
    assert setup.agents == agents
    assert setup.iteration == iteration
    assert setup.use_implementation is False
    assert setup.tasks_data is None
    assert setup.log_path == iter_dir / "conversation.jsonl"
    assert setup.debug_path == iter_dir / "debug.jsonl"
    assert setup.policy is not None


def test_prepare_session_implementation_phase(tmp_path):
    """prepare_session sets use_implementation=True and loads tasks for implementation."""
    iter_dir = _make_iter_dir(tmp_path, with_tasks=True)
    agents = [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}]
    iteration = {"id": "iter-1", "description": "test", "status": "in-progress",
                 "phase": "implementation", "max_turns": 10, "current_layer": 0}
    deps = _make_deps()

    setup = prepare_session(iter_dir, agents, iteration, {"provider": "test"}, deps)

    assert setup.use_implementation is True
    assert setup.tasks_data is not None
    assert len(setup.tasks_data) == 1
    assert setup.current_layer == 0


def test_prepare_session_no_completion_callables(tmp_path):
    """Without single_completion or stream_completion, implementation falls back to discussion."""
    iter_dir = _make_iter_dir(tmp_path, with_tasks=True)
    agents = [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}]
    iteration = {"id": "iter-1", "description": "test", "status": "in-progress",
                 "phase": "implementation", "max_turns": 10}
    deps = _make_deps(single_completion=None, stream_completion=None)

    setup = prepare_session(iter_dir, agents, iteration, {"provider": "test"}, deps)

    assert setup.use_implementation is False


def test_prepare_session_stream_only_routes_to_implementation(tmp_path):
    """With stream_completion but no single_completion, implementation still routes correctly."""
    iter_dir = _make_iter_dir(tmp_path, with_tasks=True)
    agents = [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}]
    iteration = {"id": "iter-1", "description": "test", "status": "in-progress",
                 "phase": "implementation", "max_turns": 10, "current_layer": 0}
    deps = _make_deps(single_completion=None)  # stream_completion still set

    setup = prepare_session(iter_dir, agents, iteration, {"provider": "test"}, deps)

    assert setup.use_implementation is True
    assert setup.tasks_data is not None


def test_run_and_persist_rejects_stream_only_without_streaming_policy(tmp_path):
    """stream_completion without streaming=True and no single_completion raises early."""
    iter_dir = _make_iter_dir(tmp_path, with_tasks=True)

    from gotg.policy import SessionPolicy
    policy = SessionPolicy(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=(), coach_tools=None, groomed_summary=None,
        tasks_summary=None, diffs_summary=None, kickoff_text=None,
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
        streaming=False,  # streaming disabled
    )
    # stream_completion present but single_completion is None
    deps = _make_deps(single_completion=None)
    setup = SessionSetup(
        agents=[], iteration={"id": "i", "phase": "implementation"},
        iter_dir=iter_dir, model_config={}, history=[], policy=policy,
        deps=deps, log_path=iter_dir / "conversation.jsonl",
        debug_path=iter_dir / "debug.jsonl",
        use_implementation=True,
        tasks_data=[{"id": "t1"}],
        current_layer=0, fileguard=None, approval_store=None, worktree_map=None,
    )

    with pytest.raises(SessionSetupError, match="single_completion.*or.*stream_completion"):
        list(run_and_persist(setup))


def test_run_and_persist_discussion(tmp_path):
    """run_and_persist yields events and persists AppendMessage to disk."""
    iter_dir = _make_iter_dir(tmp_path)
    msg = {"from": "agent-1", "content": "hello"}
    events_in = [
        SessionStarted(iteration_id="i", description="d", phase="refinement",
                       current_layer=None, agents=["a1"], coach=None,
                       has_file_tools=False, writable_paths=None,
                       worktree_count=0, turn=0, max_turns=10),
        AppendMessage(msg),
        SessionComplete(total_turns=1),
    ]

    from gotg.policy import SessionPolicy
    policy = SessionPolicy(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=(), coach_tools=None, groomed_summary=None,
        tasks_summary=None, diffs_summary=None, kickoff_text=None,
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
    )
    setup = SessionSetup(
        agents=[], iteration={"id": "i"}, iter_dir=iter_dir,
        model_config={}, history=[], policy=policy, deps=_make_deps(),
        log_path=iter_dir / "conversation.jsonl",
        debug_path=iter_dir / "debug.jsonl",
        use_implementation=False, tasks_data=None, current_layer=0,
        fileguard=None, approval_store=None, worktree_map=None,
    )

    with patch("gotg.engine.run_session", return_value=iter(events_in)):
        result = list(run_and_persist(setup))

    assert len(result) == 3
    assert isinstance(result[0], SessionStarted)
    assert isinstance(result[1], AppendMessage)
    assert isinstance(result[2], SessionComplete)
    # Verify persisted to disk
    lines = setup.log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["content"] == "hello"


def test_run_and_persist_implementation(tmp_path):
    """run_and_persist routes to run_implementation when use_implementation=True."""
    iter_dir = _make_iter_dir(tmp_path, with_tasks=True)
    msg = {"from": "agent-1", "content": "impl"}
    events_in = [AppendMessage(msg), SessionComplete(total_turns=1)]

    from gotg.policy import SessionPolicy
    policy = SessionPolicy(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=(), coach_tools=None, groomed_summary=None,
        tasks_summary=None, diffs_summary=None, kickoff_text=None,
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
    )
    setup = SessionSetup(
        agents=[], iteration={"id": "i", "phase": "implementation"},
        iter_dir=iter_dir, model_config={}, history=[], policy=policy,
        deps=_make_deps(), log_path=iter_dir / "conversation.jsonl",
        debug_path=iter_dir / "debug.jsonl",
        use_implementation=True,
        tasks_data=[{"id": "t1", "title": "x"}],
        current_layer=0, fileguard=None, approval_store=None, worktree_map=None,
    )

    with patch("gotg.implementation.run_implementation", return_value=iter(events_in)):
        result = list(run_and_persist(setup))

    assert len(result) == 2
    lines = setup.log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["content"] == "impl"


def test_run_and_persist_only_persists_append_events(tmp_path):
    """TextDelta, SessionStarted, SessionComplete are NOT persisted to disk."""
    iter_dir = _make_iter_dir(tmp_path)
    events_in = [
        SessionStarted(iteration_id="i", description="d", phase="refinement",
                       current_layer=None, agents=["a1"], coach=None,
                       has_file_tools=False, writable_paths=None,
                       worktree_count=0, turn=0, max_turns=10),
        TextDelta(agent="agent-1", turn_id="t1", text="chunk"),
        SessionComplete(total_turns=1),
    ]

    from gotg.policy import SessionPolicy
    policy = SessionPolicy(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=(), coach_tools=None, groomed_summary=None,
        tasks_summary=None, diffs_summary=None, kickoff_text=None,
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
    )
    setup = SessionSetup(
        agents=[], iteration={"id": "i"}, iter_dir=iter_dir,
        model_config={}, history=[], policy=policy, deps=_make_deps(),
        log_path=iter_dir / "conversation.jsonl",
        debug_path=iter_dir / "debug.jsonl",
        use_implementation=False, tasks_data=None, current_layer=0,
        fileguard=None, approval_store=None, worktree_map=None,
    )

    with patch("gotg.engine.run_session", return_value=iter(events_in)):
        result = list(run_and_persist(setup))

    assert len(result) == 3
    # No JSONL lines — nothing to persist
    assert not setup.log_path.exists() or setup.log_path.read_text().strip() == ""


def test_run_and_persist_patch_target_compat(tmp_path):
    """patch('gotg.engine.run_session') still intercepts through run_and_persist."""
    iter_dir = _make_iter_dir(tmp_path)

    from gotg.policy import SessionPolicy
    policy = SessionPolicy(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=(), coach_tools=None, groomed_summary=None,
        tasks_summary=None, diffs_summary=None, kickoff_text=None,
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
    )
    setup = SessionSetup(
        agents=[], iteration={"id": "i"}, iter_dir=iter_dir,
        model_config={}, history=[], policy=policy, deps=_make_deps(),
        log_path=iter_dir / "conversation.jsonl",
        debug_path=iter_dir / "debug.jsonl",
        use_implementation=False, tasks_data=None, current_layer=0,
        fileguard=None, approval_store=None, worktree_map=None,
    )

    sentinel = SessionComplete(total_turns=42)
    with patch("gotg.engine.run_session", return_value=iter([sentinel])) as mock_rs:
        result = list(run_and_persist(setup))
        mock_rs.assert_called_once()
        assert result[0].total_turns == 42


def test_run_and_persist_impl_patch_target_compat(tmp_path):
    """patch('gotg.implementation.run_implementation') intercepts through run_and_persist."""
    iter_dir = _make_iter_dir(tmp_path, with_tasks=True)

    from gotg.policy import SessionPolicy
    policy = SessionPolicy(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=(), coach_tools=None, groomed_summary=None,
        tasks_summary=None, diffs_summary=None, kickoff_text=None,
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
    )
    setup = SessionSetup(
        agents=[], iteration={"id": "i", "phase": "implementation"},
        iter_dir=iter_dir, model_config={}, history=[], policy=policy,
        deps=_make_deps(), log_path=iter_dir / "conversation.jsonl",
        debug_path=iter_dir / "debug.jsonl",
        use_implementation=True,
        tasks_data=[{"id": "t1"}],
        current_layer=0, fileguard=None, approval_store=None, worktree_map=None,
    )

    sentinel = SessionComplete(total_turns=99)
    with patch("gotg.implementation.run_implementation", return_value=iter([sentinel])) as mock_ri:
        result = list(run_and_persist(setup))
        mock_ri.assert_called_once()
        assert result[0].total_turns == 99


def test_run_and_persist_debug_events(tmp_path):
    """AppendDebug events are persisted to the debug log."""
    iter_dir = _make_iter_dir(tmp_path)
    debug_entry = {"turn": 1, "agent": "agent-1", "model": "test"}
    events_in = [AppendDebug(debug_entry), SessionComplete(total_turns=1)]

    from gotg.policy import SessionPolicy
    policy = SessionPolicy(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=(), coach_tools=None, groomed_summary=None,
        tasks_summary=None, diffs_summary=None, kickoff_text=None,
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
    )
    setup = SessionSetup(
        agents=[], iteration={"id": "i"}, iter_dir=iter_dir,
        model_config={}, history=[], policy=policy, deps=_make_deps(),
        log_path=iter_dir / "conversation.jsonl",
        debug_path=iter_dir / "debug.jsonl",
        use_implementation=False, tasks_data=None, current_layer=0,
        fileguard=None, approval_store=None, worktree_map=None,
    )

    with patch("gotg.engine.run_session", return_value=iter(events_in)):
        result = list(run_and_persist(setup))

    assert len(result) == 2
    # Debug log should have the entry
    debug_lines = setup.debug_path.read_text().strip().splitlines()
    assert len(debug_lines) == 1
    assert json.loads(debug_lines[0])["turn"] == 1
    # Conversation log should be empty
    assert not setup.log_path.exists() or setup.log_path.read_text().strip() == ""


# ── build_session_infra ──────────────────────────────────────────

from gotg.session import SessionInfra, build_session_infra


class _FakeCtx:
    """Minimal duck-typed TeamContext for build_session_infra tests."""
    def __init__(self, project_root, team_dir, file_access=None, agents=None):
        self.project_root = project_root
        self.team_dir = team_dir
        self.file_access = file_access
        self.agents = agents or []


def _make_team_dir(tmp_path, *, worktrees=False, streaming=False):
    """Create a minimal team dir for build_session_infra tests."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    config = {"model": {}, "agents": []}
    if worktrees:
        config["worktrees"] = {"enabled": True}
    if streaming:
        config["streaming"] = True
    (team_dir / "team.json").write_text(json.dumps(config))
    return team_dir


def test_build_session_infra_basic(tmp_path):
    """Returns SessionInfra with correct fields, no warnings when no worktrees/diffs."""
    team_dir = _make_team_dir(tmp_path)
    iter_dir = tmp_path / "iter"
    iter_dir.mkdir()
    ctx = _FakeCtx(tmp_path, team_dir)
    iteration = {"phase": "refinement"}

    infra = build_session_infra(ctx, iteration, iter_dir)

    assert isinstance(infra, SessionInfra)
    assert infra.fileguard is None
    assert infra.approval_store is None
    assert infra.worktree_map is None
    assert infra.diffs_summary is None
    assert infra.streaming is False
    assert infra.warnings == []


def test_build_session_infra_streaming_enabled(tmp_path):
    """Returns streaming=True when team.json has streaming enabled."""
    team_dir = _make_team_dir(tmp_path, streaming=True)
    iter_dir = tmp_path / "iter"
    iter_dir.mkdir()
    ctx = _FakeCtx(tmp_path, team_dir)
    iteration = {"phase": "refinement"}

    infra = build_session_infra(ctx, iteration, iter_dir)

    assert infra.streaming is True


def test_build_session_infra_collects_warnings(tmp_path):
    """Warnings from worktrees + diffs combined in order."""
    team_dir = _make_team_dir(tmp_path, worktrees=True)
    iter_dir = tmp_path / "iter"
    iter_dir.mkdir()
    ctx = _FakeCtx(tmp_path, team_dir)
    # Implementation phase triggers worktree setup (but no fileguard → warning)
    iteration = {"phase": "implementation"}

    infra = build_session_infra(ctx, iteration, iter_dir)

    assert any("file tools" in w for w in infra.warnings)


def test_build_session_infra_propagates_setup_error(tmp_path):
    """SessionSetupError from setup_worktrees propagates."""
    team_dir = _make_team_dir(tmp_path, worktrees=True)
    iter_dir = tmp_path / "iter"
    iter_dir.mkdir()
    file_access = {"writable_paths": ["**"]}
    ctx = _FakeCtx(tmp_path, team_dir, file_access=file_access)
    iteration = {"phase": "implementation"}

    # setup_worktrees will try to ensure_git_repo → fail since no git repo
    with pytest.raises(SessionSetupError):
        build_session_infra(ctx, iteration, iter_dir)


def test_no_double_persistence_after_wrapper_deletion(tmp_path):
    """AppendMessage written exactly once to conversation.jsonl when consumed via run_and_persist."""
    iter_dir = tmp_path / "iter"
    iter_dir.mkdir()
    (iter_dir / "conversation.jsonl").touch()
    msg = {"from": "agent-1", "content": "hello"}
    events_in = [
        AppendMessage(msg),
        AppendMessage({"from": "agent-2", "content": "world"}),
        SessionComplete(total_turns=1),
    ]

    from gotg.policy import SessionPolicy
    policy = SessionPolicy(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=(), coach_tools=None, groomed_summary=None,
        tasks_summary=None, diffs_summary=None, kickoff_text=None,
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
    )
    setup = SessionSetup(
        agents=[], iteration={"id": "i"}, iter_dir=iter_dir,
        model_config={}, history=[], policy=policy, deps=_make_deps(),
        log_path=iter_dir / "conversation.jsonl",
        debug_path=iter_dir / "debug.jsonl",
        use_implementation=False, tasks_data=None, current_layer=0,
        fileguard=None, approval_store=None, worktree_map=None,
    )

    with patch("gotg.engine.run_session", return_value=iter(events_in)):
        list(run_and_persist(setup))

    lines = setup.log_path.read_text().strip().splitlines()
    assert len(lines) == 2  # Exactly 2 AppendMessage events, each persisted once
    assert json.loads(lines[0])["content"] == "hello"
    assert json.loads(lines[1])["content"] == "world"


# ── prepare_grooming_session ──────────────────────────────────────

from gotg.session import prepare_grooming_session


def test_prepare_grooming_session_basic(tmp_path):
    """Returns SessionSetup with grooming defaults."""
    groom_dir = tmp_path / "groom"
    groom_dir.mkdir()
    (groom_dir / "conversation.jsonl").touch()
    agents = [{"name": "a1", "role": "SE"}, {"name": "a2", "role": "SE"}]
    iteration = {"id": "test-topic", "description": "test", "phase": None}
    deps = _make_deps()

    setup = prepare_grooming_session(
        groom_dir, agents, iteration, {"provider": "test"}, deps,
        topic="test topic",
    )

    assert setup.use_implementation is False
    assert setup.tasks_data is None
    assert setup.fileguard is None
    assert setup.log_path == groom_dir / "conversation.jsonl"
    assert setup.policy.streaming is False


def test_prepare_grooming_session_with_coach(tmp_path):
    """Policy includes coach when provided."""
    groom_dir = tmp_path / "groom"
    groom_dir.mkdir()
    (groom_dir / "conversation.jsonl").touch()
    agents = [{"name": "a1", "role": "SE"}, {"name": "a2", "role": "SE"}]
    iteration = {"id": "slug", "description": "test", "phase": None}
    coach = {"name": "coach", "role": "Coach"}
    deps = _make_deps()

    setup = prepare_grooming_session(
        groom_dir, agents, iteration, {"provider": "test"}, deps,
        topic="test", coach=coach,
    )

    assert setup.policy.coach == coach


def test_prepare_grooming_session_reads_existing_history(tmp_path):
    """History is populated from existing conversation log."""
    groom_dir = tmp_path / "groom"
    groom_dir.mkdir()
    log_path = groom_dir / "conversation.jsonl"
    conv_append_message(log_path, {"from": "a1", "content": "hello"})
    conv_append_message(log_path, {"from": "a2", "content": "hi"})
    agents = [{"name": "a1", "role": "SE"}, {"name": "a2", "role": "SE"}]
    iteration = {"id": "slug", "description": "test", "phase": None}
    deps = _make_deps()

    setup = prepare_grooming_session(
        groom_dir, agents, iteration, {"provider": "test"}, deps,
        topic="test",
    )

    assert len(setup.history) == 2
    assert setup.history[0]["content"] == "hello"


# ── prepare_continue ──────────────────────────────────────────────

from gotg.session import ContinueContext, prepare_continue, SessionInfra


def _make_infra(**overrides):
    """Build a minimal SessionInfra."""
    defaults = dict(
        fileguard=None, approval_store=None, worktree_map=None,
        diffs_summary=None, streaming=False,
    )
    defaults.update(overrides)
    return SessionInfra(**defaults)


def test_prepare_continue_no_approvals(tmp_path):
    """No approval store → empty injected messages, correct turn count."""
    iter_dir = tmp_path / "iter"
    iter_dir.mkdir()
    log_path = iter_dir / "conversation.jsonl"
    conv_append_message(log_path, {"from": "agent-1", "content": "hello"})
    conv_append_message(log_path, {"from": "agent-2", "content": "world"})

    infra = _make_infra()
    iteration = {"id": "iter-1"}
    cont = prepare_continue(infra, iteration, log_path)

    assert cont.injected_messages == []
    assert cont.has_pending_approvals is False
    assert cont.pending_count == 0
    assert cont.current_agent_turns == 2


def test_prepare_continue_with_approvals_and_pending(tmp_path):
    """Injection messages returned and pending flag set when approvals pending."""
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

    # One approved, one still pending
    store.add_request("src/good.py", "good code", "agent-1", {})
    store.add_request("src/pending.py", "pending code", "agent-2", {})
    store.approve("a1")

    infra = _make_infra(fileguard=guard, approval_store=store)
    iteration = {"id": "iter-1"}
    cont = prepare_continue(infra, iteration, log_path)

    assert len(cont.injected_messages) == 1
    assert "APPROVED" in cont.injected_messages[0]["content"]
    assert cont.has_pending_approvals is True
    assert cont.pending_count == 1


def test_prepare_continue_excludes_coach_from_turns(tmp_path):
    """Coach messages not counted as agent turns."""
    iter_dir = tmp_path / "iter"
    iter_dir.mkdir()
    log_path = iter_dir / "conversation.jsonl"
    conv_append_message(log_path, {"from": "agent-1", "content": "hello"})
    conv_append_message(log_path, {"from": "coach", "content": "guidance"})
    conv_append_message(log_path, {"from": "agent-2", "content": "world"})
    conv_append_message(log_path, {"from": "human", "content": "thanks"})

    infra = _make_infra()
    iteration = {"id": "iter-1"}
    cont = prepare_continue(infra, iteration, log_path, coach_name="coach")

    assert cont.current_agent_turns == 2  # agent-1 + agent-2, not coach/human


def test_prepare_continue_idempotent(tmp_path):
    """Calling twice without state changes does not duplicate injected messages."""
    iter_dir = tmp_path / "iter"
    iter_dir.mkdir()
    log_path = iter_dir / "conversation.jsonl"

    infra = _make_infra()
    iteration = {"id": "iter-1"}

    cont1 = prepare_continue(infra, iteration, log_path)
    cont2 = prepare_continue(infra, iteration, log_path)

    assert cont1.injected_messages == cont2.injected_messages == []


def test_prepare_continue_injection_order_matches_persistence(tmp_path):
    """Injected messages returned in the same order they were persisted to disk."""
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

    store.add_request("src/a.py", "content a", "agent-1", {})
    store.add_request("src/b.py", "content b", "agent-2", {})
    store.approve("a1")
    store.deny("a2", "nope")

    infra = _make_infra(fileguard=guard, approval_store=store)
    iteration = {"id": "iter-1"}
    cont = prepare_continue(infra, iteration, log_path)

    # 2 messages: one approved, one denied
    assert len(cont.injected_messages) == 2
    # Verify they match what was persisted
    persisted = json.loads(log_path.read_text().strip().splitlines()[0])
    assert cont.injected_messages[0]["content"] == persisted["content"]


# ── console_events grooming contract ──────────────────────────────


def test_grooming_console_events_resume_hint(capsys):
    """handle_console_events uses custom resume_hint for grooming."""
    from gotg.console_events import handle_console_events
    from gotg.events import CoachAskedPM

    events = [
        SessionStarted("test-slug", "test topic", None, None, ["a1"], None,
                       False, None, 0, 0, 30),
        CoachAskedPM(question="What do you think?", options=None),
    ]

    handle_console_events(
        iter(events),
        resume_hint="gotg groom continue test-slug",
        complete_label="Grooming",
    )

    captured = capsys.readouterr()
    assert "gotg groom continue test-slug" in captured.out
    assert "your answer" in captured.out


def test_run_and_persist_translates_validate_error(tmp_path):
    """run_and_persist catches ValueError from deps.validate and re-raises as SessionSetupError."""
    iter_dir = _make_iter_dir(tmp_path, with_tasks=True)

    from gotg.policy import SessionPolicy
    policy = SessionPolicy(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=(), coach_tools=None, groomed_summary=None,
        tasks_summary=None, diffs_summary=None, kickoff_text=None,
        fileguard=None, approval_store=None, worktree_map=None,
        system_supplement=None, coach_system_prompt=None,
        streaming=False,
    )
    deps = _make_deps()
    setup = SessionSetup(
        agents=[], iteration={"id": "i", "phase": "implementation"},
        iter_dir=iter_dir, model_config={}, history=[], policy=policy,
        deps=deps, log_path=iter_dir / "conversation.jsonl",
        debug_path=iter_dir / "debug.jsonl",
        use_implementation=True,
        tasks_data=[{"id": "t1"}],
        current_layer=0, fileguard=None, approval_store=None, worktree_map=None,
    )

    # Patch validate to raise ValueError directly
    with patch.object(setup.deps, "validate", side_effect=ValueError("test error")):
        with pytest.raises(SessionSetupError, match="test error"):
            list(run_and_persist(setup))
