"""Tests for code-review gate enforcement and rework loop."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gotg.events import PhaseCompleteSignaled
from gotg.session_types import (
    PauseReason,
    ResumeState,
    ReworkError,
    ReworkResult,
    reconstruct_resume_state,
)
from gotg.transitions import build_rework_messages, extract_review_feedback
from gotg.session_advance import advance_rework, validate_rework
from gotg.session_review import ReviewError, merge_branches
from gotg.implementation import _format_agent_tasks, _handle_complete_tasks


# ── Helpers ────────────────────────────────────────────────────


def _make_team_dir(tmp_path, phase="code-review", current_layer=0, review_outcome="changes_requested"):
    """Create a .team/ dir for rework tests."""
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / ".gitignore").write_text("/.team/\n/.worktrees/\n.env\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text(json.dumps({
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "coach": {"name": "coach", "role": "Agile Coach"},
        "model": {"provider": "ollama", "model": "test", "base_url": "http://localhost:11434"},
    }))

    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    iteration = {
        "id": "iter-1", "description": "Test", "status": "in-progress",
        "phase": phase, "max_turns": 10, "current_layer": current_layer,
    }
    if review_outcome is not None:
        iteration["review_outcome"] = review_outcome
    (team / "iteration.json").write_text(json.dumps({
        "iterations": [iteration],
        "current": "iter-1",
    }))

    return team, iter_dir, iteration


# ── PhaseCompleteSignaled event ───────────────────────────────


def test_phase_complete_signaled_default_outcome():
    """PhaseCompleteSignaled outcome defaults to 'approved'."""
    event = PhaseCompleteSignaled(phase="code-review")
    assert event.outcome == "approved"


def test_phase_complete_signaled_changes_requested():
    """PhaseCompleteSignaled preserves 'changes_requested' outcome."""
    event = PhaseCompleteSignaled(phase="code-review", outcome="changes_requested")
    assert event.outcome == "changes_requested"
    assert event.phase == "code-review"


# ── reconstruct_resume_state ─────────────────────────────────


def test_reconstruct_resume_state_phase_complete_approved():
    """Structured data with outcome='approved' sets phase_complete_outcome."""
    messages = [
        {"from": "coach", "content": "(Phase complete: approved. done)",
         "signal_phase_complete": {"summary": "done", "outcome": "approved"}},
    ]
    state = reconstruct_resume_state(messages, "code-review")
    assert state.pause_reason == PauseReason.PHASE_COMPLETE
    assert state.phase_complete_outcome == "approved"
    assert state.phase_complete_shows_review is True


def test_reconstruct_resume_state_phase_complete_changes_requested():
    """Structured data with outcome='changes_requested' flows through."""
    messages = [
        {"from": "coach", "content": "(Phase complete: changes_requested. needs work)",
         "signal_phase_complete": {"summary": "needs work", "outcome": "changes_requested"}},
    ]
    state = reconstruct_resume_state(messages, "code-review")
    assert state.pause_reason == PauseReason.PHASE_COMPLETE
    assert state.phase_complete_outcome == "changes_requested"
    assert state.phase_complete_shows_review is True


def test_reconstruct_resume_state_legacy_fallback_text():
    """Legacy '(Phase complete signal sent.)' defaults outcome to 'approved'."""
    messages = [
        {"from": "coach", "content": "(Phase complete signal sent.)"},
    ]
    state = reconstruct_resume_state(messages, "code-review")
    assert state.pause_reason == PauseReason.PHASE_COMPLETE
    assert state.phase_complete_outcome == "approved"


def test_reconstruct_resume_state_new_fallback_text():
    """New fallback '(Phase complete: ...)' text triggers phase-complete detection."""
    messages = [
        {"from": "coach", "content": "(Phase complete: approved. All good.)"},
    ]
    state = reconstruct_resume_state(messages, "refinement")
    assert state.pause_reason == PauseReason.PHASE_COMPLETE
    assert state.phase_complete_outcome == "approved"


# ── extract_review_feedback ───────────────────────────────────


def test_extract_review_feedback_success():
    """Returns feedback_map for tasks with concerns."""
    history = [
        {"from": "agent-1", "content": "my review"},
        {"from": "coach", "content": "concerns remain on T1"},
    ]
    tasks = [
        {"id": "T1", "description": "x"},
        {"id": "T2", "description": "y"},
    ]
    model_config = {"base_url": "http://localhost", "model": "m", "provider": "ollama"}

    raw_response = json.dumps([
        {"id": "T1", "feedback": "Fix the validate function", "status": "changes_requested"},
    ])

    def mock_chat(**kw):
        return raw_response

    feedback_map, raw, error = extract_review_feedback(
        history, tasks, model_config, "coach", mock_chat,
    )
    assert feedback_map == {"T1": "Fix the validate function"}
    assert raw is None
    assert error is None


def test_extract_review_feedback_all_approved():
    """Empty array means all approved → empty dict."""
    model_config = {"base_url": "http://localhost", "model": "m", "provider": "ollama"}

    def mock_chat(**kw):
        return "[]"

    feedback_map, raw, error = extract_review_feedback(
        [{"from": "agent-1", "content": "lgtm"}],
        [{"id": "T1", "description": "x"}],
        model_config, "coach", mock_chat,
    )
    assert feedback_map == {}
    assert raw is None
    assert error is None


def test_extract_review_feedback_bad_json():
    """Bad JSON returns (None, raw_text, error_msg)."""
    model_config = {"base_url": "http://localhost", "model": "m", "provider": "ollama"}

    def mock_chat(**kw):
        return "not json at all"

    feedback_map, raw, error = extract_review_feedback(
        [{"from": "agent-1", "content": "lgtm"}],
        [{"id": "T1", "description": "x"}],
        model_config, "coach", mock_chat,
    )
    assert feedback_map is None
    assert raw == "not json at all"
    assert "parse" in error.lower()


def test_extract_review_feedback_filters_unknown_ids():
    """Task IDs not in tasks_data are skipped."""
    model_config = {"base_url": "http://localhost", "model": "m", "provider": "ollama"}

    def mock_chat(**kw):
        return json.dumps([
            {"id": "T1", "feedback": "fix this", "status": "changes_requested"},
            {"id": "UNKNOWN", "feedback": "bogus", "status": "changes_requested"},
        ])

    feedback_map, _, _ = extract_review_feedback(
        [{"from": "agent-1", "content": "review"}],
        [{"id": "T1", "description": "x"}],
        model_config, "coach", mock_chat,
    )
    assert feedback_map == {"T1": "fix this"}


def test_extract_review_feedback_non_string_feedback():
    """Non-string feedback values are filtered out."""
    model_config = {"base_url": "http://localhost", "model": "m", "provider": "ollama"}

    def mock_chat(**kw):
        return json.dumps([
            {"id": "T1", "feedback": 42, "status": "changes_requested"},
        ])

    feedback_map, _, _ = extract_review_feedback(
        [{"from": "agent-1", "content": "review"}],
        [{"id": "T1", "description": "x"}],
        model_config, "coach", mock_chat,
    )
    assert feedback_map == {}


def test_extract_review_feedback_includes_coach_messages():
    """Coach messages are included in extraction transcript (unlike other extractors)."""
    model_config = {"base_url": "http://localhost", "model": "m", "provider": "ollama"}
    calls = []

    def mock_chat(**kw):
        calls.append(kw)
        return "[]"

    history = [
        {"from": "system", "content": "kickoff"},
        {"from": "agent-1", "content": "agent says"},
        {"from": "coach", "content": "coach says"},
    ]

    extract_review_feedback(
        history, [{"id": "T1", "description": "x"}],
        model_config, "coach", mock_chat,
    )
    prompt_text = calls[0]["messages"][0]["content"]
    assert "coach says" in prompt_text
    assert "agent says" in prompt_text
    assert "kickoff" not in prompt_text  # system messages excluded


# ── build_rework_messages ─────────────────────────────────────


def test_build_rework_messages():
    """Boundary + transition message structure."""
    boundary, transition = build_rework_messages("iter-1", 0, ["T1", "T2"])

    assert boundary["from"] == "system"
    assert boundary["phase_boundary"] is True
    assert boundary["from_phase"] == "code-review"
    assert boundary["to_phase"] == "implementation"

    assert transition["from"] == "system"
    assert "T1" in transition["content"]
    assert "T2" in transition["content"]
    assert "layer 0" in transition["content"]


# ── validate_rework ───────────────────────────────────────────


def test_validate_rework_wrong_phase():
    """Raises ReworkError if not in code-review."""
    iteration = {"status": "in-progress", "phase": "implementation", "current_layer": 0}
    with pytest.raises(ReworkError, match="code-review"):
        validate_rework(iteration)


def test_validate_rework_not_in_progress():
    """Raises ReworkError if status is not in-progress."""
    iteration = {"status": "done", "phase": "code-review", "current_layer": 0}
    with pytest.raises(ReworkError, match="in-progress"):
        validate_rework(iteration)


def test_validate_rework_missing_outcome():
    """Raises ReworkError if review_outcome is not 'changes_requested'."""
    iteration = {"status": "in-progress", "phase": "code-review", "current_layer": 0}
    with pytest.raises(ReworkError, match="changes_requested"):
        validate_rework(iteration)


def test_validate_rework_approved_outcome():
    """Raises ReworkError if review_outcome is 'approved' (not rework-eligible)."""
    iteration = {"status": "in-progress", "phase": "code-review", "current_layer": 0,
                 "review_outcome": "approved"}
    with pytest.raises(ReworkError, match="changes_requested"):
        validate_rework(iteration)


def test_validate_rework_success():
    """Returns current_layer on valid state with changes_requested outcome."""
    iteration = {"status": "in-progress", "phase": "code-review", "current_layer": 2,
                 "review_outcome": "changes_requested"}
    assert validate_rework(iteration) == 2


# ── advance_rework ────────────────────────────────────────────


def test_advance_rework_applies_feedback(tmp_path):
    """Tasks get status='changes_requested' + review_feedback."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    tasks = [
        {"id": "T1", "description": "x", "layer": 0, "status": "done",
         "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done",
         "completed_by": "agent-1", "completion_summary": "done"},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))

    # Write a coach message so phase history is non-empty
    from gotg.conversation import append_message
    append_message(iter_dir / "conversation.jsonl",
                   {"from": "coach", "content": "T1 needs fixes"})

    def mock_chat(**kw):
        return json.dumps([{"id": "T1", "feedback": "Fix validation", "status": "changes_requested"}])

    result = advance_rework(team, iteration, iter_dir, chat_call=mock_chat)
    assert isinstance(result, ReworkResult)
    assert result.layer == 0
    assert result.tasks_with_feedback == ["T1"]

    saved = json.loads((iter_dir / "tasks.json").read_text())["tasks"]
    t1 = saved[0]
    assert t1["status"] == "changes_requested"
    assert t1["review_feedback"] == "Fix validation"


