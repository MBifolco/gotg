import json
from pathlib import Path


def load_model_config(team_dir: Path) -> dict:
    return json.loads((team_dir / "model.json").read_text())


def load_agents(team_dir: Path) -> list[dict]:
    agents_dir = team_dir / "agents"
    agents = []
    for path in sorted(agents_dir.glob("*.json")):
        agents.append(json.loads(path.read_text()))
    return agents


def load_iteration(team_dir: Path) -> dict:
    return json.loads((team_dir / "iteration.json").read_text())
