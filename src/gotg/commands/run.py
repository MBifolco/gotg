import sys
from pathlib import Path

import gotg.cli as _cli
from gotg.context import TeamContext
from gotg.conversation import ConversationStore, render_message
from gotg.session import (
    SessionSetupError, resolve_layer, validate_iteration_for_run,
    build_session_infra,
)


def _make_pause_controller():
    """Create a PauseController if stdin is a TTY, else None."""
    if not sys.stdin.isatty():
        return None
    from gotg.pause import PauseController
    return PauseController()


def cmd_run(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    ctx = TeamContext.from_team_dir(team_dir)

    iter_switch = getattr(args, "iteration", None)
    if isinstance(iter_switch, str):
        try:
            ctx.iteration_store.set_current(iter_switch)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)

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

    pause_ctrl = _make_pause_controller()

    while True:
        result = _cli.run_conversation(
            iter_dir, ctx.agents, iteration, ctx.model_config,
            max_turns_override=args.max_turns, coach=ctx.coach,
            fileguard=infra.fileguard, approval_store=infra.approval_store,
            worktree_map=infra.worktree_map, diffs_summary=infra.diffs_summary,
            streaming=infra.streaming, model_resolver=ctx.model_resolver,
            pause_controller=pause_ctrl,
        )
        if result != "paused" or pause_ctrl is None:
            break

        from gotg.pause import RESUME, prompt_for_interjection
        user_input = prompt_for_interjection("gotg continue")
        if user_input is None:
            # Stop — write pause marker
            store = ConversationStore(iter_dir / "conversation.jsonl")
            store.append({"from": "system", "content": "(Session paused by user.)",
                          "user_pause": True, "iteration": iteration["id"]})
            break
        if user_input is not RESUME:
            msg = {"from": "human", "iteration": iteration["id"],
                   "content": user_input}
            ConversationStore(iter_dir / "conversation.jsonl").append(msg)
            print(render_message(msg))
            print()
        pause_ctrl.reset()


def cmd_continue(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    ctx = TeamContext.from_team_dir(team_dir)

    iter_switch = getattr(args, "iteration", None)
    if isinstance(iter_switch, str):
        try:
            ctx.iteration_store.set_current(iter_switch)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)

    iteration, iter_dir = ctx.iteration_store.get_current()

    try:
        validate_iteration_for_run(iteration, iter_dir, ctx.agents)
    except SessionSetupError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    # Clear stale review_outcome when resuming code-review discussion.
    # The coach will re-signal with the correct outcome.
    if iteration.get("phase") == "code-review" and iteration.get("review_outcome"):
        ctx.iteration_store.save_fields(iteration["id"], review_outcome=None)
        iteration["review_outcome"] = None

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

    # Inject human message if provided (once, before loop)
    _message_injected = False
    if args.message:
        msg = {
            "from": "human",
            "iteration": iteration["id"],
            "content": args.message,
        }
        ConversationStore(log_path).append(msg)
        print(render_message(msg))
        print()
        _message_injected = True

    # Calculate target total agent turns
    if args.max_turns is not None:
        target_total = cont.current_agent_turns + args.max_turns
    else:
        target_total = iteration["max_turns"]

    # Detect (but don't consume) stale user_pause marker
    _pause_marker_pending = False
    from gotg.conversation import read_phase_history
    phase_msgs = read_phase_history(log_path)
    for m in reversed(phase_msgs):
        if m.get("user_pause_resolved"):
            break
        if m.get("user_pause"):
            _pause_marker_pending = True
            break
        if m.get("from") == "human":
            break
        if m.get("from") not in ("system", "human"):
            break

    pause_ctrl = _make_pause_controller()

    while True:
        result = _cli.run_conversation(
            iter_dir, ctx.agents, iteration, ctx.model_config,
            max_turns_override=target_total, coach=ctx.coach,
            fileguard=infra.fileguard, approval_store=infra.approval_store,
            worktree_map=infra.worktree_map, diffs_summary=infra.diffs_summary,
            streaming=infra.streaming, model_resolver=ctx.model_resolver,
            pause_controller=pause_ctrl,
        )

        # Consume marker AFTER first successful run
        if _pause_marker_pending:
            ConversationStore(log_path).append({
                "from": "system", "content": "",
                "user_pause_resolved": True, "iteration": iteration["id"],
            })
            _pause_marker_pending = False

        if result != "paused" or pause_ctrl is None:
            break

        from gotg.pause import RESUME, prompt_for_interjection
        user_input = prompt_for_interjection("gotg continue")
        if user_input is None:
            store = ConversationStore(log_path)
            store.append({"from": "system", "content": "(Session paused by user.)",
                          "user_pause": True, "iteration": iteration["id"]})
            break
        if user_input is not RESUME:
            msg = {"from": "human", "iteration": iteration["id"],
                   "content": user_input}
            ConversationStore(log_path).append(msg)
            print(render_message(msg))
            print()
        pause_ctrl.reset()
