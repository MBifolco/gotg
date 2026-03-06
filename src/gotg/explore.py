"""Exploration conversation management — freeform pre-iteration exploration."""
from __future__ import annotations

import json
import re
from pathlib import Path

from gotg.errors import ExplorationError
from gotg.events import SessionStarted


# ── Slug generation ──────────────────────────────────────────────

_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall", "how", "what",
    "when", "where", "why", "who", "which", "that", "this", "we", "our",
    "it", "its", "if", "not", "no", "so", "up",
})

_MAX_SLUG_LENGTH = 50
_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")


def generate_slug(topic: str, existing: set[str] | None = None) -> str:
    """Generate a kebab-case slug from a topic string.

    Strips common words, lowercases, kebab-cases, truncates to 50 chars.
    Deduplicates against existing slugs by appending -2, -3, etc.
    """
    text = topic.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    words = text.split()

    # Remove stop words but keep at least 2 words
    filtered = [w for w in words if w not in _STOP_WORDS]
    if len(filtered) < 2 and words:
        filtered = words[:3]

    if not filtered:
        filtered = ["explore"]

    slug = "-".join(filtered)

    # Truncate at word boundary
    if len(slug) > _MAX_SLUG_LENGTH:
        slug = slug[:_MAX_SLUG_LENGTH].rsplit("-", 1)[0]

    # Deduplicate
    if existing and slug in existing:
        n = 2
        while f"{slug}-{n}" in existing:
            n += 1
        slug = f"{slug}-{n}"

    return slug


def validate_slug(slug: str) -> bool:
    """Check that a slug is safe for use as a directory name."""
    return bool(_SLUG_PATTERN.match(slug))


# ── Metadata ─────────────────────────────────────────────────────

def _exploration_dir(team_dir: Path, slug: str) -> Path:
    return team_dir / "exploration" / slug


def write_exploration_metadata(
    team_dir: Path, slug: str, topic: str, coach: bool, max_turns: int,
    context_from: str | bool | None = None,
) -> Path:
    """Create exploration directory and write exploration.json. Returns the dir.

    context_from semantics:
      - string (e.g. "iter-1"): explicit or auto-resolved iteration ID
      - None: no context found at start (or v1 migration default)
      - False: user passed --no-context (explicit opt-out)
    """
    explore_dir = _exploration_dir(team_dir, slug)
    explore_dir.mkdir(parents=True, exist_ok=False)
    (explore_dir / "conversation.jsonl").touch()

    metadata = {
        "slug": slug,
        "topic": topic,
        "coach": coach,
        "max_turns": max_turns,
        "status": "active",
        "context_from": context_from,
    }
    (explore_dir / "exploration.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return explore_dir


def load_exploration_metadata(team_dir: Path, slug: str) -> tuple[dict, Path]:
    """Load exploration.json. Returns (metadata, explore_dir). Exits if not found."""
    explore_dir = _exploration_dir(team_dir, slug)
    meta_path = explore_dir / "exploration.json"
    if not meta_path.exists():
        raise ExplorationError(f"exploration session '{slug}' not found.")
    return json.loads(meta_path.read_text()), explore_dir


def list_exploration_sessions(team_dir: Path) -> list[dict]:
    """List all exploration sessions sorted by directory name."""
    exploration_root = team_dir / "exploration"
    if not exploration_root.exists():
        return []
    sessions = []
    for d in sorted(exploration_root.iterdir()):
        meta_path = d / "exploration.json"
        if meta_path.exists():
            sessions.append(json.loads(meta_path.read_text()))
    return sessions


def existing_slugs(team_dir: Path) -> set[str]:
    """Return set of existing exploration slugs."""
    exploration_root = team_dir / "exploration"
    if not exploration_root.exists():
        return set()
    return {d.name for d in exploration_root.iterdir() if d.is_dir()}


# ── Session header ───────────────────────────────────────────────

def _print_exploration_header(event: SessionStarted, topic: str) -> None:
    print(f"Exploration: {event.iteration_id}")
    print(f"Topic: {topic}")
    if event.coach:
        print(f"Coach: {event.coach} (facilitating)")
    print(f"Turns: {event.turn}/{event.max_turns}")
    print("---")


# ── Event handler ────────────────────────────────────────────────

def run_exploration_conversation(
    explore_dir: Path,
    agents: list[dict],
    iteration: dict,
    model_config: dict,
    topic: str,
    coach: dict | None = None,
    max_turns_override: int | None = None,
    streaming: bool = False,
    model_resolver=None,
    project_context: str | None = None,
    project_root: Path | None = None,
    file_access: dict | None = None,
    pause_controller=None,
) -> str | None:
    """Run an exploration conversation. Handles all events from run_session.

    Returns "paused" if user paused, None otherwise.
    """
    # Late imports to preserve mock targets (bridge pattern)
    from gotg.console_events import handle_console_events
    from gotg.engine import SessionDeps
    from gotg.model import agentic_completion, chat_completion, raw_completion_stream
    from gotg.session_setup import prepare_exploration_session, run_and_persist

    deps = SessionDeps(
        agent_completion=agentic_completion,
        coach_completion=chat_completion,
        stream_completion=raw_completion_stream if streaming else None,
        model_resolver=model_resolver,
    )

    setup = prepare_exploration_session(
        explore_dir, agents, iteration, model_config, deps,
        topic=topic, coach=coach,
        max_turns=max_turns_override or iteration.get("max_turns", 30),
        streaming=streaming,
        project_context=project_context,
        project_root=project_root,
        file_access=file_access,
    )

    slug = iteration["id"]

    if pause_controller:
        pause_controller.install()
    try:
        return handle_console_events(
            run_and_persist(setup),
            on_started=lambda e: _print_exploration_header(e, topic),
            resume_hint=f"gotg explore continue {slug}",
            summarize_hint=f"gotg explore summarize {slug}",
            complete_label="Exploration",
            pause_controller=pause_controller,
        )
    finally:
        if pause_controller:
            pause_controller.uninstall()
