import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gotg.cli import main, find_team_dir, run_conversation, cmd_continue
from gotg.conversation import read_log, append_message


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
    assert (tmp_path / ".team" / "team.json").exists()


def test_cli_init_defaults_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "init"]):
        main()
    assert (tmp_path / ".team").is_dir()


# --- gotg show ---

def _make_show_team_dir(tmp_path, messages=None):
    """Helper to create .team/ for show tests (needs iteration.json + iterations dir)."""
    team = tmp_path / ".team"
    team.mkdir()
    (team / "iteration.json").write_text(json.dumps({
        "iterations": [
            {"id": "iter-1", "title": "", "description": "A task",
             "status": "in-progress", "max_turns": 10},
        ],
        "current": "iter-1",
    }, indent=2))
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    log_path = iter_dir / "conversation.jsonl"
    if messages:
        log_path.write_text(
            "\n".join(json.dumps(m) for m in messages) + "\n"
        )
    else:
        log_path.touch()
    return team


def test_cli_show_prints_messages(tmp_path, capsys):
    team = _make_show_team_dir(tmp_path, messages=[
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
        {"from": "agent-2", "iteration": "iter-1", "content": "hi back"},
    ])
    with patch("sys.argv", ["gotg", "show"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()
    output = capsys.readouterr().out
    assert "agent-1" in output
    assert "hello" in output
    assert "agent-2" in output


def test_cli_show_empty_log(tmp_path, capsys):
    team = _make_show_team_dir(tmp_path)
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


def _write_team_json(team_dir, model=None, agents=None):
    """Helper to write team.json."""
    default_agents = [
        {"name": "agent-1", "role": "Software Engineer"},
        {"name": "agent-2", "role": "Software Engineer"},
    ]
    (team_dir / "team.json").write_text(json.dumps({
        "model": model or {
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "m",
        },
        "agents": default_agents if agents is None else agents,
    }, indent=2))


def _write_iteration_json(team_dir, iterations=None, current="iter-1"):
    """Helper to write list-format iteration.json."""
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": iterations or [
            {"id": "iter-1", "title": "", "description": "A task",
             "status": "in-progress", "max_turns": 10},
        ],
        "current": current,
    }, indent=2))


def test_cli_run_fails_with_empty_description(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "",
         "status": "in-progress", "max_turns": 10},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    with patch("sys.argv", ["gotg", "run"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()


def test_cli_run_fails_with_pending_status(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "pending", "max_turns": 10},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    with patch("sys.argv", ["gotg", "run"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()


# --- run_conversation ---

def _make_iter_dir(tmp_path):
    """Helper to create a minimal iteration dir for run_conversation tests."""
    iter_dir = tmp_path / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    return iter_dir


def _default_agents():
    return [
        {"name": "agent-1", "role": "Software Engineer"},
        {"name": "agent-2", "role": "Software Engineer"},
    ]


def _default_model_config():
    return {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "test-model",
    }


def test_run_conversation_alternates_agents(tmp_path):
    """The run loop should alternate between agent-1 and agent-2."""
    iter_dir = _make_iter_dir(tmp_path)

    agents = _default_agents()
    iteration = {
        "id": "iter-1",
        "description": "Design something",
        "status": "in-progress",
        "max_turns": 4,
    }

    call_count = 0
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama"):
        nonlocal call_count
        call_count += 1
        return f"Response {call_count}"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, agents, iteration, _default_model_config())

    log_path = iter_dir / "conversation.jsonl"
    messages = read_log(log_path)
    assert len(messages) == 4
    assert messages[0]["from"] == "agent-1"
    assert messages[1]["from"] == "agent-2"
    assert messages[2]["from"] == "agent-1"
    assert messages[3]["from"] == "agent-2"


def test_run_conversation_resumes_from_existing(tmp_path):
    """If conversation.jsonl already has messages, pick up where we left off."""
    iter_dir = _make_iter_dir(tmp_path)
    log_path = iter_dir / "conversation.jsonl"
    # Pre-populate with 2 messages (agent-1, agent-2)
    log_path.write_text(
        json.dumps({"from": "agent-1", "iteration": "iter-1", "content": "existing 1"}) + "\n"
        + json.dumps({"from": "agent-2", "iteration": "iter-1", "content": "existing 2"}) + "\n"
    )

    iteration = {
        "id": "iter-1",
        "description": "Design something",
        "status": "in-progress",
        "max_turns": 4,  # 4 total, 2 already done → 2 more
    }

    def mock_completion(base_url, model, messages, api_key=None, provider="ollama"):
        return "new response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    messages = read_log(log_path)
    assert len(messages) == 4
    assert messages[0]["content"] == "existing 1"
    assert messages[1]["content"] == "existing 2"
    assert messages[2]["from"] == "agent-1"
    assert messages[3]["from"] == "agent-2"


# --- run loop edge cases ---

def test_run_conversation_max_turns_zero_produces_no_messages(tmp_path):
    """max_turns=0 should do nothing, not loop forever."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 0,
    }
    with patch("gotg.cli.chat_completion", return_value="nope"):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())
    messages = read_log(iter_dir / "conversation.jsonl")
    assert len(messages) == 0


def test_run_conversation_max_turns_one_runs_single_agent(tmp_path):
    """max_turns=1 should produce exactly one message from agent-1."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 1,
    }
    with patch("gotg.cli.chat_completion", return_value="only response"):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())
    messages = read_log(iter_dir / "conversation.jsonl")
    assert len(messages) == 1
    assert messages[0]["from"] == "agent-1"


def test_run_conversation_already_at_max_turns(tmp_path):
    """If log already has max_turns messages, running again does nothing."""
    iter_dir = _make_iter_dir(tmp_path)
    log_path = iter_dir / "conversation.jsonl"
    for i in range(4):
        agent = f"agent-{(i % 2) + 1}"
        append_message(log_path, {"from": agent, "iteration": "iter-1", "content": f"msg {i}"})
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
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())
    assert call_count == 0


