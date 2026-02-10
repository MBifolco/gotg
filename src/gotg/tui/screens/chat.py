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
    AppendDebug,
    AppendMessage,
    CoachAskedPM,
    PauseForApprovals,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
)
from gotg.session import persist_event
from gotg.tui.messages import EngineEvent, SessionError
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.info_tile import InfoTile
from gotg.tui.widgets.message_list import MessageList


class SessionState(Enum):
    VIEWING = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETE = auto()


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
        yield Footer()

    def on_mount(self) -> None:
        # Load existing messages
        messages = read_log(self._log_path) if self._log_path.exists() else []

        msg_list = self.query_one("#message-list", MessageList)
        msg_list.load_messages(messages)

        # Enrich metadata with message count for the info tile
        enriched = {**self.metadata, "message_count": len(messages)}
        info = self.query_one("#info-tile", InfoTile)
        info.load_metadata(enriched, self.data_dir)

        # Count existing agent turns
        self._turn_count = self._count_agent_turns(messages)

        # Auto-start if mode is run or continue
        if self._mode in ("run", "continue"):
            self._start_session(self._mode)

    def _count_agent_turns(self, messages: list[dict]) -> int:
        """Count engineering agent turns (not human/system/coach)."""
        non_agent = {"human", "system"}
        coach = self.metadata.get("coach")
        if coach:
            coach_name = coach if isinstance(coach, str) else coach.get("name", "coach")
            non_agent.add(coach_name)
        return sum(1 for msg in messages if msg.get("from") not in non_agent)

    # ── State machine ────────────────────────────────────────

    def watch_session_state(self, state: SessionState) -> None:
        """React to state changes by updating UI."""
        input_widget = self.query_one("#chat-input", Input)
        info = self.query_one("#info-tile", InfoTile)

        if state == SessionState.VIEWING:
            input_widget.placeholder = "Press R to run, C to continue..."
            input_widget.disabled = False
            info.update_session_status("")
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
            self.query_one("#message-list", MessageList).append_message(msg)

        self.run_worker(self._run_engine, thread=True)

    def _run_engine(self) -> None:
        """Runs in worker thread. Posts EngineEvent messages to main thread."""
        try:
            from gotg.context import TeamContext
            from gotg.engine import SessionDeps, run_session
            from gotg.model import agentic_completion, chat_completion
            from gotg.session import (
                SessionSetupError,
                build_file_infra,
                load_diffs_for_review,
                resolve_layer,
                setup_worktrees,
                validate_iteration_for_run,
            )

            ctx = TeamContext.from_team_dir(self.app.team_dir)

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

                history = read_phase_history(self._log_path)
                # Compute additive max_turns for continue
                non_agent = {"human", "system"}
                if ctx.coach:
                    non_agent.add(ctx.coach["name"])
                current_agent_turns = sum(
                    1 for msg in history if msg.get("from") not in non_agent
                )
                max_turns = current_agent_turns + iteration.get("max_turns", 30)

                from gotg.policy import iteration_policy
                policy = iteration_policy(
                    agents=ctx.agents, iteration=iteration, iter_dir=iter_dir,
                    history=history, coach=ctx.coach, fileguard=fileguard,
                    approval_store=approval_store, worktree_map=worktree_map,
                    diffs_summary=diffs_summary, max_turns_override=max_turns,
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

                from gotg.policy import grooming_policy
                policy = grooming_policy(
                    agents=ctx.agents,
                    topic=groom_meta.get("topic", ""),
                    history=history,
                    coach=coach,
                    max_turns=groom_meta.get("max_turns", 30),
                )

            deps = SessionDeps(
                agent_completion=agentic_completion,
                coach_completion=chat_completion,
            )

            for event in run_session(
                agents=ctx.agents, iteration=iteration,
                model_config=ctx.model_config, deps=deps,
                history=history, policy=policy,
            ):
                if self._cancel_requested:
                    break
                # Persist BEFORE posting to UI — if app crashes between the two,
                # message is saved but not displayed (recoverable on reload).
                persist_event(event, self._log_path, self._debug_path)
                self.post_message(EngineEvent(event))
                if isinstance(event, (PauseForApprovals, PhaseCompleteSignaled,
                                      CoachAskedPM, SessionComplete)):
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

        elif isinstance(event, AppendMessage):
            self.query_one("#message-list", MessageList).append_message(event.msg)
            # Count agent turns (not system/human/coach)
            sender = event.msg.get("from", "")
            non_agent = {"human", "system"}
            coach = self.metadata.get("coach")
            if coach:
                coach_name = coach if isinstance(coach, str) else coach.get("name", "coach")
                non_agent.add(coach_name)
            if sender not in non_agent:
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
                "Manage approvals in CLI, then press C to continue."
            )

        elif isinstance(event, CoachAskedPM):
            self._pause_reason = PauseReason.COACH_QUESTION
            self.session_state = SessionState.PAUSED
            self.query_one("#action-bar", ActionBar).show(
                f"Coach asks: {event.question}"
            )

        elif isinstance(event, PhaseCompleteSignaled):
            self._pause_reason = PauseReason.PHASE_COMPLETE
            self.session_state = SessionState.PAUSED
            self.query_one("#action-bar", ActionBar).show(
                "Phase complete. Press C to continue discussing."
            )

        elif isinstance(event, SessionComplete):
            self.session_state = SessionState.COMPLETE
            self.query_one("#action-bar", ActionBar).show(
                f"Session complete ({event.total_turns} turns). "
                "Press C to continue with more turns."
            )

    def on_session_error(self, message: SessionError) -> None:
        """Handle worker thread errors."""
        self.session_state = SessionState.VIEWING
        self.notify(f"Session error: {message.error}", severity="error")

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
