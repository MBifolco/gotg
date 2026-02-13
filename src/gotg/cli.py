import argparse
import os
import sys
from pathlib import Path

from gotg.checkpoint import create_checkpoint, list_checkpoints, restore_checkpoint
from gotg.config import (
    load_agents, load_coach, load_model_config, load_file_access,
    load_worktree_config, ensure_dotenv_key, read_dotenv,
    get_current_iteration, save_model_config,
    save_iteration_phase, save_iteration_fields, PHASE_ORDER,
)
from gotg.context import TeamContext
from gotg.conversation import append_message, append_debug, read_log, read_phase_history, render_message
from gotg.engine import SessionDeps, run_session
from gotg.events import (
    AgentTurnComplete, AppendDebug, AppendMessage, CoachAskedPM,
    LayerComplete, PauseForApprovals, PhaseCompleteSignaled,
    SessionComplete, SessionStarted, TaskBlocked, TextDelta, ToolCallProgress,
)
from gotg.model import chat_completion, agentic_completion, raw_completion, raw_completion_stream
from gotg.groom import (
    generate_slug, validate_slug, existing_slugs,
    write_grooming_metadata, load_grooming_metadata,
    list_grooming_sessions, run_grooming_conversation,
)
from gotg.scaffold import init_project
from gotg.session import (
    SessionSetupError, persist_event, resolve_layer, validate_iteration_for_run,
    build_file_infra, setup_worktrees, load_diffs_for_review,
)
from gotg.transitions import (
    extract_refinement_summary, extract_tasks, extract_task_notes,
    auto_commit_layer_worktrees, build_transition_messages,
)


def find_team_dir(cwd: Path) -> Path | None:
    team = cwd / ".team"
    if team.is_dir():
        return team
    return None


def _auto_checkpoint(iter_dir: Path, iteration: dict, coach_name: str = "coach") -> None:
    """Create an automatic checkpoint after a command completes."""
    try:
        number = create_checkpoint(iter_dir, iteration, trigger="auto", coach_name=coach_name)
        print(f"Checkpoint {number} created (auto)")
    except Exception as e:
        print(f"Warning: auto-checkpoint failed: {e}", file=sys.stderr)


def _print_session_header(event: SessionStarted) -> None:
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


def _print_phase_complete(phase: str | None) -> None:
    """Print phase-specific completion message."""
    print("---")
    if phase == "code-review":
        print("Coach signals code review complete.")
        print("Next: `gotg review` to inspect diffs, `gotg merge all` to merge, then `gotg next-layer`.")
    elif phase == PHASE_ORDER[-1]:
        print("Coach signals phase complete. This is the final phase — iteration is done.")
        print("Run `gotg continue` to keep discussing if needed.")
    else:
        print("Coach recommends advancing. Run `gotg advance` to proceed, or `gotg continue` to keep discussing.")


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
) -> None:
    log_path = iter_dir / "conversation.jsonl"
    debug_path = iter_dir / "debug.jsonl"
    history = read_phase_history(log_path)

    # Build deps from module-level imports (bridge pattern — preserves mock targets)
    deps = SessionDeps(
        agent_completion=agentic_completion,
        coach_completion=chat_completion,
        single_completion=raw_completion,
        stream_completion=raw_completion_stream,
    )

    # Build policy from iteration state (factory exercised in production)
    from gotg.policy import iteration_policy
    policy = iteration_policy(
        agents=agents, iteration=iteration, iter_dir=iter_dir,
        history=history, coach=coach, fileguard=fileguard,
        approval_store=approval_store, worktree_map=worktree_map,
        diffs_summary=diffs_summary, max_turns_override=max_turns_override,
        streaming=streaming,
    )

    # Route to implementation executor or discussion engine
    # Implementation executor requires tasks.json + single_completion
    tasks_path = iter_dir / "tasks.json"
    use_impl = (
        iteration.get("phase") == "implementation"
        and tasks_path.exists()
        and deps.single_completion is not None
    )
    if use_impl:
        _run_implementation_phase(
            agents, iteration, iter_dir, model_config, deps, history, policy,
            log_path, debug_path,
        )
    else:
        _run_discussion_phase(
            agents, iteration, model_config, deps, history, policy,
            log_path, debug_path,
        )


