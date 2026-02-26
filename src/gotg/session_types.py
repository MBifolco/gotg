"""Shared exceptions, dataclasses, enums, and utilities for session modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gotg.engine import SessionDeps
    from gotg.policy import SessionPolicy

__all__ = [
    # Exceptions
    "SessionSetupError",
    "PhaseAdvanceError",
    "ReviewError",
    # Enums
    "ResolutionStrategy",
    # Dataclasses
    "BranchReview",
    "ReviewResult",
    "MergeResult",
    "NextLayerResult",
    "AdvanceResult",
    "ConflictFileInfo",
    "ConflictInfo",
    "AiResolutionResult",
    "SessionInfra",
    "SessionSetup",
    "ContinueContext",
    # Utilities
    "resolve_layer",
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
    checkpoint_number: int | None = None
    task_count: int = 0
    removed_worktrees: list[str] = field(default_factory=list)


@dataclass
class AdvanceResult:
    """Result of a successful phase advance."""
    from_phase: str
    to_phase: str
    boundary_msg: dict
    transition_msg: dict
    checkpoint_number: int | None
    warnings: list[str] = field(default_factory=list)


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
    policy factories (e.g. grooming uses grooming_policy, not iteration_policy).
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
