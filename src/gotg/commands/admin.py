import os
import sys
from pathlib import Path

import gotg.cli as _cli
from gotg.checkpoint import create_checkpoint, list_checkpoints, restore_checkpoint
from gotg.config import (
    IterationStore, load_coach, save_model_config,
    read_dotenv, ensure_dotenv_key,
)
from gotg.conversation import ConversationStore, render_message
from gotg.scaffold import init_project


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


def cmd_init(args):
    path = Path(args.path)
    init_project(path)


def cmd_new(args):
    """Create a new iteration."""
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    store = IterationStore(team_dir)
    existing_ids = {it["id"] for it in store.list_all()}
    next_num = 1
    while f"iter-{next_num}" in existing_ids:
        next_num += 1
    new_id = f"iter-{next_num}"

    description = args.description
    store.create(new_id, description=description, set_current=True)
    print(f"Created {new_id}: {description}")
    print(f"Set as current iteration. Run 'gotg run' to start refinement.")


def cmd_model(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
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


def cmd_show(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = IterationStore(team_dir).get_current()
    log_path = iter_dir / "conversation.jsonl"
    messages = ConversationStore(log_path).read_full()

    if not messages:
        print("No messages yet.")
        return

    for msg in messages:
        print(render_message(msg))
        print()


def cmd_checkpoint(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = IterationStore(team_dir).get_current()
    coach = load_coach(team_dir)
    number = create_checkpoint(iter_dir, iteration, description=args.description, trigger="manual", coach_name=coach["name"] if coach else "coach")
    print(f"Checkpoint {number} created")


def cmd_checkpoints(args):
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    _, iter_dir = IterationStore(team_dir).get_current()
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
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = IterationStore(team_dir).get_current()

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
    from gotg.migration import normalize_phase
    restored_phase = normalize_phase(state["phase"])

    # Update iteration.json to match checkpoint state
    IterationStore(team_dir).save_fields(
        iteration["id"],
        phase=restored_phase,
        max_turns=state["max_turns"],
    )

    print(f"Restored to checkpoint {args.number} (phase: {state['phase']}, turns: {state['turn_count']})")


def cmd_approvals(args):
    """Show pending approval requests."""
    cwd = Path.cwd()
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = IterationStore(team_dir).get_current()

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
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = IterationStore(team_dir).get_current()

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
    team_dir = _cli.find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = IterationStore(team_dir).get_current()

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


def cmd_ui(args):
    try:
        from gotg.tui import run_app
    except ImportError:
        print("TUI requires the 'textual' package.", file=sys.stderr)
        print("Install with: pip install gotg[tui]", file=sys.stderr)
        raise SystemExit(1)
    team_dir = _cli.find_team_dir(Path.cwd())
    if team_dir is None:
        print("No .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)
    run_app(team_dir)
