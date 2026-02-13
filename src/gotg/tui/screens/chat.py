"""Conversation viewer with live streaming support."""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Input

from gotg.conversation import append_message, read_log, read_phase_history
from gotg.events import (
    AdvanceComplete,
    AdvanceError,
    AdvanceProgress,
    AgentTurnComplete,
    AppendDebug,
    AppendMessage,
    CoachAskedPM,
    LayerComplete,
    PauseForApprovals,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
    TaskBlocked,
    TextDelta,
    ToolCallProgress,
)
from gotg.session import persist_event
from gotg.tui.helpers import is_agent_turn, resolve_coach_name
from gotg.tui.messages import EngineEvent, SessionError, TextDeltaMsg, ToolProgress
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.info_tile import InfoTile
from gotg.tui.widgets.message_list import MessageList
from gotg.tui.widgets.participant_panel import ParticipantPanel


class SessionState(Enum):
    VIEWING = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETE = auto()
    ADVANCING = auto()


class PauseReason(Enum):
    APPROVALS = auto()
    COACH_QUESTION = auto()
    PHASE_COMPLETE = auto()


class ChatScreen(Screen):
    """Displays a conversation log with live streaming support."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("home", "scroll_top", "Top"),
        Binding("end", "scroll_bottom", "Bottom"),
        Binding("r", "run_session", "Run", show=False),
        Binding("c", "continue_session", "Continue", show=False),
        Binding("a", "manage_approvals", "Approvals", show=False),
        Binding("p", "advance_phase", "Advance", show=False),
        Binding("d", "open_review", "Diffs", show=False),
        Binding("t", "manage_tasks", "Tasks", show=False),
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
        self._pause_reason: PauseReason | None = None
        # Set by _prepare_session before launching worker
        self._log_path = data_dir / "conversation.jsonl"
        self._debug_path = data_dir / "debug.jsonl"
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
                yield Input(
                    placeholder="Press R to run, C to continue...",
                    id="chat-input",
                )
            with Vertical(id="chat-sidebar"):
                yield InfoTile(id="info-tile")
                yield ParticipantPanel(id="participant-panel")
        yield Footer()

    def on_mount(self) -> None:
        # Defer heavy I/O + widget mounting so the screen paints first
        self.call_after_refresh(self._load_initial_messages)

    def _load_initial_messages(self) -> None:
        """Parse conversation log and populate the message list."""
        messages = read_log(self._log_path) if self._log_path.exists() else []

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
        )

        # Count existing agent turns
        self._turn_count = self._count_agent_turns(messages)

        # Auto-start if mode is run or continue
        if self._mode in ("run", "continue"):
            self._start_session(self._mode)
            return

        # Restore paused state if conversation ended with a phase complete signal
        if self._session_kind == "iteration" and messages:
            self._restore_pause_state(messages)

    def _count_agent_turns(self, messages: list[dict]) -> int:
        """Count engineering agent turns (not human/system/coach)."""
        coach_name = resolve_coach_name(self.metadata.get("coach"))
        return sum(1 for msg in messages if is_agent_turn(msg, coach_name))

    def _restore_pause_state(self, messages: list[dict]) -> None:
        """Detect if the conversation was paused mid-session and restore UI state."""
        # Only look at messages in the current phase (after last boundary marker)
        phase_messages = messages
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("phase_boundary"):
                phase_messages = messages[i + 1:]
                break

        # Walk backwards past pass_turn system messages to find the real last content
        last_content_msg = None
        for msg in reversed(phase_messages):
            if not msg.get("pass_turn") and msg.get("from") != "system":
                last_content_msg = msg
                break

        if not last_content_msg:
            return

        phase = self.metadata.get("phase")

        # Detect phase complete signal (coach message ending the session)
        if last_content_msg.get("content", "").strip() == "(Phase complete signal sent.)":
            self._pause_reason = PauseReason.PHASE_COMPLETE
            self.session_state = SessionState.PAUSED
            if phase == "code-review":
                self.query_one("#action-bar", ActionBar).show(
                    "Code review complete. Press D to review diffs and merge."
                )
            else:
                self.query_one("#action-bar", ActionBar).show(
                    "Phase complete. Press P to advance, C to continue discussing."
                )
            self._pin_after_action_bar()
            return

        # Detect ask_pm (coach paused for PM input)
        ask_pm_data = last_content_msg.get("ask_pm")
        if ask_pm_data:
            self._pause_reason = PauseReason.COACH_QUESTION
            self.session_state = SessionState.PAUSED
            msg_list = self.query_one("#message-list", MessageList)
            msg_list.append_coach_prompt(ask_pm_data["question"])
            options = ask_pm_data.get("options") or []
            if options:
                from gotg.tui.modals.decision import DecisionModal
                self.app.push_screen(
                    DecisionModal(ask_pm_data["question"], options),
                    callback=self._on_decision_result,
                )
            else:
                self.query_one("#action-bar", ActionBar).show(
                    "Type reply and press Enter."
                )
            self._pin_after_action_bar()
            return

        # Detect task assignment needed (pre-code-review/implementation with unassigned tasks)
        if phase in ("pre-code-review", "implementation"):
            self._update_task_status_bar()

    # ── State machine ────────────────────────────────────────

    def watch_session_state(self, state: SessionState) -> None:
        """React to state changes by updating UI."""
        if not self.is_mounted:
            return  # Children not composed yet; on_mount handles initial state
        input_widget = self.query_one("#chat-input", Input)
        info = self.query_one("#info-tile", InfoTile)

        if state == SessionState.VIEWING:
            input_widget.placeholder = "Press R to run, C to continue..."
            input_widget.disabled = False
            info.update_session_status("")
            self.query_one("#message-list", MessageList).focus()
        elif state == SessionState.RUNNING:
            input_widget.placeholder = "Session running..."
            input_widget.disabled = True
            info.update_session_status("Running", self._turn_count)
        elif state == SessionState.PAUSED:
            input_widget.disabled = False
            if self._pause_reason == PauseReason.COACH_QUESTION:
                input_widget.placeholder = "Type reply and press Enter..."
                input_widget.focus()
            else:
                input_widget.placeholder = "Press C to continue..."
            info.update_session_status("Paused", self._turn_count)
        elif state == SessionState.COMPLETE:
            input_widget.disabled = False
            input_widget.placeholder = "Press C to continue with more turns..."
            info.update_session_status("Complete", self._turn_count)
        elif state == SessionState.ADVANCING:
            input_widget.placeholder = "Advancing phase..."
            input_widget.disabled = True
            info.update_session_status("Advancing")

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
            append_message(self._log_path, msg)
            msg_list = self.query_one("#message-list", MessageList)
            msg_list.append_message(msg)

        self.run_worker(self._run_engine, thread=True)

    def _run_engine(self) -> None:
        """Runs in worker thread. Posts EngineEvent messages to main thread."""
        try:
            from gotg.context import TeamContext
            from gotg.engine import SessionDeps, run_session
            from gotg.model import (
                agentic_completion,
                chat_completion,
                raw_completion,
                raw_completion_stream,
            )
            from gotg.session import (
                SessionSetupError,
                build_file_infra,
                load_diffs_for_review,
                resolve_layer,
                setup_worktrees,
                validate_iteration_for_run,
            )

            ctx = TeamContext.from_team_dir(self.app.team_dir)
            streaming_enabled = False

            if self._session_kind == "iteration":
                iteration, iter_dir = ctx.iteration_store.get_current()
                validate_iteration_for_run(iteration, iter_dir, ctx.agents)

                fileguard, approval_store = build_file_infra(
                    ctx.project_root, ctx.file_access, iter_dir
                )
                worktree_map, _ = setup_worktrees(
                    ctx.team_dir, ctx.agents, fileguard, None, iteration
                )
                diffs_summary, _ = load_diffs_for_review(
                    ctx.team_dir, iteration, None
                )

                # Apply approved writes and inject denials before resuming
                if approval_store:
                    from gotg.session import apply_and_inject
                    inject_msgs = apply_and_inject(
                        approval_store, fileguard, iteration,
                        self._log_path, worktree_map=worktree_map,
                    )
                    for msg in inject_msgs:
                        self.post_message(EngineEvent(AppendMessage(msg)))
                    remaining = approval_store.get_pending()
                    if remaining:
                        self.post_message(EngineEvent(
                            PauseForApprovals(pending_count=len(remaining))
                        ))
                        return

                history = read_phase_history(self._log_path)
                coach_name = ctx.coach["name"] if ctx.coach else None
                current_agent_turns = sum(
                    1 for msg in history if is_agent_turn(msg, coach_name)
                )
                max_turns = current_agent_turns + iteration.get("max_turns", 30)
                from gotg.config import load_streaming_config
                streaming_enabled = load_streaming_config(ctx.team_dir)

                from gotg.policy import iteration_policy
                policy = iteration_policy(
                    agents=ctx.agents, iteration=iteration, iter_dir=iter_dir,
                    history=history, coach=ctx.coach, fileguard=fileguard,
                    approval_store=approval_store, worktree_map=worktree_map,
                    diffs_summary=diffs_summary, max_turns_override=max_turns,
                    streaming=streaming_enabled,
                )
            else:
                # Grooming session
                from gotg.groom import load_grooming_metadata
                groom_meta, groom_dir = load_grooming_metadata(
                    self.app.team_dir, self.metadata.get("slug", "")
                )
                iteration = {
                    "id": groom_meta["slug"],
                    "description": groom_meta.get("topic", ""),
                    "phase": None,
                }
                iter_dir = groom_dir
                history = read_log(self._log_path)
                coach = ctx.coach if groom_meta.get("coach") else None

                from gotg.config import load_streaming_config as _load_streaming
                streaming_enabled = _load_streaming(ctx.team_dir)

                from gotg.policy import grooming_policy
                policy = grooming_policy(
                    agents=ctx.agents,
                    topic=groom_meta.get("topic", ""),
                    history=history,
                    coach=coach,
                    max_turns=groom_meta.get("max_turns", 30),
                    streaming=streaming_enabled,
                )

            deps = SessionDeps(
                agent_completion=agentic_completion,
                coach_completion=chat_completion,
                single_completion=raw_completion,
                stream_completion=raw_completion_stream if streaming_enabled else None,
            )

            # Route: implementation phase uses dedicated executor
            if self._session_kind == "iteration" and iteration.get("phase") == "implementation":
                import json as _json
                from gotg.implementation import run_implementation
                tasks_path = iter_dir / "tasks.json"
                tasks_data = _json.loads(tasks_path.read_text())
                current_layer = iteration.get("current_layer", 0)
                event_gen = run_implementation(
                    agents=ctx.agents, tasks=tasks_data, current_layer=current_layer,
                    iteration=iteration, iter_dir=iter_dir, model_config=ctx.model_config,
                    deps=deps, history=history, policy=policy,
                )
            else:
                event_gen = run_session(
                    agents=ctx.agents, iteration=iteration,
                    model_config=ctx.model_config, deps=deps,
                    history=history, policy=policy,
                )

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

            for event in event_gen:
                if self._cancel_requested:
                    _flush_stream_buffer()
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

                # Persist BEFORE posting to UI — if app crashes between the two,
                # message is saved but not displayed (recoverable on reload).
                persist_event(event, self._log_path, self._debug_path)
                if isinstance(event, ToolCallProgress):
                    self.post_message(ToolProgress(event))
                else:
                    self.post_message(EngineEvent(event))
                if isinstance(event, (PauseForApprovals, PhaseCompleteSignaled,
                                      CoachAskedPM, SessionComplete, LayerComplete)):
                    break

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
            participants.load_participants(event.agents, event.coach)

        elif isinstance(event, AgentTurnComplete):
            # Finalize the streaming widget with the persisted content
            if self._streaming_widget is not None:
                msg_list = self.query_one("#message-list", MessageList)
                msg_list.finalize_streaming(self._streaming_widget, event.content)
            self._streaming_widget = None
            self._streaming_turn_id = None
            self._suppress_agent_append = event.agent
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

        elif isinstance(event, PhaseCompleteSignaled):
            self._pause_reason = PauseReason.PHASE_COMPLETE
            self.session_state = SessionState.PAUSED
            if event.phase == "code-review":
                self.query_one("#action-bar", ActionBar).show(
                    "Code review complete. Press D to review diffs and merge."
                )
            else:
                self.query_one("#action-bar", ActionBar).show(
                    "Phase complete. Press P to advance, C to continue discussing."
                )
            self._pin_after_action_bar()

        elif isinstance(event, LayerComplete):
            self._pause_reason = PauseReason.PHASE_COMPLETE
            self.session_state = SessionState.PAUSED
            self.query_one("#action-bar", ActionBar).show(
                f"Layer {event.layer} complete ({len(event.completed_tasks)} tasks). "
                "Press D to review diffs and merge."
            )
            self._pin_after_action_bar()

        elif isinstance(event, TaskBlocked):
            blocked = ", ".join(event.task_ids)
            self.query_one("#action-bar", ActionBar).show(
                f"Blocked: {event.agent} -> {blocked}"
            )
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
            if event.to_phase == "pre-code-review":
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

    # ── Input handling ───────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the input widget."""
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        if self.session_state in (SessionState.PAUSED, SessionState.COMPLETE):
            self._start_session("continue", human_message=text)

    # ── Actions ──────────────────────────────────────────────

    def action_go_back(self) -> None:
        if self.session_state == SessionState.RUNNING:
            self._cancel_requested = True
            info = self.query_one("#info-tile", InfoTile)
            info.update_session_status("Cancelling...")
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
            input_widget = self.query_one("#chat-input", Input)
            text = input_widget.value.strip()
            if text:
                human_msg = text
                input_widget.value = ""
            self._start_session("continue", human_message=human_msg)

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
                checkpoint_number=result.checkpoint_number,
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
        phase = self.metadata.get("phase")
        if phase not in ("pre-code-review", "implementation"):
            return
        self._open_task_assign()

    def _open_task_assign(self) -> None:
        """Push the TaskAssignScreen."""
        from gotg.config import load_team_config
        from gotg.tui.screens.task_assign import TaskAssignScreen

        agents = load_team_config(self.app.team_dir).get("agents", [])
        self.app.push_screen(TaskAssignScreen(self.data_dir, agents))

    def _update_task_status_bar(self) -> None:
        """Update action bar with task assignment status."""
        import json

        tasks_path = self.data_dir / "tasks.json"
        bar = self.query_one("#action-bar", ActionBar)
        if not tasks_path.exists():
            bar.show("Press R to run, T to assign tasks.")
            return
        tasks = json.loads(tasks_path.read_text())
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
        if self.metadata.get("phase") not in ("implementation", "code-review"):
            return
        from gotg.context import TeamContext
        ctx = TeamContext.from_team_dir(self.app.team_dir)
        iteration, iter_dir = ctx.iteration_store.get_current()
        from gotg.tui.screens.review import ReviewScreen
        self.app.push_screen(ReviewScreen(self.app.team_dir, iteration, iter_dir))

    def on_screen_resume(self) -> None:
        """Refresh state when returning from pushed screens."""
        if self.session_state == SessionState.VIEWING:
            # Returning from TaskAssignScreen or similar
            phase = self.metadata.get("phase")
            if phase in ("pre-code-review", "implementation"):
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
                messages = read_log(self._log_path) if self._log_path.exists() else []
                msg_list = self.query_one("#message-list", MessageList)
                for m in messages[-2:]:
                    msg_list.append_message(m)
