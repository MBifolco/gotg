import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from gotg.groom import (
    generate_slug,
    validate_slug,
    write_grooming_metadata,
    load_grooming_metadata,
    list_grooming_sessions,
    existing_slugs,
    run_grooming_conversation,
)


# ── Slug generation ──────────────────────────────────────────────


def test_generate_slug_basic():
    slug = generate_slug("error handling in CLI apps")
    assert slug == "error-handling-cli-apps"


def test_generate_slug_strips_stop_words():
    slug = generate_slug("how should we handle file conflicts")
    assert "how" not in slug
    assert "should" not in slug
    assert "we" not in slug
    assert "handle" in slug
    assert "file" in slug
    assert "conflicts" in slug


def test_generate_slug_deduplicates():
    slug = generate_slug("handle file conflicts", existing={"handle-file-conflicts"})
    assert slug == "handle-file-conflicts-2"


def test_generate_slug_deduplicates_incrementing():
    existing = {"handle-file-conflicts", "handle-file-conflicts-2"}
    slug = generate_slug("handle file conflicts", existing=existing)
    assert slug == "handle-file-conflicts-3"


def test_generate_slug_truncates():
    long_topic = " ".join(f"word{i}" for i in range(20))
    slug = generate_slug(long_topic)
    assert len(slug) <= 50
    # Should truncate at a word boundary (no trailing hyphen)
    assert not slug.endswith("-")


def test_generate_slug_strips_punctuation():
    slug = generate_slug("what's the best approach? (seriously!)")
    assert "?" not in slug
    assert "(" not in slug
    assert "'" not in slug


def test_generate_slug_all_stop_words_fallback():
    """When all words are stop words, keep first 3 words as fallback."""
    slug = generate_slug("how should we do this?")
    # All content words are stop words, so fallback keeps first 3
    assert len(slug) > 0
    assert "-" in slug or slug.isalnum()


def test_generate_slug_empty_topic_fallback():
    slug = generate_slug("???!!!")
    assert slug == "groom"


def test_generate_slug_no_existing():
    slug = generate_slug("test topic", existing=None)
    assert slug == "test-topic"


# ── Slug validation ──────────────────────────────────────────────


def test_validate_slug_valid():
    assert validate_slug("handle-file-conflicts") is True
    assert validate_slug("a") is True
    assert validate_slug("abc-123-def") is True


def test_validate_slug_invalid():
    assert validate_slug("") is False
    assert validate_slug("-leading-hyphen") is False
    assert validate_slug("has spaces") is False
    assert validate_slug("../traversal") is False
    assert validate_slug("UPPERCASE") is False
    assert validate_slug("a" * 51) is False


# ── Metadata ─────────────────────────────────────────────────────


def test_write_and_load_metadata(tmp_path):
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    groom_dir = write_grooming_metadata(team_dir, "test-slug", "Test topic", coach=False, max_turns=30)
    assert groom_dir.exists()
    assert (groom_dir / "grooming.json").exists()
    assert (groom_dir / "conversation.jsonl").exists()

    meta, loaded_dir = load_grooming_metadata(team_dir, "test-slug")
    assert meta["slug"] == "test-slug"
    assert meta["topic"] == "Test topic"
    assert meta["coach"] is False
    assert meta["max_turns"] == 30
    assert loaded_dir == groom_dir


def test_load_metadata_missing_exits(tmp_path):
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    with pytest.raises(SystemExit):
        load_grooming_metadata(team_dir, "nonexistent")


def test_list_sessions_empty(tmp_path):
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    assert list_grooming_sessions(team_dir) == []


def test_list_sessions_returns_all(tmp_path):
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    write_grooming_metadata(team_dir, "aaa-topic", "Topic A", coach=False, max_turns=30)
    write_grooming_metadata(team_dir, "bbb-topic", "Topic B", coach=True, max_turns=20)
    sessions = list_grooming_sessions(team_dir)
    assert len(sessions) == 2
    assert sessions[0]["slug"] == "aaa-topic"
    assert sessions[1]["slug"] == "bbb-topic"


def test_existing_slugs(tmp_path):
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    write_grooming_metadata(team_dir, "slug-a", "Topic A", coach=False, max_turns=30)
    write_grooming_metadata(team_dir, "slug-b", "Topic B", coach=False, max_turns=30)
    slugs = existing_slugs(team_dir)
    assert slugs == {"slug-a", "slug-b"}


def test_existing_slugs_empty(tmp_path):
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    assert existing_slugs(team_dir) == set()


# ── Event handler ────────────────────────────────────────────────


AGENTS = [
    {"name": "agent-1", "role": "Software Engineer"},
    {"name": "agent-2", "role": "Software Engineer"},
]