def _run_discussion_phase(
    agents, iteration, model_config, deps, history, policy,
    log_path, debug_path,
):
    """Handle discussion phases (refinement, planning, pre-code-review, code-review)."""
    _suppress_agent_append: str | None = None  # agent name to suppress

    for event in run_session(
        agents=agents, iteration=iteration, model_config=model_config,
        deps=deps, history=history, policy=policy,
    ):
        if isinstance(event, SessionStarted):
            _print_session_header(event)
        elif isinstance(event, TextDelta):
            sys.stdout.write(event.text)
            sys.stdout.flush()
        elif isinstance(event, AgentTurnComplete):
            sys.stdout.write("\n\n")
            sys.stdout.flush()
            _suppress_agent_append = event.agent
        elif isinstance(event, ToolCallProgress):
            _print_tool_progress(event)
        elif isinstance(event, (AppendMessage, AppendDebug)):
            persist_event(event, log_path, debug_path)
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
            _print_phase_complete(event.phase)
            break
        elif isinstance(event, CoachAskedPM):
            print("---")
            print(f"Coach asks: {event.question}")
            if event.options:
                for i, option in enumerate(event.options, 1):
                    print(f"  {i}. {option}")
                print(f"  {len(event.options) + 1}. None of these (send a message)")
                print("Reply with: gotg continue -m '<number or message>'")
            else:
                print("Reply with: gotg continue -m 'your answer'")
            break
        elif isinstance(event, SessionComplete):
            print("---")
            print(f"Conversation complete ({event.total_turns} turns)")
        else:
            raise AssertionError(f"Unhandled event: {event!r}")


def _print_tool_progress(event: ToolCallProgress) -> None:
    """Print tool call progress to stderr."""
    import sys
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


def _run_implementation_phase(
    agents, iteration, iter_dir, model_config, deps, history, policy,
    log_path, debug_path,
):
    """Handle implementation phase with dedicated executor."""
    import json
    from gotg.implementation import run_implementation

    tasks_path = iter_dir / "tasks.json"
    tasks_data = json.loads(tasks_path.read_text())
    current_layer = iteration.get("current_layer", 0)

    # Track streaming state to suppress double-printing
    _suppress_agent_append: str | None = None

    for event in run_implementation(
        agents=agents, tasks=tasks_data, current_layer=current_layer,
        iteration=iteration, iter_dir=iter_dir, model_config=model_config,
        deps=deps, history=history, policy=policy,
    ):
        if isinstance(event, SessionStarted):
            _print_session_header(event)
        elif isinstance(event, TextDelta):
            sys.stdout.write(event.text)
            sys.stdout.flush()
        elif isinstance(event, AgentTurnComplete):
            sys.stdout.write("\n\n")
            sys.stdout.flush()
            _suppress_agent_append = event.agent
        elif isinstance(event, (AppendMessage, AppendDebug)):
            persist_event(event, log_path, debug_path)
            if isinstance(event, AppendMessage):
                if _suppress_agent_append and event.msg.get("from") == _suppress_agent_append:
                    _suppress_agent_append = None
                else:
                    print(render_message(event.msg))
                    print()
        elif isinstance(event, ToolCallProgress):
            _print_tool_progress(event)
        elif isinstance(event, TaskBlocked):
            print("---")
            blocked = ", ".join(event.task_ids)
            print(f"Blocked by {event.agent} (layer {event.layer}): {blocked}")
            print(f"Reason: {event.reason}")
        elif isinstance(event, PauseForApprovals):
            print("---")
            print(f"Paused: {event.pending_count} pending approval(s).")
            print("Run 'gotg approvals' to review, then 'gotg approve <id>' or 'gotg deny <id> -m reason'.")
            print("Resume with 'gotg continue'.")
            break
        elif isinstance(event, LayerComplete):
            print("---")
            print(f"Layer {event.layer} complete ({len(event.completed_tasks)} tasks).")
            print("Run `gotg merge all` then `gotg next-layer`.")
            break
        elif isinstance(event, SessionComplete):
            print("---")
            print(f"Implementation session complete ({event.total_turns} agent(s) dispatched).")
        else:
            raise AssertionError(f"Unhandled event: {event!r}")


