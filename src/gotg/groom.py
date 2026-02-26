"""Grooming conversation management — freeform pre-iteration exploration."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from gotg.errors import GroomingError
from gotg.events import SessionStarted
from gotg.migration import CURRENT_GROOMING_VERSION, migrate_grooming_metadata


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
        filtered = ["groom"]

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

def _grooming_dir(team_dir: Path, slug: str) -> Path:
    return team_dir / "grooming" / slug


def write_grooming_metadata(
    team_dir: Path, slug: str, topic: str, coach: bool, max_turns: int,
) -> Path:
    """Create grooming directory and write grooming.json. Returns the dir."""
    groom_dir = _grooming_dir(team_dir, slug)
    groom_dir.mkdir(parents=True, exist_ok=False)
    (groom_dir / "conversation.jsonl").touch()

    metadata = {
        "schema_version": CURRENT_GROOMING_VERSION,
        "slug": slug,
        "topic": topic,
        "coach": coach,
        "max_turns": max_turns,
        "status": "active",
    }
    (groom_dir / "grooming.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return groom_dir


def load_grooming_metadata(team_dir: Path, slug: str) -> tuple[dict, Path]:
    """Load grooming.json. Returns (metadata, groom_dir). Exits if not found."""
    groom_dir = _grooming_dir(team_dir, slug)
    meta_path = groom_dir / "grooming.json"
    if not meta_path.exists():
        raise GroomingError(f"grooming session '{slug}' not found.")
    warnings: list[str] = []
    data = migrate_grooming_metadata(json.loads(meta_path.read_text()), warnings=warnings)
    for w in warnings:
        print(f"Warning: {w}", file=sys.stderr)
    return data, groom_dir


def list_grooming_sessions(team_dir: Path) -> list[dict]:
    """List all grooming sessions sorted by directory name."""
    grooming_root = team_dir / "grooming"
    if not grooming_root.exists():
        return []
    sessions = []
    for d in sorted(grooming_root.iterdir()):
        meta_path = d / "grooming.json"
        if meta_path.exists():
            warnings: list[str] = []
            data = migrate_grooming_metadata(json.loads(meta_path.read_text()), warnings=warnings)
            for w in warnings:
                print(f"Warning: {w}", file=sys.stderr)
            sessions.append(data)
    return sessions


def existing_slugs(team_dir: Path) -> set[str]:
    """Return set of existing grooming slugs."""
    grooming_root = team_dir / "grooming"
    if not grooming_root.exists():
        return set()
    return {d.name for d in grooming_root.iterdir() if d.is_dir()}


# ── Session header ───────────────────────────────────────────────

def _print_grooming_header(event: SessionStarted, topic: str) -> None:
    print(f"Grooming: {event.iteration_id}")
    print(f"Topic: {topic}")
    if event.coach:
        print(f"Coach: {event.coach} (facilitating)")
    print(f"Turns: {event.turn}/{event.max_turns}")
    print("---")


# ── Event handler ────────────────────────────────────────────────

def run_grooming_conversation(
    groom_dir: Path,
    agents: list[dict],
    iteration: dict,
    model_config: dict,
    topic: str,
    coach: dict | None = None,
    max_turns_override: int | None = None,
    streaming: bool = False,
    model_resolver=None,
) -> None:
    """Run a grooming conversation. Handles all events from run_session."""
    # Late imports to preserve mock targets (bridge pattern)
    from gotg.console_events import handle_console_events
    from gotg.engine import SessionDeps
    from gotg.model import agentic_completion, chat_completion, raw_completion_stream
    from gotg.session import prepare_grooming_session, run_and_persist

    deps = SessionDeps(
        agent_completion=agentic_completion,
        coach_completion=chat_completion,
        stream_completion=raw_completion_stream if streaming else None,
        model_resolver=model_resolver,
    )

    setup = prepare_grooming_session(
        groom_dir, agents, iteration, model_config, deps,
        topic=topic, coach=coach,
        max_turns=max_turns_override or iteration.get("max_turns", 30),
        streaming=streaming,
    )

    slug = iteration["id"]
    handle_console_events(
        run_and_persist(setup),
        on_started=lambda e: _print_grooming_header(e, topic),
        resume_hint=f"gotg groom continue {slug}",
        complete_label="Grooming",
    )
