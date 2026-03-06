"""Iteration persistence — CRUD for iteration.json and IterationStore."""
from __future__ import annotations

import json
from pathlib import Path

from gotg.errors import ConfigError


PHASE_ORDER = ["refinement", "planning", "pre-code-review", "implementation", "code-review"]
ITERATION_STATUSES = ["pending", "in-progress", "done"]


def load_iteration(team_dir: Path) -> dict:
    data = json.loads((team_dir / "iteration.json").read_text())
    current_id = data.get("current")
    if not current_id:
        raise ConfigError(
            "No current iteration. Create one with 'gotg new \"description\"' "
            "or use 'gotg explore start \"topic\"' to explore first."
        )
    for iteration in data["iterations"]:
        if iteration["id"] == current_id:
            return iteration
    raise ConfigError(
        f"current iteration '{current_id}' not found in iteration list."
    )


def get_iteration_dir(team_dir: Path, iteration_id: str) -> Path:
    return team_dir / "iterations" / iteration_id


def get_current_iteration(team_dir: Path) -> tuple[dict, Path]:
    iteration = load_iteration(team_dir)
    iter_dir = get_iteration_dir(team_dir, iteration["id"])
    return iteration, iter_dir


def create_iteration(
    team_dir: Path,
    iteration_id: str,
    description: str = "",
    max_turns: int = 30,
    set_current: bool = True,
) -> dict:
    """Create a new iteration and return its dict.

    Raises ValueError if an iteration with the given ID already exists.
    """
    iter_path = team_dir / "iteration.json"
    data = json.loads(iter_path.read_text())
    existing_ids = {it["id"] for it in data.get("iterations", [])}
    if iteration_id in existing_ids:
        raise ValueError(f"Iteration '{iteration_id}' already exists.")

    iteration = {
        "id": iteration_id,
        "title": "",
        "description": description,
        "status": "pending",
        "phase": "refinement",
        "max_turns": max_turns,
    }
    data["iterations"].append(iteration)
    if set_current:
        data["current"] = iteration_id

    iter_path.write_text(json.dumps(data, indent=2) + "\n")

    # Create iteration directory with empty conversation log
    iter_dir = team_dir / "iterations" / iteration_id
    iter_dir.mkdir(parents=True, exist_ok=True)
    log_path = iter_dir / "conversation.jsonl"
    if not log_path.exists():
        log_path.touch()

    return iteration


def save_iteration_fields(team_dir: Path, iteration_id: str, **fields) -> None:
    """Update arbitrary fields on an iteration in iteration.json."""
    iter_path = team_dir / "iteration.json"
    data = json.loads(iter_path.read_text())
    for iteration in data["iterations"]:
        if iteration["id"] == iteration_id:
            iteration.update(fields)
            iter_path.write_text(json.dumps(data, indent=2) + "\n")
            return
    raise ConfigError(
        f"iteration '{iteration_id}' not found in iteration list."
    )


def save_iteration_phase(team_dir: Path, iteration_id: str, new_phase: str) -> None:
    save_iteration_fields(team_dir, iteration_id, phase=new_phase)


def switch_current_iteration(team_dir: Path, iteration_id: str) -> None:
    """Switch the current iteration pointer to the given ID."""
    iter_path = team_dir / "iteration.json"
    data = json.loads(iter_path.read_text())
    existing_ids = {it["id"] for it in data.get("iterations", [])}
    if iteration_id not in existing_ids:
        raise ValueError(f"Iteration '{iteration_id}' not found.")
    data["current"] = iteration_id
    iter_path.write_text(json.dumps(data, indent=2) + "\n")


class IterationStore:
    """iteration.json persistence.

    Wraps existing free functions with an OO interface that binds
    team_dir at construction time.
    """

    def __init__(self, team_dir: Path):
        self.team_dir = team_dir

    def load(self) -> dict:
        return load_iteration(self.team_dir)

    def get_current(self) -> tuple[dict, Path]:
        return get_current_iteration(self.team_dir)

    def get_dir(self, iteration_id: str) -> Path:
        return get_iteration_dir(self.team_dir, iteration_id)

    def save_fields(self, iteration_id: str, **fields) -> None:
        save_iteration_fields(self.team_dir, iteration_id, **fields)

    def save_phase(self, iteration_id: str, phase: str) -> None:
        save_iteration_phase(self.team_dir, iteration_id, phase)

    def create(self, iteration_id: str, **kwargs) -> dict:
        return create_iteration(self.team_dir, iteration_id, **kwargs)

    def set_current(self, iteration_id: str) -> None:
        switch_current_iteration(self.team_dir, iteration_id)

    def list_all(self) -> list[dict]:
        """Return all iterations in natural order (append-order from iteration.json)."""
        data = json.loads((self.team_dir / "iteration.json").read_text())
        return data.get("iterations", [])
