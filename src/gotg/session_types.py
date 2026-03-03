"""Shared exceptions, dataclasses, enums, and utilities for session modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gotg.conversation import ConversationStore
    from gotg.engine import SessionDeps
    from gotg.policy import SessionPolicy

__all__ = [
    # Exceptions
    "SessionSetupError",
    "PhaseAdvanceError",
    "ReviewError",
    "ReworkError",
    # Enums
    "PauseReason",
    "ResolutionStrategy",
    # Dataclasses
    "BranchReview",
    "ReviewResult",
    "MergeResult",
    "NextLayerResult",
    "AdvanceResult",
    "ReworkResult",
    "ResumeState",
    "ConflictFileInfo",
    "ConflictInfo",
    "AiResolutionResult",
    "SessionInfra",
    "SessionSetup",
    "ContinueContext",
    # Utilities
    "resolve_layer",
    "reconstruct_resume_state",
]


class SessionSetupError(Exception):
    """Raised when session setup fails. Caller decides how to display."""
    pass


class PhaseAdvanceError(Exception):
    """Raised when phase advance cannot proceed. Caller decides how to display."""
    pass


class ReviewError(Exception):
    """Raised when review/merge/next-layer cannot proceed. Caller decides how to display."""
    pass


class ReworkError(Exception):
    """Raised when rework cannot proceed. Caller decides how to display."""
    pass


@dataclass
class BranchReview:
    """Diff data for one agent branch."""
    branch: str
    merged: bool
    empty: bool
    stat: str
    diff: str
    files_changed: int
    insertions: int
    deletions: int


@dataclass
class ReviewResult:
    """Collection of branch diffs for a layer."""
    layer: int
    branches: list[BranchReview]
    total_files: int
    total_insertions: int
    total_deletions: int


@dataclass
class MergeResult:
    """Result of merging a single branch."""
    branch: str
    success: bool
    commit: str | None = None
    conflicts: list[str] = field(default_factory=list)


@dataclass
class NextLayerResult:
    """Result of next-layer advance."""
    from_layer: int
    to_layer: int | None
    all_done: bool
    boundary_msg: dict | None = None
    transition_msg: dict | None = None
    task_count: int = 0
    removed_worktrees: list[str] = field(default_factory=list)


@dataclass
class AdvanceResult:
    """Result of a successful phase advance."""
    from_phase: str
    to_phase: str
    boundary_msg: dict
    transition_msg: dict
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReworkResult:
    """Result of a successful rework transition."""
    layer: int
    tasks_with_feedback: list[str]  # task IDs that got feedback
    boundary_msg: dict
    transition_msg: dict
    warnings: list[str] = field(default_factory=list)


class PauseReason(Enum):
    """Why a session is paused. Domain knowledge, not UI state."""
    APPROVALS = auto()
    COACH_QUESTION = auto()
    PHASE_COMPLETE = auto()
    ITERATIONS_PROPOSED = auto()


@dataclass
class ResumeState:
    """Reconstructed session state from persisted messages."""
    pause_reason: PauseReason | None = None
    phase_complete_shows_review: bool = False
    phase_complete_outcome: str = "approved"
    ask_pm_data: dict | None = None
    show_task_status_bar: bool = False
    iteration_proposals: dict | None = None


class ResolutionStrategy(Enum):
    """How a conflict file was resolved."""
    OURS = "ours"
    THEIRS = "theirs"
    AI = "ai"


@dataclass
class ConflictFileInfo:
    """3-way merge content for a single conflicted file."""
    path: str
    base_content: str | None  # stage 1 — None for add/add conflicts
    ours_content: str         # stage 2 (main)
    theirs_content: str       # stage 3 (branch)
    working_content: str      # file on disk with conflict markers


@dataclass
class ConflictInfo:
    """All conflicted files for a merge-in-progress."""
    branch: str
    files: list[ConflictFileInfo]


@dataclass
class AiResolutionResult:
    """Successful AI-assisted conflict resolution."""
    path: str
    resolved_content: str
    explanation: str


@dataclass
class SessionInfra:
    """Infrastructure built from team config for a session."""
    fileguard: object | None
    approval_store: object | None
    worktree_map: dict | None
    diffs_summary: str | None
    streaming: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class SessionSetup:
    """Everything needed to run a session.

    Built by prepare_session() or manually by consumers with different
    policy factories (e.g. exploration uses exploration_policy, not iteration_policy).
    """
    agents: list[dict]
    iteration: dict
    iter_dir: Path
    model_config: dict
    history: list[dict]
    policy: SessionPolicy
    deps: SessionDeps
    log_path: Path
    debug_path: Path
    use_implementation: bool
    tasks_data: list[dict] | None
    current_layer: int
    fileguard: object | None
    approval_store: object | None
    worktree_map: dict | None
    conv_store: ConversationStore | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ContinueContext:
    """Pre-computed data for a continue operation."""
    injected_messages: list[dict]
    has_pending_approvals: bool
    pending_count: int
    current_agent_turns: int


def resolve_layer(layer_override: int | None, iteration: dict) -> int:
    """Resolve current layer: explicit override > iteration state > 0."""
    if layer_override is not None:
        return layer_override
    return iteration.get("current_layer", 0)


def reconstruct_resume_state(messages: list[dict], phase: str | None) -> ResumeState:
    """Reconstruct session pause state from persisted messages.

    Pure function — no I/O, no widget queries. Extracts the detection
    patterns that any adapter (CLI, TUI, web) would need to restore
    a paused session.
    """
    from gotg.phases import get_phase_caps_safe

    # Scope to current phase (after last boundary marker)
    phase_messages = messages
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("phase_boundary"):
            phase_messages = messages[i + 1:]
            break

    # Walk backwards past pass_turn and system messages to find real last content
    last_content_msg = None
    for msg in reversed(phase_messages):
        if not msg.get("pass_turn") and msg.get("from") != "system":
            last_content_msg = msg
            break

    if not last_content_msg:
        return ResumeState()

    # Phase complete signal — check structured data first, then fallback text
    signal_data = last_content_msg.get("signal_phase_complete")
    content_text = last_content_msg.get("content", "").strip()
    is_legacy_signal = content_text == "(Phase complete signal sent.)"
    is_new_signal = content_text.startswith("(Phase complete:")
    if isinstance(signal_data, dict) or is_legacy_signal or is_new_signal:
        caps = get_phase_caps_safe(phase)
        outcome = signal_data.get("outcome", "approved") if isinstance(signal_data, dict) else "approved"
        return ResumeState(
            pause_reason=PauseReason.PHASE_COMPLETE,
            phase_complete_shows_review=caps.phase_complete_shows_review_hint,
            phase_complete_outcome=outcome,
        )

    # Coach proposed iterations — check before ask_pm (proposals take priority)
    proposals_data = last_content_msg.get("propose_iterations")
    if isinstance(proposals_data, dict) and "proposals" in proposals_data:
        batch_id = proposals_data.get("batch_id", "")
        approved = any(
            m.get("iterations_batch_approved") == batch_id
            for m in phase_messages
        )
        if not approved:
            return ResumeState(
                pause_reason=PauseReason.ITERATIONS_PROPOSED,
                iteration_proposals=proposals_data,
            )

    # Coach asked PM — scan backwards for unanswered ask_pm.
    # Agents may have responded with "waiting for PM" messages after the coach's
    # ask_pm, so checking only last_content_msg is insufficient.
    # An ask_pm is "unanswered" if no human message appears after it.
    has_human_after = False
    for msg in reversed(phase_messages):
        if msg.get("from") == "human":
            has_human_after = True
            break
        ask_pm_data = msg.get("ask_pm")
        if isinstance(ask_pm_data, dict) and "question" in ask_pm_data:
            if not has_human_after:
                return ResumeState(
                    pause_reason=PauseReason.COACH_QUESTION,
                    ask_pm_data=ask_pm_data,
                )
            break

    # Fallback: check if phase shows task status bar
    caps = get_phase_caps_safe(phase)
    return ResumeState(show_task_status_bar=caps.show_task_status_bar)