def cmd_init(args):
    path = Path(args.path)
    init_project(path)


def cmd_run(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    ctx = TeamContext.from_team_dir(team_dir)
    iteration, iter_dir = ctx.iteration_store.get_current()

    try:
        validate_iteration_for_run(iteration, iter_dir, ctx.agents)
    except SessionSetupError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    fileguard, approval_store = build_file_infra(ctx.project_root, ctx.file_access, iter_dir)

    layer_override = getattr(args, "layer", None)
    try:
        worktree_map, wt_warnings = setup_worktrees(ctx.team_dir, ctx.agents, fileguard, layer_override, iteration)
    except SessionSetupError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    for w in wt_warnings:
        print(f"Warning: {w}", file=sys.stderr)

    diffs_summary, diff_warnings = load_diffs_for_review(ctx.team_dir, iteration, layer_override)
    for w in diff_warnings:
        print(f"Warning: {w}", file=sys.stderr)
    if diffs_summary:
        layer = resolve_layer(layer_override, iteration)
        print(f"Code review: diffs loaded for layer {layer}")

    from gotg.config import load_streaming_config
    streaming = load_streaming_config(team_dir)

    run_conversation(iter_dir, ctx.agents, iteration, ctx.model_config, max_turns_override=args.max_turns, coach=ctx.coach, fileguard=fileguard, approval_store=approval_store, worktree_map=worktree_map, diffs_summary=diffs_summary, streaming=streaming)
    _auto_checkpoint(iter_dir, iteration, coach_name=ctx.coach["name"] if ctx.coach else "coach")


PROVIDER_PRESETS = {
    "anthropic": {
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5-20250929",
        "api_key": "$ANTHROPIC_API_KEY",
    },
    "openai": {
        "provider": "openai",
        "base_url": "https://api.openai.com",
        "model": "gpt-4o",
        "api_key": "$OPENAI_API_KEY",
    },
    "ollama": {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "qwen2.5-coder:7b",
    },
}


def cmd_model(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    import json

    if args.provider:
        preset = PROVIDER_PRESETS.get(args.provider)
        if not preset:
            print(f"Error: unknown provider '{args.provider}'. Options: {', '.join(PROVIDER_PRESETS)}", file=sys.stderr)
            raise SystemExit(1)

        config = dict(preset)
        if args.model_name:
            config["model"] = args.model_name

        save_model_config(team_dir, config)
        print(f"Model config updated: {config['provider']} / {config['model']}")

        env_key = config.get("api_key", "")
        if env_key.startswith("$"):
            env_var = env_key[1:]
            project_root = team_dir.parent
            dotenv_path = project_root / ".env"
            dotenv_vars = read_dotenv(dotenv_path)
            if dotenv_vars.get(env_var) or os.environ.get(env_var):
                print(f"API key: {env_var} is set")
            else:
                ensure_dotenv_key(dotenv_path, env_var)
                print(f"Created .env with {env_var}= placeholder")
                print(f"Edit .env and add your key: {env_var}=your-key-here")
    else:
        # No args — show current config
        team_config = json.loads((team_dir / "team.json").read_text())
        config = team_config["model"]
        print(f"Provider: {config.get('provider', 'unknown')}")
        print(f"Model:    {config.get('model', 'unknown')}")
        print(f"Base URL: {config.get('base_url', 'unknown')}")
        api_key = config.get("api_key", "")
        if api_key.startswith("$"):
            env_var = api_key[1:]
            project_root = team_dir.parent
            dotenv_vars = read_dotenv(project_root / ".env")
            is_set = "set" if (dotenv_vars.get(env_var) or os.environ.get(env_var)) else "NOT SET"
            print(f"API key:  ${env_var} ({is_set})")
        elif api_key:
            print(f"API key:  (literal, {len(api_key)} chars)")
        else:
            print("API key:  none")


def cmd_continue(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    ctx = TeamContext.from_team_dir(team_dir)
    iteration, iter_dir = ctx.iteration_store.get_current()

    try:
        validate_iteration_for_run(iteration, iter_dir, ctx.agents)
    except SessionSetupError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    fileguard, approval_store = build_file_infra(ctx.project_root, ctx.file_access, iter_dir)

    layer_override = getattr(args, "layer", None)
    try:
        worktree_map, wt_warnings = setup_worktrees(ctx.team_dir, ctx.agents, fileguard, layer_override, iteration)
    except SessionSetupError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    for w in wt_warnings:
        print(f"Warning: {w}", file=sys.stderr)

    diffs_summary, diff_warnings = load_diffs_for_review(ctx.team_dir, iteration, layer_override)
    for w in diff_warnings:
        print(f"Warning: {w}", file=sys.stderr)
    if diffs_summary:
        layer = resolve_layer(layer_override, iteration)
        print(f"Code review: diffs loaded for layer {layer}")

    log_path = iter_dir / "conversation.jsonl"
    history = read_phase_history(log_path)

    # Apply approved writes and inject denials before resuming
    if approval_store:
        from gotg.session import apply_and_inject
        messages = apply_and_inject(
            approval_store, fileguard, iteration, log_path,
            worktree_map=worktree_map,
        )
        for msg in messages:
            print(render_message(msg))
            print()

        remaining = approval_store.get_pending()
        if remaining:
            print(f"Warning: {len(remaining)} approval(s) still pending. Resolve before continuing.")
            print("Run 'gotg approvals' to review.")

    # Count current engineering agent turns (not human/coach/system)
    non_agent = {"human", "system"}
    if ctx.coach:
        non_agent.add(ctx.coach["name"])
    current_agent_turns = sum(1 for msg in history if msg["from"] not in non_agent)

    # Inject human message if provided
    if args.message:
        msg = {
            "from": "human",
            "iteration": iteration["id"],
            "content": args.message,
        }
        append_message(log_path, msg)
        print(render_message(msg))
        print()

    # Calculate target total agent turns
    if args.max_turns is not None:
        target_total = current_agent_turns + args.max_turns
    else:
        target_total = iteration["max_turns"]

    from gotg.config import load_streaming_config
    streaming = load_streaming_config(team_dir)

    run_conversation(iter_dir, ctx.agents, iteration, ctx.model_config, max_turns_override=target_total, coach=ctx.coach, fileguard=fileguard, approval_store=approval_store, worktree_map=worktree_map, diffs_summary=diffs_summary, streaming=streaming)
    _auto_checkpoint(iter_dir, iteration, coach_name=ctx.coach["name"] if ctx.coach else "coach")


def cmd_show(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)
    log_path = iter_dir / "conversation.jsonl"
    messages = read_log(log_path)

    if not messages:
        print("No messages yet.")
        return

    for msg in messages:
        print(render_message(msg))
        print()


def cmd_advance(args):
    from gotg.session import PhaseAdvanceError, advance_phase

    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)
    if iteration.get("status") != "in-progress":
        print(f"Error: iteration status is '{iteration.get('status')}', expected 'in-progress'.", file=sys.stderr)
        raise SystemExit(1)

    try:
        result = advance_phase(
            team_dir, iteration, iter_dir,
            chat_call=chat_completion,
            on_progress=lambda msg: print(msg),
        )
    except PhaseAdvanceError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    for w in result.warnings:
        print(f"Warning: {w}", file=sys.stderr)
    print(render_message(result.transition_msg))
    print()
    print(f"Phase advanced: {result.from_phase} → {result.to_phase}")
    print("Turns reset for new phase.")


def cmd_checkpoint(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)
    coach = load_coach(team_dir)
    number = create_checkpoint(iter_dir, iteration, description=args.description, trigger="manual", coach_name=coach["name"] if coach else "coach")
    print(f"Checkpoint {number} created")


def cmd_checkpoints(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    _, iter_dir = get_current_iteration(team_dir)
    checkpoints = list_checkpoints(iter_dir)

    if not checkpoints:
        print("No checkpoints yet.")
        return

    print(f"{'#':<4} {'Phase':<18} {'Turns':<7} {'Trigger':<9} {'Description':<30} {'Timestamp'}")
    print("-" * 100)
    for cp in checkpoints:
        print(
            f"{cp['number']:<4} {cp['phase']:<18} {cp['turn_count']:<7} "
            f"{cp['trigger']:<9} {cp.get('description', ''):<30} {cp['timestamp']}"
        )


def cmd_restore(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)

    # Validate checkpoint exists before prompting
    cp_path = iter_dir / "checkpoints" / str(args.number)
    if not cp_path.exists():
        print(f"Error: checkpoint {args.number} does not exist.", file=sys.stderr)
        raise SystemExit(1)

    # Safety prompt
    coach = load_coach(team_dir)
    answer = input("Create checkpoint of current state before restoring? [Y/n] ")
    if answer.strip().lower() not in ("n", "no"):
        number = create_checkpoint(
            iter_dir, iteration,
            description=f"Safety before restore to #{args.number}",
            trigger="manual",
            coach_name=coach["name"] if coach else "coach",
        )
        print(f"Checkpoint {number} created (safety)")

    state = restore_checkpoint(iter_dir, args.number)

    # Normalize legacy phase names before writing back
    from gotg.config import _normalize_phase
    restored_phase = _normalize_phase(state["phase"])

    # Update iteration.json to match checkpoint state
    save_iteration_fields(
        team_dir, iteration["id"],
        phase=restored_phase,
        max_turns=state["max_turns"],
    )

    print(f"Restored to checkpoint {args.number} (phase: {state['phase']}, turns: {state['turn_count']})")


def cmd_approvals(args):
    """Show pending approval requests."""
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)

    from gotg.approvals import ApprovalStore
    store = ApprovalStore(iter_dir / "approvals.json")
    pending = store.get_pending()

    if not pending:
        print("No pending approvals.")
        return

    print(f"Pending approvals ({len(pending)}):")
    print()
    for req in pending:
        content_preview = req["content"][:200]
        if len(req["content"]) > 200:
            content_preview += "..."
        print(f"  [{req['id']}] {req['path']} ({req['content_size']} bytes)")
        print(f"       Requested by: {req['requested_by']}")
        print(f"       Preview:")
        for line in content_preview.split("\n")[:5]:
            print(f"         {line}")
        if req["content"].count("\n") > 5:
            print(f"         ... ({req['content'].count(chr(10))} total lines)")
        print()

    print("To approve: gotg approve <id>")
    print("To deny:    gotg deny <id> -m 'reason'")
    print("To approve all: gotg approve all")


def cmd_approve(args):
    """Approve a pending request or all pending requests."""
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)

    from gotg.approvals import ApprovalStore
    store = ApprovalStore(iter_dir / "approvals.json")

    if args.request_id == "all":
        approved = store.approve_all()
        if not approved:
            print("No pending approvals to approve.")
            return
        for req in approved:
            print(f"Approved: [{req['id']}] {req['path']}")
        print(f"\n{len(approved)} approval(s) granted. Run 'gotg continue' to apply writes and resume.")
    else:
        try:
            req = store.approve(args.request_id)
            print(f"Approved: [{req['id']}] {req['path']}")
            print("Run 'gotg continue' to apply the write and resume.")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)


