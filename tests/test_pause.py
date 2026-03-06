"""Tests for the interactive pause & interject feature."""

from __future__ import annotations

import json
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gotg.events import (
    AppendMessage,
    CoachAskedPM,
    LayerComplete,
    PauseForApprovals,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
    UserPauseComplete,
)
from gotg.pause import RESUME, PauseController, prompt_for_interjection
from gotg.session_types import PauseReason, ResumeState, reconstruct_resume_state


# ── Helpers ──────────────────────────────────────────────────────

def _msg(sender: str, content: str, **extra) -> dict:
    return {"from": sender, "iteration": "iter-1", "content": content, **extra}


def _boundary() -> dict:
    return {"from": "system", "iteration": "iter-1", "content": "", "phase_boundary": True}


def _started() -> SessionStarted:
    return SessionStarted(
        iteration_id="iter-1", description="test", phase="refinement",
        current_layer=None, agents=["agent-1"], coach="coach",
        has_file_tools=False, writable_paths=None, worktree_count=0,
        turn=0, max_turns=10,
    )


# ── PauseController ─────────────────────────────────────────────


class TestPauseController:
    def test_flag_set_reset(self):
        pc = PauseController()
        assert pc.is_pause_requested() is False
        pc.request_pause()
        assert pc.is_pause_requested() is True
        pc.reset()
        assert pc.is_pause_requested() is False

    def test_install_uninstall(self):
        pc = PauseController()
        original = signal.getsignal(signal.SIGINT)
        pc.install()
        assert signal.getsignal(signal.SIGINT) != original
        pc.uninstall()
        assert signal.getsignal(signal.SIGINT) == original

    def test_first_sigint_sets_flag(self):
        pc = PauseController()
        pc.install()
        try:
            handler = signal.getsignal(signal.SIGINT)
            handler(signal.SIGINT, None)
            assert pc.is_pause_requested() is True
        finally:
            pc.uninstall()

    def test_double_sigint_kills(self):
        pc = PauseController()
        pc.install()
        try:
            handler = signal.getsignal(signal.SIGINT)
            # First signal
            handler(signal.SIGINT, None)
            # Second within 2s — should call os.kill
            with patch("gotg.pause.os.kill") as mock_kill, \
                 patch("gotg.pause.signal.signal"):
                handler(signal.SIGINT, None)
                mock_kill.assert_called_once()
        finally:
            pc.uninstall()


# ── prompt_for_interjection ──────────────────────────────────────


class TestPromptForInterjection:
    def test_enter_returns_resume(self):
        with patch("builtins.input", return_value=""):
            result = prompt_for_interjection("gotg continue")
        assert result is RESUME

    def test_text_returns_string(self):
        with patch("builtins.input", return_value="fix the bug"):
            result = prompt_for_interjection("gotg continue")
        assert result == "fix the bug"

    def test_ctrl_c_returns_none(self):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = prompt_for_interjection("gotg continue")
        assert result is None

    def test_eof_returns_none(self):
        with patch("builtins.input", side_effect=EOFError):
            result = prompt_for_interjection("gotg continue")
        assert result is None


# ── handle_console_events ────────────────────────────────────────


