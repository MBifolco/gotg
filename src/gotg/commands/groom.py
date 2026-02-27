import sys
from pathlib import Path

import gotg.cli as _cli
from gotg.context import TeamContext
from gotg.conversation import ConversationStore, render_message
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

    # Resolve iteration context
    from gotg.session_setup import load_iteration_context
    from gotg.session_types import SessionSetupError

    if getattr(args, "no_context", False):
        context_from_value: str | bool | None = False
        project_context = None
    elif getattr(args, "context_from", None):
        context_from_value = args.context_from
        try:
            project_context = load_iteration_context(
                team_dir, context_from=args.context_from, strict=True
            )
        except SessionSetupError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)
    else:
        # Auto-detect
        project_context = load_iteration_context(team_dir)
        context_from_value = None
        # If auto-detect found something, record which iteration it came from
        if project_context:
            from gotg.config import IterationStore
            try:
                all_iters = IterationStore(team_dir).list_all()
                for it in all_iters:
                    if it.get("status") == "pending":
                        continue
                    d = IterationStore(team_dir).get_dir(it["id"])
                    if (d / "refinement_summary.md").exists() or (d / "tasks.json").exists():
                        context_from_value = it["id"]  # last match wins
            except (FileNotFoundError, KeyError):
                pass

    groom_dir = write_grooming_metadata(
        team_dir, slug, topic, coach=bool(coach), max_turns=max_turns,
        context_from=context_from_value,
    )

    iteration = {"id": slug, "description": topic, "phase": None}

    from gotg.config import load_streaming_config
    streaming = load_streaming_config(team_dir)

    run_grooming_conversation(
        groom_dir, ctx.agents, iteration, ctx.model_config,
        topic=topic, coach=coach, max_turns_override=max_turns,
        streaming=streaming, model_resolver=ctx.model_resolver,
        project_context=project_context,
        project_root=ctx.project_root,
        file_access=ctx.file_access,
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
    store = ConversationStore(log_path)
    history = store.read_full()

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
        store.append(msg)
        print(render_message(msg))
        print()

    # Calculate target total agent turns (additive, matching iteration continue)
    if args.max_turns is not None:
        target_total = current_agent_turns + args.max_turns
    else:
        target_total = metadata.get("max_turns", 30)

    iteration = {"id": args.slug, "description": metadata["topic"], "phase": None}

    # Load iteration context from persisted context_from
    from gotg.session_setup import load_iteration_context

    context_from = metadata.get("context_from")
    project_context = None
    if isinstance(context_from, str):
        # Explicit iteration ID — load its artifacts (non-strict: skip silently if missing)
        project_context = load_iteration_context(team_dir, context_from=context_from)
    # context_from is None or False → skip loading

    from gotg.config import load_streaming_config
    streaming = load_streaming_config(team_dir)

    run_grooming_conversation(
        groom_dir, ctx.agents, iteration, ctx.model_config,
        topic=metadata["topic"], coach=coach, max_turns_override=target_total,
        streaming=streaming, model_resolver=ctx.model_resolver,
        project_context=project_context,
        project_root=ctx.project_root,
        file_access=ctx.file_access,
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
    messages = ConversationStore(log_path).read_full()

    if not messages:
        print("No messages yet.")
        return

    for msg in messages:
        print(render_message(msg))
        print()
