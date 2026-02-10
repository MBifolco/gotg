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


@dataclass
class SessionComplete:
    total_turns: int
