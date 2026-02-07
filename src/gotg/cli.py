import argparse
import os
import sys
from pathlib import Path

from gotg.agent import build_prompt, build_coach_prompt
from gotg.checkpoint import create_checkpoint, list_checkpoints, restore_checkpoint
from gotg.config import (
    load_agents, load_coach, load_model_config,
    ensure_dotenv_key, read_dotenv,
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


def _auto_checkpoint(iter_dir: Path, iteration: dict) -> None:
    """Create an automatic checkpoint after a command completes."""
    try:
        number = create_checkpoint(iter_dir, iteration, trigger="auto")
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
    turn = sum(1 for msg in history if msg["from"] not in ("human", "coach", "system"))
    num_agents = len(agents)

    print(f"Starting conversation: {iteration['id']}")
    print(f"Task: {iteration['description']}")
    print(f"Phase: {iteration.get('phase', 'grooming')}")
    if coach:
        print(f"Coach: {coach['name']} (facilitating)")
    print(f"Turns: {turn}/{max_turns}")
    print("---")

    while turn < max_turns:
        agent = agents[turn % num_agents]
        prompt = build_prompt(agent, iteration, history, all_participants, groomed_summary=groomed_summary, tasks_summary=tasks_summary)
        append_debug(debug_path, {
            "turn": turn,
            "agent": agent["name"],
            "messages": prompt,
        })
        response = chat_completion(
            base_url=model_config["base_url"],
            model=model_config["model"],
            messages=prompt,
            api_key=model_config.get("api_key"),
            provider=model_config.get("provider", "ollama"),
        )

        msg = {
            "from": agent["name"],
            "iteration": iteration["id"],
            "content": response,
        }
        append_message(log_path, msg)
        print(render_message(msg))
        print()

        history.append(msg)
        turn += 1

        # Coach injection: after every full rotation of engineering agents
        if coach and turn % num_agents == 0:
            coach_prompt = build_coach_prompt(coach, iteration, history, all_participants, groomed_summary=groomed_summary, tasks_summary=tasks_summary)
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

    run_conversation(iter_dir, agents, iteration, model_config, max_turns_override=args.max_turns, coach=coach)
    _auto_checkpoint(iter_dir, iteration)


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

    log_path = iter_dir / "conversation.jsonl"
    history = read_log(log_path)

    # Count current engineering agent turns (not human/coach/system)
    current_agent_turns = sum(1 for msg in history if msg["from"] not in ("human", "coach", "system"))

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

    run_conversation(iter_dir, agents, iteration, model_config, max_turns_override=target_total, coach=coach)
    _auto_checkpoint(iter_dir, iteration)


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
    _auto_checkpoint(iter_dir, iteration)


def cmd_checkpoint(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    iteration, iter_dir = get_current_iteration(team_dir)
    number = create_checkpoint(iter_dir, iteration, description=args.description, trigger="manual")
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
    answer = input("Create checkpoint of current state before restoring? [Y/n] ")
    if answer.strip().lower() not in ("n", "no"):
        number = create_checkpoint(
            iter_dir, iteration,
            description=f"Safety before restore to #{args.number}",
            trigger="manual",
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


def main():
    parser = argparse.ArgumentParser(prog="gotg", description="AI SCRUM team tool")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize a new .team/ directory")
    init_parser.add_argument("path", nargs="?", default=".", help="Project path (default: current directory)")

    run_parser = subparsers.add_parser("run", help="Run the agent conversation")
    run_parser.add_argument("--max-turns", type=int, help="Override max_turns from iteration.json")

    subparsers.add_parser("show", help="Show the conversation log")

    continue_parser = subparsers.add_parser("continue", help="Continue the conversation with optional human input")
    continue_parser.add_argument("-m", "--message", help="Human message to inject before continuing")
    continue_parser.add_argument("--max-turns", type=int, help="Number of new agent turns to run")

    subparsers.add_parser("advance", help="Advance the current iteration to the next phase")

    cp_parser = subparsers.add_parser("checkpoint", help="Create a manual checkpoint")
    cp_parser.add_argument("description", nargs="?", default=None, help="Checkpoint description")

    subparsers.add_parser("checkpoints", help="List checkpoints for current iteration")

    restore_parser = subparsers.add_parser("restore", help="Restore iteration to a checkpoint")
    restore_parser.add_argument("number", type=int, help="Checkpoint number to restore")

    model_parser = subparsers.add_parser("model", help="View or change model config")
    model_parser.add_argument("provider", nargs="?", help="Provider preset: anthropic, openai, ollama")
    model_parser.add_argument("model_name", nargs="?", help="Model name (overrides preset default)")

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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
