import argparse
import os
import sys
from pathlib import Path

from gotg.agent import build_prompt, build_coach_prompt
from gotg.checkpoint import create_checkpoint, list_checkpoints, restore_checkpoint
from gotg.config import (
    load_agents, load_coach, load_model_config, load_file_access,
    load_worktree_config, ensure_dotenv_key, read_dotenv,
    get_current_iteration, save_model_config,
    save_iteration_phase, save_iteration_fields, PHASE_ORDER,
)
from gotg.conversation import append_message, append_debug, read_log, render_message
from gotg.model import chat_completion
from gotg.scaffold import init_project, COACH_GROOMING_PROMPT, COACH_PLANNING_PROMPT, COACH_TOOLS


def find_team_dir(cwd: Path) -> Path | None:
    team = cwd / ".team"
    if team.is_dir():
        return team
    return None


def _validate_task_assignments(iter_dir: Path, phase: str) -> None:
    """Check that all tasks are assigned before entering pre-code-review."""
    if phase != "pre-code-review":
        return
    import json as _json
    tasks_path = iter_dir / "tasks.json"
    if not tasks_path.exists():
        print("Error: pre-code-review requires tasks.json. Run 'gotg advance' from planning first.", file=sys.stderr)
        raise SystemExit(1)
    tasks = _json.loads(tasks_path.read_text())
    unassigned = [t["id"] for t in tasks if not t.get("assigned_to")]
    if unassigned:
        print("Error: all tasks must be assigned before starting pre-code-review.", file=sys.stderr)
        print(f"Unassigned tasks: {', '.join(unassigned)}", file=sys.stderr)
        print("Edit .team/iterations/<id>/tasks.json to assign agents.", file=sys.stderr)
        raise SystemExit(1)


def _auto_checkpoint(iter_dir: Path, iteration: dict, coach_name: str = "coach") -> None:
    """Create an automatic checkpoint after a command completes."""
    try:
        number = create_checkpoint(iter_dir, iteration, trigger="auto", coach_name=coach_name)
        print(f"Checkpoint {number} created (auto)")
    except Exception as e:
        print(f"Warning: auto-checkpoint failed: {e}", file=sys.stderr)


