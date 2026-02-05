import argparse
import sys
from pathlib import Path

from gotg.agent import build_prompt
from gotg.config import load_agents, load_iteration, load_model_config
from gotg.conversation import append_message, read_log, render_message
from gotg.model import chat_completion
from gotg.scaffold import init_project


def find_team_dir(cwd: Path) -> Path | None:
    team = cwd / ".team"
    if team.is_dir():
        return team
    return None


def run_conversation(
    team_dir: Path,
    agents: list[dict],
    iteration: dict,
    model_config: dict,
) -> None:
    log_path = team_dir / "conversation.jsonl"
    history = read_log(log_path)
    max_turns = iteration["max_turns"]
    turn = len(history)

    print(f"Starting conversation: {iteration['id']}")
    print(f"Task: {iteration['description']}")
    print(f"Turns: {turn}/{max_turns}")
    print("---")

    while turn < max_turns:
        agent = agents[turn % len(agents)]
        prompt = build_prompt(agent, iteration, history)
        response = chat_completion(
            base_url=model_config["base_url"],
            model=model_config["model"],
            messages=prompt,
            api_key=model_config.get("api_key"),
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

    iteration = load_iteration(team_dir)
    if not iteration.get("description"):
        print("Error: iteration description is empty. Edit .team/iteration.json first.", file=sys.stderr)
        raise SystemExit(1)
    if iteration.get("status") != "in-progress":
        print(f"Error: iteration status is '{iteration.get('status')}', expected 'in-progress'.", file=sys.stderr)
        raise SystemExit(1)

    model_config = load_model_config(team_dir)
    agents = load_agents(team_dir)

    if len(agents) < 2:
        print("Error: need at least 2 agent configs in .team/agents/.", file=sys.stderr)
        raise SystemExit(1)

    run_conversation(team_dir, agents, iteration, model_config)


def cmd_show(args):
    cwd = Path.cwd()
    team_dir = find_team_dir(cwd)
    if team_dir is None:
        print("Error: no .team/ directory found.", file=sys.stderr)
        raise SystemExit(1)

    log_path = team_dir / "conversation.jsonl"
    messages = read_log(log_path)

    if not messages:
        print("No messages yet.")
        return

    for msg in messages:
        print(render_message(msg))
        print()


def main():
    parser = argparse.ArgumentParser(prog="gotg", description="AI SCRUM team tool")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize a new .team/ directory")
    init_parser.add_argument("path", nargs="?", default=".", help="Project path (default: current directory)")

    subparsers.add_parser("run", help="Run the agent conversation")
    subparsers.add_parser("show", help="Show the conversation log")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "show":
        cmd_show(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
