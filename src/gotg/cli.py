"""CLI entrypoint — argument parsing, subcommand dispatch, session bridge.

Defines the argparse tree for all gotg commands. run_conversation bridges
CLI to the engine: builds SessionDeps, calls run_session via run_and_persist,
passes events to handle_console_events. Thin layer — no business logic.
"""

import argparse
import sys
from pathlib import Path

from gotg.engine import SessionDeps
from gotg.errors import GotgError
from gotg.events import PhaseCompleteSignaled
from gotg.console_events import handle_console_events
from gotg.model import chat_completion, agentic_completion, raw_completion, raw_completion_stream


def find_team_dir(cwd: Path) -> Path | None:
    team = cwd / ".team"
    if team.is_dir():
        return team
    return None


def run_conversation(
    iter_dir: Path,
    agents: list[dict],
    iteration: dict,
    model_config: dict,
    max_turns_override: int | None = None,
    coach: dict | None = None,
    fileguard=None,
    approval_store=None,
    worktree_map: dict | None = None,
    diffs_summary: str | None = None,
    streaming: bool = False,
    model_resolver=None,
    pause_controller=None,
) -> str | None:
    from gotg.session_setup import prepare_session, run_and_persist

    # Build deps from module-level imports (bridge pattern — preserves mock targets)
    deps = SessionDeps(
        agent_completion=agentic_completion,
        coach_completion=chat_completion,
        single_completion=raw_completion,
        stream_completion=raw_completion_stream,
        model_resolver=model_resolver,
    )

    setup = prepare_session(
        iter_dir, agents, iteration, model_config, deps,
        max_turns_override=max_turns_override, coach=coach,
        fileguard=fileguard, approval_store=approval_store,
        worktree_map=worktree_map, diffs_summary=diffs_summary,
        streaming=streaming,
    )

    # Wire cancel_check for implementation-mode pause
    if pause_controller:
        setup.cancel_check = pause_controller.is_pause_requested

    team_dir = iter_dir.parent.parent  # .team/iterations/iter-N → .team

    def _persist_outcome(events):
        """Wrapper: persist review_outcome on PhaseCompleteSignaled, then yield."""
        for event in events:
            if isinstance(event, PhaseCompleteSignaled):
                from gotg.phases import get_phase_caps_safe
                caps = get_phase_caps_safe(event.phase)
                if caps.phase_complete_shows_review_hint:
                    from gotg.iteration_store import save_iteration_fields
                    save_iteration_fields(team_dir, iteration["id"], review_outcome=event.outcome)
            yield event

    if pause_controller:
        pause_controller.install()
    try:
        return handle_console_events(
            _persist_outcome(run_and_persist(setup)),
            use_implementation=setup.use_implementation,
            pause_controller=pause_controller,
        )
    finally:
        if pause_controller:
            pause_controller.uninstall()