def cmd_deny(args):
    """Deny a pending request with a reason."""
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)

    from gotg.approvals import ApprovalStore
    store = ApprovalStore(iter_dir / "approvals.json")

    reason = args.message or ""
    try:
        req = store.deny(args.request_id, reason)
        print(f"Denied: [{req['id']}] {req['path']}")
        if reason:
            print(f"Reason: {reason}")
        print("Run 'gotg continue' to inject denial into conversation and resume.")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)


def cmd_review(args):
    """Show diffs of agent branches against main."""
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.session import ReviewError, load_review_branches

    iteration, _ = get_current_iteration(team_dir)

    if args.branch:
        # Specific branch — bypass layer discovery, diff just this branch
        from gotg.worktree import (
            WorktreeError, diff_branch, ensure_git_repo, is_branch_merged,
        )
        project_root = team_dir.parent
        try:
            ensure_git_repo(project_root)
        except WorktreeError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)

        merged = is_branch_merged(project_root, args.branch)
        label = " [merged]" if merged else ""
        print(f"=== {args.branch}{label} ===")
        try:
            result = diff_branch(project_root, args.branch)
        except WorktreeError as e:
            print(f"Error: {e}")
            print()
            print("---")
            print(f"1 branch(es), 0 file(s) changed, +0 -0 lines")
            return
        if result["empty"]:
            print("(no changes)")
        else:
            print(result["stat"].rstrip())
            if not args.stat_only:
                print()
                print(result["diff"].rstrip())
        print()
        print("---")
        print(f"1 branch(es), {result['files_changed']} file(s) changed, +{result['insertions']} -{result['deletions']} lines")
        return

    # Normal case — load all branches for layer
    try:
        review = load_review_branches(team_dir, iteration, args.layer)
    except ReviewError as e:
        print(f"{e}")
        return

    for br in review.branches:
        label = " [merged]" if br.merged else ""
        print(f"=== {br.branch}{label} ===")
        if br.empty:
            print("(no changes)")
        else:
            print(br.stat.rstrip())
            if not args.stat_only:
                print()
                print(br.diff.rstrip())
        print()

    print("---")
    print(
        f"Layer {review.layer}: {len(review.branches)} branch(es), "
        f"{review.total_files} file(s) changed, "
        f"+{review.total_insertions} -{review.total_deletions} lines"
    )


