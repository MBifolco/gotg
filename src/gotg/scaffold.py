import json
import subprocess
import sys
from pathlib import Path

DEFAULT_SYSTEM_PROMPT = (
    "You are a software engineer working on a collaborative team.\n\n"
    "When a teammate proposes an idea, think through its pros and cons "
    "before agreeing. Unless you think their idea is infallible, propose "
    "alternatives and discuss tradeoffs. Consider edge cases, potential scaling "
    "issues, extensibility to other use cases, bigger projects etc.\n\n"
    "If it's your turn to propose an idea from scratch, think through "
    "the problem carefully before proposing a solution. You can ask your "
    "teammates questions to clarify requirements or constraints.\n\n"
    "Your team works in phases. Each phase has specific goals and constraints "
    "that you must follow. The current phase instructions tell you exactly "
    "what to focus on and what to avoid. Follow them closely.\n\n"
    "The phases are: grooming (understand the problem and define scope), "
    "planning (break scope into tasks), pre-code-review (propose "
    "implementation approaches), implementation (write code for your "
    "assigned tasks), and code-review (review implementation "
    "diffs). Each phase builds on the previous one.\n\n"
    "Be concise. State only new information — do not repeat what teammates "
    "have already said. If you agree with a proposal, say so in one sentence "
    "and move on; silence on a specific point means approval. When reviewing "
    "a teammate's proposal, comment only on what you would change or what "
    "concerns you.\n\n"
    "Keep messages to short prose paragraphs. Avoid checkbox formatting "
    "and agreement checklists. Bullets are fine for brief lists but do not "
    "pad them. Do not use emoji."
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
    "planning": (
        "CURRENT PHASE: PLANNING\n\n"
        "You have completed grooming. The scope is defined in the groomed summary below.\n\n"
        "In this phase, break the agreed scope into concrete, assignable tasks.\n\n"
        "DO:\n"
        "- Decompose each requirement into specific engineering tasks\n"
        "- Ensure each task is independent and completable by one engineer\n"
        "- Identify dependencies between tasks and note their ordering\n"
        "- Define what 'done' looks like for each task\n"
        "- Consider which tasks can be parallelized\n\n"
        "DO NOT:\n"
        "- Write code or pseudocode\n"
        "- Re-debate requirements that were settled in grooming\n"
        "- Pick specific libraries, frameworks, or tools\n"
        "- Design APIs, schemas, or internal interfaces\n\n"
        "If a teammate re-opens a settled requirement, redirect them: "
        "\"That was decided in grooming. Let's focus on breaking it into tasks.\""
    ),
    "pre-code-review": (
        "CURRENT PHASE: PRE-CODE-REVIEW\n\n"
        "Propose implementation approaches for YOUR assigned tasks. Keep it "
        "brief — the goal is interface alignment, not detailed design. "
        "Work through tasks layer by layer, starting from Layer 0.\n\n"
        "For each of your tasks, state in one short message:\n"
        "- Files you will create or modify\n"
        "- Public function/method signatures with types\n"
        "- How dependent tasks should call your code\n"
        "- Any questions for teammates whose tasks yours depends on\n\n"
        "For teammate tasks: respond ONLY if you see a mismatch between their "
        "proposed interface and what your code needs. Silence means the "
        "interface works for you.\n\n"
        "Do not write full implementations, pseudocode, or test code. Do not "
        "discuss internal implementation details — those are your choice to make "
        "during implementation."
    ),
    "implementation": (
        "CURRENT PHASE: IMPLEMENTATION\n\n"
        "You have completed design discussions. The task list and agreed "
        "implementation approaches are below. Now write the actual code.\n\n"
        "You are implementing layer {current_layer} tasks ONLY. Do not work on "
        "tasks from other layers. Complete your current-layer tasks, report "
        "completion, and wait.\n\n"
        "You are working in your own git branch via a worktree. Use the "
        "file tools (file_read, file_write, file_list) to read existing code "
        "and write your implementation.\n\n"
        "For YOUR assigned tasks in the current layer:\n"
        "- Read existing code to understand the codebase structure\n"
        "- Write implementation code following the agreed approach\n"
        "- Write tests for your implementation\n"
        "- Keep changes focused on your assigned tasks\n\n"
        "Coordinate with teammates:\n"
        "- If your task depends on another task's output, check if that "
        "code exists yet and adapt accordingly\n"
        "- Share what files you're working on to avoid conflicts\n"
        "- Ask questions if the agreed approach is unclear\n\n"
        "When your tasks for this layer are complete, let the team know. "
        "The coach will check in on progress periodically.\n\n"
        "DO:\n"
        "- Use file_read to understand existing code before modifying\n"
        "- Use file_write to create/update source and test files\n"
        "- Follow the implementation approach agreed in pre-code-review\n"
        "- Write tests alongside your implementation\n"
        "- Communicate what you're working on\n\n"
        "DO NOT:\n"
        "- Modify files outside your assigned tasks\n"
        "- Re-debate the design approach (that was settled in pre-code-review)\n"
        "- Skip writing tests\n"
        "- Work on tasks from a different layer than the current one\n\n"
        "Redirect: \"That design decision was settled. Let's focus on "
        "writing the code.\""
    ),
    "code-review": (
        "CURRENT PHASE: CODE REVIEW\n\n"
        "If implementation diffs are included below, review the changes in each "
        "agent's branch for this layer. If no diffs are present, discuss "
        "implementation status and any concerns based on what you know so far.\n\n"
        "You are reviewing your teammates' implementations. Focus on:\n"
        "- Correctness: Does the code do what the task requires?\n"
        "- Consistency: Do components work together? Are interfaces compatible?\n"
        "- Requirements adherence: Does it match the groomed scope?\n"
        "- Test coverage: Are there tests? Do they cover edge cases?\n"
        "- Code quality: Naming, structure, duplication, error handling\n\n"
        "For YOUR implementation:\n"
        "- Defend your choices when questioned — explain your reasoning\n"
        "- Acknowledge valid concerns and describe what you would change\n\n"
        "For TEAMMATE implementations:\n"
        "- Suggest specific changes — reference file names and describe what should change\n"
        "- Approve explicitly when you think code is ready\n\n"
        "DO: Reference specific files/changes from diffs, raise interface mismatch concerns,\n"
        "    suggest concrete improvements, explicitly approve or request changes\n"
        "DO NOT: Re-open planning decisions, propose new tasks, write full replacement code,\n"
        "        rubber-stamp without reviewing\n\n"
        "Redirect: \"That was decided earlier. Let's focus on reviewing the implementation.\""
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


COACH_PLANNING_PROMPT = (
    "You are an Agile Coach. You have just observed a planning conversation "
    "between software engineers. Your job is to extract the task list they "
    "discussed and produce a structured JSON array.\n\n"
    "Capture exactly what the team discussed and agreed on. Do not add tasks "
    "they did not mention. Do not omit tasks they agreed on.\n\n"
    "Output ONLY a valid JSON array with no markdown code fences, no commentary, "
    "and no text before or after the JSON. The output must be parseable by "
    "json.loads() directly.\n\n"
    "Each task object must have exactly these fields:\n"
    '- "id": a short kebab-case identifier (e.g., "basic-timer", "state-persistence")\n'
    '- "description": what needs to be built or changed (1-3 sentences)\n'
    '- "done_criteria": how to verify the task is complete (1-2 sentences)\n'
    '- "depends_on": array of task id strings this task depends on (empty array if none)\n'
    '- "assigned_to": null (will be assigned later by the PM)\n'
    '- "status": "pending"\n\n'
    "Example output format:\n"
    "[\n"
    "  {\n"
    '    "id": "basic-timer",\n'
    '    "description": "Implement the core countdown timer with configurable duration.",\n'
    '    "done_criteria": "Timer counts down from N seconds and signals completion.",\n'
    '    "depends_on": [],\n'
    '    "assigned_to": null,\n'
    '    "status": "pending"\n'
    "  }\n"
    "]\n"
)


COACH_FACILITATION_PROMPT = (
    "You are an Agile Coach facilitating this conversation. "
    "You do NOT contribute technical opinions or suggest solutions.\n\n"
    "Your job is to:\n"
    "1. Summarize what the team has agreed on so far\n"
    "2. List what remains unresolved\n"
    "3. Ask the team to address the most important unresolved item next\n"
    "4. Before signaling completion, ask the team: 'Is there anything we "
    "haven't discussed that should be in scope? Any requirements, edge "
    "cases, or user scenarios we've missed?'\n"
    "5. If the team confirms nothing is missing and all scope items are "
    "resolved or explicitly deferred, use the signal_phase_complete tool "
    "to recommend advancing to the next phase\n\n"
    "Keep your messages concise — shorter than the engineers' messages. "
    "The engineers are the experts. You manage the process."
)


COACH_FACILITATION_PROMPTS = {
    "grooming": COACH_FACILITATION_PROMPT,

    "planning": (
        "You are an Agile Coach facilitating this conversation. "
        "You do NOT contribute technical opinions or suggest solutions.\n\n"
        "The team is in the PLANNING phase — breaking agreed scope into "
        "concrete, assignable tasks with dependencies and done criteria.\n\n"
        "Your job is to:\n"
        "1. Summarize which tasks have been defined so far\n"
        "2. Note which requirements from the groomed scope don't have "
        "corresponding tasks yet\n"
        "3. Ask the team to address gaps\n"
        "4. Ensure each task has clear done criteria and dependencies\n"
        "5. Before signaling completion, ask the team: 'Have we covered "
        "every requirement from the groomed scope? Are there any tasks "
        "missing or dependencies we haven't identified?'\n"
        "6. If the team confirms all requirements are covered and task "
        "definitions are complete, use the signal_phase_complete tool "
        "to recommend advancing to the next phase\n\n"
        "Keep your messages concise — shorter than the engineers' messages. "
        "The engineers are the experts. You manage the process."
    ),

    "pre-code-review": (
        "You are an Agile Coach facilitating this conversation. "
        "You do NOT contribute technical opinions.\n\n"
        "The team is proposing implementation approaches. Guide them through "
        "tasks layer by layer. After each agent presents their proposals for "
        "a layer, check: does any engineer see an interface mismatch? If not, "
        "move to the next layer.\n\n"
        "Signal completion when all layers have been presented and all "
        "interface concerns resolved. Most tasks should need only one round "
        "of discussion."
    ),

    "implementation": (
        "You are an Agile Coach facilitating implementation. You do NOT "
        "contribute code or technical opinions.\n\n"
        "The team is in the IMPLEMENTATION phase — agents are writing code "
        "for their assigned tasks using file tools in their worktrees.\n\n"
        "Your job:\n"
        "1. Track implementation progress — which agents are working on "
        "which tasks\n"
        "2. Periodically ask each agent for a status update on their tasks\n"
        "3. If an agent seems stuck, ask them to describe the blocker\n"
        "4. Summarize: who is done, who is still working, any blockers "
        "raised\n"
        "5. Before signaling completion, ask EVERY agent directly: 'Are "
        "your current-layer tasks complete?' List each agent and their "
        "response\n"
        "6. Only use the signal_phase_complete tool when all agents have "
        "confirmed their tasks are done. If any agent has not confirmed, "
        "do NOT signal\n\n"
        "Keep your messages concise. Engineers are doing the work. "
        "You track progress."
    ),

    "code-review": (
        "You are an Agile Coach facilitating code review. You do NOT contribute "
        "technical opinions.\n\n"
        "Your job:\n"
        "1. Track open review concerns — specific issues raised about specific "
        "branches/files\n"
        "2. A concern is RESOLVED when the author acknowledges it AND the reviewer "
        "accepts the resolution (either agree to change or explain why it stays)\n"
        "3. Periodically summarize: which branches reviewed, open concerns, "
        "resolved concerns\n"
        "4. Ensure every branch gets reviewed — direct team to unreviewed branches\n"
        "5. Before signaling: list ALL open concerns. If any unresolved, do NOT "
        "signal — direct team to address them\n"
        "6. Signal completion only when all concerns resolved and every branch "
        "reviewed. Include outcome: approved (all resolved) or changes-requested "
        "(with summary)\n\n"
        "Keep your messages concise. Engineers are experts. You manage the process."
    ),
}


COACH_TOOLS = [
    {
        "name": "signal_phase_complete",
        "description": (
            "Signal that all scope items are resolved or explicitly deferred "
            "and the team is ready to advance to the next phase. Only call "
            "this after the team confirms nothing is missing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of what was resolved in this phase",
                }
            },
            "required": ["summary"],
        },
    }
]


