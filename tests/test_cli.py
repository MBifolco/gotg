import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gotg.cli import main, find_team_dir, run_conversation, cmd_continue, _validate_task_assignments, _auto_checkpoint
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


# --- advance with coach ---

def _add_coach_to_team_json(team_dir):
    """Add coach config to an existing team.json."""
    team_path = team_dir / "team.json"
    team_config = json.loads(team_path.read_text())
    team_config["coach"] = {"name": "coach", "role": "Agile Coach"}
    team_path.write_text(json.dumps(team_config, indent=2))


def test_advance_with_coach_produces_groomed_md(tmp_path):
    """Advancing grooming→planning with coach should produce groomed.md."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="grooming")
    _add_coach_to_team_json(team)

    # Add some conversation history for the coach to summarize
    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "We need auth."})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "Agreed, JWT."})

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="## Summary\nAuth system design."):
                main()

    # groomed.md should exist with coach response
    groomed = iter_dir / "groomed.md"
    assert groomed.exists()
    assert "Auth system design" in groomed.read_text()

    # Phase should still advance
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "planning"

    # System message should mention groomed.md
    messages = read_log(log_path)
    system_msgs = [m for m in messages if m["from"] == "system"]
    assert any("groomed.md" in m["content"] for m in system_msgs)


def test_advance_with_coach_prints_status(tmp_path, capsys):
    """Coach invocation should print status messages."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="grooming")
    _add_coach_to_team_json(team)

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="summary"):
                main()

    output = capsys.readouterr().out
    assert "Coach is summarizing" in output
    assert "groomed" in output.lower()


def test_advance_without_coach_skips_summary(tmp_path):
    """No coach in team.json → advance works, no groomed.md produced."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="grooming")
    # _write_team_json does NOT include coach, so no coach

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    # No groomed.md
    assert not (iter_dir / "groomed.md").exists()

    # Phase should still advance
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "planning"


def test_advance_planning_with_coach_produces_tasks_json(tmp_path):
    """Advancing planning→pre-code-review with coach should produce tasks.json."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="planning")
    _add_coach_to_team_json(team)

    # Add some planning conversation
    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "Task 1: build auth."})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "Task 2: build API."})

    tasks_response = json.dumps([
        {"id": "build-auth", "description": "Build auth", "done_criteria": "Auth works",
         "depends_on": [], "assigned_to": None, "status": "pending"},
        {"id": "build-api", "description": "Build API", "done_criteria": "API works",
         "depends_on": ["build-auth"], "assigned_to": None, "status": "pending"},
    ])

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value=tasks_response):
                main()

    # tasks.json should exist with valid JSON
    tasks_path = iter_dir / "tasks.json"
    assert tasks_path.exists()
    tasks_data = json.loads(tasks_path.read_text())
    assert len(tasks_data) == 2
    assert tasks_data[0]["id"] == "build-auth"
    assert tasks_data[1]["depends_on"] == ["build-auth"]
    # Layers should be computed and stored
    assert tasks_data[0]["layer"] == 0
    assert tasks_data[1]["layer"] == 1

    # Phase should advance
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "pre-code-review"

    # System message should mention tasks.json
    messages = read_log(log_path)
    system_msgs = [m for m in messages if m["from"] == "system"]
    assert any("tasks.json" in m["content"] for m in system_msgs)


# --- coach-as-facilitator (in-conversation) ---

def _default_coach():
    return {"name": "coach", "role": "Agile Coach"}


def _mock_chat_with_tools(base_url, model, messages, api_key=None, provider="ollama", tools=None):
    """Mock chat_completion that handles tools parameter (returns dict for coach calls)."""
    if tools:
        return {"content": "response", "tool_calls": []}
    return "response"


def test_run_conversation_coach_injects_after_rotation(tmp_path):
    """Coach should speak after every full rotation of engineering agents."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 4,
    }

    call_log = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        call_log.append("call")
        if tools:
            return {"content": "response", "tool_calls": []}
        return "response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(iter_dir / "conversation.jsonl")
    senders = [m["from"] for m in messages]
    # 4 agent turns with coach after each full rotation (every 2 agent turns)
    # agent-1, agent-2, coach, agent-1, agent-2, coach
    assert senders == ["agent-1", "agent-2", "coach", "agent-1", "agent-2", "coach"]
    # 4 agent calls + 2 coach calls = 6 total
    assert len(call_log) == 6


def test_run_conversation_coach_turns_not_counted(tmp_path):
    """Coach messages should not count toward max_turns."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 2,
    }

    with patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(iter_dir / "conversation.jsonl")
    agent_msgs = [m for m in messages if m["from"] not in ("coach", "system")]
    coach_msgs = [m for m in messages if m["from"] == "coach"]
    assert len(agent_msgs) == 2
    assert len(coach_msgs) == 1  # coach after the single full rotation