def cmd_merge(args):
    """Merge an agent branch into main."""
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.worktree import WorktreeError, abort_merge, ensure_git_repo

    project_root = team_dir.parent
    try:
        ensure_git_repo(project_root)
    except WorktreeError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    if args.abort:
        try:
            abort_merge(project_root)
            print("Merge aborted.")
        except WorktreeError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)
        return

    from gotg.session import ReviewError, merge_branches
    from gotg.worktree import is_branch_merged

    iteration, _ = get_current_iteration(team_dir)
    layer = args.layer if args.layer is not None else iteration.get("current_layer", 0)
    is_all = args.branch == "all"

    # Single branch: check if already merged before calling merge_branches
    if not is_all and is_branch_merged(project_root, args.branch):
        print(f"Branch '{args.branch}' is already merged into main.")
        return

    branches = None if is_all else [args.branch]

    try:
        results = merge_branches(
            project_root, layer, branches=branches,
            force=args.force, on_progress=lambda msg: print(msg),
        )
    except ReviewError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    merged_count = sum(1 for r in results if r.success)
    for r in results:
        if r.success:
            if is_all:
                print(f"  Merged: {r.commit}")
            else:
                print(f"Merged {r.branch} into main: {r.commit}")
        else:
            print(f"\nCONFLICT merging {r.branch}:" if is_all else f"CONFLICT merging {r.branch}:")
            for f in r.conflicts:
                print(f"  {f}")
            if is_all:
                print(f"\nMerged {merged_count}/{merged_count + len([x for x in results if not x.success])} branches before conflict.")
                print("Resolve conflicts and commit, then run 'gotg merge all' again,")
                print("or run 'gotg merge --abort' to undo.")
            else:
                print("\nResolve conflicts and commit, or run 'gotg merge --abort' to undo.")
            return

    if is_all:
        print(f"\n{merged_count} branch(es) merged into main.")


