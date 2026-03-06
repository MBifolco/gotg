"""gotg init / gotg new / gotg model — project setup and admin commands.

cmd_init scaffolds a new .team/ directory. cmd_new creates iterations.
cmd_model configures provider, base_url, model, and API key with interactive
prompts and dotenv integration.
"""

import os
import sys
from pathlib import Path

import gotg.cli as _cli
from gotg.config import (
    save_model_config,
    read_dotenv, ensure_dotenv_key,
)
from gotg.iteration_store import IterationStore
from gotg.conversation import ConversationStore, render_message
from gotg.providers import provider_runtime_config, PROVIDERS
from gotg.scaffold import init_project


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
        if args.provider not in PROVIDERS:
            print(f"Error: unknown provider '{args.provider}'. Options: {', '.join(PROVIDERS)}", file=sys.stderr)
            raise SystemExit(1)

        config = provider_runtime_config(args.provider, args.model_name)

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
        operation = req.get("operation", "write")
        if operation == "delete":
            print(f"  [{req['id']}] [DELETE] {req['path']}")
            print(f"       Requested by: {req['requested_by']}")
            reason = req.get("tool_input", {}).get("reason", "")
            if reason:
                print(f"       Reason: {reason}")
        elif operation == "rename":
            dst = req.get("destination", "")
            print(f"  [{req['id']}] [RENAME] {req['path']} -> {dst}")
            print(f"       Requested by: {req['requested_by']}")
            reason = req.get("tool_input", {}).get("reason", "")
            if reason:
                print(f"       Reason: {reason}")
        else:
            content_preview = req.get("content", "")[:200]
            if len(req.get("content", "")) > 200:
                content_preview += "..."
            print(f"  [{req['id']}] {req['path']} ({req['content_size']} bytes)")
            print(f"       Requested by: {req['requested_by']}")
            print(f"       Preview:")
            for line in content_preview.split("\n")[:5]:
                print(f"         {line}")
            if req.get("content", "").count("\n") > 5:
                print(f"         ... ({req.get('content', '').count(chr(10))} total lines)")
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
            dest = req.get("destination", "")
            path_display = f"{req['path']} -> {dest}" if dest else req["path"]
            print(f"Approved: [{req['id']}] {path_display}")
        print(f"\n{len(approved)} approval(s) granted. Run 'gotg continue' to apply and resume.")
    else:
        try:
            req = store.approve(args.request_id)
            dest = req.get("destination", "")
            path_display = f"{req['path']} -> {dest}" if dest else req["path"]
            print(f"Approved: [{req['id']}] {path_display}")
            print("Run 'gotg continue' to apply and resume.")
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
        dest = req.get("destination", "")
        path_display = f"{req['path']} -> {dest}" if dest else req["path"]
        print(f"Denied: [{req['id']}] {path_display}")
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
