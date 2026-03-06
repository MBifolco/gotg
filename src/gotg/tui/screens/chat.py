"""Conversation viewer with live streaming support."""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, TextArea

from gotg.conversation import ConversationStore
from dataclasses import dataclass

from gotg.events import (
    AdvanceComplete,
    AdvanceError,
    AdvanceProgress,
    AgentTurnComplete,
    AppendDebug,
    AppendMessage,
    CoachAskedPM,
    IterationsProposed,
    LayerComplete,
    PauseForApprovals,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
    TaskBlocked,
    TextDelta,
    ToolCallProgress,
    UserPauseComplete,
)
from gotg.session_types import PauseReason
from gotg.tui.helpers import is_agent_turn, resolve_coach_name
from gotg.tui.messages import EngineEvent, SessionError, TextDeltaMsg, ToolProgress
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.info_tile import InfoTile
from gotg.tui.widgets.message_list import MessageList
from gotg.tui.widgets.participant_panel import ParticipantPanel


@dataclass
class _UserPaused:
    """Synthetic event for discussion-mode pause (no engine event emitted)."""
    pass


def _is_turn_boundary(msg: dict, coach_name: str | None) -> bool:
    """Return True if msg represents a turn boundary (agent turn or pass_turn).

    Inline helper — NO import from tui.helpers (which depends on textual at module level).
    """
    if msg.get("pass_turn"):
        return True
    sender = msg.get("from", "")
    if sender in ("system", "human"):
        return False
    if coach_name and sender == coach_name:
        return False
    return True


class SessionState(Enum):
    VIEWING = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETE = auto()
    ADVANCING = auto()