def _setup_worktrees(team_dir: Path, agents: list[dict], fileguard, args) -> dict | None:
    """Set up worktrees for agents if configured. Returns worktree_map or None."""
    worktree_config = load_worktree_config(team_dir)
    if not worktree_config or not worktree_config.get("enabled"):
        return None

    if not fileguard:
        print("Warning: worktrees enabled but file_access not configured — worktrees require file tools.", file=sys.stderr)
        return None

    from gotg.worktree import ensure_git_repo, create_worktree, ensure_gitignore_entries, WorktreeError
    import subprocess as _sp

    project_root = team_dir.parent
    try:
        ensure_git_repo(project_root)
    except WorktreeError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    # Verify HEAD is on main — worktrees branch from HEAD
    head_result = _sp.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_root, capture_output=True, text=True,
    )
    current_branch = head_result.stdout.strip()
    if current_branch != "main":
        print(
            f"Error: HEAD is on '{current_branch}', expected 'main'. "
            "Worktrees branch from HEAD — switch to main first.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    for warning in ensure_gitignore_entries(project_root):
        print(f"Warning: {warning}", file=sys.stderr)

    layer = getattr(args, "layer", None)
    if layer is None:
        layer = 0

    worktree_map = {}
    for agent in agents:
        try:
            wt_path = create_worktree(project_root, agent["name"], layer)
            worktree_map[agent["name"]] = wt_path
        except WorktreeError as e:
            print(f"Error creating worktree for {agent['name']}: {e}", file=sys.stderr)
            raise SystemExit(1)

    return worktree_map


def _load_diffs_for_code_review(team_dir: Path, iteration: dict, args) -> str | None:
    """Load diffs for code-review phase. Returns formatted string or None."""
    if iteration.get("phase") != "code-review":
        return None

    worktree_config = load_worktree_config(team_dir)
    if not worktree_config or not worktree_config.get("enabled"):
        print("Warning: code-review phase but worktrees not enabled. No diffs to load.", file=sys.stderr)
        return None

    from gotg.worktree import format_diffs_for_prompt

    layer = getattr(args, "layer", None)
    if layer is None:
        layer = 0

    diffs = format_diffs_for_prompt(team_dir.parent, layer)
    if diffs:
        print(f"Code review: diffs loaded for layer {layer}")
    else:
        print(f"Warning: no branches found for layer {layer}. No diffs to review.", file=sys.stderr)

    return diffs


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
) -> None:
    log_path = iter_dir / "conversation.jsonl"
    debug_path = iter_dir / "debug.jsonl"
    history = read_log(log_path)
    max_turns = max_turns_override if max_turns_override is not None else iteration["max_turns"]

    # Load groomed.md artifact if it exists (for planning/later phases)
    groomed_path = iter_dir / "groomed.md"
    groomed_summary = groomed_path.read_text().strip() if groomed_path.exists() else None

    # Load tasks.json artifact if it exists (for pre-code-review/later phases)
    tasks_path = iter_dir / "tasks.json"
    tasks_summary = None
    if tasks_path.exists():
        import json as _json
        from gotg.tasks import format_tasks_summary
        tasks_data = _json.loads(tasks_path.read_text())
        tasks_summary = format_tasks_summary(tasks_data)

    # Build participant list from agents + coach + detect human in history
    all_participants = [
        {"name": a["name"], "role": a.get("role", "Software Engineer")}
        for a in agents
    ]
    if coach:
        all_participants.append({"name": coach["name"], "role": coach.get("role", "Agile Coach")})
    if any(msg["from"] == "human" for msg in history):
        all_participants.append({"name": "human", "role": "Team Member"})

    # Count only engineering agent turns (human/coach/system don't affect rotation)
    non_agent = {"human", "system"}
    if coach:
        non_agent.add(coach["name"])
    turn = sum(1 for msg in history if msg["from"] not in non_agent)
    num_agents = len(agents)

    print(f"Starting conversation: {iteration['id']}")
    print(f"Task: {iteration['description']}")
    print(f"Phase: {iteration.get('phase', 'grooming')}")
    if coach:
        print(f"Coach: {coach['name']} (facilitating)")
    if fileguard:
        writable = ", ".join(fileguard.writable_paths) if fileguard.writable_paths else "none"
        print(f"File tools: enabled (writable: {writable})")
    if worktree_map:
        print(f"Worktrees: {len(worktree_map)} active")
    print(f"Turns: {turn}/{max_turns}")
    print("---")

    while turn < max_turns:
        agent = agents[turn % num_agents]
        prompt = build_prompt(agent, iteration, history, all_participants, groomed_summary=groomed_summary, tasks_summary=tasks_summary, diffs_summary=diffs_summary)
        append_debug(debug_path, {
            "turn": turn,
            "agent": agent["name"],
            "messages": prompt,
        })

        if fileguard:
            from gotg.model import agentic_completion
            from gotg.tools import FILE_TOOLS, execute_file_tool, format_tool_operation

            # Select per-agent FileGuard when worktrees active.
            # IMPORTANT: agent_fg must be computed inside the loop because `agent`
            # changes each iteration. The tool_executor closure captures agent_fg,
            # and since the closure is re-created each iteration, it gets the right one.
            # Do NOT refactor tool_executor outside this loop — it would break this.
            if worktree_map and agent["name"] in worktree_map:
                agent_fg = fileguard.with_root(worktree_map[agent["name"]])
            else:
                agent_fg = fileguard

            write_count = 0

            def tool_executor(name, inp):
                nonlocal write_count
                if name == "file_write":
                    write_count += 1
                    if write_count > agent_fg.max_files_per_turn:
                        return f"Error: write limit reached ({agent_fg.max_files_per_turn} per turn)"
                return execute_file_tool(name, inp, agent_fg, approval_store=approval_store, agent_name=agent["name"])

            result = agentic_completion(
                base_url=model_config["base_url"],
                model=model_config["model"],
                messages=prompt,
                api_key=model_config.get("api_key"),
                provider=model_config.get("provider", "ollama"),
                tools=FILE_TOOLS,
                tool_executor=tool_executor,
            )
            response_text = result["content"]

            # Log file operations as system messages
            for op in result["operations"]:
                op_msg = {
                    "from": "system",
                    "iteration": iteration["id"],
                    "content": format_tool_operation(op),
                }
                append_message(log_path, op_msg)
                print(render_message(op_msg))
                print()
                history.append(op_msg)

            # Debug log full tool details
            if result["operations"]:
                append_debug(debug_path, {
                    "turn": turn,
                    "agent": agent["name"],
                    "tool_operations": result["operations"],
                })
        else:
            response_text = chat_completion(
                base_url=model_config["base_url"],
                model=model_config["model"],
                messages=prompt,
                api_key=model_config.get("api_key"),
                provider=model_config.get("provider", "ollama"),
            )

        msg = {
            "from": agent["name"],
            "iteration": iteration["id"],
            "content": response_text,
        }
        append_message(log_path, msg)
        print(render_message(msg))
        print()

        history.append(msg)
        turn += 1

        # Check for pending approvals — pause conversation if any
        if approval_store:
            pending = approval_store.get_pending()
            if pending:
                print("---")
                print(f"Paused: {len(pending)} pending approval(s).")
                print("Run 'gotg approvals' to review, then 'gotg approve <id>' or 'gotg deny <id> -m reason'.")
                print("Resume with 'gotg continue'.")
                return

        # Coach injection: after every full rotation of engineering agents
        if coach and turn % num_agents == 0:
            coach_prompt = build_coach_prompt(coach, iteration, history, all_participants, groomed_summary=groomed_summary, tasks_summary=tasks_summary, diffs_summary=diffs_summary)
            append_debug(debug_path, {
                "turn": f"coach-after-{turn}",
                "agent": coach["name"],
                "messages": coach_prompt,
            })
            coach_response = chat_completion(
                base_url=model_config["base_url"],
                model=model_config["model"],
                messages=coach_prompt,
                api_key=model_config.get("api_key"),
                provider=model_config.get("provider", "ollama"),
                tools=COACH_TOOLS,
            )
            coach_text = coach_response["content"]
            coach_tool_calls = coach_response.get("tool_calls", [])
            coach_msg = {
                "from": coach["name"],
                "iteration": iteration["id"],
                "content": coach_text,
            }
            append_message(log_path, coach_msg)
            print(render_message(coach_msg))
            print()
            history.append(coach_msg)

            # Early exit: coach signals phase is complete via tool call
            if any(tc["name"] == "signal_phase_complete" for tc in coach_tool_calls):
                print("---")
                current_phase = iteration.get("phase")
                if current_phase and current_phase == PHASE_ORDER[-1]:
                    print("Coach signals phase complete. This is the final phase — iteration is done.")
                    print("Run `gotg continue` to keep discussing if needed.")
                else:
                    print("Coach recommends advancing. Run `gotg advance` to proceed, or `gotg continue` to keep discussing.")
                return

    print("---")
    print(f"Conversation complete ({turn} turns)")