MODEL_CONFIG = {
    "provider": "ollama",
    "base_url": "http://localhost:11434",
    "model": "test-model",
}


def _make_iteration(slug="test-slug", topic="Test topic"):
    return {"id": slug, "description": topic, "phase": None}


def test_run_grooming_writes_messages(tmp_path):
    groom_dir = tmp_path / "groom"
    groom_dir.mkdir()
    (groom_dir / "conversation.jsonl").touch()

    call_count = 0

    def mock_agent(**kw):
        nonlocal call_count
        call_count += 1
        return {"content": f"agent says {call_count}", "operations": []}

    with patch("gotg.model.agentic_completion", mock_agent), \
         patch("gotg.model.chat_completion"):
        run_grooming_conversation(
            groom_dir, AGENTS, _make_iteration(), MODEL_CONFIG,
            topic="Test topic", max_turns_override=2,
        )

    messages = [json.loads(line) for line in (groom_dir / "conversation.jsonl").read_text().splitlines() if line.strip()]
    # Kickoff (system) + 2 agent messages
    agent_msgs = [m for m in messages if m["from"] not in ("system",)]
    assert len(agent_msgs) == 2


def test_run_grooming_kickoff_injected(tmp_path):
    groom_dir = tmp_path / "groom"
    groom_dir.mkdir()
    (groom_dir / "conversation.jsonl").touch()

    def mock_agent(**kw):
        return {"content": "hello", "operations": []}

    with patch("gotg.model.agentic_completion", mock_agent), \
         patch("gotg.model.chat_completion"):
        run_grooming_conversation(
            groom_dir, AGENTS, _make_iteration(), MODEL_CONFIG,
            topic="Test topic", max_turns_override=1,
        )

    messages = [json.loads(line) for line in (groom_dir / "conversation.jsonl").read_text().splitlines() if line.strip()]
    assert messages[0]["from"] == "system"
    assert "Grooming: Test topic" in messages[0]["content"]


def test_run_grooming_no_kickoff_on_continue(tmp_path):
    """When conversation already has history, kickoff should not be re-injected."""
    groom_dir = tmp_path / "groom"
    groom_dir.mkdir()
    log_path = groom_dir / "conversation.jsonl"
    # Pre-existing message
    log_path.write_text(json.dumps({"from": "system", "iteration": "test-slug", "content": "--- Grooming: Test ---"}) + "\n")

    def mock_agent(**kw):
        return {"content": "hello", "operations": []}

    with patch("gotg.model.agentic_completion", mock_agent), \
         patch("gotg.model.chat_completion"):
        run_grooming_conversation(
            groom_dir, AGENTS, _make_iteration(), MODEL_CONFIG,
            topic="Test topic", max_turns_override=1,
        )

    messages = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    # Original system message + 1 agent message (no new kickoff)
    system_msgs = [m for m in messages if m["from"] == "system"]
    assert len(system_msgs) == 1  # Only the pre-existing one


def test_run_grooming_with_coach(tmp_path):
    groom_dir = tmp_path / "groom"
    groom_dir.mkdir()
    (groom_dir / "conversation.jsonl").touch()

    coach = {"name": "coach", "role": "Agile Coach"}

    def mock_agent(**kw):
        return {"content": "agent says", "operations": []}

    def mock_coach(**kw):
        return {"content": "coach says", "tool_calls": []}

    with patch("gotg.model.agentic_completion", mock_agent), \
         patch("gotg.model.chat_completion", mock_coach):
        run_grooming_conversation(
            groom_dir, AGENTS, _make_iteration(), MODEL_CONFIG,
            topic="Test topic", coach=coach, max_turns_override=4,
        )

    messages = [json.loads(line) for line in (groom_dir / "conversation.jsonl").read_text().splitlines() if line.strip()]
    coach_msgs = [m for m in messages if m["from"] == "coach"]
    assert len(coach_msgs) >= 1


def test_run_grooming_coach_ask_pm(tmp_path, capsys):
    groom_dir = tmp_path / "groom"
    groom_dir.mkdir()
    (groom_dir / "conversation.jsonl").touch()

    coach = {"name": "coach", "role": "Agile Coach"}

    def mock_agent(**kw):
        return {"content": "agent says", "operations": []}

    def mock_coach(**kw):
        return {
            "content": "Need PM input",
            "tool_calls": [{"name": "ask_pm", "input": {"question": "What priority?"}}],
        }

    with patch("gotg.model.agentic_completion", mock_agent), \
         patch("gotg.model.chat_completion", mock_coach):
        run_grooming_conversation(
            groom_dir, AGENTS, _make_iteration(), MODEL_CONFIG,
            topic="Test topic", coach=coach, max_turns_override=4,
        )

    output = capsys.readouterr().out
    assert "gotg groom continue test-slug" in output
