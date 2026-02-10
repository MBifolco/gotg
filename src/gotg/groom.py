"""Grooming conversation management — freeform pre-iteration exploration."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from gotg.conversation import append_message, append_debug, read_log, render_message
from gotg.engine import SessionDeps, run_session
from gotg.events import (
    AppendDebug,
    AppendMessage,
    CoachAskedPM,
    PauseForApprovals,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
)
from gotg.policy import grooming_policy


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
        print(f"Error: grooming session '{slug}' not found.", file=sys.stderr)
        raise SystemExit(1)
    return json.loads(meta_path.read_text()), groom_dir


def list_grooming_sessions(team_dir: Path) -> list[dict]:
    """List all grooming sessions sorted by directory name."""
    grooming_root = team_dir / "grooming"
    if not grooming_root.exists():
        return []
    sessions = []
    for d in sorted(grooming_root.iterdir()):
        meta_path = d / "grooming.json"
        if meta_path.exists():
            sessions.append(json.loads(meta_path.read_text()))
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
) -> None:
    """Run a grooming conversation. Handles all events from run_session."""
    # Late imports to preserve mock targets (bridge pattern)
    from gotg.model import agentic_completion, chat_completion

    log_path = groom_dir / "conversation.jsonl"
    debug_path = groom_dir / "debug.jsonl"
    history = read_log(log_path)

    deps = SessionDeps(
        agent_completion=agentic_completion,
        coach_completion=chat_completion,
    )

    policy = grooming_policy(
        agents=agents,
        topic=topic,
        history=history,
        coach=coach,
        max_turns=max_turns_override or iteration.get("max_turns", 30),
    )

    for event in run_session(
        agents=agents, iteration=iteration, model_config=model_config,
        deps=deps, history=history, policy=policy,
    ):
        if isinstance(event, SessionStarted):
            _print_grooming_header(event, topic)
        elif isinstance(event, AppendMessage):
            append_message(log_path, event.msg)
            print(render_message(event.msg))
            print()
        elif isinstance(event, AppendDebug):
            append_debug(debug_path, event.entry)
        elif isinstance(event, CoachAskedPM):
            print("---")
            print(f"Coach asks: {event.question}")
            slug = iteration["id"]
            print(f"Reply with: gotg groom continue {slug} -m 'your answer'")
            break
        elif isinstance(event, (PauseForApprovals, PhaseCompleteSignaled)):
            pass  # cannot fire under grooming_policy
        elif isinstance(event, SessionComplete):
            print("---")
            print(f"Grooming complete ({event.total_turns} turns)")
        else:
            raise AssertionError(f"Unhandled event: {event!r}")
