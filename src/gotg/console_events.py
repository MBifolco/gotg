"""Shared console event rendering for CLI and exploration adapters.

Adapter-only module: rendering and printing. No persistence, no config writes.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Callable

from gotg.conversation import render_message
from gotg.events import (
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

if TYPE_CHECKING:
    from gotg.pause import PauseController


def print_session_header(event: SessionStarted) -> None:
    """Print conversation session header from SessionStarted event."""
    print(f"Starting conversation: {event.iteration_id}")
    print(f"Task: {event.description}")
    if event.current_layer is not None:
        print(f"Phase: {event.phase} (layer {event.current_layer})")
    else:
        print(f"Phase: {event.phase}")
    if event.coach:
        print(f"Coach: {event.coach} (facilitating)")
    if event.has_file_tools:
        print(f"File tools: enabled (writable: {event.writable_paths or 'none'})")
    if event.worktree_count:
        print(f"Worktrees: {event.worktree_count} active")
    print(f"Turns: {event.turn}/{event.max_turns}")
    print("---")


def print_phase_complete(phase: str | None) -> None:
    """Print phase-specific completion message."""
    from gotg.iteration_store import PHASE_ORDER

    from gotg.phases import get_phase_caps_safe
    caps = get_phase_caps_safe(phase)

    print("---")
    if caps.phase_complete_shows_review_hint:
        print("Coach signals code review complete.")
        print("Next: `gotg review` to inspect diffs, `gotg merge all` to merge, then `gotg next-layer`.")
    elif phase == PHASE_ORDER[-1]:
        print("Coach signals phase complete. This is the final phase — iteration is done.")
        print("Run `gotg continue` to keep discussing if needed.")
    else:
        print("Coach recommends advancing. Run `gotg advance` to proceed, or `gotg continue` to keep discussing.")


def print_tool_progress(event: ToolCallProgress) -> None:
    """Print tool call progress to stderr."""
    if event.status == "error":
        print(f"  [{event.agent}] {event.tool_name} {event.path} FAIL", file=sys.stderr)
    elif event.status == "pending_approval":
        print(f"  [{event.agent}] {event.tool_name} {event.path} PENDING", file=sys.stderr)
    elif event.tool_name == "file_write" and event.bytes:
        print(f"  [{event.agent}] {event.tool_name} {event.path} ({event.bytes}b)", file=sys.stderr)
    elif event.tool_name == "complete_tasks":
        print(f"  [{event.agent}] complete_tasks", file=sys.stderr)
    elif event.tool_name == "report_blocked":
        print(f"  [{event.agent}] report_blocked", file=sys.stderr)
    else:
        print(f"  [{event.agent}] {event.tool_name} {event.path}", file=sys.stderr)


def _is_turn_boundary(msg: dict, coach_name: str | None) -> bool:
    """Return True if msg represents a turn boundary (agent turn or pass_turn).

    Inline helper — NO import from tui.helpers (which depends on textual).
    """
    if msg.get("pass_turn"):
        return True
    sender = msg.get("from", "")
    if sender in ("system", "human"):
        return False
    if coach_name and sender == coach_name:
        return False
    return True


_TERMINAL_EVENTS = (
    PauseForApprovals, PhaseCompleteSignaled, CoachAskedPM,
    IterationsProposed, SessionComplete, LayerComplete, UserPauseComplete,
)


def handle_console_events(
    events,
    *,
    on_started: Callable[[SessionStarted], None] | None = None,
    resume_hint: str = "gotg continue",
    summarize_hint: str | None = None,
    complete_label: str = "Conversation",
    use_implementation: bool = False,
    pause_controller: PauseController | None = None,
) -> str | None:
    """Unified console event handler for CLI and exploration.

    Args:
        events: Iterator of engine/implementation events (from run_and_persist).
        on_started: Custom SessionStarted callback (default: print_session_header).
        resume_hint: Command prefix for CoachAskedPM resume messages.
        complete_label: Label for SessionComplete message (ignored when use_implementation=True).
        use_implementation: True for implementation phase (changes SessionComplete message).
        pause_controller: If provided, enables cooperative pause handling.

    Returns:
        "paused" if session was paused by user, None otherwise.
    """
    _suppress_agent_append: str | None = None
    _coach_name: str | None = None
    _pause_pending = False

    try:
        for event in events:
            # Deferred pause: if pause was pending from previous iteration,
            # check what came next. Terminal events win over pause.
            if _pause_pending:
                if isinstance(event, _TERMINAL_EVENTS):
                    _pause_pending = False
                    # Fall through — terminal event wins
                else:
                    return "paused"

            if isinstance(event, SessionStarted):
                _coach_name = event.coach
                if on_started:
                    on_started(event)
                else:
                    print_session_header(event)
            elif isinstance(event, TextDelta):
                sys.stdout.write(event.text)
                sys.stdout.flush()
            elif isinstance(event, AgentTurnComplete):
                sys.stdout.write("\n\n")
                sys.stdout.flush()
                _suppress_agent_append = event.agent
            elif isinstance(event, ToolCallProgress):
                print_tool_progress(event)
            elif isinstance(event, (AppendMessage, AppendDebug)):
                # Already persisted by run_and_persist — display only
                if isinstance(event, AppendMessage):
                    if _suppress_agent_append and event.msg.get("from") == _suppress_agent_append:
                        _suppress_agent_append = None
                    else:
                        print(render_message(event.msg))
                        print()

                    # Discussion pause: check turn boundary after AppendMessage
                    if (not use_implementation
                            and pause_controller
                            and _is_turn_boundary(event.msg, _coach_name)
                            and pause_controller.is_pause_requested()):
                        _pause_pending = True
                        continue
            elif isinstance(event, UserPauseComplete):
                # Implementation pause — terminal event
                print("---")
                print(f"Paused ({event.total_turns} agent(s) dispatched).")
                return "paused"
            elif isinstance(event, PauseForApprovals):
                print("---")
                print(f"Paused: {event.pending_count} pending approval(s).")
                print("Run 'gotg approvals' to review, then 'gotg approve <id>' or 'gotg deny <id> -m reason'.")
                print("Resume with 'gotg continue'.")
                break
            elif isinstance(event, PhaseCompleteSignaled):
                from gotg.phases import get_phase_caps_safe
                caps = get_phase_caps_safe(event.phase)
                print("---")
                if caps.phase_complete_shows_review_hint:
                    if event.outcome == "changes_requested":
                        print("Coach signals rework needed.")
                        print("Next: `gotg review` to view diffs, or `gotg rework` to send feedback back to implementation.")
                    else:
                        print("Coach signals code review approved.")
                        print("Next: `gotg review` to inspect diffs, then `gotg merge all` + `gotg next-layer`.")
                else:
                    print("Coach recommends advancing. Run `gotg advance` to proceed, or `gotg continue` to keep discussing.")
                break
            elif isinstance(event, IterationsProposed):
                print("---")
                print(f"Coach proposes {len(event.proposals)} iteration(s):")
                print()
                for i, p in enumerate(event.proposals, 1):
                    action_label = "NEW" if p["action"] == "create" else f"UPDATE {p.get('iteration_id', '?')}"
                    print(f"  [{action_label}] {p['title']}")
                    for line in p["description"].split("\n"):
                        print(f"    {line}")
                    print()
                if event.rationale:
                    print(f"  Rationale: {event.rationale}")
                    print()
                print(f"To approve: {resume_hint} --approve-iterations")
                print(f"To give feedback: {resume_hint} -m 'your feedback'")
                break
            elif isinstance(event, CoachAskedPM):
                print("---")
                print(f"Coach asks: {event.question}")
                if event.options:
                    for i, option in enumerate(event.options, 1):
                        print(f"  {i}. {option}")
                    print(f"  {len(event.options) + 1}. None of these (send a message)")
                    print(f"Reply with: {resume_hint} -m '<number or message>'")
                else:
                    print(f"Reply with: {resume_hint} -m 'your answer'")
                break
            elif isinstance(event, TaskBlocked):
                print("---")
                blocked = ", ".join(event.task_ids)
                print(f"Blocked by {event.agent} (layer {event.layer}): {blocked}")
                print(f"Reason: {event.reason}")
            elif isinstance(event, LayerComplete):
                print("---")
                print(f"Layer {event.layer} complete ({len(event.completed_tasks)} tasks).")
                print("Run `gotg advance` to begin code review.")
                break
            elif isinstance(event, SessionComplete):
                print("---")
                if use_implementation:
                    print(f"Implementation session complete ({event.total_turns} agent(s) dispatched).")
                else:
                    print(f"{complete_label} complete ({event.total_turns} turns)")
                    if summarize_hint:
                        print(f"Run `{summarize_hint}` to generate a summary.")
            else:
                raise AssertionError(f"Unhandled event: {event!r}")

    except KeyboardInterrupt:
        if pause_controller:
            return "paused"
        raise

    # If pause was pending at end of events (no terminal event followed), return paused
    if _pause_pending:
        return "paused"

    return None