class TestHandleConsoleEventsPause:
    def test_returns_none_normally(self):
        from gotg.console_events import handle_console_events
        events = [_started(), SessionComplete(total_turns=5)]
        result = handle_console_events(events)
        assert result is None

    def test_discussion_pause_after_agent_turn(self):
        """Discussion: returns 'paused' after agent AppendMessage."""
        from gotg.console_events import handle_console_events
        pc = PauseController()
        pc.request_pause()
        events = [
            _started(),
            AppendMessage(_msg("agent-1", "hello")),
            AppendMessage(_msg("agent-2", "world")),  # should not be reached
        ]
        result = handle_console_events(events, pause_controller=pc)
        assert result == "paused"

    def test_discussion_pause_after_pass_turn(self):
        """Discussion: pass_turn messages are turn boundaries."""
        from gotg.console_events import handle_console_events
        pc = PauseController()
        pc.request_pause()
        events = [
            _started(),
            AppendMessage(_msg("system", "agent passed", pass_turn=True)),
            AppendMessage(_msg("agent-1", "next")),  # should not be reached
        ]
        result = handle_console_events(events, pause_controller=pc)
        assert result == "paused"

    def test_discussion_deferred_pause_terminal_wins(self):
        """Discussion: PauseForApprovals after agent AppendMessage wins over pause."""
        from gotg.console_events import handle_console_events
        pc = PauseController()
        pc.request_pause()
        events = [
            _started(),
            AppendMessage(_msg("agent-1", "hello")),
            PauseForApprovals(pending_count=2),
        ]
        # PauseForApprovals is a terminal event — it should be processed, not paused
        result = handle_console_events(events, pause_controller=pc)
        # The function returns None after processing terminal event (break, not "paused")
        assert result is None

    def test_implementation_no_pause_on_agent_msg(self):
        """Implementation: does NOT pause on agent AppendMessage."""
        from gotg.console_events import handle_console_events
        pc = PauseController()
        pc.request_pause()
        events = [
            _started(),
            AppendMessage(_msg("agent-1", "hello")),
            SessionComplete(total_turns=1),
        ]
        result = handle_console_events(events, use_implementation=True, pause_controller=pc)
        # Should process normally — implementation pause is via UserPauseComplete
        assert result is None

    def test_implementation_user_pause_complete(self):
        """Implementation: UserPauseComplete → returns 'paused'."""
        from gotg.console_events import handle_console_events
        pc = PauseController()
        events = [
            _started(),
            AppendMessage(_msg("agent-1", "hello")),
            UserPauseComplete(total_turns=1),
        ]
        result = handle_console_events(events, use_implementation=True, pause_controller=pc)
        assert result == "paused"

    def test_keyboard_interrupt_with_controller(self):
        """KeyboardInterrupt with controller → returns 'paused'."""
        from gotg.console_events import handle_console_events
        pc = PauseController()

        def _exploding_events():
            yield _started()
            raise KeyboardInterrupt

        result = handle_console_events(_exploding_events(), pause_controller=pc)
        assert result == "paused"

    def test_keyboard_interrupt_without_controller(self):
        """KeyboardInterrupt without controller → re-raises."""
        from gotg.console_events import handle_console_events

        def _exploding_events():
            yield _started()
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            handle_console_events(_exploding_events())

    def test_coach_message_not_turn_boundary(self):
        """Coach messages should not trigger pause."""
        from gotg.console_events import handle_console_events
        pc = PauseController()
        pc.request_pause()
        events = [
            _started(),
            AppendMessage(_msg("coach", "let me summarize")),
            SessionComplete(total_turns=5),
        ]
        result = handle_console_events(events, pause_controller=pc)
        # Coach message is not a turn boundary, so pause doesn't trigger
        assert result is None


# ── reconstruct_resume_state ─────────────────────────────────────


class TestReconstructResumeStateUserPause:
    def test_user_pause_marker(self):
        msgs = [
            _msg("agent-1", "hello"),
            _msg("system", "(Session paused by user.)", user_pause=True),
        ]
        state = reconstruct_resume_state(msgs, "refinement")
        assert state.pause_reason == PauseReason.USER_PAUSE

    def test_user_pause_resolved(self):
        msgs = [
            _msg("agent-1", "hello"),
            _msg("system", "(Session paused by user.)", user_pause=True),
            _msg("system", "", user_pause_resolved=True),
        ]
        state = reconstruct_resume_state(msgs, "refinement")
        assert state.pause_reason is None

    def test_human_message_resolves_user_pause(self):
        msgs = [
            _msg("agent-1", "hello"),
            _msg("system", "(Session paused by user.)", user_pause=True),
            _msg("human", "please continue"),
        ]
        state = reconstruct_resume_state(msgs, "refinement")
        assert state.pause_reason is None

    def test_agent_content_after_pause_makes_it_stale(self):
        msgs = [
            _msg("system", "(Session paused by user.)", user_pause=True),
            _msg("agent-1", "I continued"),
        ]
        state = reconstruct_resume_state(msgs, "refinement")
        assert state.pause_reason is None

    def test_multiple_pause_resolve_cycles(self):
        msgs = [
            _msg("system", "(Session paused by user.)", user_pause=True),
            _msg("system", "", user_pause_resolved=True),
            _msg("agent-1", "working..."),
            _msg("system", "(Session paused by user.)", user_pause=True),
        ]
        state = reconstruct_resume_state(msgs, "refinement")
        assert state.pause_reason == PauseReason.USER_PAUSE

    def test_pause_before_boundary_ignored(self):
        msgs = [
            _msg("system", "(Session paused by user.)", user_pause=True),
            _boundary(),
            _msg("agent-1", "new phase content"),
        ]
        state = reconstruct_resume_state(msgs, "refinement")
        assert state.pause_reason is None


