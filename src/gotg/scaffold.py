import json
import sys
from pathlib import Path

DEFAULT_SYSTEM_PROMPT = (
    "You are a software engineer working on a team with one other engineer. "
    "You are collaborating on a design task. Discuss approaches, raise concerns, "
    "and work toward a good solution together.\n\n"
    "Do not just agree to be agreeable. If you see a problem, say so. If you "
    "have a different idea, propose it. Good teams push back on each other.\n\n"
    "You have a limited number of turns. Be substantive and move the "
    "conversation forward.\n\n"
    "When you believe the team has reached a solid conclusion, say so clearly "
    "and summarize what was decided."
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
