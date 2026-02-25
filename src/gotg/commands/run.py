import sys
from pathlib import Path

import gotg.cli as _cli
from gotg.context import TeamContext
from gotg.conversation import append_message, render_message
from gotg.session import (
    SessionSetupError, resolve_layer, validate_iteration_for_run,
    build_session_infra,
)


def cmd_run(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
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

    layer_override = getattr(args, "layer", None)
    try:
        infra = build_session_infra(ctx, iteration, iter_dir, layer_override=layer_override)
    except SessionSetupError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    for w in infra.warnings:
        print(f"Warning: {w}", file=sys.stderr)
    if infra.diffs_summary:
        layer = resolve_layer(layer_override, iteration)
        print(f"Code review: diffs loaded for layer {layer}")

    _cli.run_conversation(
        iter_dir, ctx.agents, iteration, ctx.model_config,
        max_turns_override=args.max_turns, coach=ctx.coach,
        fileguard=infra.fileguard, approval_store=infra.approval_store,
        worktree_map=infra.worktree_map, diffs_summary=infra.diffs_summary,
        streaming=infra.streaming, model_resolver=ctx.model_resolver,
    )
    _cli._auto_checkpoint(iter_dir, iteration, coach_name=ctx.coach["name"] if ctx.coach else "coach")


def cmd_continue(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
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

    layer_override = getattr(args, "layer", None)
    try:
        infra = build_session_infra(ctx, iteration, iter_dir, layer_override=layer_override)
    except SessionSetupError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    for w in infra.warnings:
        print(f"Warning: {w}", file=sys.stderr)
    if infra.diffs_summary:
        layer = resolve_layer(layer_override, iteration)
        print(f"Code review: diffs loaded for layer {layer}")

    log_path = iter_dir / "conversation.jsonl"

    # Apply approved writes, inject denials, count turns
    from gotg.session import prepare_continue
    cont = prepare_continue(
        infra, iteration, log_path,
        coach_name=ctx.coach["name"] if ctx.coach else None,
    )
    for msg in cont.injected_messages:
        print(render_message(msg))
        print()
    if cont.has_pending_approvals:
        print(f"Warning: {cont.pending_count} approval(s) still pending. Resolve before continuing.")
        print("Run 'gotg approvals' to review.")

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
        target_total = cont.current_agent_turns + args.max_turns
    else:
        target_total = iteration["max_turns"]

    _cli.run_conversation(
        iter_dir, ctx.agents, iteration, ctx.model_config,
        max_turns_override=target_total, coach=ctx.coach,
        fileguard=infra.fileguard, approval_store=infra.approval_store,
        worktree_map=infra.worktree_map, diffs_summary=infra.diffs_summary,
        streaming=infra.streaming, model_resolver=ctx.model_resolver,
    )
    _cli._auto_checkpoint(iter_dir, iteration, coach_name=ctx.coach["name"] if ctx.coach else "coach")