PHASE_KICKOFF_MESSAGES = {
    "grooming": (
        "--- Phase: grooming ---\n"
        "Goal: define WHAT to build — scope, requirements, edge cases. "
        "Do not discuss HOW to build it.\n\n"
        "{first_agent}, what's your read on the requirements? "
        "What ambiguities or edge cases do you see?\n\n"
        "The coach will facilitate from here."
    ),
    "planning": (
        "--- Phase: planning ---\n"
        "Goal: break the groomed scope into concrete, assignable tasks "
        "with dependencies and done criteria. The groomed scope is "
        "available above.\n\n"
        "{first_agent}, propose an initial task breakdown. {second_agent}, "
        "review it and suggest modifications.\n\n"
        "The coach will facilitate from here."
    ),
    "pre-code-review": (
        "--- Phase: pre-code-review ---\n"
        "Goal: interface alignment. Each engineer proposes their approach "
        "for their assigned tasks — briefly. State: (1) files you'll "
        "create/modify, (2) public function signatures, (3) how dependent "
        "tasks should call your code.\n\n"
        "One message per task. Respond to teammates ONLY if you see an "
        "interface mismatch. Silence means the interface works for you.\n\n"
        "{agent_task_assignments}\n\n"
        "The coach will facilitate from here."
    ),
    "implementation": (
        "--- Phase: implementation (layer {current_layer}) ---\n"
        "{agent_task_assignments}\n\n"
        "{writable_paths_info}\n\n"
        "Write your code, then report completion with a brief summary "
        "of what you created. Do not discuss — just implement. If you "
        "have a blocking question, ask it specifically.\n\n"
        "The coach will facilitate from here."
    ),
    "code-review": (
        "--- Phase: code-review (layer {current_layer}) ---\n"
        "Implementation diffs are included above (if available). "
        "Review your teammates' code against the task requirements.\n\n"
        "For each branch: approve, or raise specific concerns with "
        "file names and line references. One message per reviewer.\n\n"
        "The coach will facilitate from here."
    ),
}


