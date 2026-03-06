from __future__ import annotations

from typing import NotRequired, TypedDict


class IterationDict(TypedDict):
    id: str
    description: str
    status: str
    phase: NotRequired[str]
    max_turns: int
    current_layer: NotRequired[int]
    title: NotRequired[str]


# Functional syntax because "from" is a Python reserved word.
# All code accesses this as msg["from"] (dict subscript), never attribute.
MessageDict = TypedDict(
    "MessageDict",
    {
        "from": str,
        "iteration": NotRequired[str],
        "content": str,
        "pass_turn": NotRequired[bool],
        "phase_boundary": NotRequired[bool],
        "from_phase": NotRequired[str],
        "to_phase": NotRequired[str],
        "layer": NotRequired[int],
        "user_pause": NotRequired[bool],
        "user_pause_resolved": NotRequired[bool],
    },
)


class ModelOverrideDict(TypedDict, total=False):
    """Partial model config for per-agent overrides. Merged with team default."""
    provider: str
    base_url: str
    model: str
    api_key: str | None


class AgentDict(TypedDict):
    name: str
    role: NotRequired[str]
    system_prompt: NotRequired[str]
    model: NotRequired[ModelOverrideDict]


class CoachDict(TypedDict):
    name: str
    role: NotRequired[str]
    model: NotRequired[ModelOverrideDict]


class ModelConfigDict(TypedDict):
    provider: NotRequired[str]
    base_url: str
    model: str
    api_key: NotRequired[str | None]


class FileAccessDict(TypedDict):
    writable_paths: NotRequired[list[str]]
    protected_paths: NotRequired[list[str]]
    max_file_size_bytes: NotRequired[int]
    max_files_per_turn: NotRequired[int]
    enable_approvals: NotRequired[bool]


class WorktreeConfigDict(TypedDict):
    enabled: NotRequired[bool]


class TaskDict(TypedDict):
    id: str
    description: str
    depends_on: list[str]
    assigned_to: NotRequired[str | None]  # planning extraction sets null
    layer: NotRequired[int]
    done_criteria: str
    notes: NotRequired[str]
    status: NotRequired[str]