def cmd_worktrees(args):
    """List active git worktrees."""
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.worktree import ensure_git_repo, list_active_worktrees, is_worktree_dirty, WorktreeError

    project_root = team_dir.parent
    try:
        ensure_git_repo(project_root)
    except WorktreeError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    worktrees = list_active_worktrees(project_root)
    if not worktrees:
        print("No active worktrees.")
        return

    print("Active worktrees:")
    for wt in worktrees:
        wt_path = Path(wt["path"])
        status = "[dirty]" if is_worktree_dirty(wt_path) else "[clean]"
        branch = wt.get("branch", "unknown")
        rel_path = wt_path.relative_to(project_root) if wt_path.is_relative_to(project_root) else wt_path
        print(f"  {branch:<30} {rel_path}/  {status}")


def cmd_commit_worktrees(args):
    """Commit all dirty worktrees."""
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.worktree import ensure_git_repo, list_active_worktrees, commit_worktree, WorktreeError

    project_root = team_dir.parent
    try:
        ensure_git_repo(project_root)
    except WorktreeError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    worktrees = list_active_worktrees(project_root)
    if not worktrees:
        print("No active worktrees.")
        return

    message = args.message or "Agent implementation work"
    committed = 0
    for wt in worktrees:
        wt_path = Path(wt["path"])
        branch = wt.get("branch", "unknown")
        try:
            commit_hash = commit_worktree(wt_path, message)
            if commit_hash:
                print(f"{branch}: committed {commit_hash}")
                committed += 1
            else:
                print(f"{branch}: nothing to commit")
        except WorktreeError as e:
            print(f"{branch}: error — {e}", file=sys.stderr)

    if committed:
        print(f"\n{committed} worktree(s) committed.")


