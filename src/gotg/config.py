from __future__ import annotations

import json
import os
from pathlib import Path


def read_dotenv(dotenv_path: Path) -> dict[str, str]:
    """Read a .env file and return key=value pairs as a dict."""
    env = {}
    if not dotenv_path.exists():
        return env
    for line in dotenv_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        env[key] = value
    return env


def ensure_dotenv_key(dotenv_path: Path, key: str) -> None:
    """Add KEY= to .env file if not already present. Creates file if needed."""
    if dotenv_path.exists():
        content = dotenv_path.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                return  # Key already present
        # Append to existing file
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"{key}=\n"
        dotenv_path.write_text(content)
    else:
        dotenv_path.write_text(f"{key}=\n")


def load_model_config(team_dir: Path) -> dict:
    team_config = json.loads((team_dir / "team.json").read_text())
    config = dict(team_config["model"])
    # Resolve api_key: if it starts with $, read from .env then environment
    api_key = config.get("api_key")
    if api_key and api_key.startswith("$"):
        env_var = api_key[1:]
        # Check .env file first (in project root, parent of .team/)
        dotenv_path = team_dir.parent / ".env"
        dotenv_vars = read_dotenv(dotenv_path)
        resolved = dotenv_vars.get(env_var) or os.environ.get(env_var)
        config["api_key"] = resolved
        if not config["api_key"]:
            raise SystemExit(
                f"Error: environment variable {env_var} is not set "
                f"(referenced in .team/team.json model.api_key). "
                f"Add it to .env or export it in your shell."
            )
    return config


def load_agents(team_dir: Path) -> list[dict]:
    team_config = json.loads((team_dir / "team.json").read_text())
    return team_config["agents"]


def load_coach(team_dir: Path) -> dict | None:
    team_config = json.loads((team_dir / "team.json").read_text())
    return team_config.get("coach")


def load_iteration(team_dir: Path) -> dict:
    data = json.loads((team_dir / "iteration.json").read_text())
    current_id = data["current"]
    for iteration in data["iterations"]:
        if iteration["id"] == current_id:
            if "phase" in iteration:
                iteration["phase"] = _normalize_phase(iteration["phase"])
            return iteration
    raise SystemExit(
        f"Error: current iteration '{current_id}' not found in iteration list."
    )


def get_iteration_dir(team_dir: Path, iteration_id: str) -> Path:
    return team_dir / "iterations" / iteration_id


def get_current_iteration(team_dir: Path) -> tuple[dict, Path]:
    iteration = load_iteration(team_dir)
    iter_dir = get_iteration_dir(team_dir, iteration["id"])
    return iteration, iter_dir


PHASE_ORDER = ["refinement", "planning", "pre-code-review", "implementation", "code-review"]
ITERATION_STATUSES = ["pending", "in-progress", "done"]

_PHASE_ALIASES = {"grooming": "refinement"}


def _normalize_phase(phase: str) -> str:
    """Normalize legacy phase names (e.g. 'grooming' → 'refinement')."""
    return _PHASE_ALIASES.get(phase, phase)


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
    raise SystemExit(
        f"Error: iteration '{iteration_id}' not found in iteration list."
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


def load_streaming_config(team_dir: Path) -> bool:
    """Read streaming flag from team.json. Returns False if not configured."""
    team_config = json.loads((team_dir / "team.json").read_text())
    return bool(team_config.get("streaming", False))


def load_file_access(team_dir: Path) -> dict | None:
    """Read file_access config from team.json. Returns None if not configured."""
    team_config = json.loads((team_dir / "team.json").read_text())
    return team_config.get("file_access")


def load_worktree_config(team_dir: Path) -> dict | None:
    """Read worktrees config from team.json. Returns None if not configured."""
    team_config = json.loads((team_dir / "team.json").read_text())
    return team_config.get("worktrees")


def load_team_config(team_dir: Path) -> dict:
    """Load the full team.json as a dict."""
    return json.loads((team_dir / "team.json").read_text())


def save_team_config(team_dir: Path, config: dict) -> None:
    """Write the full team.json."""
    team_path = team_dir / "team.json"
    team_path.write_text(json.dumps(config, indent=2) + "\n")


def save_model_config(team_dir: Path, model_config: dict) -> None:
    team_path = team_dir / "team.json"
    team_config = json.loads(team_path.read_text())
    team_config["model"] = model_config
    team_path.write_text(json.dumps(team_config, indent=2) + "\n")


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
