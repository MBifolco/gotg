from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SessionStarted:
    iteration_id: str
    description: str
    phase: str | None
    current_layer: int | None
    agents: list[str]
    coach: str | None
    has_file_tools: bool
    writable_paths: str | None
    worktree_count: int
    turn: int
    max_turns: int


@dataclass
class AppendMessage:
    msg: dict


@dataclass
class AppendDebug:
    entry: dict


@dataclass
class PauseForApprovals:
    pending_count: int


@dataclass
class PhaseCompleteSignaled:
    phase: str | None


@dataclass
class CoachAskedPM:
    question: str
    response_type: str = "feedback"   # "feedback" or "decision"
    options: tuple[str, ...] = ()     # non-empty when response_type == "decision"


@dataclass
class SessionComplete:
    total_turns: int


@dataclass
class AdvanceProgress:
    """Reports advance progress step to the UI."""
    message: str


@dataclass
class AdvanceComplete:
    """Phase advance finished successfully."""
    from_phase: str
    to_phase: str
    checkpoint_number: int | None


@dataclass
class AdvanceError:
    """Phase advance failed or had warnings."""
    error: str
    partial: bool  # True = advance succeeded but extraction had warnings
