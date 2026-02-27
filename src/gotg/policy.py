from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gotg.prompts import (
    AGENT_TOOLS,
    COACH_TOOLS,
    GROOMING_COACH_PROMPT,
    GROOMING_COACH_TOOLS,
    GROOMING_KICKOFF_TEMPLATE,
    GROOMING_KICKOFF_WITH_CONTEXT_AND_TOOLS_TEMPLATE,
    GROOMING_KICKOFF_WITH_CONTEXT_TEMPLATE,
    GROOMING_SYSTEM_SUPPLEMENT,
    GROOMING_SYSTEM_SUPPLEMENT_WITH_CONTEXT,
)
from gotg.scaffold import should_inject_kickoff, format_phase_kickoff
from gotg.tasks import TaskRepo, format_tasks_summary
from gotg.tools import FILE_TOOLS, READ_ONLY_FILE_TOOLS


@dataclass(frozen=True)
class SessionPolicy:
    """Configures engine behavior for a conversation session."""

    # Behavioral config
    max_turns: int
    coach: dict | None
    coach_cadence: int | None
    stop_on_phase_complete: bool
    stop_on_ask_pm: bool
    # Tools (immutable tuples — engine copies with list() at use site)
    agent_tools: tuple[dict, ...]
    coach_tools: tuple[dict, ...] | None  # None when no coach (NOT empty — truthiness)
    # Content artifacts
    groomed_summary: str | None
    tasks_summary: str | None
    diffs_summary: str | None
    kickoff_text: str | None
    # Infrastructure
    fileguard: object | None
    approval_store: object | None
    worktree_map: dict | None
    # Prompt supplements (grooming mode)
    system_supplement: str | None     # Extra text injected early in agent system prompt
    coach_system_prompt: str | None   # Overrides phase-based coach facilitation prompt
    # Phase context
    phase_skeleton: str | None = None  # Compressed prior-phase context
    project_context: str | None = None  # Iteration artifacts for context injection (grooming, cross-iteration)
    # Streaming
    streaming: bool = False           # opt-in via team.json, default off for safe rollout


def iteration_policy(
    agents: list[dict],
    iteration: dict,
    iter_dir: Path,
    history: list[dict],
    coach: dict | None = None,
    fileguard=None,
    approval_store=None,
    worktree_map: dict | None = None,
    diffs_summary: str | None = None,
    max_turns_override: int | None = None,
    streaming: bool = False,
) -> SessionPolicy:
    """Build policy for an iteration conversation.

    Loads refinement_summary.md and tasks.json artifacts from iter_dir.
    Computes kickoff text from history.
    Assembles tool tuples based on fileguard presence.
    Sets coach_tools=None when no coach.
    """
    max_turns = max_turns_override if max_turns_override is not None else iteration["max_turns"]

    # Load refinement_summary.md artifact
    summary_path = iter_dir / "refinement_summary.md"
    groomed_summary = summary_path.read_text().strip() if summary_path.exists() else None

    # Load phase skeleton (compressed prior-phase context)
    skeleton_path = iter_dir / "phase_skeleton.md"
    phase_skeleton = skeleton_path.read_text().strip() if skeleton_path.exists() else None

    # Load tasks.json artifact
    tasks_path = iter_dir / "tasks.json"
    tasks_summary = None
    if tasks_path.exists():
        tasks_data = TaskRepo(tasks_path).load()
        from gotg.phases import get_phase_caps_safe
        caps = get_phase_caps_safe(iteration.get("phase"))
        impl_layer = iteration.get("current_layer") if caps.filter_tasks_by_layer else None
        tasks_summary = format_tasks_summary(tasks_data, layer=impl_layer)

    # Pre-compute kickoff
    phase = iteration.get("phase", "refinement")
    kickoff_text = None
    if should_inject_kickoff(history, phase):
        text = format_phase_kickoff(phase, agents, iteration, fileguard, iter_dir)
        if text:
            kickoff_text = text

    # Build tool tuples
    if fileguard:
        agent_tools = tuple(list(AGENT_TOOLS) + list(FILE_TOOLS))
    else:
        agent_tools = tuple(AGENT_TOOLS)

    coach_tools = tuple(COACH_TOOLS) if coach else None

    return SessionPolicy(
        max_turns=max_turns,
        coach=coach,
        coach_cadence=len(agents) if coach else None,
        stop_on_phase_complete=True,
        stop_on_ask_pm=True,
        agent_tools=agent_tools,
        coach_tools=coach_tools,
        groomed_summary=groomed_summary,
        tasks_summary=tasks_summary,
        diffs_summary=diffs_summary,
        kickoff_text=kickoff_text,
        fileguard=fileguard,
        approval_store=approval_store,
        worktree_map=worktree_map,
        system_supplement=None,
        coach_system_prompt=None,
        phase_skeleton=phase_skeleton,
        streaming=streaming,
    )


def grooming_policy(
    agents: list[dict],
    topic: str,
    history: list[dict],
    coach: dict | None = None,
    max_turns: int = 30,
    streaming: bool = False,
    project_context: str | None = None,
    project_root: Path | None = None,
    file_access: dict | None = None,
) -> SessionPolicy:
    """Build policy for a freeform grooming conversation."""
    first_agent = agents[0]["name"] if agents else "agent-1"

    # Build read-only file tools + fileguard when file_access is configured
    fileguard = None
    read_only_tools: tuple[dict, ...] = ()
    if project_root and file_access:
        from gotg.fileguard import FileGuard
        read_only_config = {**file_access, "writable_paths": [], "enable_approvals": False}
        fileguard = FileGuard(project_root, read_only_config)
        read_only_tools = tuple(READ_ONLY_FILE_TOOLS)

    agent_tools = tuple(list(AGENT_TOOLS) + list(read_only_tools))

    # Select system supplement based on context availability
    system_supplement = (
        GROOMING_SYSTEM_SUPPLEMENT_WITH_CONTEXT if project_context
        else GROOMING_SYSTEM_SUPPLEMENT
    )

    # Only inject kickoff on first run (empty history)
    kickoff_text = None
    if not history:
        if project_context and fileguard:
            kickoff_text = GROOMING_KICKOFF_WITH_CONTEXT_AND_TOOLS_TEMPLATE.format(
                topic=topic, first_agent=first_agent,
            )
        elif project_context:
            kickoff_text = GROOMING_KICKOFF_WITH_CONTEXT_TEMPLATE.format(
                topic=topic, first_agent=first_agent,
            )
        else:
            kickoff_text = GROOMING_KICKOFF_TEMPLATE.format(
                topic=topic, first_agent=first_agent,
            )

    return SessionPolicy(
        max_turns=max_turns,
        coach=coach,
        coach_cadence=len(agents) if coach else None,
        stop_on_phase_complete=False,
        stop_on_ask_pm=bool(coach),
        agent_tools=agent_tools,
        coach_tools=tuple(GROOMING_COACH_TOOLS) if coach else None,
        groomed_summary=None,
        tasks_summary=None,
        diffs_summary=None,
        kickoff_text=kickoff_text,
        fileguard=fileguard,
        approval_store=None,
        worktree_map=None,
        system_supplement=system_supplement,
        coach_system_prompt=GROOMING_COACH_PROMPT if coach else None,
        project_context=project_context,
        streaming=streaming,
    )
