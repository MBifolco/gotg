"""Pure-function tests for reconstruct_resume_state — no TUI, no filesystem."""

import pytest

from gotg.session_types import PauseReason, ResumeState, reconstruct_resume_state


def _msg(sender: str, content: str, **extra) -> dict:
    return {"from": sender, "iteration": "iter-1", "content": content, **extra}


def _boundary() -> dict:
    return {"from": "system", "iteration": "iter-1", "content": "", "phase_boundary": True}


# ── Empty / trivial ──────────────────────────────────────────

def test_empty_messages():
    state = reconstruct_resume_state([], "refinement")
    assert state.pause_reason is None
    assert state.phase_complete_shows_review is False
    assert state.ask_pm_data is None
    assert state.show_task_status_bar is False


def test_only_system_messages():
    msgs = [_msg("system", "kickoff")]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason is None


# ── Phase complete ───────────────────────────────────────────

def test_phase_complete_refinement():
    msgs = [
        _msg("alice", "Let's discuss scope."),
        _msg("coach", "(Phase complete signal sent.)"),
    ]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason == PauseReason.PHASE_COMPLETE
    assert state.phase_complete_shows_review is False


def test_phase_complete_code_review():
    msgs = [
        _msg("alice", "LGTM."),
        _msg("coach", "(Phase complete signal sent.)"),
    ]
    state = reconstruct_resume_state(msgs, "code-review")
    assert state.pause_reason == PauseReason.PHASE_COMPLETE
    assert state.phase_complete_shows_review is True


# ── ask_pm ───────────────────────────────────────────────────

def test_ask_pm_with_options():
    ask_data = {"question": "Which approach?", "options": ["A", "B"], "response_type": "choice"}
    msgs = [
        _msg("alice", "I have two ideas."),
        _msg("coach", "Asking PM.", ask_pm=ask_data),
    ]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason == PauseReason.COACH_QUESTION
    assert state.ask_pm_data == ask_data
    assert state.ask_pm_data["options"] == ["A", "B"]


def test_ask_pm_without_options():
    ask_data = {"question": "What should we do?"}
    msgs = [
        _msg("coach", "Need input.", ask_pm=ask_data),
    ]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason == PauseReason.COACH_QUESTION
    assert state.ask_pm_data == ask_data


# ── Boundary scoping ────────────────────────────────────────

def test_boundary_scoping():
    """Signal before boundary should be ignored; only messages after boundary matter."""
    msgs = [
        _msg("coach", "(Phase complete signal sent.)"),
        _boundary(),
        _msg("alice", "Starting new phase."),
    ]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason is None  # Signal is before boundary


# ── pass_turn filtering ─────────────────────────────────────

def test_pass_turn_filtering():
    """pass_turn messages at the tail should be skipped."""
    msgs = [
        _msg("coach", "(Phase complete signal sent.)"),
        _msg("alice", "pass", pass_turn=True),
    ]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason == PauseReason.PHASE_COMPLETE


# ── Task status bar ─────────────────────────────────────────

def test_task_status_bar_pre_code_review():
    msgs = [_msg("alice", "Let me look at the tasks.")]
    state = reconstruct_resume_state(msgs, "pre-code-review")
    assert state.pause_reason is None
    assert state.show_task_status_bar is True


def test_task_status_bar_implementation():
    msgs = [_msg("alice", "Working on task 1.")]
    state = reconstruct_resume_state(msgs, "implementation")
    assert state.pause_reason is None
    assert state.show_task_status_bar is True


def test_none_phase_exploration():
    msgs = [_msg("alice", "Exploring ideas.")]
    state = reconstruct_resume_state(msgs, None)
    assert state.pause_reason is None
    assert state.show_task_status_bar is False


def test_normal_conversation_no_pause():
    msgs = [_msg("alice", "Just chatting.")]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason is None
    assert state.show_task_status_bar is False


# ── System tail regression tests ────────────────────────────

def test_system_tail_after_ask_pm():
    """System message at the tail should be skipped, revealing ask_pm underneath."""
    ask_data = {"question": "Thoughts?", "options": ["X"]}
    msgs = [
        _msg("coach", "Asking.", ask_pm=ask_data),
        _msg("system", "kickoff injection"),
    ]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason == PauseReason.COACH_QUESTION
    assert state.ask_pm_data == ask_data


def test_system_tail_after_phase_complete():
    """System message at the tail should be skipped, revealing phase complete signal."""
    msgs = [
        _msg("coach", "(Phase complete signal sent.)"),
        _msg("system", "Phase boundary note"),
    ]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason == PauseReason.PHASE_COMPLETE


# ── Malformed payload robustness ────────────────────────────

def test_ask_pm_missing_question_key():
    """ask_pm without 'question' key should not be treated as COACH_QUESTION."""
    msgs = [_msg("coach", "Bad payload.", ask_pm={"options": ["A"]})]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason is None


def test_ask_pm_not_a_dict():
    """ask_pm that is not a dict should not be treated as COACH_QUESTION."""
    msgs = [_msg("coach", "Bad payload.", ask_pm="malformed")]
    state = reconstruct_resume_state(msgs, "refinement")
    assert state.pause_reason is None