# ── build_prompt filtering ───────────────────────────────────────


class TestBuildPromptFiltering:
    def test_user_pause_filtered_from_prompt(self):
        from gotg.agent import build_prompt
        history = [
            _msg("agent-1", "hello"),
            _msg("system", "(Session paused by user.)", user_pause=True),
            _msg("system", "", user_pause_resolved=True),
            _msg("human", "continue please"),
        ]
        iteration = {"description": "test task", "phase": "refinement"}
        agent_config = {"name": "agent-1"}
        messages = build_prompt(agent_config, iteration, history)
        # user_pause and user_pause_resolved messages should not appear in prompt
        content_parts = [m["content"] for m in messages if m["role"] == "user"]
        full = "\n".join(content_parts)
        assert "paused by user" not in full
        assert "user_pause" not in full

    def test_user_pause_filtered_from_coach_prompt(self):
        from gotg.agent import build_coach_prompt
        history = [
            _msg("coach", "let's begin"),
            _msg("agent-1", "hello"),
            _msg("system", "(Session paused by user.)", user_pause=True),
            _msg("system", "", user_pause_resolved=True),
            _msg("human", "continue please"),
        ]
        iteration = {"description": "test task", "phase": "refinement"}
        coach_config = {"name": "coach"}
        messages = build_coach_prompt(coach_config, iteration, history)
        content_parts = [m["content"] for m in messages if m["role"] == "user"]
        full = "\n".join(content_parts)
        assert "paused by user" not in full
        assert "user_pause" not in full


# ── Implementation cancel_check ──────────────────────────────────


def _make_policy(**overrides):
    """Build a SessionPolicy with test defaults."""
    from gotg.policy import SessionPolicy
    defaults = dict(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=(), coach_tools=None,
        refinement_summary=None, tasks_summary=None, diffs_summary=None,
        kickoff_text=None, fileguard=None, approval_store=None,
        worktree_map=None, system_supplement=None, coach_system_prompt=None,
        phase_skeleton=None, streaming=False,
    )
    defaults.update(overrides)
    return SessionPolicy(**defaults)


class TestImplementationCancelCheck:
    def test_cancel_at_dispatch_boundary(self, tmp_path):
        """cancel_check fires between agent dispatches → UserPauseComplete."""
        from gotg.implementation import run_implementation
        from gotg.engine import SessionDeps

        iter_dir = tmp_path / "iter"
        iter_dir.mkdir()

        tasks = [
            {"id": "t1", "description": "task 1", "depends_on": [],
             "assigned_to": "agent-1", "layer": 0, "done_criteria": "done"},
            {"id": "t2", "description": "task 2", "depends_on": [],
             "assigned_to": "agent-2", "layer": 0, "done_criteria": "done"},
        ]
        (iter_dir / "tasks.json").write_text(json.dumps(tasks))

        agents = [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ]
        iteration = {"id": "iter-1", "description": "test", "phase": "implementation",
                      "current_layer": 0}

        # Mock completion
        mock_round = MagicMock()
        mock_round.tool_calls = []
        mock_round.content = "done"

        deps = SessionDeps(
            agent_completion=None,
            coach_completion=None,
            single_completion=MagicMock(return_value=mock_round),
        )

        policy = _make_policy()

        def cancel_check():
            return True

        events = list(run_implementation(
            agents=agents, tasks=tasks, current_layer=0,
            iteration=iteration, iter_dir=iter_dir,
            model_config={"base_url": "http://test", "model": "test"},
            deps=deps, history=[], policy=policy,
            cancel_check=cancel_check,
        ))

        event_types = [type(e).__name__ for e in events]
        assert "UserPauseComplete" in event_types
        pause_event = [e for e in events if isinstance(e, UserPauseComplete)][0]
        assert pause_event.total_turns == 1

    def test_cancel_ignored_before_first_dispatch(self, tmp_path):
        """cancel_check ignored when dispatched_agents == 0."""
        from gotg.implementation import run_implementation
        from gotg.engine import SessionDeps

        iter_dir = tmp_path / "iter"
        iter_dir.mkdir()

        tasks = [
            {"id": "t1", "description": "task 1", "depends_on": [],
             "assigned_to": "agent-1", "layer": 0, "done_criteria": "done"},
        ]
        (iter_dir / "tasks.json").write_text(json.dumps(tasks))

        agents = [{"name": "agent-1", "role": "Software Engineer"}]
        iteration = {"id": "iter-1", "description": "test", "phase": "implementation",
                      "current_layer": 0}

        mock_round = MagicMock()
        mock_round.tool_calls = []
        mock_round.content = "done"

        deps = SessionDeps(
            agent_completion=None,
            coach_completion=None,
            single_completion=MagicMock(return_value=mock_round),
        )

        policy = _make_policy()

        # Cancel immediately — but ignored because dispatched_agents == 0
        events = list(run_implementation(
            agents=agents, tasks=tasks, current_layer=0,
            iteration=iteration, iter_dir=iter_dir,
            model_config={"base_url": "http://test", "model": "test"},
            deps=deps, history=[], policy=policy,
            cancel_check=lambda: True,
        ))

        event_types = [type(e).__name__ for e in events]
        # Should complete normally, not yield UserPauseComplete
        assert "UserPauseComplete" not in event_types
        assert "SessionComplete" in event_types


