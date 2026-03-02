from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable

from gotg.errors import ConfigError
from gotg.migration import migrate_iteration_data, migrate_team_config


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


def _resolve_api_key(config: dict, team_dir: Path) -> dict:
    """Resolve $VAR api_key references via .env and os.environ.

    Returns a new dict with api_key resolved. Raises ConfigError if
    a $VAR reference cannot be resolved.
    """
    config = dict(config)
    api_key = config.get("api_key")
    if api_key and api_key.startswith("$"):
        env_var = api_key[1:]
        dotenv_path = team_dir.parent / ".env"
        dotenv_vars = read_dotenv(dotenv_path)
        resolved = dotenv_vars.get(env_var) or os.environ.get(env_var)
        config["api_key"] = resolved
        if not config["api_key"]:
            raise ConfigError(
                f"environment variable {env_var} is not set "
                f"(referenced in .team/team.json model.api_key). "
                f"Add it to .env or export it in your shell."
            )
    return config


def load_model_config(team_dir: Path) -> dict:
    team_config = load_team_config(team_dir)
    config = dict(team_config["model"])
    return _resolve_api_key(config, team_dir)


def build_model_resolver(
    team_default: dict,
    agents: list[dict],
    coach: dict | None,
    team_dir: Path,
) -> Callable[[str | None], dict]:
    """Build a resolver: agent_name -> merged model config.

    None or unknown name -> team default.
    Pre-computes + caches per-agent configs with API key resolution.
    """
    overrides: dict[str, dict] = {}
    entries = list(agents)
    if coach:
        entries.append(coach)

    for entry in entries:
        agent_model = entry.get("model")
        if not agent_model:
            continue
        name = entry["name"]
        merged = {**team_default, **agent_model}
        # Cross-provider validation: changing provider without base_url is likely a mistake
        if (
            "provider" in agent_model
            and agent_model["provider"] != team_default.get("provider")
            and "base_url" not in agent_model
        ):
            raise ValueError(
                f"Agent '{name}' overrides provider to '{agent_model['provider']}' "
                f"but does not specify base_url. "
                f"Add base_url to the model override or remove the provider override."
            )
        overrides[name] = _resolve_api_key(merged, team_dir)

    # Pre-resolve the team default too (already resolved by load_model_config,
    # but callers may pass raw config in tests)
    resolved_default = _resolve_api_key(team_default, team_dir)

    def resolver(name: str | None) -> dict:
        if name and name in overrides:
            return dict(overrides[name])
        return dict(resolved_default)

    return resolver


def resolve_model_config(
    model_resolver: Callable | None,
    model_config: dict,
    agent_name: str | None = None,
) -> dict:
    """Resolve model config for a specific agent. Falls back to model_config."""
    if model_resolver:
        return model_resolver(agent_name)
    return dict(model_config)


def load_agents(team_dir: Path) -> list[dict]:
    return load_team_config(team_dir)["agents"]


def load_coach(team_dir: Path) -> dict | None:
    return load_team_config(team_dir).get("coach")


def load_iteration(team_dir: Path) -> dict:
    data = json.loads((team_dir / "iteration.json").read_text())
    warnings: list[str] = []
    data = migrate_iteration_data(data, warnings=warnings)
    for w in warnings:
        print(f"Warning: {w}", file=sys.stderr)
    current_id = data.get("current")
    if not current_id:
        raise ConfigError(
            "No current iteration. Create one with 'gotg new \"description\"' "
            "or use 'gotg groom start \"topic\"' to explore first."
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


PHASE_ORDER = ["refinement", "planning", "pre-code-review", "implementation", "code-review"]
ITERATION_STATUSES = ["pending", "in-progress", "done"]

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
    data = migrate_iteration_data(data)
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
    data = migrate_iteration_data(data)
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
    data = migrate_iteration_data(data)
    existing_ids = {it["id"] for it in data.get("iterations", [])}
    if iteration_id not in existing_ids:
        raise ValueError(f"Iteration '{iteration_id}' not found.")
    data["current"] = iteration_id
    iter_path.write_text(json.dumps(data, indent=2) + "\n")


def load_streaming_config(team_dir: Path) -> bool:
    """Read streaming flag from team.json. Returns False if not configured."""
    return bool(load_team_config(team_dir).get("streaming", False))


def load_file_access(team_dir: Path) -> dict | None:
    """Read file_access config from team.json. Returns None if not configured."""
    return load_team_config(team_dir).get("file_access")


def load_worktree_config(team_dir: Path) -> dict | None:
    """Read worktrees config from team.json. Returns None if not configured."""
    return load_team_config(team_dir).get("worktrees")


def load_team_config(team_dir: Path) -> dict:
    """Load the full team.json as a dict, with migration applied."""
    raw = json.loads((team_dir / "team.json").read_text())
    warnings: list[str] = []
    data = migrate_team_config(raw, warnings=warnings)
    for w in warnings:
        print(f"Warning: {w}", file=sys.stderr)
    return data


def save_team_config(team_dir: Path, config: dict) -> None:
    """Write the full team.json with schema_version stamped."""
    config = migrate_team_config(config)
    team_path = team_dir / "team.json"
    team_path.write_text(json.dumps(config, indent=2) + "\n")


def save_model_config(team_dir: Path, model_config: dict) -> None:
    team_config = load_team_config(team_dir)
    team_config["model"] = model_config
    save_team_config(team_dir, team_config)


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
        """Return all iterations in natural order (append-order from iteration.json).

        Uses migration path — same as load_iteration().
        """
        data = json.loads((self.team_dir / "iteration.json").read_text())
        warnings: list[str] = []
        data = migrate_iteration_data(data, warnings=warnings)
        for w in warnings:
            print(f"Warning: {w}", file=sys.stderr)
        return data.get("iterations", [])
