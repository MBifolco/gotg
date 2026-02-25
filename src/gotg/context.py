from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from typing import Callable

from gotg.config import (
    IterationStore,
    build_model_resolver,
    load_agents,
    load_coach,
    load_file_access,
    load_model_config,
    load_worktree_config,
)
from gotg.types import (
    AgentDict,
    CoachDict,
    FileAccessDict,
    ModelConfigDict,
    WorktreeConfigDict,
)


@dataclass(frozen=True)
class TeamContext:
    """Bundles all project config. Loaded once per command."""

    team_dir: Path
    project_root: Path
    model_config: ModelConfigDict
    agents: list[AgentDict]
    coach: CoachDict | None
    file_access: FileAccessDict | None
    worktree_config: WorktreeConfigDict | None
    iteration_store: IterationStore
    model_resolver: Callable[[str | None], dict] | None = None

    @classmethod
    def from_team_dir(cls, team_dir: Path) -> TeamContext:
        """Load all config from a .team/ directory."""
        model_config = load_model_config(team_dir)
        agents = load_agents(team_dir)
        coach = load_coach(team_dir)
        try:
            resolver = build_model_resolver(model_config, agents, coach, team_dir)
        except ValueError as e:
            raise SystemExit(f"Error: invalid model override in team.json: {e}")
        return cls(
            team_dir=team_dir,
            project_root=team_dir.parent,
            model_config=model_config,
            agents=agents,
            coach=coach,
            file_access=load_file_access(team_dir),
            worktree_config=load_worktree_config(team_dir),
            iteration_store=IterationStore(team_dir),
            model_resolver=resolver,
        )
