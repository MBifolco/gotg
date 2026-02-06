import argparse
import os
import sys
from pathlib import Path

from gotg.agent import build_prompt
from gotg.config import load_agents, load_iteration, load_model_config, ensure_dotenv_key, read_dotenv
from gotg.conversation import append_message, append_debug, read_log, render_message
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
    debug_path = team_dir / "debug.jsonl"
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

    model_path = team_dir / "model.json"

    if args.provider:
        preset = PROVIDER_PRESETS.get(args.provider)
        if not preset:
            print(f"Error: unknown provider '{args.provider}'. Options: {', '.join(PROVIDER_PRESETS)}", file=sys.stderr)
            raise SystemExit(1)

        config = dict(preset)
        if args.model_name:
            config["model"] = args.model_name

        model_path.write_text(json.dumps(config, indent=2) + "\n")
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
        config = json.loads(model_path.read_text())
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
    elif args.command == "model":
        cmd_model(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