def test_run_conversation_coach_early_exit(tmp_path):
    """Coach using signal_phase_complete tool should end the conversation early."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 10,
    }

    call_count = 0
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        nonlocal call_count
        call_count += 1
        # 3rd call is the coach (after agent-1, agent-2)
        if call_count == 3:
            return {
                "content": "All items resolved. Recommend advancing.",
                "tool_calls": [{"name": "signal_phase_complete", "input": {"summary": "Scope agreed."}}],
            }
        if tools:
            return {"content": "response", "tool_calls": []}
        return "response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(iter_dir / "conversation.jsonl")
    # Should stop after: agent-1, agent-2, coach (3 messages only)
    assert len(messages) == 3
    assert messages[2]["from"] == "coach"
    assert "Recommend advancing" in messages[2]["content"]


def test_run_conversation_coach_no_tool_call_continues(tmp_path):
    """Coach returning empty tool_calls should NOT trigger early exit."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 4,
    }

    with patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(iter_dir / "conversation.jsonl")
    # All 4 agent turns should complete (no early exit)
    agent_msgs = [m for m in messages if m["from"] not in ("coach", "system")]
    assert len(agent_msgs) == 4


def test_run_conversation_no_coach_backward_compatible(tmp_path):
    """Without coach, run_conversation should behave exactly as before."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 4,
    }

    with patch("gotg.cli.chat_completion", return_value="response"):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config())  # no coach kwarg

    messages = read_log(iter_dir / "conversation.jsonl")
    senders = [m["from"] for m in messages]
    assert senders == ["agent-1", "agent-2", "agent-1", "agent-2"]


def test_run_conversation_coach_in_participants(tmp_path):
    """Engineers should see the coach in their prompt's teammate list."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 1,
    }

    captured_messages = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama"):
        captured_messages.append(messages)
        return "response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    # First call is agent-1's prompt — system message should mention coach
    system_msg = captured_messages[0][0]["content"]
    assert "coach" in system_msg.lower()


def test_run_conversation_three_agents_with_coach(tmp_path):
    """Coach should inject after every 3-agent rotation."""
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

    with patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
        run_conversation(iter_dir, agents, iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(iter_dir / "conversation.jsonl")
    senders = [m["from"] for m in messages]
    # alice, bob, carol, coach, alice, bob, carol, coach
    assert senders == ["alice", "bob", "carol", "coach", "alice", "bob", "carol", "coach"]


def test_run_conversation_resumes_with_coach_history(tmp_path):
    """Resuming with coach messages in log should not miscount turns."""
    iter_dir = _make_iter_dir(tmp_path)
    log_path = iter_dir / "conversation.jsonl"
    # Pre-populate: agent-1, agent-2, coach (1 full rotation + coach)
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "idea"})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "reply"})
    append_message(log_path, {"from": "coach", "iteration": "iter-1", "content": "summary"})

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 4,  # 2 existing + 2 more
    }

    with patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(log_path)
    senders = [m["from"] for m in messages]
    # existing: agent-1, agent-2, coach; new: agent-1, agent-2, coach
    assert senders == ["agent-1", "agent-2", "coach", "agent-1", "agent-2", "coach"]