def format_agent_task_assignments(
    iter_dir: Path, agents: list[dict], current_layer: int | None = None,
) -> str:
    """Format task assignments grouped by agent for kickoff messages."""
    tasks_path = iter_dir / "tasks.json"
    if not tasks_path.exists():
        return "No tasks assigned yet."
    try:
        tasks = json.loads(tasks_path.read_text())
    except (json.JSONDecodeError, OSError):
        return "No tasks assigned yet."
    if not tasks:
        return "No tasks assigned yet."

    if current_layer is not None:
        tasks = [t for t in tasks if t.get("layer") == current_layer]

    agent_names = [a["name"] for a in agents]
    lines = []
    for name in agent_names:
        agent_tasks = [t for t in tasks if t.get("assigned_to") == name]
        if agent_tasks:
            task_ids = ", ".join(t["id"] for t in agent_tasks)
            lines.append(f"{name}: {task_ids}")
    if not lines:
        return "No tasks assigned yet."
    return "Task assignments: " + ". ".join(lines) + "."


def should_inject_kickoff(history: list[dict], phase: str) -> bool:
    """Determine if a phase kickoff message should be injected.

    Returns True when:
    - Conversation is empty (first run)
    - A phase transition exists in history but no kickoff has been injected after it
    """
    if not history:
        return True

    # Find the last phase-transition system message
    transition_idx = None
    for i in range(len(history) - 1, -1, -1):
        msg = history[i]
        if msg.get("from") != "system":
            continue
        content = msg.get("content", "")
        if content.startswith("--- Phase advanced:") or content.startswith("--- Layer"):
            transition_idx = i
            break

    if transition_idx is None:
        return False  # No transition found — mid-phase resume

    # Check if a kickoff already exists after the transition
    for msg in history[transition_idx + 1:]:
        if msg.get("from") == "system" and msg.get("content", "").startswith("--- Phase:"):
            return False  # Kickoff already injected

    return True


