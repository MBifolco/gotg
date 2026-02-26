"""Declarative phase capability table.

Co-locates all phase-specific behavior knowledge in one place,
replacing scattered ``if phase == "X"`` checks across the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseCapabilities:
    """Declarative capabilities for a single phase."""

    requires_tasks: bool = False
    requires_task_assignment: bool = False
    filter_tasks_by_layer: bool = False
    inject_file_access_prompt: bool = False
    inject_writable_paths_kickoff: bool = False
    include_task_assignments_kickoff: bool = False
    scope_kickoff_to_layer: bool = False
    enable_worktrees: bool = False
    filter_worktree_agents_by_tasks: bool = False
    use_implementation_executor: bool = False
    supports_next_layer: bool = False
    phase_complete_shows_review_hint: bool = False
    can_open_review_screen: bool = False
    show_task_status_bar: bool = False
    auto_open_task_assign_on_advance: bool = False


PHASE_CAPS: dict[str, PhaseCapabilities] = {
    "refinement": PhaseCapabilities(),
    "planning": PhaseCapabilities(),
    "pre-code-review": PhaseCapabilities(
        requires_tasks=True,
        requires_task_assignment=True,
        include_task_assignments_kickoff=True,
        show_task_status_bar=True,
        auto_open_task_assign_on_advance=True,
    ),
    "implementation": PhaseCapabilities(
        requires_tasks=True,
        requires_task_assignment=True,
        filter_tasks_by_layer=True,
        inject_file_access_prompt=True,
        inject_writable_paths_kickoff=True,
        include_task_assignments_kickoff=True,
        scope_kickoff_to_layer=True,
        enable_worktrees=True,
        filter_worktree_agents_by_tasks=True,
        use_implementation_executor=True,
        supports_next_layer=True,
        can_open_review_screen=True,
        show_task_status_bar=True,
    ),
    "code-review": PhaseCapabilities(
        inject_file_access_prompt=True,
        inject_writable_paths_kickoff=True,
        include_task_assignments_kickoff=True,
        scope_kickoff_to_layer=True,
        enable_worktrees=True,
        supports_next_layer=True,
        phase_complete_shows_review_hint=True,
        can_open_review_screen=True,
    ),
}

_EMPTY = PhaseCapabilities()


def get_phase_caps(phase: str | None) -> PhaseCapabilities:
    """Look up capabilities for a phase (strict).

    Returns empty caps for None (grooming/no phase).
    Raises ValueError for unknown non-None phases (catches typos).
    Use this in core paths (session.py) where callers translate
    ValueError into domain errors (SessionSetupError, ReviewError).
    """
    if phase is None:
        return _EMPTY
    if phase not in PHASE_CAPS:
        raise ValueError(
            f"Unknown phase {phase!r}. "
            f"Valid phases: {', '.join(PHASE_CAPS)}"
        )
    return PHASE_CAPS[phase]


def get_phase_caps_safe(phase: str | None) -> PhaseCapabilities:
    """Look up capabilities for a phase (lenient).

    Returns empty caps for None OR unknown phases.
    Logs a warning for unknown non-None phases.
    Use this in downstream/presentation paths (policy.py, scaffold.py,
    console_events.py, agent.py, tui/).
    """
    if phase is None:
        return _EMPTY
    if phase not in PHASE_CAPS:
        import logging

        logging.getLogger("gotg.phases").warning(
            "Unknown phase %r in capability lookup", phase
        )
        return _EMPTY
    return PHASE_CAPS[phase]