def test_run_conversation_three_agents_rotate(tmp_path):
    """N-agent rotation should work, not just 2."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = [
        {"name": "alice", "role": "Software Engineer"},
        {"name": "bob", "role": "Software Engineer"},
        {"name": "carol", "role": "Software Engineer"},
    ]
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 6,
    }
    with patch("gotg.cli.chat_completion", return_value="response"):
        run_conversation(iter_dir, agents, iteration, _default_model_config())
    messages = read_log(iter_dir / "conversation.jsonl")
    assert [m["from"] for m in messages] == ["alice", "bob", "carol", "alice", "bob", "carol"]


def test_run_conversation_model_error_mid_conversation(tmp_path):
    """If the model errors on turn 3, turns 1-2 should be saved in the log."""
    import httpx
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 6,
    }

    call_count = 0
    def flaky_completion(base_url, model, messages, api_key=None, provider="ollama"):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise httpx.ConnectError("Ollama crashed")
        return f"response {call_count}"

    with pytest.raises(httpx.ConnectError):
        with patch("gotg.cli.chat_completion", side_effect=flaky_completion):
            run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    messages = read_log(iter_dir / "conversation.jsonl")
    assert len(messages) == 2
    assert messages[0]["from"] == "agent-1"
    assert messages[1]["from"] == "agent-2"


def test_run_conversation_messages_have_correct_iteration_id(tmp_path):
    """Every message should carry the iteration id."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-42-todo-design", "description": "A task",
        "status": "in-progress", "max_turns": 4,
    }
    with patch("gotg.cli.chat_completion", return_value="ok"):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())
    messages = read_log(iter_dir / "conversation.jsonl")
    assert all(m["iteration"] == "iter-42-todo-design" for m in messages)


# --- cmd_run validation edge cases ---