class ChatScreen(Screen):
    """Displays a conversation log with live streaming support."""

    BINDINGS = [
        Binding("ctrl+s", "send_message", "Send", priority=True),
        Binding("r", "run_session", "Run"),
        Binding("c", "continue_session", "Continue"),
        Binding("p", "advance_phase", "Advance"),
        Binding("d", "open_review", "Diffs"),
        Binding("t", "manage_tasks", "Tasks"),
        Binding("w", "rework", "Rework"),
        Binding("a", "manage_approvals", "Approvals"),
        Binding("i", "review_proposals", "Proposals"),
        Binding("escape", "go_back", "Back"),
        Binding("home", "scroll_top", "Top", show=False),
        Binding("end", "scroll_bottom", "Bottom", show=False),
    ]

    session_state: reactive[SessionState] = reactive(SessionState.VIEWING)

    def __init__(
        self,
        data_dir: Path,
        metadata: dict,
        mode: str = "view",
        session_kind: str = "iteration",
    ) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.metadata = metadata
        self._mode = mode
        self._session_kind = session_kind
        self._cancel_requested = False
        self._turn_count = 0
        self._initial_load_done = False
        self._pause_reason: PauseReason | None = None
        self._phase_complete_outcome: str | None = None
        self._pause_resolve_pending = False
        # Set by _prepare_session before launching worker
        self._log_path = data_dir / "conversation.jsonl"
        self._debug_path = data_dir / "debug.jsonl"
        self._conv_store = ConversationStore(self._log_path, self._debug_path)
        # Streaming state
        self._streaming_widget = None       # StreamingChatbox | None
        self._streaming_turn_id: str | None = None
        self._suppress_agent_append: str | None = None

    def compose(self):
        yield Header()
        with Horizontal(id="chat-layout"):
            with Vertical(id="chat-main"):
                yield MessageList(id="message-list")
                yield ActionBar(id="action-bar")
                with Horizontal(id="input-row"):
                    yield TextArea(
                        language="markdown",
                        theme="css",
                        soft_wrap=True,
                        compact=True,
                        show_line_numbers=False,
                        tab_behavior="indent",
                        placeholder="Ctrl+S to send...",
                        id="chat-input",
                    )
                    yield Button("Send", id="send-btn", variant="primary")
            with Vertical(id="chat-sidebar"):
                yield InfoTile(id="info-tile")
                yield ParticipantPanel(id="participant-panel")
        yield Footer()

    def on_mount(self) -> None:
        # Defer heavy I/O + widget mounting so the screen paints first
        self.call_after_refresh(self._load_initial_messages)

    def _load_initial_messages(self) -> None:
        """Parse conversation log and populate the message list."""
        messages = self._conv_store.read_full()

        msg_list = self.query_one("#message-list", MessageList)
        msg_list.load_messages(messages)

        # Enrich metadata with message count for the info tile
        enriched = {**self.metadata, "message_count": len(messages)}
        info = self.query_one("#info-tile", InfoTile)
        info.load_metadata(enriched, self.data_dir)
        participants = self.query_one("#participant-panel", ParticipantPanel)
        participants.load_participants(
            self.metadata.get("agents", []),
            self.metadata.get("coach"),
            team_model=self.metadata.get("team_model", ""),
        )

        # Count existing agent turns
        self._turn_count = self._count_agent_turns(messages)
        self._initial_load_done = True

        # Auto-start if mode is run or continue
        if self._mode in ("run", "continue"):
            self._start_session(self._mode)
            return

        # Restore paused state for any session type
        if messages:
            self._restore_pause_state(messages)

    def _count_agent_turns(self, messages: list[dict]) -> int:
        """Count engineering agent turns (not human/system/coach)."""
        coach_name = resolve_coach_name(self.metadata.get("coach"))
        return sum(1 for msg in messages if is_agent_turn(msg, coach_name))

    def _restore_pause_state(self, messages: list[dict]) -> None:
        """Detect if the conversation was paused mid-session and restore UI state."""
        from gotg.session_types import reconstruct_resume_state

        state = reconstruct_resume_state(messages, self.metadata.get("phase"))

        if state.pause_reason == PauseReason.USER_PAUSE:
            self._pause_resolve_pending = True
            self._start_session("continue")
            return

        if state.pause_reason == PauseReason.PHASE_COMPLETE:
            self._pause_reason = PauseReason.PHASE_COMPLETE
            self._phase_complete_outcome = state.phase_complete_outcome
            self.session_state = SessionState.PAUSED
            bar = self.query_one("#action-bar", ActionBar)
            if state.phase_complete_shows_review:
                if state.phase_complete_outcome == "changes_requested":
                    bar.show("Rework needed. Press W to rework, D to view diffs.")
                else:
                    bar.show("Code review approved. Press D to review diffs and merge.")
            else:
                bar.show("Phase complete. Press P to advance, C to continue discussing.")
            self._pin_after_action_bar()
            return

        if state.pause_reason == PauseReason.ITERATIONS_PROPOSED:
            self._pause_reason = PauseReason.ITERATIONS_PROPOSED
            self.session_state = SessionState.PAUSED
            pd = state.iteration_proposals
            from gotg.tui.modals.iteration_proposals import IterationProposalModal
            self.app.push_screen(
                IterationProposalModal(
                    pd["proposals"], pd.get("rationale", ""), pd.get("batch_id", ""),
                ),
                callback=self._on_proposals_result,
            )
            return

        if state.pause_reason == PauseReason.COACH_QUESTION:
            self._pause_reason = PauseReason.COACH_QUESTION
            self.session_state = SessionState.PAUSED
            msg_list = self.query_one("#message-list", MessageList)
            msg_list.append_coach_prompt(state.ask_pm_data["question"])
            options = state.ask_pm_data.get("options") or []
            if options:
                from gotg.tui.modals.decision import DecisionModal
                self.app.push_screen(
                    DecisionModal(state.ask_pm_data["question"], options),
                    callback=self._on_decision_result,
                )
            else:
                self.query_one("#action-bar", ActionBar).show(
                    "Type reply and press Enter."
                )
            self._pin_after_action_bar()
            return

        if state.show_task_status_bar:
            self._update_task_status_bar()
            return

        # No specific pause — check if we just advanced (boundary + transition, no real content)
        phase = self.metadata.get("phase", "")
        bar = self.query_one("#action-bar", ActionBar)
        # Find last boundary
        last_boundary_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("phase_boundary"):
                last_boundary_idx = i
                break
        if last_boundary_idx >= 0:
            after_boundary = messages[last_boundary_idx + 1:]
            has_real_content = any(
                m.get("from") not in ("system", None) and not m.get("pass_turn")
                for m in after_boundary
            )
            if not has_real_content:
                bar.show(f"Advanced to {phase}. Press R to run.")
                return

    # ── Dynamic bindings ────────────────────────────────────

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Show/hide bindings based on current state."""
        state = self.session_state
        phase = self.metadata.get("phase")
        is_iter = self._session_kind == "iteration"
        pr = self._pause_reason
        paused = state == SessionState.PAUSED

        if action == "send_message":
            return state in (SessionState.VIEWING, SessionState.PAUSED, SessionState.COMPLETE, SessionState.RUNNING)
        if action == "run_session":
            return state == SessionState.VIEWING
        if action == "continue_session":
            return state in (SessionState.VIEWING, SessionState.PAUSED, SessionState.COMPLETE)
        if action == "advance_phase":
            return paused and pr == PauseReason.PHASE_COMPLETE and is_iter
        if action == "open_review":
            if not (paused and pr == PauseReason.PHASE_COMPLETE and is_iter):
                return False
            from gotg.phases import get_phase_caps_safe
            return get_phase_caps_safe(phase).can_open_review_screen
        if action == "manage_tasks":
            if not (state == SessionState.VIEWING and is_iter):
                return False
            from gotg.phases import get_phase_caps_safe
            return get_phase_caps_safe(phase).show_task_status_bar
        if action == "rework":
            return (
                paused and pr == PauseReason.PHASE_COMPLETE and is_iter
                and phase == "code-review"
                and self._phase_complete_outcome == "changes_requested"
            )
        if action == "manage_approvals":
            return paused and pr == PauseReason.APPROVALS
        if action == "review_proposals":
            return paused and pr == PauseReason.ITERATIONS_PROPOSED
        return True

    # ── State machine ────────────────────────────────────────

    def watch_session_state(self, state: SessionState) -> None:
        """React to state changes by updating UI."""
        if not self.is_mounted:
            return  # Children not composed yet; on_mount handles initial state
        ta = self.query_one("#chat-input", TextArea)
        btn = self.query_one("#send-btn", Button)
        info = self.query_one("#info-tile", InfoTile)

        if state == SessionState.VIEWING:
            ta.placeholder = "Press R to run, C to continue..."
            ta.disabled = False
            btn.disabled = False
            info.update_session_status("")
            self.query_one("#message-list", MessageList).focus()
        elif state == SessionState.RUNNING:
            ta.placeholder = "Session running..."
            ta.disabled = True
            btn.label = "Pause"
            btn.disabled = False
            info.update_session_status("Running", self._turn_count)
        elif state == SessionState.PAUSED:
            ta.disabled = False
            btn.label = "Send"
            btn.disabled = False
            if self._pause_reason == PauseReason.COACH_QUESTION:
                ta.placeholder = "Type reply and Ctrl+S to send..."
                ta.focus()
            else:
                ta.placeholder = "Press C to continue..."
            info.update_session_status("Paused", self._turn_count)
        elif state == SessionState.COMPLETE:
            ta.disabled = False
            btn.label = "Send"
            btn.disabled = False
            ta.placeholder = "Press C to continue with more turns..."
            info.update_session_status("Complete", self._turn_count)
        elif state == SessionState.ADVANCING:
            ta.placeholder = "Advancing phase..."
            ta.disabled = True
            btn.disabled = True
            info.update_session_status("Advancing")

        self.refresh_bindings()

    # ── Session lifecycle ────────────────────────────────────

    def _start_session(self, mode: str, human_message: str | None = None) -> None:
        """Start or continue the engine in a worker thread."""
        self._cancel_requested = False
        self.session_state = SessionState.RUNNING
        self.query_one("#action-bar", ActionBar).hide()

        # Inject human message if continuing with text
        if mode == "continue" and human_message:
            iteration_id = self.metadata.get("id") or self.metadata.get("slug", "")
            msg = {
                "from": "human",
                "iteration": iteration_id,
                "content": human_message,
            }
            self._conv_store.append(msg)
            msg_list = self.query_one("#message-list", MessageList)
            msg_list.append_message(msg)

        self.run_worker(self._run_engine, thread=True)

    def _resolve_pause_marker(self) -> None:
        """Write resolution marker if pending. Called once setup succeeds."""
        if self._pause_resolve_pending:
            iteration_id = self.metadata.get("id") or self.metadata.get("slug", "")
            self._conv_store.append({"from": "system", "content": "",
                                      "user_pause_resolved": True,
                                      "iteration": iteration_id})
            self._pause_resolve_pending = False

    def _run_engine(self) -> None:
        """Runs in worker thread. Posts EngineEvent messages to main thread."""
        try:
            from gotg.context import TeamContext
            from gotg.engine import SessionDeps
            from gotg.model import (
                agentic_completion,
                chat_completion,
                raw_completion,
                raw_completion_stream,
            )
            from gotg.session import (
                SessionSetupError,
                build_session_infra,
                prepare_session, run_and_persist,
                validate_iteration_for_run,
            )

            ctx = TeamContext.from_team_dir(self.app.team_dir)
            streaming_enabled = False

            if self._session_kind == "iteration":
                # Ensure we load the iteration this screen was opened for
                target_id = self.metadata.get("id")
                if target_id:
                    ctx.iteration_store.set_current(target_id)
                iteration, iter_dir = ctx.iteration_store.get_current()
                validate_iteration_for_run(iteration, iter_dir, ctx.agents)

                # Clear stale review_outcome when resuming code-review discussion.
                if iteration.get("phase") == "code-review" and iteration.get("review_outcome"):
                    from gotg.iteration_store import save_iteration_fields
                    save_iteration_fields(self.app.team_dir, iteration["id"], review_outcome=None)
                    iteration["review_outcome"] = None

                infra = build_session_infra(ctx, iteration, iter_dir)

                # Apply approved writes, inject denials, count turns
                from gotg.session import prepare_continue
                cont = prepare_continue(
                    infra, iteration, self._log_path,
                    coach_name=ctx.coach["name"] if ctx.coach else None,
                )
                self._resolve_pause_marker()
                for msg in cont.injected_messages:
                    self.post_message(EngineEvent(AppendMessage(msg)))
                if cont.has_pending_approvals:
                    self.post_message(EngineEvent(
                        PauseForApprovals(pending_count=cont.pending_count)
                    ))
                    return

                max_turns = cont.current_agent_turns + iteration.get("max_turns", 30)
                streaming_enabled = infra.streaming

                deps = SessionDeps(
                    agent_completion=agentic_completion,
                    coach_completion=chat_completion,
                    single_completion=raw_completion,
                    stream_completion=raw_completion_stream if streaming_enabled else None,
                    model_resolver=ctx.model_resolver,
                )

                setup = prepare_session(
                    iter_dir, ctx.agents, iteration, ctx.model_config, deps,
                    max_turns_override=max_turns, coach=ctx.coach,
                    fileguard=infra.fileguard, approval_store=infra.approval_store,
                    worktree_map=infra.worktree_map, diffs_summary=infra.diffs_summary,
                    streaming=streaming_enabled,
                )
            else:
                # Exploration session — uses prepare_exploration_session
                from gotg.explore import load_exploration_metadata
                from gotg.session import prepare_exploration_session, load_iteration_context

                explore_meta, explore_dir = load_exploration_metadata(
                    self.app.team_dir, self.metadata.get("slug", "")
                )
                iteration = {
                    "id": explore_meta["slug"],
                    "description": explore_meta.get("topic", ""),
                    "phase": None,
                }
                coach = ctx.coach if explore_meta.get("coach") else None

                # Load iteration context from persisted context_from
                context_from = explore_meta.get("context_from")
                project_context = None
                if isinstance(context_from, str):
                    project_context = load_iteration_context(
                        ctx.team_dir, context_from=context_from
                    )

                from gotg.config import load_streaming_config as _load_streaming
                streaming_enabled = _load_streaming(ctx.team_dir)

                deps = SessionDeps(
                    agent_completion=agentic_completion,
                    coach_completion=chat_completion,
                    single_completion=raw_completion,
                    stream_completion=raw_completion_stream if streaming_enabled else None,
                    model_resolver=ctx.model_resolver,
                )

                setup = prepare_exploration_session(
                    explore_dir, ctx.agents, iteration, ctx.model_config, deps,
                    topic=explore_meta.get("topic", ""),
                    coach=coach,
                    max_turns=explore_meta.get("max_turns", 30),
                    streaming=streaming_enabled,
                    project_context=project_context,
                    project_root=ctx.project_root,
                    file_access=ctx.file_access,
                )
                self._resolve_pause_marker()

            # Wire cancel_check for implementation-mode pause
            setup.cancel_check = lambda: self._cancel_requested

            # Track coach name for discussion-mode turn boundary detection
            _coach_name = resolve_coach_name(self.metadata.get("coach"))

            # Unified event loop — run_and_persist handles persistence + phase routing
            import time
            _stream_buffer: list[str] = []
            _stream_turn_id: str | None = None
            _stream_agent: str = ""
            _last_flush = time.monotonic()

            def _flush_stream_buffer():
                nonlocal _stream_buffer, _last_flush
                if _stream_buffer:
                    self.post_message(TextDeltaMsg(
                        _stream_agent, _stream_turn_id or "", "".join(_stream_buffer),
                    ))
                    _stream_buffer = []
                    _last_flush = time.monotonic()

            _terminal_handled = False
            _pause_pending = False

            for event in run_and_persist(setup):
                # Deferred pause: if pause was pending, check what came next
                if _pause_pending:
                    if isinstance(event, (PauseForApprovals, PhaseCompleteSignaled,
                                          CoachAskedPM, IterationsProposed,
                                          SessionComplete, LayerComplete,
                                          UserPauseComplete)):
                        _pause_pending = False
                        # Fall through — terminal event wins
                    else:
                        break  # Non-terminal → pause wins

                # Terminal events ALWAYS processed (even if cancel requested)
                if isinstance(event, (PauseForApprovals, PhaseCompleteSignaled,
                                      CoachAskedPM, IterationsProposed,
                                      SessionComplete, LayerComplete,
                                      UserPauseComplete)):
                    _flush_stream_buffer()
                    self.post_message(EngineEvent(event))
                    _terminal_handled = True
                    break

                if isinstance(event, TextDelta):
                    _stream_buffer.append(event.text)
                    _stream_turn_id = event.turn_id
                    _stream_agent = event.agent
                    now = time.monotonic()
                    if now - _last_flush >= 0.05:
                        _flush_stream_buffer()
                    continue

                if isinstance(event, AgentTurnComplete):
                    _flush_stream_buffer()
                    self.post_message(EngineEvent(event))
                    continue

                # Flush any pending stream data before non-delta events
                _flush_stream_buffer()

                # Already persisted by run_and_persist — just post to UI
                if isinstance(event, ToolCallProgress):
                    self.post_message(ToolProgress(event))
                else:
                    self.post_message(EngineEvent(event))
                    # Discussion pause: defer to next event (don't break immediately)
                    if (not setup.use_implementation
                            and isinstance(event, AppendMessage)
                            and _is_turn_boundary(event.msg, _coach_name)
                            and self._cancel_requested):
                        _pause_pending = True
                        continue

            # After loop — discussion break needs synthetic pause event
            if (self._cancel_requested or _pause_pending) and not _terminal_handled and self.is_mounted:
                self.post_message(EngineEvent(_UserPaused()))

        except SessionSetupError as e:
            self.post_message(SessionError(str(e)))
        except Exception as e:
            self.post_message(SessionError(str(e)))

    # ── Event handlers ───────────────────────────────────────

    def on_engine_event(self, message: EngineEvent) -> None:
        """Handle engine events on the main thread."""
        event = message.event

        if isinstance(event, SessionStarted):
            info = self.query_one("#info-tile", InfoTile)
            info.update_session_status("Running", event.turn)
            self._turn_count = event.turn
            participants = self.query_one("#participant-panel", ParticipantPanel)
            participants.load_participants(
                self.metadata.get("agents", event.agents),
                self.metadata.get("coach") or event.coach,
                team_model=self.metadata.get("team_model", ""),
            )

        elif isinstance(event, AgentTurnComplete):
            # Finalize the streaming widget with the persisted content
            if self._streaming_widget is not None:
                msg_list = self.query_one("#message-list", MessageList)
                msg_list.finalize_streaming(self._streaming_widget, event.content)
            self._streaming_widget = None
            self._streaming_turn_id = None
            self._suppress_agent_append = event.agent
            self.query_one("#action-bar", ActionBar).hide()
            participants = self.query_one("#participant-panel", ParticipantPanel)
            participants.mark_idle(event.agent)

        elif isinstance(event, AppendMessage):
            msg_list = self.query_one("#message-list", MessageList)
            # Skip rendering if already shown via streaming widget
            if self._suppress_agent_append and event.msg.get("from") == self._suppress_agent_append:
                self._suppress_agent_append = None
            else:
                msg_list.append_message(event.msg)
            coach_name = resolve_coach_name(self.metadata.get("coach"))
            if is_agent_turn(event.msg, coach_name):
                self._turn_count += 1
            info = self.query_one("#info-tile", InfoTile)
            info.update_session_status("Running", self._turn_count)

        elif isinstance(event, AppendDebug):
            pass  # Already persisted in worker

        elif isinstance(event, PauseForApprovals):
            self._pause_reason = PauseReason.APPROVALS
            self.session_state = SessionState.PAUSED
            self.query_one("#action-bar", ActionBar).show(
                f"Paused: {event.pending_count} pending approval(s). "
                "Press A to review approvals, C to continue."
            )
            self._pin_after_action_bar()

        elif isinstance(event, CoachAskedPM):
            self._pause_reason = PauseReason.COACH_QUESTION
            self.session_state = SessionState.PAUSED
            msg_list = self.query_one("#message-list", MessageList)
            msg_list.append_coach_prompt(event.question)
            if event.options:
                from gotg.tui.modals.decision import DecisionModal
                self.app.push_screen(
                    DecisionModal(event.question, event.options),
                    callback=self._on_decision_result,
                )
            else:
                self.query_one("#action-bar", ActionBar).show(
                    "Type reply and press Enter."
                )
            self._pin_after_action_bar()

        elif isinstance(event, IterationsProposed):
            self._pause_reason = PauseReason.ITERATIONS_PROPOSED
            self.session_state = SessionState.PAUSED
            from gotg.tui.modals.iteration_proposals import IterationProposalModal
            self.app.push_screen(
                IterationProposalModal(
                    list(event.proposals), event.rationale, event.batch_id,
                ),
                callback=self._on_proposals_result,
            )

        elif isinstance(event, PhaseCompleteSignaled):
            self._pause_reason = PauseReason.PHASE_COMPLETE
            self._phase_complete_outcome = event.outcome
            self.session_state = SessionState.PAUSED
            from gotg.phases import get_phase_caps_safe
            caps = get_phase_caps_safe(event.phase)
            bar = self.query_one("#action-bar", ActionBar)
            if caps.phase_complete_shows_review_hint:
                # Persist review outcome to iteration.json
                from gotg.iteration_store import save_iteration_fields
                save_iteration_fields(self.app.team_dir, self.metadata["id"], review_outcome=event.outcome)
                if event.outcome == "changes_requested":
                    bar.show("Rework needed. Press W to rework, D to view diffs.")
                else:
                    bar.show("Code review approved. Press D to review diffs and merge.")
            else:
                bar.show("Phase complete. Press P to advance, C to continue discussing.")
            self._pin_after_action_bar()

        elif isinstance(event, LayerComplete):
            self._pause_reason = PauseReason.PHASE_COMPLETE
            self.session_state = SessionState.PAUSED
            self.query_one("#action-bar", ActionBar).show(
                f"Layer {event.layer} complete ({len(event.completed_tasks)} tasks). "
                "Press P to advance to code review."
            )
            self._pin_after_action_bar()

        elif isinstance(event, TaskBlocked):
            blocked = ", ".join(event.task_ids)
            self.query_one("#action-bar", ActionBar).show(
                f"Blocked: {event.agent} -> {blocked}"
            )
            self._pin_after_action_bar()

        elif isinstance(event, (_UserPaused, UserPauseComplete)):
            self._pause_reason = PauseReason.USER_PAUSE
            self.session_state = SessionState.PAUSED
            bar = self.query_one("#action-bar", ActionBar)
            bar.show("Paused. Type a message and Send, or press C to resume.")
            self._pin_after_action_bar()

        elif isinstance(event, SessionComplete):
            self.session_state = SessionState.COMPLETE
            self.query_one("#action-bar", ActionBar).show(
                f"Session complete ({event.total_turns} turns). "
                "Press C to continue with more turns."
            )
            self._pin_after_action_bar()

        elif isinstance(event, AdvanceProgress):
            self.query_one("#action-bar", ActionBar).show(event.message)

        elif isinstance(event, AdvanceComplete):
            self.session_state = SessionState.VIEWING
            # Patch metadata for display only — R → run reloads from disk
            self.metadata["phase"] = event.to_phase
            self.query_one("#info-tile", InfoTile).update_phase(event.to_phase)
            from gotg.phases import get_phase_caps_safe
            if get_phase_caps_safe(event.to_phase).auto_open_task_assign_on_advance:
                self.query_one("#action-bar", ActionBar).show(
                    "Assigning tasks..."
                )
                self._open_task_assign()
            else:
                self.query_one("#action-bar", ActionBar).show(
                    f"Advanced: {event.from_phase} -> {event.to_phase}. Press R to run."
                )

        elif isinstance(event, AdvanceError):
            if event.partial:
                self.notify(f"Warning: {event.error}", severity="warning")
            else:
                self._pause_reason = PauseReason.PHASE_COMPLETE
                self.session_state = SessionState.PAUSED
                self.query_one("#action-bar", ActionBar).show(
                    f"Advance failed: {event.error}"
                )

    def _pin_after_action_bar(self) -> None:
        """Re-pin scroll after ActionBar appears and steals viewport height."""
        msg_list = self.query_one("#message-list", MessageList)
        msg_list.pin_to_bottom()

    def on_text_delta_msg(self, message: TextDeltaMsg) -> None:
        """Handle batched text deltas from streaming responses."""
        from gotg.tui.widgets.message_list import StreamingChatbox, _css_class_for

        msg_list = self.query_one("#message-list", MessageList)

        if self._streaming_turn_id != message.turn_id:
            # New turn — create a new streaming widget
            css_class = _css_class_for(message.agent, msg_list._agent_index)
            self._streaming_widget = msg_list.begin_streaming(
                message.agent, css_class,
            )
            self._streaming_turn_id = message.turn_id

        if self._streaming_widget is not None:
            msg_list.append_stream_delta(self._streaming_widget, message.text)
        participants = self.query_one("#participant-panel", ParticipantPanel)
        participants.mark_typing(message.agent)

    def on_tool_progress(self, message: ToolProgress) -> None:
        """Handle ToolCallProgress events — update action bar with current operation."""
        event = message.event
        if event.status == "error":
            text = f"[{event.agent}] {event.tool_name} {event.path} FAIL"
        elif event.tool_name == "complete_tasks":
            text = f"[{event.agent}] complete_tasks"
        elif event.tool_name == "report_blocked":
            text = f"[{event.agent}] report_blocked"
        elif event.tool_name == "file_write" and event.bytes:
            text = f"[{event.agent}] {event.tool_name} {event.path} ({event.bytes}b)"
        else:
            text = f"[{event.agent}] {event.tool_name} {event.path}"
        self.query_one("#action-bar", ActionBar).show(text)
        self.query_one("#participant-panel", ParticipantPanel).add_tool_progress(event)

    def on_session_error(self, message: SessionError) -> None:
        """Handle worker thread errors."""
        self.session_state = SessionState.VIEWING
        self.notify(f"Session error: {message.error}", severity="error")

    # ── Decision modal callback ─────────────────────────────

    def _on_decision_result(self, result: str | None) -> None:
        """Handle the result from DecisionModal."""
        if result is None:
            self.query_one("#action-bar", ActionBar).show(
                "Decision cancelled. Type reply and press Enter, or press C to continue."
            )
            return
        self._start_session("continue", human_message=result)

    def _on_proposals_result(self, result: str | None) -> None:
        """Handle the result from IterationProposalModal."""
        if result is None:
            # Dismissed — stay paused, show action bar
            self.query_one("#action-bar", ActionBar).show(
                "Proposals pending. Press I to review."
            )
            self._pin_after_action_bar()
            return
        if result == "approved":
            # Find the unapproved batch
            history = self._conv_store.read_full()
            proposals_msg = None
            approved_batches = {
                m["iterations_batch_approved"] for m in history
                if "iterations_batch_approved" in m
            }
            for msg in reversed(history):
                pi = msg.get("propose_iterations")
                if pi and pi.get("batch_id") not in approved_batches:
                    proposals_msg = pi
                    break

            if proposals_msg:
                from gotg.session_setup import apply_iteration_proposals
                results = apply_iteration_proposals(
                    self.app.team_dir, proposals_msg["proposals"],
                    batch_id=proposals_msg["batch_id"],
                    explore_slug=self.metadata.get("slug", ""),
                    store=self._conv_store,
                )
                msg_list = self.query_one("#message-list", MessageList)
                for r in results:
                    msg_list.append_message(r)
            self._start_session("continue")
        else:
            # Feedback — continue with message
            self._start_session("continue", human_message=result)

    # ── Input handling ───────────────────────────────────────

    def _send_input(self) -> None:
        """Extract text from the input, clear it, and continue the session."""
        if self.session_state == SessionState.RUNNING:
            # Pause button during RUNNING
            self._cancel_requested = True
            info = self.query_one("#info-tile", InfoTile)
            info.update_session_status("Cancelling...")
            return

        ta = self.query_one("#chat-input", TextArea)
        text = ta.text.strip()
        if not text:
            return
        ta.clear()

        if self.session_state in (SessionState.VIEWING, SessionState.PAUSED, SessionState.COMPLETE):
            self._start_session("continue", human_message=text)

    def action_send_message(self) -> None:
        """Handle Ctrl+S to send the message."""
        self._send_input()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Send/Pause button click."""
        if event.button.id == "send-btn":
            self._send_input()

    # ── Actions ──────────────────────────────────────────────

    def action_go_back(self) -> None:
        if self.session_state == SessionState.RUNNING:
            self._cancel_requested = True
            info = self.query_one("#info-tile", InfoTile)
            info.update_session_status("Cancelling...")
            return  # Don't pop — wait for PAUSED transition, then Esc again to exit
        elif (self.session_state == SessionState.PAUSED
              and self._pause_reason == PauseReason.USER_PAUSE):
            iteration_id = self.metadata.get("id") or self.metadata.get("slug", "")
            self._conv_store.append({"from": "system",
                                      "content": "(Session paused by user.)",
                                      "user_pause": True, "iteration": iteration_id})
        self.app.pop_screen()

    def action_scroll_top(self) -> None:
        self.query_one("#message-list", MessageList).scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        self.query_one("#message-list", MessageList).scroll_end(animate=False)

    def action_run_session(self) -> None:
        if self.session_state == SessionState.VIEWING:
            self._start_session("run")

    def action_continue_session(self) -> None:
        if self.session_state in (SessionState.PAUSED, SessionState.COMPLETE, SessionState.VIEWING):
            human_msg = None
            ta = self.query_one("#chat-input", TextArea)
            text = ta.text.strip()
            if text:
                human_msg = text
                ta.clear()
            self._start_session("continue", human_message=human_msg)

    def action_review_proposals(self) -> None:
        """Re-open iteration proposal modal when paused with proposals."""
        if self.session_state != SessionState.PAUSED:
            return
        if self._pause_reason != PauseReason.ITERATIONS_PROPOSED:
            return
        # Find the unapproved batch from history
        history = self._conv_store.read_full()
        approved_batches = {
            m["iterations_batch_approved"] for m in history
            if "iterations_batch_approved" in m
        }
        for msg in reversed(history):
            pi = msg.get("propose_iterations")
            if pi and pi.get("batch_id") not in approved_batches:
                from gotg.tui.modals.iteration_proposals import IterationProposalModal
                self.app.push_screen(
                    IterationProposalModal(
                        pi["proposals"], pi.get("rationale", ""), pi.get("batch_id", ""),
                    ),
                    callback=self._on_proposals_result,
                )
                return

    def action_manage_approvals(self) -> None:
        """Open approval management screen."""
        if self.session_state != SessionState.PAUSED:
            return
        if self._pause_reason != PauseReason.APPROVALS:
            return
        approvals_path = self.data_dir / "approvals.json"
        if not approvals_path.exists():
            self.notify("No approvals file found.", severity="warning")
            return
        from gotg.tui.screens.approval import ApprovalScreen
        self.app.push_screen(ApprovalScreen(approvals_path))

    def action_advance_phase(self) -> None:
        """Start phase advance when paused at phase complete."""
        if self.session_state != SessionState.PAUSED:
            return
        if self._pause_reason != PauseReason.PHASE_COMPLETE:
            return
        if self._session_kind != "iteration":
            return
        self.session_state = SessionState.ADVANCING
        self.query_one("#action-bar", ActionBar).show("Advancing phase...")
        self.run_worker(self._run_advance, thread=True)

    def _run_advance(self) -> None:
        """Runs in worker thread. Calls advance_phase and posts progress events."""
        try:
            from gotg.context import TeamContext
            from gotg.model import chat_completion
            from gotg.session import PhaseAdvanceError, advance_phase

            ctx = TeamContext.from_team_dir(self.app.team_dir)
            iteration, iter_dir = ctx.iteration_store.get_current()

            def on_progress(step: str):
                self.post_message(EngineEvent(AdvanceProgress(message=step)))

            result = advance_phase(
                ctx.team_dir, iteration, iter_dir,
                chat_call=chat_completion,
                on_progress=on_progress,
            )

            # Show boundary + transition messages in conversation
            # (already persisted to disk by advance_phase)
            self.post_message(EngineEvent(AppendMessage(result.boundary_msg)))
            self.post_message(EngineEvent(AppendMessage(result.transition_msg)))

            for w in result.warnings:
                self.post_message(EngineEvent(AdvanceError(error=w, partial=True)))

            self.post_message(EngineEvent(AdvanceComplete(
                from_phase=result.from_phase,
                to_phase=result.to_phase,
            )))

        except PhaseAdvanceError as e:
            self.post_message(EngineEvent(AdvanceError(error=str(e), partial=False)))
        except Exception as e:
            self.post_message(SessionError(f"Advance failed: {e}"))

    def action_manage_tasks(self) -> None:
        """Open task assignment screen."""
        if self.session_state != SessionState.VIEWING:
            return
        if self._session_kind != "iteration":
            return
        from gotg.phases import get_phase_caps_safe
        if not get_phase_caps_safe(self.metadata.get("phase")).show_task_status_bar:
            return
        self._open_task_assign()

    def _open_task_assign(self) -> None:
        """Push the TaskAssignScreen."""
        from gotg.config import load_team_config
        from gotg.tui.screens.task_assign import TaskAssignScreen

        agents = load_team_config(self.app.team_dir).get("agents", [])
        self.app.push_screen(TaskAssignScreen(self.data_dir, agents))

    def _update_task_status_bar(self) -> None:
        """Update action bar with task assignment/completion status."""
        from gotg.tasks import TaskRepo

        repo = TaskRepo(self.data_dir / "tasks.json")
        bar = self.query_one("#action-bar", ActionBar)
        if not repo.exists():
            bar.show("Press R to run, T to assign tasks.")
            return
        tasks = repo.load()
        completed = sum(1 for t in tasks if t.get("status") == "done")
        if completed == len(tasks):
            bar.show("All tasks complete. Press P to advance to code review.")
            return
        if completed > 0:
            bar.show(
                f"{completed}/{len(tasks)} tasks done. Press R to continue implementation."
            )
            return
        unassigned = sum(1 for t in tasks if not t.get("assigned_to"))
        if unassigned:
            bar.show(
                f"{unassigned} task(s) unassigned. Press T to assign, then R to run."
            )
        else:
            bar.show("All tasks assigned. Press R to run.")

    def action_open_review(self) -> None:
        """Open review screen for code-review diffs and merge."""
        if self.session_state != SessionState.PAUSED:
            return
        if self._pause_reason != PauseReason.PHASE_COMPLETE:
            return
        if self._session_kind != "iteration":
            return
        from gotg.phases import get_phase_caps_safe
        if not get_phase_caps_safe(self.metadata.get("phase")).can_open_review_screen:
            return
        from gotg.context import TeamContext
        ctx = TeamContext.from_team_dir(self.app.team_dir)
        iteration, iter_dir = ctx.iteration_store.get_current()
        from gotg.tui.screens.review import ReviewScreen
        self.app.push_screen(ReviewScreen(
            self.app.team_dir, iteration, iter_dir,
            review_outcome=iteration.get("review_outcome"),
        ))

    def action_rework(self) -> None:
        """Send tasks back for rework based on review feedback."""
        if self.session_state != SessionState.PAUSED:
            return
        if self._pause_reason != PauseReason.PHASE_COMPLETE:
            return
        if self._session_kind != "iteration":
            return
        # Only available when code-review ended with changes_requested
        if self.metadata.get("phase") != "code-review":
            return
        if self._phase_complete_outcome != "changes_requested":
            return
        self.session_state = SessionState.ADVANCING
        self.query_one("#action-bar", ActionBar).show("Extracting review feedback...")
        self.run_worker(self._run_rework, thread=True)

    def _run_rework(self) -> None:
        """Runs in worker thread. Calls advance_rework and posts events."""
        try:
            from gotg.context import TeamContext
            from gotg.model import chat_completion
            from gotg.session_advance import advance_rework
            from gotg.session_types import ReworkError

            ctx = TeamContext.from_team_dir(self.app.team_dir)
            iteration, iter_dir = ctx.iteration_store.get_current()

            def on_progress(step: str):
                self.post_message(EngineEvent(AdvanceProgress(message=step)))

            result = advance_rework(
                ctx.team_dir, iteration, iter_dir,
                chat_call=chat_completion,
                on_progress=on_progress,
            )

            self.post_message(EngineEvent(AppendMessage(result.boundary_msg)))
            self.post_message(EngineEvent(AppendMessage(result.transition_msg)))

            for w in result.warnings:
                self.post_message(EngineEvent(AdvanceError(error=w, partial=True)))

            self.post_message(EngineEvent(AdvanceComplete(
                from_phase="code-review",
                to_phase="implementation",
            )))

        except ReworkError as e:
            self.post_message(EngineEvent(AdvanceError(error=str(e), partial=False)))
        except Exception as e:
            self.post_message(SessionError(f"Rework failed: {e}"))

    def on_screen_resume(self) -> None:
        """Refresh state when returning from pushed screens."""
        if not self._initial_load_done:
            return
        if self.session_state == SessionState.VIEWING:
            # Returning from TaskAssignScreen or similar
            from gotg.phases import get_phase_caps_safe
            if get_phase_caps_safe(self.metadata.get("phase")).show_task_status_bar:
                self._update_task_status_bar()
            return

        if self.session_state != SessionState.PAUSED:
            return

        if self._pause_reason == PauseReason.APPROVALS:
            approvals_path = self.data_dir / "approvals.json"
            if not approvals_path.exists():
                return
            from gotg.approvals import ApprovalStore
            store = ApprovalStore(approvals_path)
            pending = store.get_pending()
            bar = self.query_one("#action-bar", ActionBar)
            if pending:
                bar.show(
                    f"Paused: {len(pending)} pending approval(s). "
                    "Press A to review approvals, C to continue."
                )
            else:
                bar.show("All approvals resolved. Press C to continue.")

        elif self._pause_reason == PauseReason.PHASE_COMPLETE:
            # Re-read iteration state from disk (may have changed in ReviewScreen)
            from gotg.context import TeamContext
            ctx = TeamContext.from_team_dir(self.app.team_dir)
            iteration, _ = ctx.iteration_store.get_current()
            new_phase = iteration.get("phase")
            new_layer = iteration.get("current_layer")
            new_status = iteration.get("status")
            old_phase = self.metadata.get("phase")
            old_layer = self.metadata.get("current_layer")

            if new_status == "done":
                self.metadata["status"] = "done"
                self.session_state = SessionState.COMPLETE
                self.query_one("#action-bar", ActionBar).show(
                    "Iteration complete. Press Esc to return home."
                )
            elif new_phase != old_phase or new_layer != old_layer:
                self.metadata["phase"] = new_phase
                self.metadata["current_layer"] = new_layer
                self.query_one("#info-tile", InfoTile).update_phase(new_phase)
                layer = new_layer if new_layer is not None else 0
                self.session_state = SessionState.VIEWING
                self.query_one("#action-bar", ActionBar).show(
                    f"Advanced to layer {layer} ({new_phase}). Press R to run."
                )
                # Append only the new messages (boundary + transition)
                messages = self._conv_store.read_full()
                msg_list = self.query_one("#message-list", MessageList)
                for m in messages[-2:]:
                    msg_list.append_message(m)
