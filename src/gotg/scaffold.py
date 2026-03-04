import json
import subprocess
from pathlib import Path

from gotg.errors import ConfigError

from gotg.prompts import (  # noqa: F401 — re-export for backward compatibility
    DEFAULT_SYSTEM_PROMPT, PHASE_PROMPTS,
    COACH_FACILITATION_PROMPT, COACH_FACILITATION_PROMPTS,
    COACH_REFINEMENT_PROMPT,
    COACH_PLANNING_PROMPT, COACH_NOTES_EXTRACTION_PROMPT,
    PHASE_KICKOFF_MESSAGES, AGENT_TOOLS, COACH_TOOLS,
)


def format_agent_task_assignments(
    iter_dir: Path, agents: list[dict], current_layer: int | None = None,
) -> str:
    """Format task assignments grouped by agent for kickoff messages."""
    tasks_path = iter_dir / "tasks.json"
    if not tasks_path.exists():
        return "No tasks assigned yet."
    try:
        from gotg.tasks import TaskRepo
        tasks = TaskRepo(tasks_path).load()
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
    from gotg.phases import get_phase_caps_safe
    caps = get_phase_caps_safe(phase)
    agent_task_assignments = ""
    if iter_dir and caps.include_task_assignments_kickoff:
        layer_arg = current_layer if caps.scope_kickoff_to_layer else None
        agent_task_assignments = format_agent_task_assignments(
            iter_dir, agents, layer_arg,
        )

    # Build writable paths info
    writable_paths_info = ""
    if fileguard and caps.inject_writable_paths_kickoff:
        writable = ", ".join(fileguard.writable_paths) if fileguard.writable_paths else "none"
        writable_paths_info = (
            f"File access: you can read project files and write to: {writable}. "
            "Writes to other paths will be denied."
        )

    task_description = iteration.get("description", "")

    return template.format(
        first_agent=first_agent,
        second_agent=second_agent,
        current_layer=current_layer,
        agent_task_assignments=agent_task_assignments,
        writable_paths_info=writable_paths_info,
        task_description=task_description,
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
        raise ConfigError(f"{team_dir} already exists.")

    # Require git repo
    if not (path / ".git").exists():
        raise ConfigError("not a git repository. Run 'git init' first.")

    # Gitignore .team/ and .env before creating them
    _ensure_gitignore(path)

    # Commit .gitignore so it doesn't show as untracked later
    subprocess.run(
        ["git", "add", ".gitignore"],
        cwd=path, check=True, capture_output=True,
    )
    try:
        subprocess.run(
            ["git", "commit", "-m", "Add .gitignore for gotg"],
            cwd=path, check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, (bytes, bytearray)) else str(e.stderr or "")
        benign = (
            "nothing to commit" in stderr.lower()
            or "author identity unknown" in stderr.lower()
            or "unable to auto-detect email address" in stderr.lower()
        )
        if not benign:
            raise

    team_dir.mkdir(parents=True)

    # team.json: model config + agents
    (team_dir / "team.json").write_text(json.dumps({
        "schema_version": 1,
        "model": {
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "model": "claude-sonnet-4-6",
            "api_key": "$ANTHROPIC_API_KEY",
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
            "enable_approvals": True,
        },
        "worktrees": {
            "enabled": True,
        },
        "streaming": True,
    }, indent=2) + "\n")

    # iteration.json: empty list, no current pointer
    (team_dir / "iteration.json").write_text(json.dumps({
        "schema_version": 1,
        "iterations": [],
        "current": None,
    }, indent=2) + "\n")

    # iterations directory (empty)
    (team_dir / "iterations").mkdir(parents=True)

    print(f"Initialized .team/ in {path.resolve()}")
    print("  .gitignore (added .team/, .env)")
    print("  .team/team.json")
    print("  .team/iteration.json")
    print()
    print("Next: run 'gotg explore start \"topic\"' to explore, or 'gotg new \"description\"' to create an iteration.")
