import json
import sys
from pathlib import Path

DEFAULT_SYSTEM_PROMPT = (
    "You are a software engineer working on a team with one other engineer.\n\n"
    "The most important job you have is to talk through design decisions and "
    "not jump to implementation too quickly.\n\n"
    "When another engineer proposes an idea, think through its pros and cons "
    "before agreeing. Unless you think their idea is infallible, propose "
    "alternatives and discuss tradeoffs. Consider edge cases, potential scaling "
    "issues, extensibility to other use cases, bigger projects etc.\n\n"
    "If it's your turn to propose an idea from scratch, try to think through "
    "the problem carefully before proposing a solution. You can ask the other "
    "engineer questions to clarify requirements or constraints.\n\n"
    "Your goal is to reach a solid conclusion on the design of the project "
    "before moving to implementation. Before you write any code you must reach "
    "consensus with the other engineer on the design. Then summarize the "
    "design decisions you have made and why."
)


def init_project(path: Path) -> None:
    team_dir = path / ".team"

    if team_dir.exists():
        print(f"Error: {team_dir} already exists.", file=sys.stderr)
        raise SystemExit(1)

    team_dir.mkdir(parents=True)
    agents_dir = team_dir / "agents"
    agents_dir.mkdir()

    # Model config
    (team_dir / "model.json").write_text(json.dumps({
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "qwen2.5-coder:7b",
    }, indent=2) + "\n")

    # Agent configs
    for i in (1, 2):
        (agents_dir / f"agent-{i}.json").write_text(json.dumps({
            "name": f"agent-{i}",
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
        }, indent=2) + "\n")

    # Iteration config
    (team_dir / "iteration.json").write_text(json.dumps({
        "id": "iter-1",
        "description": "",
        "status": "pending",
        "max_turns": 10,
    }, indent=2) + "\n")

    # Empty conversation log
    (team_dir / "conversation.jsonl").touch()

    print(f"Initialized .team/ in {path.resolve()}")
    print("  .team/model.json")
    print("  .team/agents/agent-1.json")
    print("  .team/agents/agent-2.json")
    print("  .team/iteration.json")
    print("  .team/conversation.jsonl")
    print()
    print("Next: edit .team/iteration.json to set your task description and status to 'in-progress'.")