def test_advance_rework_preserves_done_tasks(tmp_path):
    """Tasks without feedback keep their status."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    tasks = [
        {"id": "T1", "description": "x", "layer": 0, "status": "done",
         "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
        {"id": "T2", "description": "y", "layer": 0, "status": "done",
         "assigned_to": "agent-2", "depends_on": [], "done_criteria": "done"},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    from gotg.conversation import append_message
    append_message(iter_dir / "conversation.jsonl",
                   {"from": "coach", "content": "Only T1 needs work"})

    def mock_chat(**kw):
        return json.dumps([{"id": "T1", "feedback": "Fix it", "status": "changes_requested"}])

    result = advance_rework(team, iteration, iter_dir, chat_call=mock_chat)
    assert result.tasks_with_feedback == ["T1"]

    saved = json.loads((iter_dir / "tasks.json").read_text())["tasks"]
    t2 = [t for t in saved if t["id"] == "T2"][0]
    assert t2["status"] == "done"


def test_advance_rework_saves_phase(tmp_path):
    """Phase is set to 'implementation' after rework."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done",
              "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    from gotg.conversation import append_message
    append_message(iter_dir / "conversation.jsonl", {"from": "coach", "content": "fix T1"})

    def mock_chat(**kw):
        return json.dumps([{"id": "T1", "feedback": "Fix it", "status": "changes_requested"}])

    advance_rework(team, iteration, iter_dir, chat_call=mock_chat)

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "implementation"