def test_cli_run_fails_with_fewer_than_two_agents(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team, agents=[
        {"name": "agent-1", "role": "Software Engineer"},
    ])
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    with patch("sys.argv", ["gotg", "run"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()


# --- max-turns override ---

def test_run_conversation_with_max_turns_override(tmp_path):
    """max_turns_override should take precedence over iteration config."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 10,
    }
    with patch("gotg.cli.chat_completion", return_value="response"):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config(),
                         max_turns_override=3)
    messages = read_log(iter_dir / "conversation.jsonl")
    assert len(messages) == 3


# --- human turn skipping ---

def test_run_conversation_skips_human_in_turn_count(tmp_path):
    """Human messages in log should not affect agent turn count or rotation."""
    iter_dir = _make_iter_dir(tmp_path)
    log_path = iter_dir / "conversation.jsonl"
    # Pre-populate: agent-1, human, agent-2 (2 agent turns, 1 human)
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "idea"})
    append_message(log_path, {"from": "human", "iteration": "iter-1", "content": "feedback"})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "response"})

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 4,
    }

    call_log = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama"):
        call_log.append("call")
        return "new response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    assert len(call_log) == 2
    messages = read_log(log_path)
    agent_messages = [m for m in messages if m["from"] != "human"]
    assert len(agent_messages) == 4
    assert agent_messages[2]["from"] == "agent-1"
    assert agent_messages[3]["from"] == "agent-2"


# --- continue command ---

def _make_full_team_dir(tmp_path):
    """Helper to create a .team/ dir with all config files for continue tests."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    return team, iter_dir


def test_continue_appends_human_message(tmp_path):
    """continue -m should append human message to log."""
    team, iter_dir = _make_full_team_dir(tmp_path)
    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "idea"})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "response"})

    # --max-turns 0 so no agent turns, just the human message
    with patch("sys.argv", ["gotg", "continue", "-m", "consider auth", "--max-turns", "0"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    messages = read_log(log_path)
    assert len(messages) == 3
    assert messages[2]["from"] == "human"
    assert messages[2]["content"] == "consider auth"
    assert messages[2]["iteration"] == "iter-1"


def test_continue_without_message_just_continues(tmp_path):
    """continue without -m should just run more agent turns."""
    team, iter_dir = _make_full_team_dir(tmp_path)
    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "idea"})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "response"})

    with patch("sys.argv", ["gotg", "continue", "--max-turns", "2"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="more talk"):
                main()

    messages = read_log(log_path)
    assert len(messages) == 4
    assert messages[2]["from"] == "agent-1"
    assert messages[3]["from"] == "agent-2"


def test_continue_max_turns_means_new_turns(tmp_path):
    """--max-turns on continue means N MORE turns, not total."""
    team, iter_dir = _make_full_team_dir(tmp_path)
    log_path = iter_dir / "conversation.jsonl"
    # Pre-populate 6 agent turns
    for i in range(6):
        agent = f"agent-{(i % 2) + 1}"
        append_message(log_path, {"from": agent, "iteration": "iter-1", "content": f"msg {i}"})

    with patch("sys.argv", ["gotg", "continue", "--max-turns", "2"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="extended"):
                main()

    messages = read_log(log_path)
    assert len(messages) == 8


def test_continue_human_message_not_counted_in_turns(tmp_path):
    """Human message via -m should not count toward --max-turns limit."""
    team, iter_dir = _make_full_team_dir(tmp_path)

    with patch("sys.argv", ["gotg", "continue", "-m", "my input", "--max-turns", "2"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="response"):
                main()

    messages = read_log(iter_dir / "conversation.jsonl")
    human_msgs = [m for m in messages if m["from"] == "human"]
    agent_msgs = [m for m in messages if m["from"] != "human"]
    assert len(human_msgs) == 1
    assert len(agent_msgs) == 2


# --- advance command ---

def _make_advance_team_dir(tmp_path, phase="grooming"):
    """Helper to create a .team/ dir for advance tests."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": phase, "max_turns": 10},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    return team, iter_dir


def test_advance_grooming_to_planning(tmp_path):
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="grooming")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    # Verify iteration.json updated
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "planning"

    # Verify system message in log
    messages = read_log(iter_dir / "conversation.jsonl")
    assert len(messages) == 1
    assert messages[0]["from"] == "system"
    assert "grooming" in messages[0]["content"]
    assert "planning" in messages[0]["content"]


def test_advance_planning_to_pre_code_review(tmp_path):
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="planning")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "pre-code-review"


def test_advance_past_last_phase_errors(tmp_path):
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="pre-code-review")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()


def test_advance_fails_without_team_dir(tmp_path):
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=None):
            with pytest.raises(SystemExit):
                main()


def test_advance_fails_if_not_in_progress(tmp_path):
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "pending", "phase": "grooming", "max_turns": 10},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()


def test_advance_defaults_to_grooming_if_no_phase(tmp_path):
    """Backward compat: iteration without phase field defaults to grooming."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    # No phase field in iteration
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "max_turns": 10},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "planning"
