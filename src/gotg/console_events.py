"""Shared console event rendering for CLI and grooming adapters.

Adapter-only module: rendering and printing. No persistence, no config writes.
"""

from __future__ import annotations

import sys
from typing import Callable

from gotg.conversation import render_message
from gotg.events import (
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
    from gotg.config import PHASE_ORDER

    print("---")
    if phase == "code-review":
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


def handle_console_events(
    events,
    *,
    on_started: Callable[[SessionStarted], None] | None = None,
    resume_hint: str = "gotg continue",
    complete_label: str = "Conversation",
    use_implementation: bool = False,
) -> None:
    """Unified console event handler for CLI and grooming.

    Args:
        events: Iterator of engine/implementation events (from run_and_persist).
        on_started: Custom SessionStarted callback (default: print_session_header).
        resume_hint: Command prefix for CoachAskedPM resume messages.
        complete_label: Label for SessionComplete message (ignored when use_implementation=True).
        use_implementation: True for implementation phase (changes SessionComplete message).
    """
    _suppress_agent_append: str | None = None

    for event in events:
        if isinstance(event, SessionStarted):
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
        elif isinstance(event, PauseForApprovals):
            print("---")
            print(f"Paused: {event.pending_count} pending approval(s).")
            print("Run 'gotg approvals' to review, then 'gotg approve <id>' or 'gotg deny <id> -m reason'.")
            print("Resume with 'gotg continue'.")
            break
        elif isinstance(event, PhaseCompleteSignaled):
            print_phase_complete(event.phase)
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
            print("Run `gotg merge all` then `gotg next-layer`.")
            break
        elif isinstance(event, SessionComplete):
            print("---")
            if use_implementation:
                print(f"Implementation session complete ({event.total_turns} agent(s) dispatched).")
            else:
                print(f"{complete_label} complete ({event.total_turns} turns)")
        else:
            raise AssertionError(f"Unhandled event: {event!r}")