def test_advance_rework_keeps_layer(tmp_path):
    """current_layer is unchanged after rework."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, current_layer=2)
    tasks = [{"id": "T1", "description": "x", "layer": 2, "status": "done",
              "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    from gotg.conversation import append_message
    append_message(iter_dir / "conversation.jsonl", {"from": "coach", "content": "fix T1"})

    def mock_chat(**kw):
        return json.dumps([{"id": "T1", "feedback": "Fix it", "status": "changes_requested"}])

    result = advance_rework(team, iteration, iter_dir, chat_call=mock_chat)
    assert result.layer == 2

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0].get("current_layer") == 2


def test_advance_rework_empty_feedback_raises(tmp_path):
    """Empty feedback_map raises ReworkError."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done",
              "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    from gotg.conversation import append_message
    append_message(iter_dir / "conversation.jsonl", {"from": "coach", "content": "all good"})

    def mock_chat(**kw):
        return "[]"

    with pytest.raises(ReworkError, match="No tasks have actionable feedback"):
        advance_rework(team, iteration, iter_dir, chat_call=mock_chat)


def test_advance_rework_clears_completion_metadata(tmp_path):
    """completed_by and completion_summary are popped on affected tasks."""
    team, iter_dir, iteration = _make_team_dir(tmp_path)
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done",
              "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done",
              "completed_by": "agent-1", "completion_summary": "done it"}]
    (iter_dir / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    from gotg.conversation import append_message
    append_message(iter_dir / "conversation.jsonl", {"from": "coach", "content": "fix T1"})

    def mock_chat(**kw):
        return json.dumps([{"id": "T1", "feedback": "Fix it", "status": "changes_requested"}])

    advance_rework(team, iteration, iter_dir, chat_call=mock_chat)

    saved = json.loads((iter_dir / "tasks.json").read_text())["tasks"]
    assert "completed_by" not in saved[0]
    assert "completion_summary" not in saved[0]


def test_advance_rework_clears_review_outcome(tmp_path):
    """review_outcome is cleared after rework."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, review_outcome="changes_requested")
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done",
              "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    from gotg.conversation import append_message
    append_message(iter_dir / "conversation.jsonl", {"from": "coach", "content": "fix T1"})

    def mock_chat(**kw):
        return json.dumps([{"id": "T1", "feedback": "Fix it", "status": "changes_requested"}])

    advance_rework(team, iteration, iter_dir, chat_call=mock_chat)

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0].get("review_outcome") is None


def test_advance_rework_scoped_to_layer(tmp_path):
    """Only current-layer tasks are passed to extraction."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, current_layer=0)
    tasks = [
        {"id": "T1", "description": "x", "layer": 0, "status": "done",
         "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
        {"id": "T2", "description": "y", "layer": 1, "status": "todo",
         "assigned_to": "agent-1", "depends_on": ["T1"], "done_criteria": "done"},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    from gotg.conversation import append_message
    append_message(iter_dir / "conversation.jsonl", {"from": "coach", "content": "fix T1"})

    extraction_calls = []

    def mock_chat(**kw):
        extraction_calls.append(kw)
        return json.dumps([{"id": "T1", "feedback": "Fix it", "status": "changes_requested"}])

    advance_rework(team, iteration, iter_dir, chat_call=mock_chat)

    # The prompt should only mention T1, not T2
    prompt_text = extraction_calls[0]["messages"][0]["content"]
    assert "T1" in prompt_text
    assert "T2" not in prompt_text


# ── Merge gate ────────────────────────────────────────────────


def test_merge_blocked_when_changes_requested(tmp_path):
    """Merge raises ReviewError when outcome is 'changes_requested'."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, review_outcome="changes_requested")
    with pytest.raises(ReviewError, match="approved code review"):
        merge_branches(tmp_path, layer=0, phase="code-review", review_outcome="changes_requested")


def test_merge_blocked_when_no_outcome(tmp_path):
    """Merge raises ReviewError when review_outcome is missing."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, review_outcome=None)
    with pytest.raises(ReviewError, match="approved code review"):
        merge_branches(tmp_path, layer=0, phase="code-review", review_outcome=None)


def test_merge_blocked_when_not_code_review(tmp_path):
    """Merge raises ReviewError when not in code-review phase."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, phase="implementation")
    with pytest.raises(ReviewError, match="approved code review"):
        merge_branches(tmp_path, layer=0, phase="implementation", review_outcome="approved")


# ── Next-layer gate ───────────────────────────────────────────


def test_next_layer_blocked_when_changes_requested(tmp_path):
    """next-layer raises ReviewError when outcome is 'changes_requested'."""
    from gotg.session_advance import validate_next_layer
    team, iter_dir, iteration = _make_team_dir(tmp_path, review_outcome="changes_requested")
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done",
              "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    iteration["review_outcome"] = "changes_requested"

    with pytest.raises(ReviewError, match="approved code review"):
        validate_next_layer(team, iteration, iter_dir)


def test_next_layer_blocked_when_no_outcome(tmp_path):
    """next-layer raises ReviewError when review_outcome is missing."""
    from gotg.session_advance import validate_next_layer
    team, iter_dir, iteration = _make_team_dir(tmp_path, review_outcome=None)
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done",
              "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    # iteration has no review_outcome key
    iteration.pop("review_outcome", None)

    with pytest.raises(ReviewError, match="approved code review"):
        validate_next_layer(team, iteration, iter_dir)


# ── Implementation task display ───────────────────────────────


def test_format_agent_tasks_includes_review_feedback():
    """REVIEW FEEDBACK rendered in prompt."""
    tasks = [
        {"id": "T1", "description": "Fix bug", "layer": 0, "status": "changes_requested",
         "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done",
         "review_feedback": "The validate() function doesn't handle empty input"},
    ]
    output = _format_agent_tasks(tasks, "agent-1", 0)
    assert "REVIEW FEEDBACK" in output
    assert "validate()" in output


def test_format_agent_tasks_no_feedback():
    """REVIEW FEEDBACK line omitted when absent."""
    tasks = [
        {"id": "T1", "description": "Fix bug", "layer": 0, "status": "todo",
         "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
    ]
    output = _format_agent_tasks(tasks, "agent-1", 0)
    assert "REVIEW FEEDBACK" not in output


def test_format_agent_tasks_separates_done_from_actionable():
    """Done tasks shown as compact summary, actionable get full formatting."""
    tasks = [
        {"id": "T1", "description": "Done task", "layer": 0, "status": "done",
         "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
        {"id": "T2", "description": "Rework task", "layer": 0, "status": "changes_requested",
         "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done",
         "review_feedback": "needs fixes"},
    ]
    output = _format_agent_tasks(tasks, "agent-1", 0)
    assert "Already completed" in output
    assert "T1" in output
    assert "TASK 1 ID: T2" in output  # T2 is the only actionable task → TASK 1
    assert "REVIEW FEEDBACK" in output


def test_format_agent_tasks_all_actionable_no_done_section():
    """No 'Already completed' line when no done tasks."""
    tasks = [
        {"id": "T1", "description": "Task A", "layer": 0, "status": "todo",
         "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
    ]
    output = _format_agent_tasks(tasks, "agent-1", 0)
    assert "Already completed" not in output


def test_handle_complete_tasks_clears_review_feedback(tmp_path):
    """Re-completion pops review_feedback."""
    iter_dir = tmp_path / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    tasks = [
        {"id": "T1", "description": "x", "layer": 0, "status": "changes_requested",
         "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done",
         "review_feedback": "Fix the bug"},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))

    result = _handle_complete_tasks(
        {"task_ids": ["T1"], "summary": "fixed"},
        "agent-1", tasks, 0, iter_dir,
    )
    assert "Completed" in result
    assert tasks[0].get("review_feedback") is None


# ── cmd_rework CLI ────────────────────────────────────────────


def test_cmd_rework_success(tmp_path, capsys):
    """Happy path for gotg rework."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, review_outcome="changes_requested")
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done",
              "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    from gotg.conversation import append_message
    append_message(iter_dir / "conversation.jsonl", {"from": "coach", "content": "fix T1"})

    from gotg.cli import main
    import sys

    def mock_chat(**kw):
        return json.dumps([{"id": "T1", "feedback": "Fix it", "status": "changes_requested"}])

    with patch("sys.argv", ["gotg", "rework"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.commands.advance._cli.chat_completion", side_effect=mock_chat):
                main()

    output = capsys.readouterr().out
    assert "task(s) sent back" in output.lower() or "rework" in output.lower()


def test_cmd_rework_wrong_phase(tmp_path, capsys):
    """Rework errors if not in code-review."""
    team, iter_dir, iteration = _make_team_dir(tmp_path, phase="implementation")

    from gotg.cli import main

    with patch("sys.argv", ["gotg", "rework"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()

    err = capsys.readouterr().err
    assert "code-review" in err


# ── Prompts ───────────────────────────────────────────────────


def test_review_feedback_prompt_exists():
    """REVIEW_FEEDBACK_EXTRACTION_PROMPT loads from TOML."""
    from gotg.prompts import REVIEW_FEEDBACK_EXTRACTION_PROMPT
    assert isinstance(REVIEW_FEEDBACK_EXTRACTION_PROMPT, str)
    assert len(REVIEW_FEEDBACK_EXTRACTION_PROMPT) > 50
    assert "{tasks_json}" in REVIEW_FEEDBACK_EXTRACTION_PROMPT
    assert "{conversation}" in REVIEW_FEEDBACK_EXTRACTION_PROMPT


def test_signal_phase_complete_schema_has_outcome():
    """signal_phase_complete tool schema includes outcome enum."""
    from gotg.prompts import COACH_TOOLS
    signal_tool = [t for t in COACH_TOOLS if t["name"] == "signal_phase_complete"][0]
    props = signal_tool["input_schema"]["properties"]
    assert "outcome" in props
    assert "enum" in props["outcome"]
    assert "approved" in props["outcome"]["enum"]
    assert "changes_requested" in props["outcome"]["enum"]


# ── Codex findings: stale outcome, rework gate, TUI phase ───


def test_cli_continue_clears_review_outcome(tmp_path):
    """CLI 'gotg continue' clears review_outcome when resuming code-review."""
    team, iter_dir, iteration = _make_team_dir(
        tmp_path, phase="code-review", review_outcome="approved",
    )
    # Write a conversation message so continue has something to count
    from gotg.conversation import append_message
    append_message(iter_dir / "conversation.jsonl",
                   {"from": "agent-1", "content": "hello", "iteration": "iter-1"})

    from gotg.config import IterationStore

    with patch("gotg.commands.run._cli.run_conversation"):
        with patch("gotg.commands.run._cli._auto_checkpoint"):
            from gotg.commands.run import cmd_continue
            args = type("A", (), {"iteration": None, "layer": None, "max_turns": None, "message": None})()
            with patch("gotg.commands.run._cli.find_team_dir", return_value=team):
                with patch("gotg.commands.run.Path.cwd", return_value=tmp_path):
                    cmd_continue(args)

    # Check that review_outcome was cleared in iteration.json
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0].get("review_outcome") is None


def test_action_rework_guards_phase_and_outcome():
    """TUI action_rework returns early when phase != code-review or outcome != changes_requested."""
    from unittest.mock import MagicMock, PropertyMock
    from gotg.tui.screens.chat import ChatScreen, SessionState
    from gotg.session_types import PauseReason

    screen = ChatScreen.__new__(ChatScreen)
    screen._session_kind = "iteration"
    screen._pause_reason = PauseReason.PHASE_COMPLETE
    screen._phase_complete_outcome = "approved"
    screen.metadata = {"phase": "code-review"}
    # Mock session_state as a plain attribute (bypass reactive)
    type(screen).session_state = PropertyMock(return_value=SessionState.PAUSED)
    screen.run_worker = MagicMock()

    # Approved outcome → should not trigger rework
    screen.action_rework()
    screen.run_worker.assert_not_called()

    # Implementation phase → should not trigger rework
    screen.metadata = {"phase": "implementation"}
    screen._phase_complete_outcome = "changes_requested"
    screen.action_rework()
    screen.run_worker.assert_not_called()

    # Not paused → should not trigger rework
    type(screen).session_state = PropertyMock(return_value=SessionState.VIEWING)
    screen.metadata = {"phase": "code-review"}
    screen._phase_complete_outcome = "changes_requested"
    screen.action_rework()
    screen.run_worker.assert_not_called()


def test_validate_rework_requires_changes_requested():
    """validate_rework rejects 'approved' outcome — rework is only for changes_requested."""
    iteration = {
        "status": "in-progress", "phase": "code-review",
        "current_layer": 0, "review_outcome": "approved",
    }
    with pytest.raises(ReworkError, match="changes_requested"):
        validate_rework(iteration)


def test_validate_rework_rejects_no_outcome():
    """validate_rework rejects missing review_outcome."""
    iteration = {
        "status": "in-progress", "phase": "code-review",
        "current_layer": 0,
    }
    with pytest.raises(ReworkError, match="changes_requested"):
        validate_rework(iteration)