def main():
    parser = argparse.ArgumentParser(prog="gotg", description="AI SCRUM team tool")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize a new .team/ directory")
    init_parser.add_argument("path", nargs="?", default=".", help="Project path (default: current directory)")

    new_parser = subparsers.add_parser("new", help="Create a new iteration")
    new_parser.add_argument("description", help="Iteration description")

    run_parser = subparsers.add_parser("run", help="Run the agent conversation")
    run_parser.add_argument("-i", "--iteration", help="Switch to this iteration before running")
    run_parser.add_argument("--max-turns", type=int, help="Override max_turns from iteration.json")
    run_parser.add_argument("--layer", type=int, default=None, help="Worktree layer (default: current layer)")

    subparsers.add_parser("show", help="Show the conversation log")

    continue_parser = subparsers.add_parser("continue", help="Continue the conversation with optional human input")
    continue_parser.add_argument("-i", "--iteration", help="Switch to this iteration before continuing")
    continue_parser.add_argument("-m", "--message", help="Human message to inject before continuing")
    continue_parser.add_argument("--max-turns", type=int, help="Number of new agent turns to run")
    continue_parser.add_argument("--layer", type=int, default=None, help="Worktree layer (default: current layer)")

    subparsers.add_parser("advance", help="Advance the current iteration to the next phase")

    model_parser = subparsers.add_parser("model", help="View or change model config")
    from gotg.providers import PROVIDERS
    model_parser.add_argument("provider", nargs="?",
        help=f"Provider preset: {', '.join(PROVIDERS)}")
    model_parser.add_argument("model_name", nargs="?", help="Model name (overrides preset default)")

    subparsers.add_parser("approvals", help="Show pending approval requests")

    approve_parser = subparsers.add_parser("approve", help="Approve a pending file write request")
    approve_parser.add_argument("request_id", help="Approval request ID (e.g., 'a1') or 'all'")

    deny_parser = subparsers.add_parser("deny", help="Deny a pending file write request")
    deny_parser.add_argument("request_id", help="Approval request ID (e.g., 'a1')")
    deny_parser.add_argument("-m", "--message", help="Denial reason")

    review_parser = subparsers.add_parser("review", help="Review agent diffs against main")
    review_parser.add_argument("--layer", type=int, default=None, help="Layer to review (default: current layer)")
    review_parser.add_argument("--stat-only", action="store_true", help="Show only file stats, not full diff")
    review_parser.add_argument("branch", nargs="?", default=None, help="Specific branch to review")

    merge_parser = subparsers.add_parser("merge", help="Merge an agent branch into main")
    merge_parser.add_argument("branch", nargs="?", default=None, help="Branch name or 'all'")
    merge_parser.add_argument("--layer", type=int, default=None, help="Layer for 'merge all' (default: current layer)")
    merge_parser.add_argument("--abort", action="store_true", help="Abort in-progress merge")
    merge_parser.add_argument("--force", action="store_true", help="(no-op, dirty worktrees are auto-committed)")

    subparsers.add_parser("worktrees", help="List active git worktrees")

    subparsers.add_parser("next-layer", help="Advance to the next task layer after merging")

    subparsers.add_parser("rework", help="Send tasks back for rework based on review feedback")

    commit_wt_parser = subparsers.add_parser("commit-worktrees", help="Commit all dirty worktrees")
    commit_wt_parser.add_argument("-m", "--message", help="Commit message (default: 'Agent implementation work')")

    explore_parser = subparsers.add_parser("explore", help="Freeform exploration conversations")
    explore_sub = explore_parser.add_subparsers(dest="explore_command")

    explore_start = explore_sub.add_parser("start", help="Start a new exploration conversation")
    explore_start.add_argument("topic", help="Topic to explore")
    explore_start.add_argument("--slug", help="Override auto-generated slug")
    explore_start.add_argument("--coach", action="store_true", help="Enable coach facilitation")
    explore_start.add_argument("--max-turns", type=int, help="Max turns (default: 30)")
    explore_context_group = explore_start.add_mutually_exclusive_group()
    explore_context_group.add_argument("--context-from", help="Iteration ID to load context from")
    explore_context_group.add_argument("--no-context", action="store_true", help="Skip iteration context injection")

    explore_continue = explore_sub.add_parser("continue", help="Continue an exploration conversation")
    explore_continue.add_argument("slug", help="Session slug")
    explore_continue_action = explore_continue.add_mutually_exclusive_group()
    explore_continue_action.add_argument("--approve-iterations", action="store_true",
                                         help="Apply pending iteration proposals")
    explore_continue_action.add_argument("-m", "--message", help="Human message to inject")
    explore_continue.add_argument("--max-turns", type=int, help="Additional turns to run")

    explore_sub.add_parser("list", help="List exploration sessions")

    explore_show = explore_sub.add_parser("show", help="Show exploration conversation")
    explore_show.add_argument("slug", help="Session slug")

    explore_summarize = explore_sub.add_parser("summarize", help="Generate a summary of an exploration conversation")
    explore_summarize.add_argument("slug", help="Session slug")

    subparsers.add_parser("ui", help="Launch interactive TUI")

    args = parser.parse_args()

    try:
        if args.command == "init":
            from gotg.commands.admin import cmd_init
            cmd_init(args)
        elif args.command == "new":
            from gotg.commands.admin import cmd_new
            cmd_new(args)
        elif args.command == "run":
            from gotg.commands.run import cmd_run
            cmd_run(args)
        elif args.command == "show":
            from gotg.commands.admin import cmd_show
            cmd_show(args)
        elif args.command == "continue":
            from gotg.commands.run import cmd_continue
            cmd_continue(args)
        elif args.command == "model":
            from gotg.commands.admin import cmd_model
            cmd_model(args)
        elif args.command == "advance":
            from gotg.commands.advance import cmd_advance
            cmd_advance(args)
        elif args.command == "approvals":
            from gotg.commands.admin import cmd_approvals
            cmd_approvals(args)
        elif args.command == "approve":
            from gotg.commands.admin import cmd_approve
            cmd_approve(args)
        elif args.command == "deny":
            from gotg.commands.admin import cmd_deny
            cmd_deny(args)
        elif args.command == "review":
            from gotg.commands.review import cmd_review
            cmd_review(args)
        elif args.command == "merge":
            if not args.abort and args.branch is None:
                parser.error("merge requires a branch name or 'all' (or use --abort)")
            from gotg.commands.review import cmd_merge
            cmd_merge(args)
        elif args.command == "worktrees":
            from gotg.commands.review import cmd_worktrees
            cmd_worktrees(args)
        elif args.command == "next-layer":
            from gotg.commands.advance import cmd_next_layer
            cmd_next_layer(args)
        elif args.command == "rework":
            from gotg.commands.advance import cmd_rework
            cmd_rework(args)
        elif args.command == "commit-worktrees":
            from gotg.commands.review import cmd_commit_worktrees
            cmd_commit_worktrees(args)
        elif args.command == "explore":
            if args.explore_command == "start":
                from gotg.commands.explore import cmd_explore_start
                cmd_explore_start(args)
            elif args.explore_command == "continue":
                from gotg.commands.explore import cmd_explore_continue
                cmd_explore_continue(args)
            elif args.explore_command == "list":
                from gotg.commands.explore import cmd_explore_list
                cmd_explore_list(args)
            elif args.explore_command == "show":
                from gotg.commands.explore import cmd_explore_show
                cmd_explore_show(args)
            elif args.explore_command == "summarize":
                from gotg.commands.explore import cmd_explore_summarize
                cmd_explore_summarize(args)
            else:
                explore_parser.print_help()
        elif args.command == "ui":
            from gotg.commands.admin import cmd_ui
            cmd_ui(args)
        else:
            parser.print_help()
    except GotgError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