def cmd_next_layer(args):
    """Advance to the next task layer after merging."""
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)
    if iteration.get("status") != "in-progress":
        print(f"Error: iteration status is '{iteration.get('status')}', expected 'in-progress'.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.session import ReviewError, advance_next_layer

    try:
        result = advance_next_layer(
            team_dir, iteration, iter_dir,
            on_progress=lambda msg: print(msg),
        )
    except ReviewError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    if result.all_done:
        print(f"All layers complete (through layer {result.from_layer}). Iteration is done.")
        print("Edit .team/iteration.json to set status to 'done' when ready.")
        return

    for wt_name in result.removed_worktrees:
        print(f"Removed worktree: {wt_name}")

    print(render_message(result.transition_msg))
    print()
    print(f"Advanced to layer {result.to_layer} (implementation phase).")
    print(f"Layer {result.to_layer} has {result.task_count} task(s).")
    print("Turns reset for new phase.")


# ── Grooming commands ────────────────────────────────────────────


def cmd_groom_start(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    ctx = TeamContext.from_team_dir(team_dir)

    if len(ctx.agents) < 2:
        print("Error: need at least 2 agents in .team/team.json.", file=sys.stderr)
        raise SystemExit(1)

    topic = args.topic

    # Slug: user-provided or auto-generated
    slugs = existing_slugs(team_dir)
    if args.slug:
        if not validate_slug(args.slug):
            print("Error: invalid slug. Use lowercase letters, numbers, and hyphens (e.g., 'my-topic').", file=sys.stderr)
            raise SystemExit(1)
        if args.slug in slugs:
            print(f"Error: slug '{args.slug}' already exists.", file=sys.stderr)
            raise SystemExit(1)
        slug = args.slug
    else:
        slug = generate_slug(topic, slugs)

    coach = ctx.coach if args.coach else None
    max_turns = args.max_turns or 30

    groom_dir = write_grooming_metadata(team_dir, slug, topic, coach=bool(coach), max_turns=max_turns)

    iteration = {"id": slug, "description": topic, "phase": None}

    from gotg.config import load_streaming_config
    streaming = load_streaming_config(team_dir)

    run_grooming_conversation(
        groom_dir, ctx.agents, iteration, ctx.model_config,
        topic=topic, coach=coach, max_turns_override=max_turns,
        streaming=streaming,
    )


def cmd_groom_continue(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    ctx = TeamContext.from_team_dir(team_dir)
    metadata, groom_dir = load_grooming_metadata(team_dir, args.slug)

    if len(ctx.agents) < 2:
        print("Error: need at least 2 agents in .team/team.json.", file=sys.stderr)
        raise SystemExit(1)

    coach = ctx.coach if metadata.get("coach") else None

    log_path = groom_dir / "conversation.jsonl"
    history = read_log(log_path)

    # Count current agent turns (not human/coach/system)
    non_agent = {"human", "system"}
    if coach:
        non_agent.add(coach["name"])
    current_agent_turns = sum(1 for msg in history if msg["from"] not in non_agent)

    # Inject human message if provided
    if args.message:
        msg = {
            "from": "human",
            "iteration": args.slug,
            "content": args.message,
        }
        append_message(log_path, msg)
        print(render_message(msg))
        print()

    # Calculate target total agent turns (additive, matching iteration continue)
    if args.max_turns is not None:
        target_total = current_agent_turns + args.max_turns
    else:
        target_total = metadata.get("max_turns", 30)

    iteration = {"id": args.slug, "description": metadata["topic"], "phase": None}

    from gotg.config import load_streaming_config
    streaming = load_streaming_config(team_dir)

    run_grooming_conversation(
        groom_dir, ctx.agents, iteration, ctx.model_config,
        topic=metadata["topic"], coach=coach, max_turns_override=target_total,
        streaming=streaming,
    )


def cmd_groom_list(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    sessions = list_grooming_sessions(team_dir)
    if not sessions:
        print("No grooming sessions.")
        return

    for s in sessions:
        coach_flag = " [coach]" if s.get("coach") else ""
        print(f"  {s['slug']:<30} {s['topic']}{coach_flag}")


def cmd_groom_show(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    _, groom_dir = load_grooming_metadata(team_dir, args.slug)
    log_path = groom_dir / "conversation.jsonl"
    messages = read_log(log_path)

    if not messages:
        print("No messages yet.")
        return

    for msg in messages:
        print(render_message(msg))
        print()


def cmd_ui(args):
    try:
        from gotg.tui import run_app
    except ImportError:
        print("TUI requires the 'textual' package.", file=sys.stderr)
        print("Install with: pip install gotg[tui]", file=sys.stderr)
        raise SystemExit(1)
    team_dir = find_team_dir(Path.cwd())
    if team_dir is None:
        print("No .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)
    run_app(team_dir)


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
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "continue":
        cmd_continue(args)
    elif args.command == "model":
        cmd_model(args)
    elif args.command == "advance":
        cmd_advance(args)
    elif args.command == "checkpoint":
        cmd_checkpoint(args)
    elif args.command == "checkpoints":
        cmd_checkpoints(args)
    elif args.command == "restore":
        cmd_restore(args)
    elif args.command == "approvals":
        cmd_approvals(args)
    elif args.command == "approve":
        cmd_approve(args)
    elif args.command == "deny":
        cmd_deny(args)
    elif args.command == "review":
        cmd_review(args)
    elif args.command == "merge":
        if not args.abort and args.branch is None:
            parser.error("merge requires a branch name or 'all' (or use --abort)")
        cmd_merge(args)
    elif args.command == "worktrees":
        cmd_worktrees(args)
    elif args.command == "next-layer":
        cmd_next_layer(args)
    elif args.command == "commit-worktrees":
        cmd_commit_worktrees(args)
    elif args.command == "groom":
        if args.groom_command == "start":
            cmd_groom_start(args)
        elif args.groom_command == "continue":
            cmd_groom_continue(args)
        elif args.groom_command == "list":
            cmd_groom_list(args)
        elif args.groom_command == "show":
            cmd_groom_show(args)
        else:
            groom_parser.print_help()
    elif args.command == "ui":
        cmd_ui(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