def test_cmd_run_loads_and_passes_coach(tmp_path):
    """cmd_run should load coach from team.json and pass to run_conversation."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _add_coach_to_team_json(team)
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    captured_kwargs = {}
    original_run = run_conversation
    def spy_run(*args, **kwargs):
        captured_kwargs.update(kwargs)
        kwargs["max_turns_override"] = 0  # don't actually run
        return original_run(*args, **kwargs)

    with patch("sys.argv", ["gotg", "run"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.run_conversation", side_effect=spy_run):
                main()

    assert captured_kwargs.get("coach") is not None
    assert captured_kwargs["coach"]["name"] == "coach"


def test_continue_excludes_coach_from_turn_count(tmp_path):
    """continue --max-turns should not count coach messages as agent turns."""
    team, iter_dir = _make_full_team_dir(tmp_path)
    _add_coach_to_team_json(team)
    log_path = iter_dir / "conversation.jsonl"
    # Pre-populate: agent-1, agent-2, coach (2 agent turns, 1 coach)
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "idea"})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "reply"})
    append_message(log_path, {"from": "coach", "iteration": "iter-1", "content": "summary"})

    with patch("sys.argv", ["gotg", "continue", "--max-turns", "2"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
                main()

    messages = read_log(log_path)
    # Coach message should not have inflated the turn count
    agent_msgs = [m for m in messages if m["from"] not in ("coach", "system")]
    assert len(agent_msgs) == 4  # 2 existing + 2 new


# --- groomed.md artifact injection ---

def test_run_conversation_reads_groomed_md(tmp_path):
    """run_conversation should read groomed.md and pass it to build_prompt."""
    iter_dir = _make_iter_dir(tmp_path)
    (iter_dir / "groomed.md").write_text("## Summary\nBuild auth.\n")

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "planning", "max_turns": 1,
    }

    captured_prompts = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama"):
        captured_prompts.append(messages)
        return "response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    system_msg = captured_prompts[0][0]["content"]
    assert "Build auth." in system_msg
    assert "GROOMED SCOPE SUMMARY" in system_msg


def test_run_conversation_no_groomed_md_no_injection(tmp_path):
    """Without groomed.md, no summary should appear in prompts."""
    iter_dir = _make_iter_dir(tmp_path)

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "grooming", "max_turns": 1,
    }

    captured_prompts = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama"):
        captured_prompts.append(messages)
        return "response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    system_msg = captured_prompts[0][0]["content"]
    assert "GROOMED SCOPE SUMMARY" not in system_msg


def test_run_conversation_groomed_md_passed_to_coach(tmp_path):
    """Coach prompt should also receive the groomed summary."""
    iter_dir = _make_iter_dir(tmp_path)
    (iter_dir / "groomed.md").write_text("## Summary\nBuild auth.\n")

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "planning", "max_turns": 2,
    }

    captured_prompts = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        captured_prompts.append(messages)
        if tools:
            return {"content": "response", "tool_calls": []}
        return "response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    # 3rd call is the coach (after agent-1, agent-2)
    coach_system_msg = captured_prompts[2][0]["content"]
    assert "Build auth." in coach_system_msg
    assert "GROOMED SCOPE SUMMARY" in coach_system_msg


# --- tasks.json advance + injection ---

def test_advance_planning_without_coach_no_tasks_json(tmp_path):
    """No coach in team.json → advance planning still works, no tasks.json."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="planning")
    # No coach added

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    assert not (iter_dir / "tasks.json").exists()
    assert not (iter_dir / "tasks_raw.txt").exists()

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "pre-code-review"


def test_advance_planning_invalid_json_saves_raw(tmp_path):
    """Invalid JSON from coach should save tasks_raw.txt, still advance."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="planning")
    _add_coach_to_team_json(team)

    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "idea"})

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="Not valid JSON at all {{{"):
                main()

    # tasks_raw.txt should exist, tasks.json should not
    assert not (iter_dir / "tasks.json").exists()
    assert (iter_dir / "tasks_raw.txt").exists()
    assert "Not valid JSON" in (iter_dir / "tasks_raw.txt").read_text()

    # Phase should still advance
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "pre-code-review"


def test_advance_planning_strips_code_fences(tmp_path):
    """Coach output wrapped in markdown fences should still parse."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="planning")
    _add_coach_to_team_json(team)

    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "idea"})

    fenced = '```json\n[{"id": "t1", "description": "Do it", "done_criteria": "Done", "depends_on": [], "assigned_to": null, "status": "pending"}]\n```'

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value=fenced):
                main()

    tasks_path = iter_dir / "tasks.json"
    assert tasks_path.exists()
    tasks_data = json.loads(tasks_path.read_text())
    assert len(tasks_data) == 1
    assert tasks_data[0]["id"] == "t1"
    assert tasks_data[0]["layer"] == 0


def test_run_conversation_reads_tasks_json(tmp_path):
    """run_conversation should read tasks.json and inject TASK LIST into prompts."""
    iter_dir = _make_iter_dir(tmp_path)
    tasks = [
        {"id": "auth", "depends_on": [], "description": "Build auth",
         "done_criteria": "Auth works", "assigned_to": None, "status": "pending"},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "pre-code-review", "max_turns": 1,
    }

    captured_prompts = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama"):
        captured_prompts.append(messages)
        return "response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    system_msg = captured_prompts[0][0]["content"]
    assert "TASK LIST" in system_msg
    assert "auth" in system_msg


