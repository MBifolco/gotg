from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable

from gotg.errors import ConfigError
from gotg.migration import migrate_team_config


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


# Re-exports from iteration_store (moved for module cohesion)
from gotg.iteration_store import (  # noqa: F401, E402
    ITERATION_STATUSES,
    PHASE_ORDER,
    IterationStore,
    create_iteration,
    get_current_iteration,
    get_iteration_dir,
    load_iteration,
    save_iteration_fields,
    save_iteration_phase,
    switch_current_iteration,
)


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


