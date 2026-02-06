import json
import sys
from pathlib import Path

DEFAULT_SYSTEM_PROMPT = (
    "You are a software engineer working on a collaborative team.\n\n"
    "The most important job you have is to talk through design decisions and "
    "not jump to implementation too quickly.\n\n"
    "When a teammate proposes an idea, think through its pros and cons "
    "before agreeing. Unless you think their idea is infallible, propose "
    "alternatives and discuss tradeoffs. Consider edge cases, potential scaling "
    "issues, extensibility to other use cases, bigger projects etc.\n\n"
    "If it's your turn to propose an idea from scratch, try to think through "
    "the problem carefully before proposing a solution. You can ask your "
    "teammates questions to clarify requirements or constraints.\n\n"
    "Your goal is to reach a solid conclusion on the design of the project "
    "before moving to implementation. Before you write any code you must reach "
    "consensus with your team on the design. Then summarize the "
    "design decisions you have made and why."
)


def init_project(path: Path) -> None:
    team_dir = path / ".team"

    if team_dir.exists():
        print(f"Error: {team_dir} already exists.", file=sys.stderr)
        raise SystemExit(1)

    team_dir.mkdir(parents=True)

    # team.json: model config + agents
    (team_dir / "team.json").write_text(json.dumps({
        "model": {
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:7b",
        },
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
    }, indent=2) + "\n")

    # iteration.json: list format with current pointer
    iter_id = "iter-1"
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [
            {
                "id": iter_id,
                "title": "",
                "description": "",
                "status": "pending",
                "phase": "grooming",
                "max_turns": 10,
            }
        ],
        "current": iter_id,
    }, indent=2) + "\n")

    # Iteration directory with empty conversation log
    iter_dir = team_dir / "iterations" / iter_id
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    print(f"Initialized .team/ in {path.resolve()}")
    print("  .team/team.json")
    print("  .team/iteration.json")
    print(f"  .team/iterations/{iter_id}/conversation.jsonl")
    print()
    print("Next: edit .team/iteration.json to set your task description and status to 'in-progress'.")
