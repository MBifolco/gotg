import sys
from pathlib import Path

import gotg.cli as _cli
from gotg.context import TeamContext
from gotg.conversation import append_message, read_log, render_message
from gotg.groom import (
    generate_slug, validate_slug, existing_slugs,
    write_grooming_metadata, load_grooming_metadata,
    list_grooming_sessions, run_grooming_conversation,
)


def cmd_groom_start(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
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
        streaming=streaming, model_resolver=ctx.model_resolver,
    )


def cmd_groom_continue(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
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
        streaming=streaming, model_resolver=ctx.model_resolver,
    )


def cmd_groom_list(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
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
    team_dir = _cli.find_team_dir(cwd)
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
