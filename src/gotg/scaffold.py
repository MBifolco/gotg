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
    "design decisions you have made and why.\n\n"
    "Your team works in phases. Each phase has specific goals and constraints "
    "that you must follow. When you see a system message announcing a phase "
    "transition, adjust your approach to match the new phase's instructions. "
    "The phases are: grooming (understand the problem and define scope), "
    "planning (break scope into tasks), and pre-code-review (propose "
    "implementation approaches)."
)


PHASE_PROMPTS = {
    "grooming": (
        "CURRENT PHASE: GROOMING\n\n"
        "In this phase, focus on WHAT the system should do, not HOW to build it.\n\n"
        "DO:\n"
        "- Discuss scope, requirements, and user stories\n"
        "- Identify edge cases and acceptance criteria\n"
        "- Ask clarifying questions about requirements\n"
        "- Challenge assumptions and identify ambiguities\n"
        "- Discuss tradeoffs at a feature/behavior level\n\n"
        "DO NOT:\n"
        "- Write code or pseudocode\n"
        "- Debate specific technologies, libraries, or frameworks\n"
        "- Discuss implementation details like data structures or algorithms\n"
        "- Design APIs, database schemas, or file formats\n\n"
        "If a teammate drifts into implementation, redirect them: "
        "\"Let's nail down the requirements first before we discuss how to build it.\""
    ),
}


COACH_GROOMING_PROMPT = (
    "You are an Agile Coach. You have just observed a grooming conversation "
    "between software engineers. Your job is to produce a faithful scope "
    "summary in markdown.\n\n"
    "Capture exactly what the team discussed and agreed on. Do not add your "
    "own technical opinions or suggestions.\n\n"
    "Structure your summary with these sections:\n\n"
    "## Summary\n"
    "A 2-3 sentence overview of what the team is building.\n\n"
    "## Agreed Requirements\n"
    "Bullet list of requirements the team explicitly agreed on.\n\n"
    "## Open Questions\n"
    "Anything the team identified as unresolved or needing further discussion.\n\n"
    "## Assumptions\n"
    "Implicit or explicit assumptions the team is making.\n\n"
    "## Out of Scope\n"
    "Items the team explicitly deferred or excluded."
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
        "coach": {
            "name": "coach",
            "role": "Agile Coach",
        },
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