def cmd_init(args):
    path = Path(args.path)
    init_project(path)


def cmd_run(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)
    if not iteration.get("description"):
        print("Error: iteration description is empty. Edit .team/iteration.json first.", file=sys.stderr)
        raise SystemExit(1)
    if iteration.get("status") != "in-progress":
        print(f"Error: iteration status is '{iteration.get('status')}', expected 'in-progress'.", file=sys.stderr)
        raise SystemExit(1)

    model_config = load_model_config(team_dir)
    agents = load_agents(team_dir)
    coach = load_coach(team_dir)

    if len(agents) < 2:
        print("Error: need at least 2 agents in .team/team.json.", file=sys.stderr)
        raise SystemExit(1)

    _validate_task_assignments(iter_dir, iteration.get("phase", "grooming"))

    file_access = load_file_access(team_dir)
    fileguard = None
    approval_store = None
    if file_access:
        from gotg.fileguard import FileGuard
        fileguard = FileGuard(team_dir.parent, file_access)
        if file_access.get("enable_approvals"):
            from gotg.approvals import ApprovalStore
            approval_store = ApprovalStore(iter_dir / "approvals.json")

    worktree_map = _setup_worktrees(team_dir, agents, fileguard, args)

    diffs_summary = _load_diffs_for_code_review(team_dir, iteration, args)

    run_conversation(iter_dir, agents, iteration, model_config, max_turns_override=args.max_turns, coach=coach, fileguard=fileguard, approval_store=approval_store, worktree_map=worktree_map, diffs_summary=diffs_summary)
    _auto_checkpoint(iter_dir, iteration, coach_name=coach["name"] if coach else "coach")


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

    iteration, iter_dir = get_current_iteration(team_dir)
    if not iteration.get("description"):
        print("Error: iteration description is empty.", file=sys.stderr)
        raise SystemExit(1)
    if iteration.get("status") != "in-progress":
        print(f"Error: iteration status is '{iteration.get('status')}', expected 'in-progress'.", file=sys.stderr)
        raise SystemExit(1)

    model_config = load_model_config(team_dir)
    agents = load_agents(team_dir)
    coach = load_coach(team_dir)

    if len(agents) < 2:
        print("Error: need at least 2 agents in .team/team.json.", file=sys.stderr)
        raise SystemExit(1)

    _validate_task_assignments(iter_dir, iteration.get("phase", "grooming"))

    file_access = load_file_access(team_dir)
    fileguard = None
    approval_store = None
    if file_access:
        from gotg.fileguard import FileGuard
        fileguard = FileGuard(team_dir.parent, file_access)
        if file_access.get("enable_approvals"):
            from gotg.approvals import ApprovalStore, apply_approved_writes
            approval_store = ApprovalStore(iter_dir / "approvals.json")

    worktree_map = _setup_worktrees(team_dir, agents, fileguard, args)

    diffs_summary = _load_diffs_for_code_review(team_dir, iteration, args)

    log_path = iter_dir / "conversation.jsonl"
    history = read_log(log_path)

    # Apply approved writes and inject denials before resuming
    if approval_store:
        # When worktrees active, route approved writes to correct agent's worktree
        fg_for_agent = None
        if worktree_map:
            fg_for_agent = lambda name: fileguard.with_root(worktree_map[name]) if name in worktree_map else fileguard
        results = apply_approved_writes(approval_store, fileguard, fileguard_for_agent=fg_for_agent)
        for r in results:
            result_msg = {
                "from": "system",
                "iteration": iteration["id"],
                "content": (
                    f"[file_write] APPROVED: {r['message']}"
                    if r["success"]
                    else f"[file_write] APPROVAL FAILED: {r['message']}"
                ),
            }
            append_message(log_path, result_msg)
            print(render_message(result_msg))
            print()

        for req in approval_store.get_denied_uninjected():
            reason = req.get("denial_reason") or "No reason provided"
            denial_msg = {
                "from": "system",
                "iteration": iteration["id"],
                "content": (
                    f"[file_write] DENIED by PM: {req['path']} — {reason}. "
                    f"(Originally requested by {req['requested_by']})"
                ),
            }
            append_message(log_path, denial_msg)
            print(render_message(denial_msg))
            print()
            approval_store.mark_injected(req["id"])

        remaining = approval_store.get_pending()
        if remaining:
            print(f"Warning: {len(remaining)} approval(s) still pending. Resolve before continuing.")
            print("Run 'gotg approvals' to review.")

    # Count current engineering agent turns (not human/coach/system)
    non_agent = {"human", "system"}
    if coach:
        non_agent.add(coach["name"])
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

    run_conversation(iter_dir, agents, iteration, model_config, max_turns_override=target_total, coach=coach, fileguard=fileguard, approval_store=approval_store, worktree_map=worktree_map, diffs_summary=diffs_summary)
    _auto_checkpoint(iter_dir, iteration, coach_name=coach["name"] if coach else "coach")


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
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found. Run 'gotg init' first.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)
    if iteration.get("status") != "in-progress":
        print(f"Error: iteration status is '{iteration.get('status')}', expected 'in-progress'.", file=sys.stderr)
        raise SystemExit(1)

    current_phase = iteration.get("phase", "grooming")
    try:
        idx = PHASE_ORDER.index(current_phase)
    except ValueError:
        print(f"Error: unknown phase '{current_phase}'.", file=sys.stderr)
        raise SystemExit(1)

    if idx >= len(PHASE_ORDER) - 1:
        print(f"Error: cannot advance past {current_phase}.", file=sys.stderr)
        raise SystemExit(1)

    next_phase = PHASE_ORDER[idx + 1]

    # Invoke coach on grooming → planning transition
    coach_ran = False
    if current_phase == "grooming" and next_phase == "planning":
        coach = load_coach(team_dir)
        if coach:
            print("Coach is summarizing the grooming conversation...")
            model_config = load_model_config(team_dir)
            log_path = iter_dir / "conversation.jsonl"
            history = read_log(log_path)
            conversation_text = "\n\n".join(
                f"[{m['from']}]: {m['content']}" for m in history
            )
            coach_messages = [
                {"role": "system", "content": COACH_GROOMING_PROMPT},
                {"role": "user", "content": conversation_text},
            ]
            summary = chat_completion(
                base_url=model_config["base_url"],
                model=model_config["model"],
                messages=coach_messages,
                api_key=model_config.get("api_key"),
                provider=model_config.get("provider", "ollama"),
            )
            groomed_path = iter_dir / "groomed.md"
            groomed_path.write_text(summary + "\n")
            print(f"Wrote {groomed_path}")
            coach_ran = True

    # Invoke coach on planning → pre-code-review transition
    tasks_written = False
    if current_phase == "planning" and next_phase == "pre-code-review":
        coach = load_coach(team_dir)
        if coach:
            import json as _json
            print("Coach is extracting tasks from the planning conversation...")
            model_config = load_model_config(team_dir)
            log_path = iter_dir / "conversation.jsonl"
            history = read_log(log_path)
            conversation_text = "\n\n".join(
                f"[{m['from']}]: {m['content']}" for m in history
            )
            coach_messages = [
                {"role": "system", "content": COACH_PLANNING_PROMPT},
                {"role": "user", "content": conversation_text},
            ]
            tasks_json_text = chat_completion(
                base_url=model_config["base_url"],
                model=model_config["model"],
                messages=coach_messages,
                api_key=model_config.get("api_key"),
                provider=model_config.get("provider", "ollama"),
            )
            # Strip markdown code fences if present
            text = tasks_json_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            try:
                tasks_data = _json.loads(text)
                # Compute and store layers from dependency graph
                from gotg.tasks import compute_layers
                layers = compute_layers(tasks_data)
                for task in tasks_data:
                    task["layer"] = layers[task["id"]]
                tasks_path = iter_dir / "tasks.json"
                tasks_path.write_text(_json.dumps(tasks_data, indent=2) + "\n")
                print(f"Wrote {tasks_path}")
                tasks_written = True
            except _json.JSONDecodeError as e:
                print(f"Warning: Coach produced invalid JSON: {e}", file=sys.stderr)
                print("Raw output saved to tasks_raw.txt for manual correction.", file=sys.stderr)
                (iter_dir / "tasks_raw.txt").write_text(tasks_json_text + "\n")
            coach_ran = True

    save_iteration_phase(team_dir, iteration["id"], next_phase)

    log_path = iter_dir / "conversation.jsonl"
    if tasks_written:
        transition_content = f"--- Phase advanced: {current_phase} → {next_phase}. Task list written to tasks.json ---"
    elif coach_ran and current_phase == "grooming":
        transition_content = f"--- Phase advanced: {current_phase} → {next_phase}. Scope summary written to groomed.md ---"
    else:
        transition_content = f"--- Phase advanced: {current_phase} → {next_phase} ---"
    msg = {
        "from": "system",
        "iteration": iteration["id"],
        "content": transition_content,
    }
    append_message(log_path, msg)
    print(render_message(msg))
    print()
    print(f"Phase advanced: {current_phase} → {next_phase}")

    # Auto-checkpoint with updated phase
    iteration["phase"] = next_phase
    coach_for_cp = load_coach(team_dir)
    _auto_checkpoint(iter_dir, iteration, coach_name=coach_for_cp["name"] if coach_for_cp else "coach")


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

    # Update iteration.json to match checkpoint state
    save_iteration_fields(
        team_dir, iteration["id"],
        phase=state["phase"],
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

    from gotg.worktree import (
        ensure_git_repo, diff_branch, list_layer_branches,
        is_branch_merged, WorktreeError,
    )

    project_root = team_dir.parent
    try:
        ensure_git_repo(project_root)
    except WorktreeError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    if args.branch:
        branches = [args.branch]
    else:
        branches = list_layer_branches(project_root, args.layer)

    if not branches:
        print(f"No branches found for layer {args.layer}.")
        return

    total_files = 0
    total_ins = 0
    total_del = 0

    for br in branches:
        merged = is_branch_merged(project_root, br)
        label = f" [merged]" if merged else ""
        print(f"=== {br}{label} ===")

        try:
            result = diff_branch(project_root, br)
        except WorktreeError as e:
            print(f"Error: {e}")
            print()
            continue

        if result["empty"]:
            print("(no changes)")
        else:
            print(result["stat"].rstrip())
            if not args.stat_only:
                print()
                print(result["diff"].rstrip())
            total_files += result["files_changed"]
            total_ins += result["insertions"]
            total_del += result["deletions"]

        print()

    print("---")
    if args.branch:
        print(f"{len(branches)} branch(es), {total_files} file(s) changed, +{total_ins} -{total_del} lines")
    else:
        print(f"Layer {args.layer}: {len(branches)} branch(es), {total_files} file(s) changed, +{total_ins} -{total_del} lines")


def cmd_merge(args):
    """Merge an agent branch into main."""
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    from gotg.worktree import (
        ensure_git_repo, merge_branch, abort_merge, is_merge_in_progress,
        list_layer_branches, is_branch_merged, is_worktree_dirty,
        list_active_worktrees, WorktreeError,
    )

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

    if is_merge_in_progress(project_root):
        print("Error: a merge is already in progress.", file=sys.stderr)
        print("Resolve conflicts and commit, or run 'gotg merge --abort'.", file=sys.stderr)
        raise SystemExit(1)

    # Block if main has uncommitted changes
    if is_worktree_dirty(project_root):
        print("Error: uncommitted changes on main.", file=sys.stderr)
        print("Commit or stash changes before merging.", file=sys.stderr)
        raise SystemExit(1)

    if args.branch == "all":
        branches = list_layer_branches(project_root, args.layer)
        if not branches:
            print(f"No branches found for layer {args.layer}.")
            return

        # Filter out already-merged branches
        unmerged = [br for br in branches if not is_branch_merged(project_root, br)]
        if not unmerged:
            print(f"All {len(branches)} branch(es) in layer {args.layer} already merged.")
            return

        # Check for dirty worktrees (hard block unless --force)
        if not args.force:
            active_wts = list_active_worktrees(project_root)
            wt_by_branch = {wt.get("branch"): Path(wt["path"]) for wt in active_wts}
            for br in unmerged:
                if br in wt_by_branch and is_worktree_dirty(wt_by_branch[br]):
                    print(f"Error: uncommitted changes in worktree for {br}.", file=sys.stderr)
                    print("Run 'gotg commit-worktrees' first, or use --force to merge anyway.", file=sys.stderr)
                    raise SystemExit(1)

        merged_count = 0
        for br in unmerged:
            print(f"Merging {br}...")
            try:
                result = merge_branch(project_root, br)
            except WorktreeError as e:
                print(f"\nError merging {br}: {e}", file=sys.stderr)
                print(f"Merged {merged_count}/{len(unmerged)} branches before error.")
                raise SystemExit(1)
            if result["success"]:
                print(f"  Merged: {result['commit']}")
                merged_count += 1
            else:
                print(f"\nCONFLICT merging {br}:")
                for f in result["conflicts"]:
                    print(f"  {f}")
                print(f"\nMerged {merged_count}/{len(unmerged)} branches before conflict.")
                print("Resolve conflicts and commit, then run 'gotg merge all' again,")
                print("or run 'gotg merge --abort' to undo.")
                return

        print(f"\n{merged_count} branch(es) merged into main.")
    else:
        branch = args.branch

        if is_branch_merged(project_root, branch):
            print(f"Branch '{branch}' is already merged into main.")
            return

        # Check dirty worktree (hard block unless --force)
        if not args.force:
            active_wts = list_active_worktrees(project_root)
            wt_by_branch = {wt.get("branch"): Path(wt["path"]) for wt in active_wts}
            if branch in wt_by_branch and is_worktree_dirty(wt_by_branch[branch]):
                print(f"Error: uncommitted changes in worktree for {branch}.", file=sys.stderr)
                print("Run 'gotg commit-worktrees' first, or use --force to merge anyway.", file=sys.stderr)
                raise SystemExit(1)

        try:
            result = merge_branch(project_root, branch)
        except WorktreeError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)

        if result["success"]:
            print(f"Merged {branch} into main: {result['commit']}")
        else:
            print(f"CONFLICT merging {branch}:")
            for f in result["conflicts"]:
                print(f"  {f}")
            print("\nResolve conflicts and commit, or run 'gotg merge --abort' to undo.")


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


