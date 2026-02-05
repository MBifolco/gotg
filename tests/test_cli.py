import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gotg.cli import main, find_team_dir, run_conversation
from gotg.conversation import read_log


# --- find_team_dir ---

def test_find_team_dir_returns_path_when_exists(tmp_path):
    (tmp_path / ".team").mkdir()
    result = find_team_dir(tmp_path)
    assert result == tmp_path / ".team"


def test_find_team_dir_returns_none_when_missing(tmp_path):
    result = find_team_dir(tmp_path)
    assert result is None


# --- gotg init via CLI ---

def test_cli_init(tmp_path):
    with patch("sys.argv", ["gotg", "init", str(tmp_path)]):
        main()
    assert (tmp_path / ".team").is_dir()
    assert (tmp_path / ".team" / "model.json").exists()


def test_cli_init_defaults_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "init"]):
        main()
    assert (tmp_path / ".team").is_dir()


# --- gotg show ---

def test_cli_show_prints_messages(tmp_path, capsys):
    team = tmp_path / ".team"
    team.mkdir()
    log = team / "conversation.jsonl"
    log.write_text(
        json.dumps({"from": "agent-1", "iteration": "iter-1", "content": "hello"}) + "\n"
        + json.dumps({"from": "agent-2", "iteration": "iter-1", "content": "hi back"}) + "\n"
    )
    with patch("sys.argv", ["gotg", "show"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()
    output = capsys.readouterr().out
    assert "agent-1" in output
    assert "hello" in output
    assert "agent-2" in output


def test_cli_show_empty_log(tmp_path, capsys):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "conversation.jsonl").touch()
    with patch("sys.argv", ["gotg", "show"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()
    output = capsys.readouterr().out
    assert "No messages" in output


# --- gotg run validation ---

def test_cli_run_fails_without_team_dir(tmp_path, capsys):
    with patch("sys.argv", ["gotg", "run"]):
        with patch("gotg.cli.find_team_dir", return_value=None):
            with pytest.raises(SystemExit):
                main()


def test_cli_run_fails_with_empty_description(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "agents").mkdir()
    (team / "iteration.json").write_text(json.dumps({
        "id": "iter-1", "description": "", "status": "in-progress", "max_turns": 10,
    }))
    (team / "model.json").write_text(json.dumps({
        "provider": "ollama", "base_url": "http://localhost:11434", "model": "m",
    }))
    (team / "conversation.jsonl").touch()

    with patch("sys.argv", ["gotg", "run"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()


def test_cli_run_fails_with_pending_status(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    (team / "agents").mkdir()
    (team / "iteration.json").write_text(json.dumps({
        "id": "iter-1", "description": "A task", "status": "pending", "max_turns": 10,
    }))
    (team / "model.json").write_text(json.dumps({
        "provider": "ollama", "base_url": "http://localhost:11434", "model": "m",
    }))
    (team / "conversation.jsonl").touch()

    with patch("sys.argv", ["gotg", "run"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()


# --- run_conversation ---

def test_run_conversation_alternates_agents(tmp_path):
    """The run loop should alternate between agent-1 and agent-2."""
    team = tmp_path / ".team"
    team.mkdir()
    (team / "agents").mkdir()
    log_path = team / "conversation.jsonl"
    log_path.touch()

    agents = [
        {"name": "agent-1", "system_prompt": "You are an engineer."},
        {"name": "agent-2", "system_prompt": "You are an engineer."},
    ]
    iteration = {
        "id": "iter-1",
        "description": "Design something",
        "status": "in-progress",
        "max_turns": 4,
    }
    model_config = {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "test-model",
    }

    call_count = 0
    def mock_completion(base_url, model, messages, api_key=None):
        nonlocal call_count
        call_count += 1
        return f"Response {call_count}"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(team, agents, iteration, model_config)

    messages = []
    for line in log_path.read_text().splitlines():
        if line.strip():
            messages.append(json.loads(line))

    assert len(messages) == 4
    assert messages[0]["from"] == "agent-1"
    assert messages[1]["from"] == "agent-2"
    assert messages[2]["from"] == "agent-1"
    assert messages[3]["from"] == "agent-2"


def test_run_conversation_resumes_from_existing(tmp_path):
    """If conversation.jsonl already has messages, pick up where we left off."""
    team = tmp_path / ".team"
    team.mkdir()
    (team / "agents").mkdir()
    log_path = team / "conversation.jsonl"
    # Pre-populate with 2 messages (agent-1, agent-2)
    log_path.write_text(
        json.dumps({"from": "agent-1", "iteration": "iter-1", "content": "existing 1"}) + "\n"
        + json.dumps({"from": "agent-2", "iteration": "iter-1", "content": "existing 2"}) + "\n"
    )

    agents = [
        {"name": "agent-1", "system_prompt": "You are an engineer."},
        {"name": "agent-2", "system_prompt": "You are an engineer."},
    ]
    iteration = {
        "id": "iter-1",
        "description": "Design something",
        "status": "in-progress",
        "max_turns": 4,  # 4 total, 2 already done → 2 more
    }
    model_config = {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "test-model",
    }

    def mock_completion(base_url, model, messages, api_key=None):
        return "new response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(team, agents, iteration, model_config)

    messages = []
    for line in log_path.read_text().splitlines():
        if line.strip():
            messages.append(json.loads(line))

    assert len(messages) == 4
    # First two are the originals
    assert messages[0]["content"] == "existing 1"
    assert messages[1]["content"] == "existing 2"
    # Next two continue the alternation
    assert messages[2]["from"] == "agent-1"
    assert messages[3]["from"] == "agent-2"


# --- run loop edge cases ---

def _make_team_dir(tmp_path):
    """Helper to create a minimal .team/ dir for run_conversation tests."""
    team = tmp_path / ".team"
    team.mkdir()
    (team / "agents").mkdir()
    (team / "conversation.jsonl").touch()
    return team


def _default_agents():
    return [
        {"name": "agent-1", "system_prompt": "You are an engineer."},
        {"name": "agent-2", "system_prompt": "You are an engineer."},
    ]


def _default_model_config():
    return {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "test-model",
    }


def test_run_conversation_max_turns_zero_produces_no_messages(tmp_path):
    """max_turns=0 should do nothing, not loop forever."""
    team = _make_team_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 0,
    }
    with patch("gotg.cli.chat_completion", return_value="nope"):
        run_conversation(team, _default_agents(), iteration, _default_model_config())
    messages = read_log(team / "conversation.jsonl")
    assert len(messages) == 0


def test_run_conversation_max_turns_one_runs_single_agent(tmp_path):
    """max_turns=1 should produce exactly one message from agent-1."""
    team = _make_team_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 1,
    }
    with patch("gotg.cli.chat_completion", return_value="only response"):
        run_conversation(team, _default_agents(), iteration, _default_model_config())
    messages = read_log(team / "conversation.jsonl")
    assert len(messages) == 1
    assert messages[0]["from"] == "agent-1"


def test_run_conversation_already_at_max_turns(tmp_path):
    """If log already has max_turns messages, running again does nothing."""
    team = _make_team_dir(tmp_path)
    log_path = team / "conversation.jsonl"
    for i in range(4):
        agent = f"agent-{(i % 2) + 1}"
        log_path.write_text(
            log_path.read_text()
            + json.dumps({"from": agent, "iteration": "iter-1", "content": f"msg {i}"}) + "\n"
        )
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 4,
    }
    call_count = 0
    def mock_completion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return "should not happen"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(team, _default_agents(), iteration, _default_model_config())
    assert call_count == 0


def test_run_conversation_three_agents_rotate(tmp_path):
    """N-agent rotation should work, not just 2."""
    team = _make_team_dir(tmp_path)
    agents = [
        {"name": "alice", "system_prompt": "You are an engineer."},
        {"name": "bob", "system_prompt": "You are an engineer."},
        {"name": "carol", "system_prompt": "You are an engineer."},
    ]
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 6,
    }
    with patch("gotg.cli.chat_completion", return_value="response"):
        run_conversation(team, agents, iteration, _default_model_config())
    messages = read_log(team / "conversation.jsonl")
    assert [m["from"] for m in messages] == ["alice", "bob", "carol", "alice", "bob", "carol"]


def test_run_conversation_model_error_mid_conversation(tmp_path):
    """If the model errors on turn 3, turns 1-2 should be saved in the log."""
    import httpx
    team = _make_team_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 6,
    }

    call_count = 0
    def flaky_completion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise httpx.ConnectError("Ollama crashed")
        return f"response {call_count}"

    with pytest.raises(httpx.ConnectError):
        with patch("gotg.cli.chat_completion", side_effect=flaky_completion):
            run_conversation(team, _default_agents(), iteration, _default_model_config())

    # First 2 messages should be safely written
    messages = read_log(team / "conversation.jsonl")
    assert len(messages) == 2
    assert messages[0]["from"] == "agent-1"
    assert messages[1]["from"] == "agent-2"


def test_run_conversation_messages_have_correct_iteration_id(tmp_path):
    """Every message should carry the iteration id."""
    team = _make_team_dir(tmp_path)
    iteration = {
        "id": "iter-42-todo-design", "description": "A task",
        "status": "in-progress", "max_turns": 4,
    }
    with patch("gotg.cli.chat_completion", return_value="ok"):
        run_conversation(team, _default_agents(), iteration, _default_model_config())
    messages = read_log(team / "conversation.jsonl")
    assert all(m["iteration"] == "iter-42-todo-design" for m in messages)


# --- cmd_run validation edge cases ---

def test_cli_run_fails_with_fewer_than_two_agents(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    agents_dir = team / "agents"
    agents_dir.mkdir()
    (agents_dir / "agent-1.json").write_text(json.dumps({
        "name": "agent-1", "system_prompt": "hi",
    }))
    (team / "iteration.json").write_text(json.dumps({
        "id": "iter-1", "description": "A task", "status": "in-progress", "max_turns": 10,
    }))
    (team / "model.json").write_text(json.dumps({
        "provider": "ollama", "base_url": "http://localhost:11434", "model": "m",
    }))
    (team / "conversation.jsonl").touch()

    with patch("sys.argv", ["gotg", "run"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()