# ── Marker shape + persistence ───────────────────────────────────


class TestMarkerPersistence:
    def test_pause_marker_shape(self, tmp_path):
        from gotg.conversation import ConversationStore
        log = tmp_path / "conversation.jsonl"
        store = ConversationStore(log)
        marker = {"from": "system", "content": "(Session paused by user.)",
                  "user_pause": True, "iteration": "iter-1"}
        store.append(marker)
        msgs = store.read_full()
        assert len(msgs) == 1
        assert msgs[0].get("user_pause") is True

    def test_resolution_marker_shape(self, tmp_path):
        from gotg.conversation import ConversationStore
        log = tmp_path / "conversation.jsonl"
        store = ConversationStore(log)
        store.append({"from": "system", "content": "(Session paused by user.)",
                       "user_pause": True, "iteration": "iter-1"})
        store.append({"from": "system", "content": "",
                       "user_pause_resolved": True, "iteration": "iter-1"})
        msgs = store.read_full()
        assert len(msgs) == 2
        assert msgs[1].get("user_pause_resolved") is True


# ── UserPauseComplete event ──────────────────────────────────────


class TestExplorePauseMarkerConsumption:
    def test_explore_continue_consumes_pause_marker(self, tmp_path):
        """cmd_explore_continue writes user_pause_resolved after first successful run."""
        from gotg.commands.explore import cmd_explore_continue

        team_dir = tmp_path / ".team"
        team_dir.mkdir()
        explore_dir = team_dir / "exploration" / "test-slug"
        explore_dir.mkdir(parents=True)

        # Write exploration metadata
        import json
        (explore_dir / "exploration.json").write_text(json.dumps({
            "schema_version": 2,
            "slug": "test-slug",
            "topic": "test topic",
            "coach": False,
            "max_turns": 30,
            "status": "active",
            "context_from": None,
        }))

        # Write conversation with a stale user_pause marker
        log_path = explore_dir / "conversation.jsonl"
        from gotg.conversation import ConversationStore
        store = ConversationStore(log_path)
        store.append(_msg("agent-1", "hello"))
        store.append({"from": "system", "content": "(Session paused by user.)",
                       "user_pause": True, "iteration": "test-slug"})

        # Mock the conversation runner to return immediately (not "paused")
        with patch("gotg.commands.explore.run_exploration_conversation", return_value=None), \
             patch("gotg.commands.explore._cli.find_team_dir", return_value=team_dir), \
             patch("gotg.commands.explore.TeamContext") as mock_ctx_cls, \
             patch("gotg.config.load_streaming_config", return_value=False), \
             patch("gotg.commands.run._make_pause_controller", return_value=None):

            mock_ctx = MagicMock()
            mock_ctx.agents = [{"name": "a1", "role": "SE"}, {"name": "a2", "role": "SE"}]
            mock_ctx.coach = None
            mock_ctx.model_config = {"base_url": "http://test", "model": "test"}
            mock_ctx.model_resolver = None
            mock_ctx.project_root = tmp_path
            mock_ctx.file_access = None
            mock_ctx_cls.from_team_dir.return_value = mock_ctx

            args = MagicMock()
            args.slug = "test-slug"
            args.approve_iterations = False
            args.message = None
            args.max_turns = None

            cmd_explore_continue(args)

        # Verify the resolution marker was written
        msgs = store.read_full()
        resolved = [m for m in msgs if m.get("user_pause_resolved")]
        assert len(resolved) == 1


class TestUserPauseCompleteEvent:
    def test_event_fields(self):
        event = UserPauseComplete(total_turns=3)
        assert event.total_turns == 3