def main():
    parser = argparse.ArgumentParser(prog="gotg", description="AI SCRUM team tool")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize a new .team/ directory")
    init_parser.add_argument("path", nargs="?", default=".", help="Project path (default: current directory)")

    run_parser = subparsers.add_parser("run", help="Run the agent conversation")
    run_parser.add_argument("--max-turns", type=int, help="Override max_turns from iteration.json")
    run_parser.add_argument("--layer", type=int, default=None, help="Worktree layer (default: 0)")

    subparsers.add_parser("show", help="Show the conversation log")

    continue_parser = subparsers.add_parser("continue", help="Continue the conversation with optional human input")
    continue_parser.add_argument("-m", "--message", help="Human message to inject before continuing")
    continue_parser.add_argument("--max-turns", type=int, help="Number of new agent turns to run")
    continue_parser.add_argument("--layer", type=int, default=None, help="Worktree layer (default: 0)")

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
    review_parser.add_argument("--layer", type=int, default=0, help="Layer to review (default: 0)")
    review_parser.add_argument("--stat-only", action="store_true", help="Show only file stats, not full diff")
    review_parser.add_argument("branch", nargs="?", default=None, help="Specific branch to review")

    merge_parser = subparsers.add_parser("merge", help="Merge an agent branch into main")
    merge_parser.add_argument("branch", nargs="?", default=None, help="Branch name or 'all'")
    merge_parser.add_argument("--layer", type=int, default=0, help="Layer for 'merge all' (default: 0)")
    merge_parser.add_argument("--abort", action="store_true", help="Abort in-progress merge")
    merge_parser.add_argument("--force", action="store_true", help="Merge even if worktree has uncommitted changes")

    subparsers.add_parser("worktrees", help="List active git worktrees")

    commit_wt_parser = subparsers.add_parser("commit-worktrees", help="Commit all dirty worktrees")
    commit_wt_parser.add_argument("-m", "--message", help="Commit message (default: 'Agent implementation work')")

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
    elif args.command == "commit-worktrees":
        cmd_commit_worktrees(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
