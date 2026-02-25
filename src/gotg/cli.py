import argparse
import sys
from pathlib import Path

from gotg.engine import SessionDeps
from gotg.console_events import handle_console_events
from gotg.model import chat_completion, agentic_completion, raw_completion, raw_completion_stream


def find_team_dir(cwd: Path) -> Path | None:
    team = cwd / ".team"
    if team.is_dir():
        return team
    return None


def _auto_checkpoint(iter_dir: Path, iteration: dict, coach_name: str = "coach") -> None:
    """Create an automatic checkpoint after a command completes."""
    from gotg.checkpoint import create_checkpoint
    try:
        number = create_checkpoint(iter_dir, iteration, trigger="auto", coach_name=coach_name)
        print(f"Checkpoint {number} created (auto)")
    except Exception as e:
        print(f"Warning: auto-checkpoint failed: {e}", file=sys.stderr)


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
) -> None:
    from gotg.session import prepare_session, run_and_persist

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

    handle_console_events(
        run_and_persist(setup),
        use_implementation=setup.use_implementation,
    )


# ── Re-exports for external compatibility ──────────────────────────
# These were importable from gotg.cli before the commands/ split.
# Lazy to avoid circular imports (command modules do `import gotg.cli as _cli`).

def __getattr__(name):
    _reexports = {
        "cmd_init": ("gotg.commands.admin", "cmd_init"),
        "cmd_model": ("gotg.commands.admin", "cmd_model"),
        "cmd_show": ("gotg.commands.admin", "cmd_show"),
        "cmd_checkpoint": ("gotg.commands.admin", "cmd_checkpoint"),
        "cmd_checkpoints": ("gotg.commands.admin", "cmd_checkpoints"),
        "cmd_restore": ("gotg.commands.admin", "cmd_restore"),
        "cmd_approvals": ("gotg.commands.admin", "cmd_approvals"),
        "cmd_approve": ("gotg.commands.admin", "cmd_approve"),
        "cmd_deny": ("gotg.commands.admin", "cmd_deny"),
        "cmd_ui": ("gotg.commands.admin", "cmd_ui"),
        "PROVIDER_PRESETS": ("gotg.commands.admin", "PROVIDER_PRESETS"),
        "cmd_run": ("gotg.commands.run", "cmd_run"),
        "cmd_continue": ("gotg.commands.run", "cmd_continue"),
        "cmd_advance": ("gotg.commands.advance", "cmd_advance"),
        "cmd_next_layer": ("gotg.commands.advance", "cmd_next_layer"),
        "cmd_review": ("gotg.commands.review", "cmd_review"),
        "cmd_merge": ("gotg.commands.review", "cmd_merge"),
        "cmd_worktrees": ("gotg.commands.review", "cmd_worktrees"),
        "cmd_commit_worktrees": ("gotg.commands.review", "cmd_commit_worktrees"),
        "cmd_groom_start": ("gotg.commands.groom", "cmd_groom_start"),
        "cmd_groom_continue": ("gotg.commands.groom", "cmd_groom_continue"),
        "cmd_groom_list": ("gotg.commands.groom", "cmd_groom_list"),
        "cmd_groom_show": ("gotg.commands.groom", "cmd_groom_show"),
    }
    if name in _reexports:
        module_path, attr = _reexports[name]
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module 'gotg.cli' has no attribute {name!r}")


def main():
    parser = argparse.ArgumentParser(prog="gotg", description="AI SCRUM team tool")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize a new .team/ directory")
    init_parser.add_argument("path", nargs="?", default=".", help="Project path (default: current directory)")

    run_parser = subparsers.add_parser("run", help="Run the agent conversation")
    run_parser.add_argument("--max-turns", type=int, help="Override max_turns from iteration.json")
    run_parser.add_argument("--layer", type=int, default=None, help="Worktree layer (default: current layer)")

    subparsers.add_parser("show", help="Show the conversation log")

    continue_parser = subparsers.add_parser("continue", help="Continue the conversation with optional human input")
    continue_parser.add_argument("-m", "--message", help="Human message to inject before continuing")
    continue_parser.add_argument("--max-turns", type=int, help="Number of new agent turns to run")
    continue_parser.add_argument("--layer", type=int, default=None, help="Worktree layer (default: current layer)")

    subparsers.add_parser("advance", help="Advance the current iteration to the next phase")

    cp_parser = subparsers.add_parser("checkpoint", help="Create a manual checkpoint")
    cp_parser.add_argument("description", nargs="?", default=None, help="Checkpoint description")

    subparsers.add_parser("checkpoints", help="List checkpoints for current iteration")

    restore_parser = subparsers.add_parser("restore", help="Restore iteration to a checkpoint")
    restore_parser.add_argument("number", type=int, help="Checkpoint number to restore")

    model_parser = subparsers.add_parser("model", help="View or change model config")
    model_parser.add_argument("provider", nargs="?", help="Provider preset: anthropic, openai, ollama")
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

    commit_wt_parser = subparsers.add_parser("commit-worktrees", help="Commit all dirty worktrees")
    commit_wt_parser.add_argument("-m", "--message", help="Commit message (default: 'Agent implementation work')")

    # Groom subcommand family
    groom_parser = subparsers.add_parser("groom", help="Freeform grooming conversations")
    groom_sub = groom_parser.add_subparsers(dest="groom_command")

    groom_start = groom_sub.add_parser("start", help="Start a new grooming conversation")
    groom_start.add_argument("topic", help="Topic to explore")
    groom_start.add_argument("--slug", help="Override auto-generated slug")
    groom_start.add_argument("--coach", action="store_true", help="Enable coach facilitation")
    groom_start.add_argument("--max-turns", type=int, help="Max turns (default: 30)")

    groom_continue = groom_sub.add_parser("continue", help="Continue a grooming conversation")
    groom_continue.add_argument("slug", help="Session slug")
    groom_continue.add_argument("-m", "--message", help="Human message to inject")
    groom_continue.add_argument("--max-turns", type=int, help="Additional turns to run")

    groom_sub.add_parser("list", help="List grooming sessions")

    groom_show = groom_sub.add_parser("show", help="Show grooming conversation")
    groom_show.add_argument("slug", help="Session slug")

    subparsers.add_parser("ui", help="Launch interactive TUI")

    args = parser.parse_args()

    if args.command == "init":
        from gotg.commands.admin import cmd_init
        cmd_init(args)
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
    elif args.command == "checkpoint":
        from gotg.commands.admin import cmd_checkpoint
        cmd_checkpoint(args)
    elif args.command == "checkpoints":
        from gotg.commands.admin import cmd_checkpoints
        cmd_checkpoints(args)
    elif args.command == "restore":
        from gotg.commands.admin import cmd_restore
        cmd_restore(args)
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
    elif args.command == "commit-worktrees":
        from gotg.commands.review import cmd_commit_worktrees
        cmd_commit_worktrees(args)
    elif args.command == "groom":
        if args.groom_command == "start":
            from gotg.commands.groom import cmd_groom_start
            cmd_groom_start(args)
        elif args.groom_command == "continue":
            from gotg.commands.groom import cmd_groom_continue
            cmd_groom_continue(args)
        elif args.groom_command == "list":
            from gotg.commands.groom import cmd_groom_list
            cmd_groom_list(args)
        elif args.groom_command == "show":
            from gotg.commands.groom import cmd_groom_show
            cmd_groom_show(args)
        else:
            groom_parser.print_help()
    elif args.command == "ui":
        from gotg.commands.admin import cmd_ui
        cmd_ui(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
