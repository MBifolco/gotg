"""Data loading helpers for the TUI."""

from __future__ import annotations

import json
import time
from pathlib import Path

from gotg.tui.helpers import count_jsonl_lines


def list_iterations(team_dir: Path) -> list[dict]:
    """List all iterations with enriched metadata.

    Reads iteration.json and cross-references with conversation logs
    to add is_current flag and message_count.
    """
    iter_path = team_dir / "iteration.json"
    if not iter_path.exists():
        return []
    data = json.loads(iter_path.read_text())
    current_id = data.get("current")
    result = []
    for it in data.get("iterations", []):
        it_dir = team_dir / "iterations" / it["id"]
        log_path = it_dir / "conversation.jsonl"
        msg_count = count_jsonl_lines(log_path)
        last_modified: float | None = None
        if log_path.exists():
            last_modified = log_path.stat().st_mtime
        result.append({
            **it,
            "is_current": it["id"] == current_id,
            "message_count": msg_count,
            "last_modified": last_modified,
        })
    return result


def load_session_metadata(team_dir: Path, base_metadata: dict) -> dict:
    """Bundle iteration/grooming metadata with agents and coach info.

    Returns a copy of base_metadata enriched with agents and coach
    loaded from team.json.
    """
    from gotg.config import load_agents, load_coach

    agents = load_agents(team_dir)
    coach = load_coach(team_dir)
    return {**base_metadata, "agents": agents, "coach": coach}


def relative_time(timestamp: float | None) -> str:
    """Format a Unix timestamp as a relative time string."""
    if timestamp is None:
        return ""
    delta = time.time() - timestamp
    if delta < 60:
        return "just now"
    if delta < 3600:
        mins = int(delta / 60)
        return f"{mins}m ago"
    if delta < 86400:
        hours = int(delta / 3600)
        return f"{hours}h ago"
    days = int(delta / 86400)
    return f"{days}d ago"
