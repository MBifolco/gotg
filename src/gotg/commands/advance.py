"""gotg advance / gotg rework — phase transitions and rework loops.

Thin wrappers calling session_advance.py bridge functions. Validates current
phase, triggers artifact extraction, and outputs transition messages.
"""

import sys
from pathlib import Path

import gotg.cli as _cli
from gotg.iteration_store import IterationStore
from gotg.conversation import render_message


def cmd_advance(args):
    from gotg.session_types import PhaseAdvanceError
    from gotg.session_advance import advance_phase

    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = IterationStore(team_dir).get_current()
    if iteration.get("status") != "in-progress":
        print(f"Error: iteration status is '{iteration.get('status')}', expected 'in-progress'.", file=sys.stderr)
        raise SystemExit(1)

    try:
        result = advance_phase(
            team_dir, iteration, iter_dir,
            chat_call=_cli.chat_completion,
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


def cmd_next_layer(args):
    """Advance to the next task layer after merging."""
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = IterationStore(team_dir).get_current()
    if iteration.get("status") != "in-progress":
        print(f"Error: iteration status is '{iteration.get('status')}', expected 'in-progress'.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.session_types import ReviewError
    from gotg.session_advance import advance_next_layer

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


def cmd_rework(args):
    """Send tasks back for rework based on review feedback."""
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = IterationStore(team_dir).get_current()

    from gotg.session_advance import advance_rework
    from gotg.session_types import ReworkError

    try:
        result = advance_rework(
            team_dir, iteration, iter_dir,
            chat_call=_cli.chat_completion,
            on_progress=lambda msg: print(msg),
        )
    except ReworkError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    for w in result.warnings:
        print(f"Warning: {w}", file=sys.stderr)
    print(render_message(result.transition_msg))
    print()
    print(f"Rework: {len(result.tasks_with_feedback)} task(s) sent back for implementation (layer {result.layer}).")
    print("Turns reset for new phase.")
