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


def load_iteration(team_dir: Path) -> dict:
    data = json.loads((team_dir / "iteration.json").read_text())
    current_id = data["current"]
    for iteration in data["iterations"]:
        if iteration["id"] == current_id:
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


PHASE_ORDER = ["grooming", "planning", "pre-code-review"]


def save_iteration_phase(team_dir: Path, iteration_id: str, new_phase: str) -> None:
    iter_path = team_dir / "iteration.json"
    data = json.loads(iter_path.read_text())
    for iteration in data["iterations"]:
        if iteration["id"] == iteration_id:
            iteration["phase"] = new_phase
            iter_path.write_text(json.dumps(data, indent=2) + "\n")
            return
    raise SystemExit(
        f"Error: iteration '{iteration_id}' not found in iteration list."
    )


def save_model_config(team_dir: Path, model_config: dict) -> None:
    team_path = team_dir / "team.json"
    team_config = json.loads(team_path.read_text())
    team_config["model"] = model_config
    team_path.write_text(json.dumps(team_config, indent=2) + "\n")
