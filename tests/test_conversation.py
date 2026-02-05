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