def format_phase_kickoff(
    phase: str,
    agents: list[dict],
    iteration: dict,
    fileguard=None,
    iter_dir: Path | None = None,
) -> str:
    """Format a phase kickoff message with resolved template variables."""
    template = PHASE_KICKOFF_MESSAGES.get(phase)
    if not template:
        return ""

    first_agent = agents[0]["name"] if agents else "agent-1"
    second_agent = agents[1]["name"] if len(agents) > 1 else first_agent
    current_layer = iteration.get("current_layer", 0)

    # Build agent task assignments
    agent_task_assignments = ""
    if iter_dir:
        if phase in ("implementation", "code-review"):
            agent_task_assignments = format_agent_task_assignments(
                iter_dir, agents, current_layer,
            )
        elif phase == "pre-code-review":
            agent_task_assignments = format_agent_task_assignments(iter_dir, agents)

    # Build writable paths info
    writable_paths_info = ""
    if fileguard and phase in ("implementation", "code-review"):
        writable = ", ".join(fileguard.writable_paths) if fileguard.writable_paths else "none"
        writable_paths_info = (
            f"File access: you can read project files and write to: {writable}. "
            "Writes to other paths will be denied."
        )

    return template.format(
        first_agent=first_agent,
        second_agent=second_agent,
        current_layer=current_layer,
        agent_task_assignments=agent_task_assignments,
        writable_paths_info=writable_paths_info,
    )