def test_run_conversation_no_tasks_json_no_task_list(tmp_path):
    """Without tasks.json, no TASK LIST should appear in prompts."""
    iter_dir = _make_iter_dir(tmp_path)

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "pre-code-review", "max_turns": 1,
    }

    captured_prompts = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama"):
        captured_prompts.append(messages)
        return "response"

    with patch("gotg.cli.chat_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    system_msg = captured_prompts[0][0]["content"]
    assert "TASK LIST" not in system_msg


# --- task assignment validation ---

def test_validate_task_assignments_blocks_unassigned(tmp_path):
    """Pre-code-review should fail if any tasks are unassigned."""
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir(parents=True)
    tasks = [
        {"id": "t1", "assigned_to": "agent-1", "depends_on": [], "description": "x",
         "done_criteria": "y", "status": "pending"},
        {"id": "t2", "assigned_to": None, "depends_on": [], "description": "x",
         "done_criteria": "y", "status": "pending"},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    with pytest.raises(SystemExit):
        _validate_task_assignments(iter_dir, "pre-code-review")


def test_validate_task_assignments_passes_when_all_assigned(tmp_path):
    """Pre-code-review should succeed if all tasks are assigned."""
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir(parents=True)
    tasks = [
        {"id": "t1", "assigned_to": "agent-1", "depends_on": [], "description": "x",
         "done_criteria": "y", "status": "pending"},
        {"id": "t2", "assigned_to": "agent-2", "depends_on": [], "description": "x",
         "done_criteria": "y", "status": "pending"},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    # Should not raise
    _validate_task_assignments(iter_dir, "pre-code-review")


def test_validate_task_assignments_skips_non_pre_code_review(tmp_path):
    """Validation should be a no-op for other phases."""
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir(parents=True)
    # No tasks.json at all — should not raise for grooming/planning
    _validate_task_assignments(iter_dir, "grooming")
    _validate_task_assignments(iter_dir, "planning")


def test_validate_task_assignments_missing_tasks_json(tmp_path):
    """Pre-code-review without tasks.json should fail."""
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir(parents=True)

    with pytest.raises(SystemExit):
        _validate_task_assignments(iter_dir, "pre-code-review")


# --- auto-checkpoint ---

def test_auto_checkpoint_creates_checkpoint(tmp_path):
    """_auto_checkpoint should create a checkpoint directory."""
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    iteration = {"id": "iter-1", "phase": "grooming", "status": "in-progress", "max_turns": 10}
    _auto_checkpoint(iter_dir, iteration)

    assert (iter_dir / "checkpoints" / "1").is_dir()
    assert (iter_dir / "checkpoints" / "1" / "state.json").exists()


def test_auto_checkpoint_prints_message(tmp_path, capsys):
    """_auto_checkpoint should print confirmation."""
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    iteration = {"id": "iter-1", "phase": "grooming", "status": "in-progress", "max_turns": 10}
    _auto_checkpoint(iter_dir, iteration)

    output = capsys.readouterr().out
    assert "Checkpoint 1 created (auto)" in output


def test_cmd_run_creates_auto_checkpoint(tmp_path):
    """gotg run should create auto-checkpoint after conversation ends."""
    team, iter_dir = _make_full_team_dir(tmp_path)

    with patch("sys.argv", ["gotg", "run", "--max-turns", "2"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="response"):
                main()

    assert (iter_dir / "checkpoints" / "1").is_dir()


def test_cmd_continue_creates_auto_checkpoint(tmp_path):
    """gotg continue should create auto-checkpoint after conversation ends."""
    team, iter_dir = _make_full_team_dir(tmp_path)

    with patch("sys.argv", ["gotg", "continue", "--max-turns", "2"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="response"):
                main()

    assert (iter_dir / "checkpoints" / "1").is_dir()


def test_cmd_advance_creates_auto_checkpoint(tmp_path):
    """gotg advance should create auto-checkpoint after phase transition."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="grooming")

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    assert (iter_dir / "checkpoints" / "1").is_dir()
    # Checkpoint should have the NEW phase
    state = json.loads((iter_dir / "checkpoints" / "1" / "state.json").read_text())
    assert state["phase"] == "planning"


# --- checkpoint command ---

def test_cmd_checkpoint_creates_manual(tmp_path, capsys):
    """gotg checkpoint should create a manual checkpoint."""
    team, iter_dir = _make_full_team_dir(tmp_path)
    (iter_dir / "conversation.jsonl").write_text('{"from":"agent-1","iteration":"iter-1","content":"hi"}\n')

    with patch("sys.argv", ["gotg", "checkpoint", "my save point"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    assert (iter_dir / "checkpoints" / "1").is_dir()
    state = json.loads((iter_dir / "checkpoints" / "1" / "state.json").read_text())
    assert state["trigger"] == "manual"
    assert state["description"] == "my save point"
    output = capsys.readouterr().out
    assert "Checkpoint 1 created" in output


# --- checkpoints command ---

def test_cmd_checkpoints_empty(tmp_path, capsys):
    """gotg checkpoints with no checkpoints should show message."""
    team, iter_dir = _make_full_team_dir(tmp_path)

    with patch("sys.argv", ["gotg", "checkpoints"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    output = capsys.readouterr().out
    assert "No checkpoints yet" in output


def test_cmd_checkpoints_lists(tmp_path, capsys):
    """gotg checkpoints should list existing checkpoints."""
    team, iter_dir = _make_full_team_dir(tmp_path)
    (iter_dir / "conversation.jsonl").touch()

    from gotg.checkpoint import create_checkpoint
    iteration = {"id": "iter-1", "phase": "grooming", "status": "in-progress", "max_turns": 10}
    create_checkpoint(iter_dir, iteration, description="first", trigger="auto")
    create_checkpoint(iter_dir, iteration, description="second", trigger="manual")

    with patch("sys.argv", ["gotg", "checkpoints"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    output = capsys.readouterr().out
    assert "first" in output
    assert "second" in output
    assert "auto" in output
    assert "manual" in output


# --- restore command ---

def test_cmd_restore_restores_state(tmp_path, capsys):
    """gotg restore should restore conversation and update iteration.json."""
    team, iter_dir = _make_full_team_dir(tmp_path)
    # Set phase in iteration.json
    iter_json = json.loads((team / "iteration.json").read_text())
    iter_json["iterations"][0]["phase"] = "grooming"
    (team / "iteration.json").write_text(json.dumps(iter_json, indent=2))

    (iter_dir / "conversation.jsonl").write_text('{"from":"agent-1","iteration":"iter-1","content":"original"}\n')

    from gotg.checkpoint import create_checkpoint
    iteration = {"id": "iter-1", "phase": "grooming", "status": "in-progress", "max_turns": 10}
    create_checkpoint(iter_dir, iteration, description="checkpoint 1")

    # Modify state after checkpoint
    (iter_dir / "conversation.jsonl").write_text('{"from":"agent-1","iteration":"iter-1","content":"modified"}\n')

    with patch("sys.argv", ["gotg", "restore", "1"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("builtins.input", return_value="n"):  # skip safety checkpoint
                main()

    # Conversation should be restored
    assert "original" in (iter_dir / "conversation.jsonl").read_text()
    output = capsys.readouterr().out
    assert "Restored to checkpoint 1" in output


def test_cmd_restore_safety_checkpoint_yes(tmp_path):
    """Restore with Y should create safety checkpoint first."""
    team, iter_dir = _make_full_team_dir(tmp_path)
    iter_json = json.loads((team / "iteration.json").read_text())
    iter_json["iterations"][0]["phase"] = "grooming"
    (team / "iteration.json").write_text(json.dumps(iter_json, indent=2))

    (iter_dir / "conversation.jsonl").write_text('{"from":"agent-1","iteration":"iter-1","content":"current"}\n')

    from gotg.checkpoint import create_checkpoint
    iteration = {"id": "iter-1", "phase": "grooming", "status": "in-progress", "max_turns": 10}
    create_checkpoint(iter_dir, iteration)

    with patch("sys.argv", ["gotg", "restore", "1"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("builtins.input", return_value=""):  # default = yes
                main()

    # Safety checkpoint should exist as #2
    assert (iter_dir / "checkpoints" / "2").is_dir()
    state = json.loads((iter_dir / "checkpoints" / "2" / "state.json").read_text())
    assert "Safety" in state["description"]


def test_cmd_restore_safety_checkpoint_no(tmp_path):
    """Restore with 'n' should skip safety checkpoint."""
    team, iter_dir = _make_full_team_dir(tmp_path)
    iter_json = json.loads((team / "iteration.json").read_text())
    iter_json["iterations"][0]["phase"] = "grooming"
    (team / "iteration.json").write_text(json.dumps(iter_json, indent=2))

    (iter_dir / "conversation.jsonl").touch()

    from gotg.checkpoint import create_checkpoint
    iteration = {"id": "iter-1", "phase": "grooming", "status": "in-progress", "max_turns": 10}
    create_checkpoint(iter_dir, iteration)

    with patch("sys.argv", ["gotg", "restore", "1"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("builtins.input", return_value="n"):
                main()

    # Only original checkpoint, no safety
    assert not (iter_dir / "checkpoints" / "2").exists()


def test_cmd_restore_invalid_number(tmp_path, capsys):
    """Restore with nonexistent checkpoint should error."""
    team, iter_dir = _make_full_team_dir(tmp_path)

    with patch("sys.argv", ["gotg", "restore", "99"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()
