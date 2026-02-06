import json

import pytest

from gotg.conversation import read_log, append_message, render_message


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "conversation.jsonl"


def test_read_log_empty_file(log_path):
    log_path.write_text("")
    assert read_log(log_path) == []


def test_read_log_with_messages(log_path):
    lines = [
        json.dumps({"from": "agent-1", "iteration": "iter-1", "content": "hello"}),
        json.dumps({"from": "agent-2", "iteration": "iter-1", "content": "hi back"}),
    ]
    log_path.write_text("\n".join(lines) + "\n")
    messages = read_log(log_path)
    assert len(messages) == 2
    assert messages[0]["from"] == "agent-1"
    assert messages[1]["content"] == "hi back"


def test_read_log_nonexistent_file(log_path):
    assert read_log(log_path) == []


def test_append_message_creates_file(log_path):
    msg = {"from": "agent-1", "iteration": "iter-1", "content": "first message"}
    append_message(log_path, msg)
    content = log_path.read_text()
    assert content.endswith("\n")
    parsed = json.loads(content.strip())
    assert parsed["from"] == "agent-1"


def test_append_message_appends(log_path):
    log_path.write_text("")
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "one"})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "two"})
    messages = read_log(log_path)
    assert len(messages) == 2


def test_render_message_contains_name_and_content():
    msg = {"from": "agent-1", "iteration": "iter-1", "content": "Let's discuss."}
    rendered = render_message(msg)
    assert "agent-1" in rendered
    assert "Let's discuss." in rendered


def test_render_message_different_agents_different_colors():
    msg1 = {"from": "agent-1", "iteration": "iter-1", "content": "hi"}
    msg2 = {"from": "agent-2", "iteration": "iter-1", "content": "hi"}
    r1 = render_message(msg1)
    r2 = render_message(msg2)
    # Both should have ANSI escapes, but different ones
    assert "\033[" in r1
    assert "\033[" in r2
    # The agent name portion should differ (different color codes)
    assert r1 != r2


# --- JSONL corruption / edge cases ---

def test_read_log_skips_blank_lines_in_middle(log_path):
    """Blank lines between messages shouldn't break parsing."""
    lines = [
        json.dumps({"from": "agent-1", "content": "one"}),
        "",
        "",
        json.dumps({"from": "agent-2", "content": "two"}),
    ]
    log_path.write_text("\n".join(lines) + "\n")
    messages = read_log(log_path)
    assert len(messages) == 2


def test_read_log_file_missing_trailing_newline(log_path):
    """File written without trailing newline should still parse."""
    log_path.write_text(json.dumps({"from": "agent-1", "content": "no newline"}))
    messages = read_log(log_path)
    assert len(messages) == 1
    assert messages[0]["content"] == "no newline"


def test_read_log_whitespace_only_file(log_path):
    log_path.write_text("  \n\t\n  \n")
    assert read_log(log_path) == []


def test_append_then_read_roundtrip_preserves_unicode(log_path):
    """Unicode content survives write→read roundtrip."""
    log_path.touch()
    msg = {"from": "agent-1", "iteration": "iter-1", "content": "design with emojis and CJK chars"}
    append_message(log_path, msg)
    messages = read_log(log_path)
    assert messages[0]["content"] == msg["content"]


def test_append_message_with_newlines_in_content(log_path):
    """Content containing newlines must not break JSONL (json.dumps escapes them)."""
    log_path.touch()
    msg = {"from": "agent-1", "iteration": "iter-1", "content": "line one\nline two\nline three"}
    append_message(log_path, msg)
    messages = read_log(log_path)
    assert len(messages) == 1
    assert "\n" in messages[0]["content"]


def test_append_message_with_quotes_in_content(log_path):
    """Quotes in content must be properly escaped."""
    log_path.touch()
    msg = {"from": "agent-1", "iteration": "iter-1", "content": 'He said "hello" and \'goodbye\''}
    append_message(log_path, msg)
    messages = read_log(log_path)
    assert messages[0]["content"] == msg["content"]


# --- render_message edge cases ---

def test_render_message_unknown_agent_gets_default_color():
    msg = {"from": "agent-99", "iteration": "iter-1", "content": "hello"}
    rendered = render_message(msg)
    assert "agent-99" in rendered
    assert "hello" in rendered
    assert "\033[" in rendered  # still has ANSI


def test_render_message_multiline_content():
    """Multi-line content should render without crashing."""
    msg = {"from": "agent-1", "iteration": "iter-1", "content": "line 1\nline 2\nline 3"}
    rendered = render_message(msg)
    assert "line 1" in rendered
    assert "line 3" in rendered


def test_render_message_human_gets_green_color():
    """Human messages should render with green color."""
    msg = {"from": "human", "iteration": "iter-1", "content": "PM feedback"}
    rendered = render_message(msg)
    assert "[human]" in rendered
    assert "PM feedback" in rendered
    assert "\033[32m" in rendered  # green


def test_render_message_system_gets_magenta_color():
    """System messages should render with magenta color."""
    msg = {"from": "system", "iteration": "iter-1", "content": "--- Phase advanced ---"}
    rendered = render_message(msg)
    assert "[system]" in rendered
    assert "Phase advanced" in rendered
    assert "\033[35m" in rendered  # magenta


def test_render_message_coach_gets_distinct_color():
    """Coach messages should render with a distinct color (not white default)."""
    msg = {"from": "coach", "iteration": "iter-1", "content": "Team has agreed on X."}
    rendered = render_message(msg)
    assert "[coach]" in rendered
    assert "Team has agreed on X." in rendered
    assert "\033[37m" not in rendered  # not white default