def _ensure_gitignore(path: Path) -> None:
    """Add .team/ and .env to .gitignore so they're never tracked."""
    gitignore = path / ".gitignore"
    entries = ["/.team/", ".env", "/.worktrees/"]

    if gitignore.exists():
        content = gitignore.read_text()
    else:
        content = ""

    existing = {line.strip() for line in content.splitlines()}
    added = [e for e in entries if e not in existing]

    if added:
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n".join(added) + "\n"
        gitignore.write_text(content)


def init_project(path: Path) -> None:
    team_dir = path / ".team"

    if team_dir.exists():
        print(f"Error: {team_dir} already exists.", file=sys.stderr)
        raise SystemExit(1)

    # Require git repo
    if not (path / ".git").exists():
        print("Error: not a git repository. Run 'git init' first.", file=sys.stderr)
        raise SystemExit(1)

    # Gitignore .team/ and .env before creating them
    _ensure_gitignore(path)

    # Commit .gitignore so it doesn't show as untracked later
    subprocess.run(
        ["git", "add", ".gitignore"],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add .gitignore for gotg"],
        cwd=path, check=True, capture_output=True,
    )

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
        "file_access": {
            "writable_paths": ["src/**", "tests/**", "docs/**"],
            "protected_paths": [],
            "max_file_size_bytes": 1048576,
            "max_files_per_turn": 10,
            "enable_approvals": False,
        },
        "worktrees": {
            "enabled": False,
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
    print("  .gitignore (added .team/, .env)")
    print("  .team/team.json")
    print("  .team/iteration.json")
    print(f"  .team/iterations/{iter_id}/conversation.jsonl")
    print()
    print("Next: edit .team/iteration.json to set your task description and status to 'in-progress'.")
