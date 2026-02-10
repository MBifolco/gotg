import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gotg.cli import main, find_team_dir, run_conversation, cmd_continue, _auto_checkpoint
from gotg.session import validate_iteration_for_run, resolve_layer, setup_worktrees, SessionSetupError
from gotg.conversation import read_log, read_phase_history, append_message


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
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    with patch("sys.argv", ["gotg", "init", str(tmp_path)]):
        main()
    assert (tmp_path / ".team").is_dir()
    assert (tmp_path / ".team" / "team.json").exists()


def test_cli_init_defaults_to_cwd(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
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
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        nonlocal call_count
        call_count += 1
        return {"content": f"Response {call_count}", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
        run_conversation(iter_dir, agents, iteration, _default_model_config())

    log_path = iter_dir / "conversation.jsonl"
    messages = [m for m in read_log(log_path) if m["from"] != "system"]
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

    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        return {"content": "new response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    messages = read_log(log_path)
    assert len(messages) == 4
    assert messages[0]["content"] == "existing 1"
    assert messages[1]["content"] == "existing 2"
    assert messages[2]["from"] == "agent-1"
    assert messages[3]["from"] == "agent-2"


# --- run loop edge cases ---

def test_run_conversation_max_turns_zero_produces_no_messages(tmp_path):
    """max_turns=0 should produce no agent messages (only system kickoff)."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 0,
    }
    with patch("gotg.cli.agentic_completion", return_value={"content": "nope", "operations": []}):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())
    messages = [m for m in read_log(iter_dir / "conversation.jsonl") if m["from"] != "system"]
    assert len(messages) == 0


def test_run_conversation_max_turns_one_runs_single_agent(tmp_path):
    """max_turns=1 should produce exactly one agent message from agent-1."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 1,
    }
    with patch("gotg.cli.agentic_completion", return_value={"content": "only response", "operations": []}):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())
    messages = [m for m in read_log(iter_dir / "conversation.jsonl") if m["from"] != "system"]
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
        return {"content": "should not happen", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
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
    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}):
        run_conversation(iter_dir, agents, iteration, _default_model_config())
    messages = [m for m in read_log(iter_dir / "conversation.jsonl") if m["from"] != "system"]
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
    def flaky_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise httpx.ConnectError("Ollama crashed")
        return {"content": f"response {call_count}", "operations": []}

    with pytest.raises(httpx.ConnectError):
        with patch("gotg.cli.agentic_completion", side_effect=flaky_completion):
            run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    messages = [m for m in read_log(iter_dir / "conversation.jsonl") if m["from"] != "system"]
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
    with patch("gotg.cli.agentic_completion", return_value={"content": "ok", "operations": []}):
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
    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config(),
                         max_turns_override=3)
    messages = [m for m in read_log(iter_dir / "conversation.jsonl") if m["from"] != "system"]
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
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        call_log.append("call")
        return {"content": "new response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
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
            with patch("gotg.cli.agentic_completion", return_value={"content": "more talk", "operations": []}):
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
            with patch("gotg.cli.agentic_completion", return_value={"content": "extended", "operations": []}):
                main()

    messages = read_log(log_path)
    assert len(messages) == 8


def test_continue_human_message_not_counted_in_turns(tmp_path):
    """Human message via -m should not count toward --max-turns limit."""
    team, iter_dir = _make_full_team_dir(tmp_path)

    with patch("sys.argv", ["gotg", "continue", "-m", "my input", "--max-turns", "2"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}):
                main()

    messages = read_log(iter_dir / "conversation.jsonl")
    human_msgs = [m for m in messages if m["from"] == "human"]
    agent_msgs = [m for m in messages if m["from"] != "human"]
    assert len(human_msgs) == 1
    assert len(agent_msgs) == 2


# --- advance command ---

def _make_advance_team_dir(tmp_path, phase="refinement"):
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


def test_advance_refinement_to_planning(tmp_path):
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="refinement")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    # Verify iteration.json updated
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "planning"

    # Verify system messages in log (boundary + transition)
    messages = read_log(iter_dir / "conversation.jsonl")
    assert len(messages) == 2
    assert messages[0].get("phase_boundary") is True
    assert messages[1]["from"] == "system"
    assert "refinement" in messages[1]["content"]
    assert "planning" in messages[1]["content"]


def test_advance_planning_to_pre_code_review(tmp_path):
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="planning")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "pre-code-review"


def test_advance_past_last_phase_errors(tmp_path):
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="code-review")
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
         "status": "pending", "phase": "refinement", "max_turns": 10},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()


def test_advance_defaults_to_refinement_if_no_phase(tmp_path):
    """Backward compat: iteration without phase field defaults to refinement."""
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
    """Advancing refinement→planning with coach should produce refinement_summary.md."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="refinement")
    _add_coach_to_team_json(team)

    # Add some conversation history for the coach to summarize
    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "We need auth."})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "Agreed, JWT."})

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="## Summary\nAuth system design."):
                main()

    # refinement_summary.md should exist with coach response
    groomed = iter_dir / "refinement_summary.md"
    assert groomed.exists()
    assert "Auth system design" in groomed.read_text()

    # Phase should still advance
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "planning"

    # System message should mention refinement_summary.md
    messages = read_log(log_path)
    system_msgs = [m for m in messages if m["from"] == "system"]
    assert any("refinement_summary.md" in m["content"] for m in system_msgs)


def test_advance_with_coach_prints_status(tmp_path, capsys):
    """Coach invocation should print status messages."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="refinement")
    _add_coach_to_team_json(team)

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="summary"):
                main()

    output = capsys.readouterr().out
    assert "Summarizing refinement" in output
    assert "refinement_summary.md" in output


def test_advance_without_coach_skips_summary(tmp_path):
    """No coach in team.json → advance works, no refinement_summary.md produced."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="refinement")
    # _write_team_json does NOT include coach, so no coach

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    # No refinement_summary.md
    assert not (iter_dir / "refinement_summary.md").exists()

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
    def mock_agent(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        call_log.append("agent")
        return {"content": "response", "operations": []}
    def mock_coach(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        call_log.append("coach")
        return {"content": "response", "tool_calls": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent), \
         patch("gotg.cli.chat_completion", side_effect=mock_coach):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = [m for m in read_log(iter_dir / "conversation.jsonl") if m["from"] != "system"]
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

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
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

    def mock_agent(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        return {"content": "response", "operations": []}

    coach_call_count = 0
    def mock_coach(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        nonlocal coach_call_count
        coach_call_count += 1
        if coach_call_count == 1:
            return {
                "content": "All items resolved. Recommend advancing.",
                "tool_calls": [{"name": "signal_phase_complete", "input": {"summary": "Scope agreed."}}],
            }
        return {"content": "response", "tool_calls": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent), \
         patch("gotg.cli.chat_completion", side_effect=mock_coach):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = [m for m in read_log(iter_dir / "conversation.jsonl") if m["from"] != "system"]
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

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
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

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config())  # no coach kwarg

    messages = [m for m in read_log(iter_dir / "conversation.jsonl") if m["from"] != "system"]
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
    def mock_agent(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        captured_messages.append(messages)
        return {"content": "response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent), \
         patch("gotg.cli.chat_completion", return_value={"content": "response", "tool_calls": []}):
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

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
        run_conversation(iter_dir, agents, iteration,
                         _default_model_config(), coach=_default_coach())

    messages = [m for m in read_log(iter_dir / "conversation.jsonl") if m["from"] != "system"]
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

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
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
            with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
                 patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
                main()

    messages = read_log(log_path)
    # Coach message should not have inflated the turn count
    agent_msgs = [m for m in messages if m["from"] not in ("coach", "system")]
    assert len(agent_msgs) == 4  # 2 existing + 2 new


# --- refinement_summary.md artifact injection ---

def test_run_conversation_reads_groomed_md(tmp_path):
    """run_conversation should read refinement_summary.md and pass it to build_prompt."""
    iter_dir = _make_iter_dir(tmp_path)
    (iter_dir / "refinement_summary.md").write_text("## Summary\nBuild auth.\n")

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "planning", "max_turns": 1,
    }

    captured_prompts = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        captured_prompts.append(messages)
        return {"content": "response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    system_msg = captured_prompts[0][0]["content"]
    assert "Build auth." in system_msg
    assert "GROOMED SCOPE SUMMARY" in system_msg


def test_run_conversation_no_groomed_md_no_injection(tmp_path):
    """Without refinement_summary.md, no summary should appear in prompts."""
    iter_dir = _make_iter_dir(tmp_path)

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "refinement", "max_turns": 1,
    }

    captured_prompts = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        captured_prompts.append(messages)
        return {"content": "response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    system_msg = captured_prompts[0][0]["content"]
    assert "GROOMED SCOPE SUMMARY" not in system_msg


def test_run_conversation_groomed_md_passed_to_coach(tmp_path):
    """Coach prompt should also receive the groomed summary."""
    iter_dir = _make_iter_dir(tmp_path)
    (iter_dir / "refinement_summary.md").write_text("## Summary\nBuild auth.\n")

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "planning", "max_turns": 2,
    }

    captured_prompts = []
    def mock_agent(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        captured_prompts.append(messages)
        return {"content": "response", "operations": []}
    def mock_coach(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        captured_prompts.append(messages)
        return {"content": "response", "tool_calls": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent), \
         patch("gotg.cli.chat_completion", side_effect=mock_coach):
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
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        captured_prompts.append(messages)
        return {"content": "response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
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
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        captured_prompts.append(messages)
        return {"content": "response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    system_msg = captured_prompts[0][0]["content"]
    assert "TASK LIST" not in system_msg


# --- task assignment validation ---

_DUMMY_AGENTS = [{"name": "a1", "role": "SE"}, {"name": "a2", "role": "SE"}]


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
    iteration = {"id": "iter-1", "description": "test", "status": "in-progress", "phase": "pre-code-review"}

    with pytest.raises(SessionSetupError):
        validate_iteration_for_run(iteration, iter_dir, _DUMMY_AGENTS)


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
    iteration = {"id": "iter-1", "description": "test", "status": "in-progress", "phase": "pre-code-review"}

    # Should not raise
    validate_iteration_for_run(iteration, iter_dir, _DUMMY_AGENTS)


def test_validate_task_assignments_skips_non_pre_code_review(tmp_path):
    """Validation should be a no-op for other phases."""
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir(parents=True)
    # No tasks.json at all — should not raise for refinement/planning
    iteration_r = {"id": "i", "description": "t", "status": "in-progress", "phase": "refinement"}
    validate_iteration_for_run(iteration_r, iter_dir, _DUMMY_AGENTS)
    iteration_p = {"id": "i", "description": "t", "status": "in-progress", "phase": "planning"}
    validate_iteration_for_run(iteration_p, iter_dir, _DUMMY_AGENTS)


def test_validate_task_assignments_missing_tasks_json(tmp_path):
    """Pre-code-review without tasks.json should fail."""
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir(parents=True)
    iteration = {"id": "iter-1", "description": "test", "status": "in-progress", "phase": "pre-code-review"}

    with pytest.raises(SessionSetupError):
        validate_iteration_for_run(iteration, iter_dir, _DUMMY_AGENTS)


# --- auto-checkpoint ---

def test_auto_checkpoint_creates_checkpoint(tmp_path):
    """_auto_checkpoint should create a checkpoint directory."""
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    iteration = {"id": "iter-1", "phase": "refinement", "status": "in-progress", "max_turns": 10}
    _auto_checkpoint(iter_dir, iteration)

    assert (iter_dir / "checkpoints" / "1").is_dir()
    assert (iter_dir / "checkpoints" / "1" / "state.json").exists()


def test_auto_checkpoint_prints_message(tmp_path, capsys):
    """_auto_checkpoint should print confirmation."""
    iter_dir = tmp_path / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    iteration = {"id": "iter-1", "phase": "refinement", "status": "in-progress", "max_turns": 10}
    _auto_checkpoint(iter_dir, iteration)

    output = capsys.readouterr().out
    assert "Checkpoint 1 created (auto)" in output


def test_cmd_run_creates_auto_checkpoint(tmp_path):
    """gotg run should create auto-checkpoint after conversation ends."""
    team, iter_dir = _make_full_team_dir(tmp_path)

    with patch("sys.argv", ["gotg", "run", "--max-turns", "2"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}):
                main()

    assert (iter_dir / "checkpoints" / "1").is_dir()


def test_cmd_continue_creates_auto_checkpoint(tmp_path):
    """gotg continue should create auto-checkpoint after conversation ends."""
    team, iter_dir = _make_full_team_dir(tmp_path)

    with patch("sys.argv", ["gotg", "continue", "--max-turns", "2"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}):
                main()

    assert (iter_dir / "checkpoints" / "1").is_dir()


def test_cmd_advance_creates_auto_checkpoint(tmp_path):
    """gotg advance should create auto-checkpoint after phase transition."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="refinement")

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
    iteration = {"id": "iter-1", "phase": "refinement", "status": "in-progress", "max_turns": 10}
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
    iter_json["iterations"][0]["phase"] = "refinement"
    (team / "iteration.json").write_text(json.dumps(iter_json, indent=2))

    (iter_dir / "conversation.jsonl").write_text('{"from":"agent-1","iteration":"iter-1","content":"original"}\n')

    from gotg.checkpoint import create_checkpoint
    iteration = {"id": "iter-1", "phase": "refinement", "status": "in-progress", "max_turns": 10}
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
    iter_json["iterations"][0]["phase"] = "refinement"
    (team / "iteration.json").write_text(json.dumps(iter_json, indent=2))

    (iter_dir / "conversation.jsonl").write_text('{"from":"agent-1","iteration":"iter-1","content":"current"}\n')

    from gotg.checkpoint import create_checkpoint
    iteration = {"id": "iter-1", "phase": "refinement", "status": "in-progress", "max_turns": 10}
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
    iter_json["iterations"][0]["phase"] = "refinement"
    (team / "iteration.json").write_text(json.dumps(iter_json, indent=2))

    (iter_dir / "conversation.jsonl").touch()

    from gotg.checkpoint import create_checkpoint
    iteration = {"id": "iter-1", "phase": "refinement", "status": "in-progress", "max_turns": 10}
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


# --- File tools integration ---

def test_run_conversation_no_fileguard_backward_compat(tmp_path):
    """run_conversation without fileguard works exactly as before."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = _default_agents()
    iteration = {"id": "iter-1", "description": "Test", "status": "in-progress", "max_turns": 2}

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}):
        run_conversation(iter_dir, agents, iteration, _default_model_config(), fileguard=None)

    messages = [m for m in read_log(iter_dir / "conversation.jsonl") if m["from"] != "system"]
    assert len(messages) == 2
    assert all(m["content"] == "response" for m in messages)


def test_run_conversation_with_fileguard_uses_agentic(tmp_path):
    """When fileguard is provided, run_conversation uses agentic_completion."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = _default_agents()
    iteration = {"id": "iter-1", "description": "Test", "status": "in-progress", "max_turns": 1}

    from gotg.fileguard import FileGuard
    fileguard = FileGuard(tmp_path, {"writable_paths": ["src/**"]})

    mock_result = {
        "content": "I wrote a file.",
        "operations": [
            {"name": "file_write", "input": {"path": "src/main.py", "content": "hello"}, "result": "Written: src/main.py (5 bytes)"},
        ],
    }

    with patch("gotg.cli.agentic_completion", return_value=mock_result) as mock_agentic:
        run_conversation(iter_dir, agents, iteration, _default_model_config(), fileguard=fileguard)

    mock_agentic.assert_called_once()
    messages = read_log(iter_dir / "conversation.jsonl")
    # Should have system message for file op + agent message
    assert any(m["from"] == "system" and "[file_write]" in m["content"] for m in messages)
    assert any(m["from"] == "agent-1" and m["content"] == "I wrote a file." for m in messages)


def test_run_conversation_fileguard_prints_status(tmp_path, capsys):
    """File tools status should be printed at conversation start."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = _default_agents()
    iteration = {"id": "iter-1", "description": "Test", "status": "in-progress", "max_turns": 1}

    from gotg.fileguard import FileGuard
    fileguard = FileGuard(tmp_path, {"writable_paths": ["src/**", "tests/**"]})

    mock_result = {"content": "done", "operations": []}
    with patch("gotg.cli.agentic_completion", return_value=mock_result):
        run_conversation(iter_dir, agents, iteration, _default_model_config(), fileguard=fileguard)

    output = capsys.readouterr().out
    assert "File tools: enabled" in output
    assert "src/**" in output


def test_run_conversation_fileguard_write_limit(tmp_path):
    """Per-turn write limit should be enforced via tool_executor closure."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = _default_agents()
    iteration = {"id": "iter-1", "description": "Test", "status": "in-progress", "max_turns": 1}

    from gotg.fileguard import FileGuard
    fileguard = FileGuard(tmp_path, {"writable_paths": ["src/**"], "max_files_per_turn": 2})

    # The agentic_completion mock will capture the tool_executor
    captured_executor = {}

    def mock_agentic(**kwargs):
        captured_executor["fn"] = kwargs["tool_executor"]
        return {"content": "done", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agentic):
        run_conversation(iter_dir, agents, iteration, _default_model_config(), fileguard=fileguard)

    executor = captured_executor["fn"]
    # Create src/ so writes succeed
    (tmp_path / "src").mkdir()

    # First two writes should succeed (within limit)
    result1 = executor("file_write", {"path": "src/a.py", "content": "a"})
    assert "Written" in result1
    result2 = executor("file_write", {"path": "src/b.py", "content": "b"})
    assert "Written" in result2

    # Third write should be blocked by counter
    result3 = executor("file_write", {"path": "src/c.py", "content": "c"})
    assert "write limit reached" in result3


def test_cmd_run_loads_file_access(tmp_path, monkeypatch):
    """cmd_run should load file_access from team.json and construct FileGuard."""
    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "file_access": {"writable_paths": ["src/**"]},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "max_turns": 2, "phase": "refinement"},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    monkeypatch.chdir(tmp_path)

    with patch("gotg.cli.run_conversation") as mock_run:
        with patch("gotg.cli._auto_checkpoint"):
            with patch("sys.argv", ["gotg", "run"]):
                main()

    # Verify fileguard was passed
    call_kwargs = mock_run.call_args
    fileguard = call_kwargs[1].get("fileguard") if call_kwargs[1] else None
    # If positional, check the args
    if fileguard is None and len(call_kwargs[0]) > 6:
        fileguard = call_kwargs[0][6]
    assert fileguard is not None
    assert fileguard.writable_paths == ["src/**"]


def test_cmd_run_no_file_access_passes_none(tmp_path, monkeypatch):
    """Without file_access in team.json, fileguard should be None."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "max_turns": 2, "phase": "refinement"},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    monkeypatch.chdir(tmp_path)

    with patch("gotg.cli.run_conversation") as mock_run:
        with patch("gotg.cli._auto_checkpoint"):
            with patch("sys.argv", ["gotg", "run"]):
                main()

    call_kwargs = mock_run.call_args
    fileguard = call_kwargs[1].get("fileguard") if call_kwargs[1] else None
    assert fileguard is None


# --- Approval system ---

def test_run_conversation_pauses_on_pending_approval(tmp_path, capsys):
    """Conversation loop should stop when pending approvals exist."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = _default_agents()
    iteration = {"id": "iter-1", "description": "Test", "status": "in-progress", "max_turns": 5}

    from gotg.fileguard import FileGuard
    from gotg.approvals import ApprovalStore
    fileguard = FileGuard(tmp_path, {"writable_paths": ["src/**"], "enable_approvals": True})
    store = ApprovalStore(iter_dir / "approvals.json")

    # Simulate: agentic_completion's tool_executor adds pending request, returns result
    mock_result = {
        "content": "I tried to write a Dockerfile.",
        "operations": [
            {"name": "file_write", "input": {"path": "Dockerfile", "content": "FROM python"}, "result": "Pending approval [a1]: write to Dockerfile"},
        ],
    }

    def mock_agentic(**kwargs):
        # Simulate tool_executor adding pending request during agentic loop
        store.add_request("Dockerfile", "FROM python", "agent-1", {"path": "Dockerfile", "content": "FROM python"})
        return mock_result

    with patch("gotg.cli.agentic_completion", side_effect=mock_agentic):
        run_conversation(iter_dir, agents, iteration, _default_model_config(), fileguard=fileguard, approval_store=store)

    output = capsys.readouterr().out
    assert "Paused" in output
    assert "pending approval" in output
    # Should have stopped after 1 turn (not 5)
    messages = read_log(iter_dir / "conversation.jsonl")
    agent_msgs = [m for m in messages if m["from"] not in ("system",)]
    assert len(agent_msgs) == 1


def test_run_conversation_no_pause_without_approval_store(tmp_path):
    """Without approval_store, no pause logic runs even with fileguard."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = _default_agents()
    iteration = {"id": "iter-1", "description": "Test", "status": "in-progress", "max_turns": 2}

    from gotg.fileguard import FileGuard
    fileguard = FileGuard(tmp_path, {"writable_paths": ["src/**"]})

    mock_result = {"content": "done", "operations": []}

    with patch("gotg.cli.agentic_completion", return_value=mock_result):
        run_conversation(iter_dir, agents, iteration, _default_model_config(), fileguard=fileguard)

    messages = read_log(iter_dir / "conversation.jsonl")
    agent_msgs = [m for m in messages if m["from"] not in ("system",)]
    assert len(agent_msgs) == 2  # Both turns completed


def test_continue_applies_approved_writes(tmp_path, monkeypatch):
    """gotg continue should apply approved writes before resuming."""
    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "file_access": {"writable_paths": ["src/**"], "enable_approvals": True},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "max_turns": 50, "phase": "refinement"},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    # Create a pending request and approve it
    from gotg.approvals import ApprovalStore
    store = ApprovalStore(iter_dir / "approvals.json")
    store.add_request("Dockerfile", "FROM python:3.12", "agent-1", {"path": "Dockerfile", "content": "FROM python:3.12"})
    store.approve("a1")

    monkeypatch.chdir(tmp_path)

    with patch("gotg.cli.run_conversation"):
        with patch("gotg.cli._auto_checkpoint"):
            with patch("sys.argv", ["gotg", "continue"]):
                main()

    # File should have been written
    assert (tmp_path / "Dockerfile").read_text() == "FROM python:3.12"
    # System message should be in conversation log
    messages = read_log(iter_dir / "conversation.jsonl")
    assert any("APPROVED" in m["content"] for m in messages if m["from"] == "system")


def test_continue_injects_denial_messages(tmp_path, monkeypatch):
    """gotg continue should inject denial reasons into conversation."""
    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "file_access": {"writable_paths": ["src/**"], "enable_approvals": True},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "max_turns": 50, "phase": "refinement"},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    from gotg.approvals import ApprovalStore
    store = ApprovalStore(iter_dir / "approvals.json")
    store.add_request("Dockerfile", "FROM python:3.12", "agent-1", {"path": "Dockerfile", "content": "FROM python:3.12"})
    store.deny("a1", "Use src/ directory instead")

    monkeypatch.chdir(tmp_path)

    with patch("gotg.cli.run_conversation"):
        with patch("gotg.cli._auto_checkpoint"):
            with patch("sys.argv", ["gotg", "continue"]):
                main()

    messages = read_log(iter_dir / "conversation.jsonl")
    denial_msgs = [m for m in messages if m["from"] == "system" and "DENIED by PM" in m["content"]]
    assert len(denial_msgs) == 1
    assert "Use src/ directory instead" in denial_msgs[0]["content"]


def test_cmd_approvals_shows_pending(tmp_path, monkeypatch, capsys):
    """gotg approvals should list pending requests."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    from gotg.approvals import ApprovalStore
    store = ApprovalStore(iter_dir / "approvals.json")
    store.add_request("Dockerfile", "FROM python:3.12", "agent-1", {"path": "Dockerfile", "content": "FROM python:3.12"})

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "approvals"]):
        main()

    output = capsys.readouterr().out
    assert "[a1]" in output
    assert "Dockerfile" in output
    assert "agent-1" in output


def test_cmd_approvals_empty(tmp_path, monkeypatch, capsys):
    """gotg approvals with no pending shows 'No pending'."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "approvals"]):
        main()

    output = capsys.readouterr().out
    assert "No pending" in output


def test_cmd_approve_marks_approved(tmp_path, monkeypatch, capsys):
    """gotg approve a1 should mark request approved."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    from gotg.approvals import ApprovalStore
    store = ApprovalStore(iter_dir / "approvals.json")
    store.add_request("Dockerfile", "FROM python", "agent-1", {})

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "approve", "a1"]):
        main()

    output = capsys.readouterr().out
    assert "Approved" in output

    store2 = ApprovalStore(iter_dir / "approvals.json")
    assert store2._get("a1")["status"] == "approved"


def test_cmd_approve_all(tmp_path, monkeypatch, capsys):
    """gotg approve all should approve all pending."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    from gotg.approvals import ApprovalStore
    store = ApprovalStore(iter_dir / "approvals.json")
    store.add_request("f1.txt", "a", "agent-1", {})
    store.add_request("f2.txt", "b", "agent-2", {})

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "approve", "all"]):
        main()

    output = capsys.readouterr().out
    assert "2 approval(s)" in output

    store2 = ApprovalStore(iter_dir / "approvals.json")
    assert len(store2.get_pending()) == 0


def test_cmd_deny_with_reason(tmp_path, monkeypatch, capsys):
    """gotg deny a1 -m 'reason' should deny with reason."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    from gotg.approvals import ApprovalStore
    store = ApprovalStore(iter_dir / "approvals.json")
    store.add_request("Dockerfile", "FROM python", "agent-1", {})

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "deny", "a1", "-m", "Use src/ instead"]):
        main()

    output = capsys.readouterr().out
    assert "Denied" in output
    assert "Use src/ instead" in output

    store2 = ApprovalStore(iter_dir / "approvals.json")
    assert store2._get("a1")["status"] == "denied"
    assert store2._get("a1")["denial_reason"] == "Use src/ instead"


def test_cmd_approve_invalid_id_errors(tmp_path, monkeypatch):
    """gotg approve bad-id should error."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team)
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "approve", "bad-id"]):
        with pytest.raises(SystemExit):
            main()


def test_cmd_run_with_enable_approvals_constructs_store(tmp_path, monkeypatch):
    """cmd_run with enable_approvals should pass approval_store to run_conversation."""
    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "file_access": {"writable_paths": ["src/**"], "enable_approvals": True},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "max_turns": 2, "phase": "refinement"},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    monkeypatch.chdir(tmp_path)

    with patch("gotg.cli.run_conversation") as mock_run:
        with patch("gotg.cli._auto_checkpoint"):
            with patch("sys.argv", ["gotg", "run"]):
                main()

    call_kwargs = mock_run.call_args[1]
    assert call_kwargs.get("approval_store") is not None


def test_cmd_run_without_enable_approvals_no_store(tmp_path, monkeypatch):
    """cmd_run without enable_approvals should pass approval_store=None."""
    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "file_access": {"writable_paths": ["src/**"]},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "max_turns": 2, "phase": "refinement"},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    monkeypatch.chdir(tmp_path)

    with patch("gotg.cli.run_conversation") as mock_run:
        with patch("gotg.cli._auto_checkpoint"):
            with patch("sys.argv", ["gotg", "run"]):
                main()

    call_kwargs = mock_run.call_args[1]
    assert call_kwargs.get("approval_store") is None


# --- Worktree integration ---

def test_run_conversation_with_worktree_map_routes_writes(tmp_path):
    """Agent file writes should go to their worktree, not project root."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = _default_agents()
    iteration = {"id": "iter-1", "description": "Test", "status": "in-progress", "max_turns": 2}

    from gotg.fileguard import FileGuard

    # Set up two "worktree" directories
    wt1 = tmp_path / "wt-agent-1"
    wt1.mkdir()
    (wt1 / "src").mkdir()
    wt2 = tmp_path / "wt-agent-2"
    wt2.mkdir()
    (wt2 / "src").mkdir()

    fileguard = FileGuard(tmp_path, {"writable_paths": ["src/**"]})
    worktree_map = {"agent-1": wt1, "agent-2": wt2}

    # Mock agentic_completion to capture tool_executor and invoke it
    captured = {}

    def mock_agentic(**kwargs):
        agent_name = None
        # Determine which agent by looking at the write path result
        executor = kwargs["tool_executor"]
        captured[len(captured)] = executor
        # Each agent writes a file
        result = executor("file_write", {"path": "src/output.py", "content": f"from agent"})
        return {"content": "done", "operations": [
            {"name": "file_write", "input": {"path": "src/output.py", "content": "from agent"}, "result": result},
        ]}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agentic):
        run_conversation(iter_dir, agents, iteration, _default_model_config(),
                        fileguard=fileguard, worktree_map=worktree_map)

    # Both worktrees should have the file
    assert (wt1 / "src" / "output.py").exists()
    assert (wt2 / "src" / "output.py").exists()
    # Project root should NOT have the file
    assert not (tmp_path / "src" / "output.py").exists()


def test_run_conversation_without_worktree_map_backward_compat(tmp_path):
    """Without worktree_map, writes go to project root as before."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = _default_agents()
    iteration = {"id": "iter-1", "description": "Test", "status": "in-progress", "max_turns": 1}

    from gotg.fileguard import FileGuard
    (tmp_path / "src").mkdir()
    fileguard = FileGuard(tmp_path, {"writable_paths": ["src/**"]})

    def mock_agentic(**kwargs):
        executor = kwargs["tool_executor"]
        result = executor("file_write", {"path": "src/main.py", "content": "hello"})
        return {"content": "done", "operations": [
            {"name": "file_write", "input": {"path": "src/main.py", "content": "hello"}, "result": result},
        ]}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agentic):
        run_conversation(iter_dir, agents, iteration, _default_model_config(),
                        fileguard=fileguard, worktree_map=None)

    assert (tmp_path / "src" / "main.py").read_text() == "hello"


def test_run_conversation_three_agents_with_worktrees(tmp_path):
    """Worktree routing works with N>2 agents."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = [
        {"name": "agent-1", "role": "Software Engineer"},
        {"name": "agent-2", "role": "Software Engineer"},
        {"name": "agent-3", "role": "Software Engineer"},
    ]
    iteration = {"id": "iter-1", "description": "Test", "status": "in-progress", "max_turns": 3}

    from gotg.fileguard import FileGuard

    worktree_map = {}
    for a in agents:
        wt = tmp_path / f"wt-{a['name']}"
        wt.mkdir()
        (wt / "src").mkdir()
        worktree_map[a["name"]] = wt

    fileguard = FileGuard(tmp_path, {"writable_paths": ["src/**"]})

    def mock_agentic(**kwargs):
        executor = kwargs["tool_executor"]
        result = executor("file_write", {"path": "src/file.py", "content": "code"})
        return {"content": "done", "operations": [
            {"name": "file_write", "input": {"path": "src/file.py", "content": "code"}, "result": result},
        ]}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agentic):
        run_conversation(iter_dir, agents, iteration, _default_model_config(),
                        fileguard=fileguard, worktree_map=worktree_map)

    # All three worktrees should have the file
    for a in agents:
        assert (worktree_map[a["name"]] / "src" / "file.py").exists()
    # Project root should NOT
    assert not (tmp_path / "src" / "file.py").exists()


def test_run_conversation_worktree_map_prints_status(tmp_path, capsys):
    """Worktree count should be printed at conversation start."""
    iter_dir = _make_iter_dir(tmp_path)
    agents = _default_agents()
    iteration = {"id": "iter-1", "description": "Test", "status": "in-progress", "max_turns": 1}

    from gotg.fileguard import FileGuard
    fileguard = FileGuard(tmp_path, {"writable_paths": ["src/**"]})
    worktree_map = {"agent-1": tmp_path / "wt1", "agent-2": tmp_path / "wt2"}

    mock_result = {"content": "done", "operations": []}
    with patch("gotg.cli.agentic_completion", return_value=mock_result):
        run_conversation(iter_dir, agents, iteration, _default_model_config(),
                        fileguard=fileguard, worktree_map=worktree_map)

    output = capsys.readouterr().out
    assert "Worktrees: 2 active" in output


def test_setup_worktrees_disabled(tmp_path, monkeypatch):
    """cmd_run without worktrees enabled should pass worktree_map=None."""
    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "file_access": {"writable_paths": ["src/**"]},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "max_turns": 2, "phase": "refinement"},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    monkeypatch.chdir(tmp_path)

    with patch("gotg.cli.run_conversation") as mock_run:
        with patch("gotg.cli._auto_checkpoint"):
            with patch("sys.argv", ["gotg", "run"]):
                main()

    call_kwargs = mock_run.call_args[1]
    assert call_kwargs.get("worktree_map") is None


def test_setup_worktrees_warns_without_file_access(tmp_path):
    """Worktrees enabled without file_access should return a warning."""
    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}],
        "worktrees": {"enabled": True},
    }
    (team / "team.json").write_text(json.dumps(team_config))

    iteration = {"phase": "implementation"}
    result, warnings = setup_worktrees(team, [], None, None, iteration)
    assert result is None
    assert any("worktrees require file tools" in w for w in warnings)


def test_cmd_worktrees_no_worktrees(tmp_path, monkeypatch, capsys):
    """gotg worktrees with no active worktrees prints a message."""
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text("{}")
    (team / "iteration.json").write_text(json.dumps({
        "iterations": [{"id": "iter-1", "title": "", "description": "T", "status": "in-progress", "max_turns": 10}],
        "current": "iter-1",
    }))
    (team / "iterations" / "iter-1").mkdir(parents=True)

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "worktrees"]):
        main()

    output = capsys.readouterr().out
    assert "No active worktrees" in output


def test_cmd_commit_worktrees_commits_dirty(tmp_path, monkeypatch, capsys):
    """gotg commit-worktrees should commit dirty worktrees."""
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    from gotg.worktree import create_worktree
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "new.txt").write_text("new content")

    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text("{}")
    (team / "iteration.json").write_text(json.dumps({
        "iterations": [{"id": "iter-1", "title": "", "description": "T", "status": "in-progress", "max_turns": 10}],
        "current": "iter-1",
    }))
    (team / "iterations" / "iter-1").mkdir(parents=True)

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "commit-worktrees"]):
        main()

    output = capsys.readouterr().out
    assert "committed" in output
    assert "agent-1/layer-0" in output


# --- review and merge commands ---

def _make_git_project_with_team(tmp_path):
    """Helper: git repo with initial commit + .team directory (gitignored like gotg init)."""
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / ".gitignore").write_text("/.team/\n/.worktrees/\n.env\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    team = tmp_path / ".team"
    team.mkdir()
    (team / "team.json").write_text("{}")
    (team / "iteration.json").write_text(json.dumps({
        "iterations": [{"id": "iter-1", "title": "", "description": "T", "status": "in-progress", "max_turns": 10}],
        "current": "iter-1",
    }))
    (team / "iterations" / "iter-1").mkdir(parents=True)
    return tmp_path


def test_cmd_review_shows_diffs(tmp_path, monkeypatch, capsys):
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature code")
    commit_worktree(wt, "add feature")

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "review"]):
        main()

    output = capsys.readouterr().out
    assert "agent-1/layer-0" in output
    assert "feature.py" in output
    assert "feature code" in output


def test_cmd_review_stat_only(tmp_path, monkeypatch, capsys):
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature code")
    commit_worktree(wt, "add feature")

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "review", "--stat-only"]):
        main()

    output = capsys.readouterr().out
    assert "feature.py" in output
    # Full diff content should NOT appear in stat-only mode
    assert "feature code" not in output


def test_cmd_review_specific_branch(tmp_path, monkeypatch, capsys):
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree
    wt1 = create_worktree(tmp_path, "agent-1", 0)
    wt2 = create_worktree(tmp_path, "agent-2", 0)
    (wt1 / "src" / "a.py").write_text("a")
    (wt2 / "src" / "b.py").write_text("b")
    commit_worktree(wt1, "add a")
    commit_worktree(wt2, "add b")

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "review", "agent-1/layer-0"]):
        main()

    output = capsys.readouterr().out
    assert "agent-1/layer-0" in output
    assert "a.py" in output
    assert "agent-2/layer-0" not in output


def test_cmd_review_summary_line(tmp_path, monkeypatch, capsys):
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "review"]):
        main()

    output = capsys.readouterr().out
    assert "Layer 0:" in output
    assert "branch(es)" in output


def test_cmd_merge_single_branch(tmp_path, monkeypatch, capsys):
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature code")
    commit_worktree(wt, "add feature")

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "merge", "agent-1/layer-0"]):
        main()

    output = capsys.readouterr().out
    assert "Merged agent-1/layer-0 into main" in output
    assert (tmp_path / "src" / "feature.py").read_text() == "feature code"


def test_cmd_merge_all(tmp_path, monkeypatch, capsys):
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree
    wt1 = create_worktree(tmp_path, "agent-1", 0)
    wt2 = create_worktree(tmp_path, "agent-2", 0)
    (wt1 / "src" / "a.py").write_text("a")
    (wt2 / "src" / "b.py").write_text("b")
    commit_worktree(wt1, "add a")
    commit_worktree(wt2, "add b")

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "merge", "all"]):
        main()

    output = capsys.readouterr().out
    assert "2 branch(es) merged into main" in output
    assert (tmp_path / "src" / "a.py").exists()
    assert (tmp_path / "src" / "b.py").exists()


def test_cmd_merge_all_stops_on_conflict(tmp_path, monkeypatch, capsys):
    import subprocess
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree

    wt1 = create_worktree(tmp_path, "agent-1", 0)
    wt2 = create_worktree(tmp_path, "agent-2", 0)
    (wt1 / "src" / "main.py").write_text("agent-1 version")
    (wt2 / "src" / "main.py").write_text("agent-2 version")
    commit_worktree(wt1, "agent-1 change")
    commit_worktree(wt2, "agent-2 change")

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "merge", "all"]):
        main()

    output = capsys.readouterr().out
    # First should merge, second should conflict
    assert "CONFLICT" in output
    # Clean up
    subprocess.run(["git", "merge", "--abort"], cwd=tmp_path, capture_output=True)


def test_cmd_merge_already_merged(tmp_path, monkeypatch, capsys):
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree, merge_branch
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")
    merge_branch(tmp_path, "agent-1/layer-0")

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "merge", "agent-1/layer-0"]):
        main()

    output = capsys.readouterr().out
    assert "already merged" in output


def test_cmd_merge_abort(tmp_path, monkeypatch, capsys):
    import subprocess
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree, merge_branch

    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "main.py").write_text("agent version")
    commit_worktree(wt, "agent change")
    (tmp_path / "src" / "main.py").write_text("main version")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "main change"], cwd=tmp_path, capture_output=True, check=True)
    merge_branch(tmp_path, "agent-1/layer-0")  # creates conflict

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "merge", "--abort"]):
        main()

    output = capsys.readouterr().out
    assert "Merge aborted" in output


def test_cmd_merge_dirty_worktree_blocks(tmp_path, monkeypatch, capsys):
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")
    # Make worktree dirty
    (wt / "src" / "dirty.py").write_text("uncommitted")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        with patch("sys.argv", ["gotg", "merge", "agent-1/layer-0"]):
            main()

    output = capsys.readouterr().err
    assert "uncommitted changes" in output
    assert "commit-worktrees" in output


# --- Integration tests ---

def test_full_layer_create_review_merge(tmp_path, monkeypatch, capsys):
    """Full flow: create worktrees, commit, review, merge all, verify main."""
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree

    wt1 = create_worktree(tmp_path, "agent-1", 0)
    wt2 = create_worktree(tmp_path, "agent-2", 0)
    (wt1 / "src" / "routes.py").write_text("routes code")
    (wt2 / "src" / "models.py").write_text("models code")
    commit_worktree(wt1, "add routes")
    commit_worktree(wt2, "add models")

    monkeypatch.chdir(tmp_path)

    # Review
    with patch("sys.argv", ["gotg", "review"]):
        main()
    review_output = capsys.readouterr().out
    assert "routes.py" in review_output
    assert "models.py" in review_output

    # Merge all
    with patch("sys.argv", ["gotg", "merge", "all"]):
        main()
    merge_output = capsys.readouterr().out
    assert "2 branch(es) merged into main" in merge_output

    # Verify main has both files
    assert (tmp_path / "src" / "routes.py").read_text() == "routes code"
    assert (tmp_path / "src" / "models.py").read_text() == "models code"


def test_layer_progression(tmp_path, monkeypatch, capsys):
    """Merge layer 0, create layer 1, verify layer 1 sees layer 0 work."""
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree, merge_branch

    # Layer 0
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "base.py").write_text("base module")
    commit_worktree(wt, "add base")
    merge_branch(tmp_path, "agent-1/layer-0")

    # Layer 1 — should see layer 0 work since it branches from main (which now has layer 0)
    wt1 = create_worktree(tmp_path, "agent-1", 1)
    assert (wt1 / "src" / "base.py").read_text() == "base module"


def test_cmd_review_specific_branch_no_layer_label(tmp_path, monkeypatch, capsys):
    """When reviewing a specific branch, summary omits 'Layer N:' prefix."""
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")

    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["gotg", "review", "agent-1/layer-0"]):
        main()

    output = capsys.readouterr().out
    assert "Layer 0:" not in output
    assert "1 branch(es)" in output


def test_cmd_merge_dirty_main_blocks(tmp_path, monkeypatch, capsys):
    """Dirty main checkout blocks merge."""
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")

    # Dirty main
    (tmp_path / "src" / "dirty.py").write_text("uncommitted on main")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        with patch("sys.argv", ["gotg", "merge", "agent-1/layer-0"]):
            main()

    output = capsys.readouterr().err
    assert "uncommitted changes on main" in output


def test_cmd_merge_all_handles_worktree_error(tmp_path, monkeypatch, capsys):
    """merge all catches WorktreeError from merge_branch and reports cleanly."""
    import subprocess
    _make_git_project_with_team(tmp_path)
    from gotg.worktree import create_worktree, commit_worktree
    wt = create_worktree(tmp_path, "agent-1", 0)
    (wt / "src" / "feature.py").write_text("feature")
    commit_worktree(wt, "add feature")

    # Move main off the main branch to trigger "not on main" error
    subprocess.run(["git", "checkout", "-b", "other"], cwd=tmp_path, capture_output=True, check=True)

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        with patch("sys.argv", ["gotg", "merge", "all"]):
            main()

    output = capsys.readouterr().err
    assert "expected 'main'" in output
    # Clean up
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, capture_output=True)


# --- code-review phase ---

def test_advance_pre_code_review_to_implementation(tmp_path):
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="pre-code-review")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "implementation"


def test_advance_past_code_review_errors(tmp_path):
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="code-review")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()


def test_run_conversation_passes_diffs_summary(tmp_path):
    """run_conversation with diffs_summary injects IMPLEMENTATION DIFFS into prompts."""
    iter_dir = _make_iter_dir(tmp_path)

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "code-review", "max_turns": 1,
    }

    diffs = "=== agent-1/layer-0 ===\n src/main.py | 5 +++++"

    captured_prompts = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        captured_prompts.append(messages)
        return {"content": "response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), diffs_summary=diffs)

    system_msg = captured_prompts[0][0]["content"]
    assert "IMPLEMENTATION DIFFS" in system_msg
    assert "agent-1/layer-0" in system_msg


def test_run_conversation_no_diffs_no_injection(tmp_path):
    """run_conversation without diffs_summary has no IMPLEMENTATION DIFFS."""
    iter_dir = _make_iter_dir(tmp_path)

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "code-review", "max_turns": 1,
    }

    captured_prompts = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        captured_prompts.append(messages)
        return {"content": "response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), diffs_summary=None)

    system_msg = captured_prompts[0][0]["content"]
    assert "IMPLEMENTATION DIFFS" not in system_msg


def test_run_conversation_diffs_passed_to_coach(tmp_path):
    """Coach prompt should also receive diffs_summary."""
    iter_dir = _make_iter_dir(tmp_path)

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "code-review", "max_turns": 2,
    }

    diffs = "=== agent-1/layer-0 ===\n src/main.py | 5 +++++"

    captured_prompts = []
    def mock_agent(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        captured_prompts.append(messages)
        return {"content": "response", "operations": []}
    def mock_coach(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        captured_prompts.append(messages)
        return {"content": "response", "tool_calls": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent), \
         patch("gotg.cli.chat_completion", side_effect=mock_coach):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach(),
                         diffs_summary=diffs)

    # 3rd call is the coach (after agent-1, agent-2)
    coach_system_msg = captured_prompts[2][0]["content"]
    assert "IMPLEMENTATION DIFFS" in coach_system_msg
    assert "agent-1/layer-0" in coach_system_msg


def test_coach_completion_code_review_message(tmp_path, capsys):
    """Coach signals completion in code-review shows merge/next-layer message."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "code-review", "max_turns": 2,
    }

    def mock_coach(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        return {
            "content": "All concerns resolved.",
            "tool_calls": [{"name": "signal_phase_complete", "input": {"summary": "Done"}}],
        }

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=mock_coach):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    output = capsys.readouterr().out
    assert "code review complete" in output
    assert "gotg merge" in output
    assert "gotg next-layer" in output
    assert "gotg advance" not in output


def test_coach_completion_non_last_phase_message(tmp_path, capsys):
    """Coach signals completion in refinement shows 'gotg advance' message."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "refinement", "max_turns": 2,
    }

    def mock_coach(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        return {
            "content": "All done.",
            "tool_calls": [{"name": "signal_phase_complete", "input": {"summary": "Done"}}],
        }

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=mock_coach):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    output = capsys.readouterr().out
    assert "gotg advance" in output
    assert "final phase" not in output


# --- resolve_layer ---

def test_resolve_layer_cli_override():
    """Explicit override takes precedence over iteration state."""
    iteration = {"current_layer": 1}
    assert resolve_layer(3, iteration) == 3


def test_resolve_layer_from_iteration_state():
    """Falls back to iteration.current_layer when no override."""
    iteration = {"current_layer": 2}
    assert resolve_layer(None, iteration) == 2


def test_resolve_layer_defaults_to_zero():
    """Defaults to 0 when neither override nor iteration state has a layer."""
    iteration = {}
    assert resolve_layer(None, iteration) == 0


# --- phase-gated worktree setup ---

def test_setup_worktrees_skips_refinement_phase(tmp_path):
    """setup_worktrees returns None for refinement phase even with worktrees enabled."""
    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [{"name": "agent-1", "role": "SE"}],
        "worktrees": {"enabled": True},
        "file_access": {"writable_paths": ["src/**"]},
    }
    (team / "team.json").write_text(json.dumps(team_config))

    from gotg.fileguard import FileGuard
    fg = FileGuard(tmp_path, {"writable_paths": ["src/**"]})
    iteration = {"phase": "refinement"}
    result, warnings = setup_worktrees(team, [{"name": "agent-1", "role": "SE"}], fg, None, iteration)
    assert result is None


def test_setup_worktrees_active_in_implementation_phase(tmp_path):
    """setup_worktrees creates worktrees in implementation phase."""
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [{"name": "agent-1", "role": "SE"}],
        "worktrees": {"enabled": True},
        "file_access": {"writable_paths": ["src/**"]},
    }
    (team / "team.json").write_text(json.dumps(team_config))

    from gotg.fileguard import FileGuard
    fg = FileGuard(tmp_path, {"writable_paths": ["src/**"]})
    iteration = {"phase": "implementation"}
    result, warnings = setup_worktrees(team, [{"name": "agent-1", "role": "SE"}], fg, None, iteration)
    assert result is not None
    assert "agent-1" in result


# --- advance: implementation phase ---

def test_advance_implementation_to_code_review(tmp_path):
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="implementation")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "code-review"


def test_advance_sets_current_layer_zero(tmp_path):
    """Advancing pre-code-review → implementation sets current_layer=0."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="pre-code-review")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "implementation"
    assert data["iterations"][0]["current_layer"] == 0


def test_advance_implementation_auto_commits_worktrees(tmp_path, capsys):
    """Advancing implementation → code-review auto-commits dirty worktrees for current layer."""
    import subprocess

    # Set up git repo with a worktree
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}],
        "worktrees": {"enabled": True},
        "file_access": {"writable_paths": ["src/**"]},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": "implementation", "max_turns": 10, "current_layer": 0},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    # Create a worktree and make it dirty
    from gotg.worktree import create_worktree
    wt_path = create_worktree(tmp_path, "agent-1", 0)
    (wt_path / "new.txt").write_text("code")
    subprocess.run(["git", "add", "-A"], cwd=wt_path, capture_output=True, check=True)

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    output = capsys.readouterr().out
    assert "Auto-committed" in output

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "code-review"


def test_advance_auto_commit_only_current_layer(tmp_path, capsys):
    """Auto-commit on advance only affects worktrees matching current layer."""
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}],
        "worktrees": {"enabled": True},
        "file_access": {"writable_paths": ["src/**"]},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": "implementation", "max_turns": 10, "current_layer": 1},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    # Create worktrees for layer 0 and layer 1, both dirty
    from gotg.worktree import create_worktree, is_worktree_dirty
    wt0 = create_worktree(tmp_path, "agent-1", 0)
    (wt0 / "old.txt").write_text("old code")
    subprocess.run(["git", "add", "-A"], cwd=wt0, capture_output=True, check=True)

    wt1 = create_worktree(tmp_path, "agent-1", 1)
    (wt1 / "new.txt").write_text("new code")
    subprocess.run(["git", "add", "-A"], cwd=wt1, capture_output=True, check=True)

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    output = capsys.readouterr().out
    # Layer 1 worktree should be auto-committed
    assert "agent-1/layer-1" in output
    # Layer 0 worktree should NOT be auto-committed (still dirty)
    assert is_worktree_dirty(wt0)


def test_advance_past_code_review_hints_next_layer(tmp_path, capsys):
    """Advancing past code-review includes hint about next-layer."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="code-review")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()

    err = capsys.readouterr().err
    assert "next-layer" in err


# --- coach completion messages ---

def test_coach_completion_implementation_suggests_advance(tmp_path, capsys):
    """Coach signals completion in implementation shows 'gotg advance' message."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "implementation", "max_turns": 2,
    }

    def mock_coach(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        return {
            "content": "All tasks done.",
            "tool_calls": [{"name": "signal_phase_complete", "input": {"summary": "Done"}}],
        }

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=mock_coach):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    output = capsys.readouterr().out
    assert "gotg advance" in output
    assert "gotg next-layer" not in output


# --- cmd_next_layer ---

def _make_next_layer_team_dir(tmp_path, current_layer=0, phase="code-review", tasks=None):
    """Helper to create a .team/ dir for next-layer tests."""
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": phase, "max_turns": 10,
         "current_layer": current_layer},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    if tasks is None:
        tasks = [
            {"id": "T1", "description": "Task 1", "layer": 0, "status": "done", "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
            {"id": "T2", "description": "Task 2", "layer": 1, "status": "todo", "assigned_to": "agent-1", "depends_on": ["T1"], "done_criteria": "done"},
        ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    return team, iter_dir


def test_next_layer_requires_code_review_phase(tmp_path, capsys):
    """next-layer errors if not in code-review phase."""
    team, iter_dir = _make_next_layer_team_dir(tmp_path, phase="implementation")
    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()

    err = capsys.readouterr().err
    assert "code-review" in err


def test_next_layer_advances_to_layer_1(tmp_path, capsys):
    """next-layer increments layer and sets phase to implementation."""
    team, iter_dir = _make_next_layer_team_dir(tmp_path, current_layer=0)
    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["current_layer"] == 1
    assert data["iterations"][0]["phase"] == "implementation"

    output = capsys.readouterr().out
    assert "layer 1" in output.lower()


def test_next_layer_all_layers_complete_with_hint(tmp_path, capsys):
    """next-layer with no more layers prints completion message with hint."""
    tasks = [
        {"id": "T1", "description": "Task 1", "layer": 0, "status": "done", "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
    ]
    team, iter_dir = _make_next_layer_team_dir(tmp_path, current_layer=0, tasks=tasks)
    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    output = capsys.readouterr().out
    assert "All layers complete" in output
    assert "done" in output.lower()

    # Phase should NOT have changed
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "code-review"


def test_next_layer_logs_transition_message(tmp_path):
    """next-layer writes a system message to conversation.jsonl."""
    team, iter_dir = _make_next_layer_team_dir(tmp_path, current_layer=0)
    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    messages = read_log(iter_dir / "conversation.jsonl")
    assert len(messages) >= 1
    system_msgs = [m for m in messages if m["from"] == "system"]
    assert any("layer 0" in m["content"].lower() and "layer 1" in m["content"].lower() for m in system_msgs)


def test_next_layer_auto_checkpoints(tmp_path):
    """next-layer creates an auto checkpoint."""
    team, iter_dir = _make_next_layer_team_dir(tmp_path, current_layer=0)
    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    # Check that a checkpoint was created
    cp_dir = iter_dir / "checkpoints"
    assert cp_dir.exists()
    assert len(list(cp_dir.iterdir())) >= 1


def test_next_layer_verifies_head_on_main(tmp_path, capsys):
    """next-layer errors if HEAD is not on main."""
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "-b", "other"], cwd=tmp_path, capture_output=True, check=True)

    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}],
        "worktrees": {"enabled": True},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": "code-review", "max_turns": 10,
         "current_layer": 0},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done", "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
             {"id": "T2", "description": "y", "layer": 1, "status": "todo", "assigned_to": "agent-1", "depends_on": ["T1"], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()

    err = capsys.readouterr().err
    assert "main" in err

    # Clean up
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, capture_output=True)


def test_next_layer_blocks_on_unmerged_branches(tmp_path, capsys):
    """next-layer errors if branches for current layer are not merged."""
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    # Create an unmerged branch for layer 0
    subprocess.run(["git", "checkout", "-b", "agent-1/layer-0"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "new.txt").write_text("y")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "work"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, capture_output=True, check=True)

    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}],
        "worktrees": {"enabled": True},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": "code-review", "max_turns": 10,
         "current_layer": 0},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done", "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
             {"id": "T2", "description": "y", "layer": 1, "status": "todo", "assigned_to": "agent-1", "depends_on": ["T1"], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()

    err = capsys.readouterr().err
    assert "unmerged" in err.lower()
    assert "agent-1/layer-0" in err


def test_next_layer_cleans_up_worktrees(tmp_path, capsys):
    """next-layer removes worktrees for the completed layer."""
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    # Create and merge a worktree for layer 0
    from gotg.worktree import create_worktree, commit_worktree, merge_branch
    wt_path = create_worktree(tmp_path, "agent-1", 0)
    (wt_path / "code.txt").write_text("code")
    commit_worktree(wt_path, "work")
    merge_branch(tmp_path, "agent-1/layer-0")

    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}],
        "worktrees": {"enabled": True},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": "code-review", "max_turns": 10,
         "current_layer": 0},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done", "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
             {"id": "T2", "description": "y", "layer": 1, "status": "todo", "assigned_to": "agent-1", "depends_on": ["T1"], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    assert wt_path.exists()

    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    output = capsys.readouterr().out
    assert "Removed worktree" in output


# --- review/merge layer resolution ---

def test_review_defaults_to_current_layer(tmp_path, capsys):
    """gotg review defaults to current_layer from iteration state."""
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    # Create a branch for layer 2
    subprocess.run(["git", "checkout", "-b", "agent-1/layer-2"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "new.txt").write_text("code")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "work"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, capture_output=True, check=True)

    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": "code-review", "max_turns": 10,
         "current_layer": 2},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    with patch("sys.argv", ["gotg", "review"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    output = capsys.readouterr().out
    assert "Layer 2" in output
    assert "agent-1/layer-2" in output


# --- Codex review fixes ---

def test_advance_planning_catches_bad_task_structure(tmp_path, capsys):
    """compute_layers errors (ValueError/KeyError) are caught like JSONDecodeError."""
    team = tmp_path / ".team"
    team.mkdir()
    # Need a coach in team.json so the planning→pre-code-review coach runs
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}],
        "coach": {"name": "coach", "role": "Agile Coach"},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": "planning", "max_turns": 10},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    # Coach returns valid JSON but with bad dependency references
    bad_tasks = json.dumps([
        {"id": "T1", "description": "x", "depends_on": ["NONEXISTENT"], "assigned_to": "", "status": "todo", "done_criteria": "done"},
    ])

    def mock_completion(base_url, model, messages, api_key=None, provider="ollama"):
        return bad_tasks

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", side_effect=mock_completion):
                main()

    err = capsys.readouterr().err
    assert "bad task structure" in err.lower()
    assert (iter_dir / "tasks_raw.txt").exists()

    # Phase should still advance (advance isn't blocked by bad structure)
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "pre-code-review"


def test_next_layer_recomputes_missing_layers(tmp_path, capsys):
    """next-layer recomputes layers when stored layer field is missing."""
    # Tasks without stored layer field (simulating pre-iter-14 tasks.json)
    tasks = [
        {"id": "T1", "description": "x", "depends_on": [], "assigned_to": "agent-1", "status": "done", "done_criteria": "done"},
        {"id": "T2", "description": "y", "depends_on": ["T1"], "assigned_to": "agent-1", "status": "todo", "done_criteria": "done"},
    ]
    team, iter_dir = _make_next_layer_team_dir(tmp_path, current_layer=0, tasks=tasks)
    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    # Should recompute: T1=layer0, T2=layer1 → next layer (1) has tasks
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["current_layer"] == 1
    assert data["iterations"][0]["phase"] == "implementation"


def test_validate_task_assignments_message_mentions_phase(tmp_path):
    """Error message mentions the actual phase, not always pre-code-review."""
    iter_dir = tmp_path / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    tasks = [
        {"id": "T1", "description": "x", "depends_on": [], "assigned_to": "", "status": "todo", "done_criteria": "done", "layer": 0},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    iteration = {"id": "i", "description": "t", "status": "in-progress", "phase": "implementation", "current_layer": 0}

    with pytest.raises(SessionSetupError, match="implementation"):
        validate_iteration_for_run(iteration, iter_dir, _DUMMY_AGENTS)


def test_validate_task_assignments_scopes_to_current_layer(tmp_path):
    """In implementation, only current-layer tasks are checked for assignment."""
    iter_dir = tmp_path / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    tasks = [
        {"id": "T1", "description": "x", "depends_on": [], "assigned_to": "agent-1", "status": "done", "done_criteria": "done", "layer": 0},
        {"id": "T2", "description": "y", "depends_on": ["T1"], "assigned_to": "", "status": "todo", "done_criteria": "done", "layer": 1},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    # Layer 0 — T1 is assigned, T2 is layer 1 so not checked
    iteration_l0 = {"id": "i", "description": "t", "status": "in-progress", "phase": "implementation", "current_layer": 0}
    validate_iteration_for_run(iteration_l0, iter_dir, _DUMMY_AGENTS)
    # Should not raise — layer 0 tasks are all assigned

    # Layer 1 — T2 is unassigned
    iteration_l1 = {"id": "i", "description": "t", "status": "in-progress", "phase": "implementation", "current_layer": 1}
    with pytest.raises(SessionSetupError, match="layer 1") as exc_info:
        validate_iteration_for_run(iteration_l1, iter_dir, _DUMMY_AGENTS)
    assert "T2" in str(exc_info.value)


def test_run_header_shows_layer(tmp_path, capsys):
    """run_conversation header shows current layer when set."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "implementation", "max_turns": 0,
        "current_layer": 2,
    }

    with patch("gotg.cli.agentic_completion", return_value={"content": "x", "operations": []}):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    output = capsys.readouterr().out
    assert "layer 2" in output.lower()


def test_run_header_no_layer_without_current_layer(tmp_path, capsys):
    """run_conversation header doesn't show layer info when not set."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "refinement", "max_turns": 0,
    }

    with patch("gotg.cli.agentic_completion", return_value={"content": "x", "operations": []}):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    output = capsys.readouterr().out
    assert "layer" not in output.lower()


def test_next_layer_blocks_on_dirty_worktrees(tmp_path, capsys):
    """next-layer errors if current-layer worktrees have uncommitted changes."""
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    # Create worktree, commit some work, then merge into main
    from gotg.worktree import create_worktree, commit_worktree, merge_branch
    wt_path = create_worktree(tmp_path, "agent-1", 0)
    (wt_path / "code.txt").write_text("done")
    commit_worktree(wt_path, "work")
    merge_branch(tmp_path, "agent-1/layer-0")

    # Now make worktree dirty again (uncommitted changes)
    (wt_path / "extra.txt").write_text("oops")

    team = tmp_path / ".team"
    team.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [{"name": "agent-1", "role": "SE"}, {"name": "agent-2", "role": "SE"}],
        "worktrees": {"enabled": True},
    }
    (team / "team.json").write_text(json.dumps(team_config))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": "code-review", "max_turns": 10,
         "current_layer": 0},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    tasks = [{"id": "T1", "description": "x", "layer": 0, "status": "done", "assigned_to": "agent-1", "depends_on": [], "done_criteria": "done"},
             {"id": "T2", "description": "y", "layer": 1, "status": "todo", "assigned_to": "agent-1", "depends_on": ["T1"], "done_criteria": "done"}]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with pytest.raises(SystemExit):
                main()

    err = capsys.readouterr().err
    assert "dirty" in err.lower()
    assert "agent-1/layer-0" in err


# --- kickoff injection ---

def test_kickoff_injected_on_empty_conversation(tmp_path):
    """First run should inject a phase kickoff system message."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "Build X",
        "status": "in-progress", "phase": "refinement", "max_turns": 2,
    }

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(iter_dir / "conversation.jsonl")
    # First message should be the system kickoff
    assert messages[0]["from"] == "system"
    assert "--- Phase: refinement ---" in messages[0]["content"]
    assert "coach will facilitate" in messages[0]["content"].lower()


def test_kickoff_injected_after_phase_advance(tmp_path):
    """After a phase advance system message, kickoff should be injected on resume."""
    iter_dir = _make_iter_dir(tmp_path)
    log_path = iter_dir / "conversation.jsonl"
    # Pre-populate with messages ending in a phase advance
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "idea"})
    append_message(log_path, {"from": "system", "iteration": "iter-1",
                              "content": "--- Phase advanced: refinement → planning ---"})

    iteration = {
        "id": "iter-1", "description": "Build X",
        "status": "in-progress", "phase": "planning", "max_turns": 4,
    }

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(log_path)
    # Find the kickoff message after the advance
    kickoff_msgs = [m for m in messages if m.get("from") == "system"
                    and m.get("content", "").startswith("--- Phase: planning")]
    assert len(kickoff_msgs) == 1
    assert "coach will facilitate" in kickoff_msgs[0]["content"].lower()


def test_no_kickoff_on_mid_phase_resume(tmp_path):
    """Mid-phase resume (no transition) should not inject kickoff."""
    iter_dir = _make_iter_dir(tmp_path)
    log_path = iter_dir / "conversation.jsonl"
    # Pre-populate with normal conversation (no phase transition)
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "idea"})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "agreed"})

    iteration = {
        "id": "iter-1", "description": "Build X",
        "status": "in-progress", "phase": "refinement", "max_turns": 4,
    }

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(log_path)
    kickoff_msgs = [m for m in messages if m.get("from") == "system"
                    and m.get("content", "").startswith("--- Phase:")]
    assert len(kickoff_msgs) == 0


# --- empty coach message fallback ---

def test_empty_coach_message_gets_fallback(tmp_path):
    """Empty coach text with signal_phase_complete should get fallback text."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "refinement", "max_turns": 2,
    }

    coach_call_count = 0
    def mock_coach(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        nonlocal coach_call_count
        coach_call_count += 1
        if coach_call_count == 1:
            return {
                "content": "",
                "tool_calls": [{"name": "signal_phase_complete", "input": {"summary": "Done."}}],
            }
        return {"content": "response", "tool_calls": []}

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=mock_coach):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(iter_dir / "conversation.jsonl")
    coach_msgs = [m for m in messages if m["from"] == "coach"]
    assert len(coach_msgs) == 1
    assert coach_msgs[0]["content"] == "(Phase complete signal sent.)"


# --- Iteration 16: History boundary and phase-scoped history ---

def test_advance_writes_history_boundary(tmp_path):
    """cmd_advance writes a boundary marker before the transition message."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="refinement")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    messages = read_log(iter_dir / "conversation.jsonl")
    # First message should be boundary, second should be transition
    assert len(messages) == 2
    assert messages[0]["content"] == "--- HISTORY BOUNDARY ---"
    assert messages[1]["content"].startswith("--- Phase advanced:")


def test_advance_boundary_has_metadata(tmp_path):
    """Boundary marker includes from_phase and to_phase metadata."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="planning")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    messages = read_log(iter_dir / "conversation.jsonl")
    boundary = messages[0]
    assert boundary.get("phase_boundary") is True
    assert boundary.get("from_phase") == "planning"
    assert boundary.get("to_phase") == "pre-code-review"


def test_advance_prints_turns_reset(tmp_path, capsys):
    """cmd_advance prints 'Turns reset for new phase.' after advancing."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="refinement")
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    captured = capsys.readouterr()
    assert "Turns reset for new phase." in captured.out


def test_next_layer_writes_history_boundary(tmp_path):
    """cmd_next_layer writes a boundary marker with layer metadata."""
    team, iter_dir = _make_next_layer_team_dir(tmp_path, current_layer=0)
    with patch("sys.argv", ["gotg", "next-layer"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    messages = read_log(iter_dir / "conversation.jsonl")
    boundary = [m for m in messages if m.get("phase_boundary")]
    assert len(boundary) == 1
    assert boundary[0].get("layer") == 1
    assert boundary[0].get("from_phase") == "code-review"
    assert boundary[0].get("to_phase") == "implementation"


def test_task_notes_extracted_on_pre_code_review_advance(tmp_path):
    """Advancing from pre-code-review extracts task notes via LLM call."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="pre-code-review")
    _add_coach_to_team_json(team)
    # Write tasks.json and some conversation history
    tasks = [
        {"id": "t1", "description": "Do thing", "done_criteria": "Done",
         "depends_on": [], "assigned_to": "agent-1", "status": "pending", "layer": 0},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    append_message(iter_dir / "conversation.jsonl",
                   {"from": "agent-1", "content": "I'll create src/main.py with def run()."})

    notes_response = json.dumps([{"id": "t1", "notes": "File: src/main.py. def run() -> None."}])

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value=notes_response):
                main()

    updated_tasks = json.loads((iter_dir / "tasks.json").read_text())
    assert updated_tasks[0].get("notes") == "File: src/main.py. def run() -> None."


def test_task_notes_extraction_handles_bad_json(tmp_path, capsys):
    """Bad JSON from notes extraction saves raw output and doesn't block advance."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="pre-code-review")
    _add_coach_to_team_json(team)
    tasks = [
        {"id": "t1", "description": "Do thing", "done_criteria": "Done",
         "depends_on": [], "assigned_to": "agent-1", "status": "pending", "layer": 0},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))
    append_message(iter_dir / "conversation.jsonl",
                   {"from": "agent-1", "content": "proposal"})

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", return_value="not valid json {{{"):
                main()

    # Advance should still succeed
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "implementation"
    # tasks.json should be unchanged (no notes field)
    updated_tasks = json.loads((iter_dir / "tasks.json").read_text())
    assert "notes" not in updated_tasks[0]
    # Raw output saved
    assert (iter_dir / "notes_raw.txt").exists()


def test_task_notes_extraction_skips_without_coach(tmp_path):
    """Without a coach, notes extraction is skipped."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="pre-code-review")
    # No coach in team.json (default helper doesn't add one)

    tasks = [
        {"id": "t1", "description": "Do thing", "done_criteria": "Done",
         "depends_on": [], "assigned_to": "agent-1", "status": "pending", "layer": 0},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    # Should advance without calling chat_completion
    data = json.loads((team / "iteration.json").read_text())
    assert data["iterations"][0]["phase"] == "implementation"
    # No notes added
    updated_tasks = json.loads((iter_dir / "tasks.json").read_text())
    assert "notes" not in updated_tasks[0]


def test_run_conversation_uses_phase_history(tmp_path):
    """run_conversation only sees messages after the last boundary."""
    iter_dir = _make_iter_dir(tmp_path)
    log_path = iter_dir / "conversation.jsonl"

    # Write pre-boundary messages (simulating prior phase)
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "old phase msg"})
    append_message(log_path, {
        "from": "system", "iteration": "iter-1",
        "content": "--- HISTORY BOUNDARY ---", "phase_boundary": True,
    })
    append_message(log_path, {
        "from": "system", "iteration": "iter-1",
        "content": "--- Phase advanced: refinement → planning ---",
    })

    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "planning", "max_turns": 1,
    }

    captured_prompts = []
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        captured_prompts.append(messages)
        return {"content": "response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config())

    # The old phase message should NOT appear in the prompt
    system_content = captured_prompts[0][0]["content"]
    assert "old phase msg" not in system_content


def test_continue_uses_phase_history(tmp_path):
    """cmd_continue counts turns from phase-scoped history only."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="planning")
    log_path = iter_dir / "conversation.jsonl"

    # Write messages from prior phase + boundary + new phase messages
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "grooming msg 1"})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "grooming msg 2"})
    append_message(log_path, {
        "from": "system", "iteration": "iter-1",
        "content": "--- HISTORY BOUNDARY ---", "phase_boundary": True,
    })
    append_message(log_path, {
        "from": "system", "iteration": "iter-1",
        "content": "--- Phase advanced: refinement → planning ---",
    })

    # Phase-scoped history has 0 agent turns, so max_turns=1 should allow 1 turn
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        return {"content": "response", "operations": []}

    with patch("sys.argv", ["gotg", "continue", "--max-turns", "1"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
                main()

    # Should have added at least 1 agent message in the new phase
    all_msgs = read_log(log_path)
    phase_msgs = read_phase_history(log_path)
    agent_msgs = [m for m in phase_msgs if m["from"] not in ("system", "human")]
    assert len(agent_msgs) >= 1


def test_advance_then_continue_with_message_ordering(tmp_path):
    """After advance, continue -m injects human msg; kickoff + human both in new phase."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="refinement")

    # Advance refinement → planning
    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            main()

    # Continue with a human message
    def mock_completion(base_url, model, messages, api_key=None, provider="ollama", **kwargs):
        return {"content": "response", "operations": []}

    with patch("sys.argv", ["gotg", "continue", "-m", "focus on task splitting", "--max-turns", "1"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.agentic_completion", side_effect=mock_completion):
                main()

    # Check phase-scoped history
    phase_msgs = read_phase_history(iter_dir / "conversation.jsonl")
    # Should have: transition msg, kickoff (system), human msg, agent response
    senders = [m["from"] for m in phase_msgs]
    assert "system" in senders  # transition + kickoff
    assert "human" in senders  # PM's message
    human_msg = [m for m in phase_msgs if m["from"] == "human"][0]
    assert "focus on task splitting" in human_msg["content"]


# --- extraction input content tests ---


def test_refinement_extraction_excludes_system_and_coach_messages(tmp_path):
    """Grooming extraction should filter out system and coach messages."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="refinement")
    _add_coach_to_team_json(team)

    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "We need auth."})
    append_message(log_path, {"from": "system", "iteration": "iter-1", "content": "System kickoff message"})
    append_message(log_path, {"from": "coach", "iteration": "iter-1", "content": "Good point about auth."})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "Agreed, JWT."})

    captured = []
    def mock_completion(**kwargs):
        captured.append(kwargs.get("messages", []))
        return "## Summary\nAuth design."

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", side_effect=lambda **kw: mock_completion(**kw)):
                main()

    assert len(captured) == 1
    user_msg = captured[0][1]["content"]
    assert "We need auth." in user_msg
    assert "Agreed, JWT." in user_msg
    assert "System kickoff" not in user_msg
    assert "Good point about auth." not in user_msg


def test_planning_extraction_excludes_system_and_coach_messages(tmp_path):
    """Planning extraction should filter out system and coach messages."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="planning")
    _add_coach_to_team_json(team)

    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "Task 1: auth module."})
    append_message(log_path, {"from": "system", "iteration": "iter-1", "content": "--- Phase advanced: refinement → planning ---"})
    append_message(log_path, {"from": "coach", "iteration": "iter-1", "content": "Excellent, let me verify coverage."})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "Task 2: API layer."})

    captured = []
    def mock_completion(**kwargs):
        captured.append(kwargs.get("messages", []))
        return json.dumps([
            {"id": "auth", "description": "Auth", "done_criteria": "Works",
             "depends_on": [], "assigned_to": None, "status": "pending"},
        ])

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", side_effect=lambda **kw: mock_completion(**kw)):
                main()

    assert len(captured) == 1
    user_msg = captured[0][1]["content"]
    assert "Task 1: auth module." in user_msg
    assert "Task 2: API layer." in user_msg
    assert "Phase advanced" not in user_msg
    assert "let me verify coverage" not in user_msg


def test_extraction_has_transcript_framing(tmp_path):
    """Extraction user messages should have TRANSCRIPT START/END delimiters."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="refinement")
    _add_coach_to_team_json(team)

    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "Hello."})

    captured = []
    def mock_completion(**kwargs):
        captured.append(kwargs.get("messages", []))
        return "## Summary\nDone."

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", side_effect=lambda **kw: mock_completion(**kw)):
                main()

    assert len(captured) == 1
    user_msg = captured[0][1]["content"]
    assert user_msg.startswith("=== TRANSCRIPT START ===")
    assert user_msg.endswith("=== TRANSCRIPT END ===")


def test_planning_extraction_uses_phase_history(tmp_path):
    """Planning extraction should only see messages from the current phase."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="planning")
    _add_coach_to_team_json(team)

    log_path = iter_dir / "conversation.jsonl"
    # Grooming phase messages
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "grooming msg"})
    # Boundary from refinement → planning
    append_message(log_path, {
        "from": "system", "iteration": "iter-1",
        "content": "--- HISTORY BOUNDARY ---", "phase_boundary": True,
        "from_phase": "refinement", "to_phase": "planning",
    })
    # Planning phase messages
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "Task: build CLI."})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "Agreed."})

    captured = []
    def mock_completion(**kwargs):
        captured.append(kwargs.get("messages", []))
        return json.dumps([
            {"id": "cli", "description": "CLI", "done_criteria": "Works",
             "depends_on": [], "assigned_to": None, "status": "pending"},
        ])

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", side_effect=lambda **kw: mock_completion(**kw)):
                main()

    assert len(captured) == 1
    user_msg = captured[0][1]["content"]
    assert "Task: build CLI." in user_msg
    assert "Agreed." in user_msg
    assert "grooming msg" not in user_msg


def test_notes_extraction_excludes_system_and_coach_messages(tmp_path):
    """Notes extraction should filter out system and coach messages."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="pre-code-review")
    _add_coach_to_team_json(team)

    tasks = [
        {"id": "t1", "description": "Do thing", "done_criteria": "Done",
         "depends_on": [], "assigned_to": "agent-1", "status": "pending", "layer": 0},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "I'll use src/main.py."})
    append_message(log_path, {"from": "system", "iteration": "iter-1", "content": "kickoff message"})
    append_message(log_path, {"from": "coach", "iteration": "iter-1", "content": "Good, let me verify."})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "Interface: def run()."})

    captured = []
    def mock_completion(**kwargs):
        captured.append(kwargs.get("messages", []))
        return json.dumps([{"id": "t1", "notes": "File: src/main.py"}])

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", side_effect=lambda **kw: mock_completion(**kw)):
                main()

    assert len(captured) == 1
    user_msg = captured[0][0]["content"]  # notes uses single user message
    assert "I'll use src/main.py." in user_msg
    assert "Interface: def run()." in user_msg
    assert "kickoff message" not in user_msg
    assert "let me verify" not in user_msg


def test_notes_extraction_has_transcript_framing(tmp_path):
    """Notes extraction prompt should have TRANSCRIPT START/END delimiters."""
    team, iter_dir = _make_advance_team_dir(tmp_path, phase="pre-code-review")
    _add_coach_to_team_json(team)

    tasks = [
        {"id": "t1", "description": "Do thing", "done_criteria": "Done",
         "depends_on": [], "assigned_to": "agent-1", "status": "pending", "layer": 0},
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks))

    log_path = iter_dir / "conversation.jsonl"
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "Proposal."})

    captured = []
    def mock_completion(**kwargs):
        captured.append(kwargs.get("messages", []))
        return json.dumps([{"id": "t1", "notes": "Note."}])

    with patch("sys.argv", ["gotg", "advance"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.chat_completion", side_effect=lambda **kw: mock_completion(**kw)):
                main()

    assert len(captured) == 1
    user_msg = captured[0][0]["content"]  # notes uses single user message
    assert "=== TRANSCRIPT START ===" in user_msg
    assert "=== TRANSCRIPT END ===" in user_msg


# --- pass_turn behavior ---

def test_pass_turn_logged_as_system_note(tmp_path):
    """When agent calls pass_turn, a system note is logged (not an agent message)."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 1,
    }

    def mock_agent(**kwargs):
        return {
            "content": "",
            "operations": [{"name": "pass_turn", "input": {"reason": "agree with proposal"}}],
        }

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    messages = read_log(iter_dir / "conversation.jsonl")
    pass_msgs = [m for m in messages if m.get("pass_turn")]
    assert len(pass_msgs) == 1
    assert pass_msgs[0]["from"] == "system"
    assert "(agent-1 passes: agree with proposal)" == pass_msgs[0]["content"]


def test_pass_turn_reason_in_system_note(tmp_path):
    """The pass_turn reason text appears in the logged system note."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 1,
    }

    def mock_agent(**kwargs):
        return {
            "content": "",
            "operations": [{"name": "pass_turn", "input": {"reason": "waiting for layer 2"}}],
        }

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    messages = read_log(iter_dir / "conversation.jsonl")
    pass_msgs = [m for m in messages if m.get("pass_turn")]
    assert "waiting for layer 2" in pass_msgs[0]["content"]


def test_pass_turn_skips_agent_message(tmp_path):
    """When agent passes, no agent-attributed message is logged."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 2,
    }

    call_count = 0
    def mock_agent(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"content": "I pass", "operations": [{"name": "pass_turn", "input": {"reason": "agree"}}]}
        return {"content": "real response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    messages = read_log(iter_dir / "conversation.jsonl")
    agent_msgs = [m for m in messages if m["from"] == "agent-1"]
    assert len(agent_msgs) == 0  # agent-1 passed, agent-2 spoke
    agent2_msgs = [m for m in messages if m["from"] == "agent-2"]
    assert len(agent2_msgs) == 1
    assert agent2_msgs[0]["content"] == "real response"


def test_pass_turn_counts_as_turn(tmp_path):
    """Pass still increments the turn counter."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 1,
    }

    def mock_agent(**kwargs):
        return {"content": "", "operations": [{"name": "pass_turn", "input": {"reason": "agree"}}]}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    # max_turns=1 means exactly 1 agent call, even with a pass
    messages = read_log(iter_dir / "conversation.jsonl")
    pass_msgs = [m for m in messages if m.get("pass_turn")]
    assert len(pass_msgs) == 1  # Just the pass note


def test_pass_turn_does_not_skip_coach_injection(tmp_path):
    """Coach still speaks after a full rotation that includes passes."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 2,
    }

    def mock_agent(**kwargs):
        return {"content": "", "operations": [{"name": "pass_turn", "input": {"reason": "agree"}}]}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent), \
         patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(iter_dir / "conversation.jsonl")
    coach_msgs = [m for m in messages if m["from"] == "coach"]
    assert len(coach_msgs) == 1


def test_pass_turn_does_not_skip_approval_check(tmp_path):
    """Approval pause still triggers even when agent passes after writing files."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "phase": "implementation", "max_turns": 4,
    }

    from gotg.fileguard import FileGuard
    from gotg.approvals import ApprovalStore

    fg = FileGuard(tmp_path, {"writable_paths": ["src/**"], "enable_approvals": True})
    store = ApprovalStore(iter_dir / "approvals.json")

    # Simulate: agent writes a protected file (triggers pending approval) then passes
    def mock_agent(**kwargs):
        tool_executor = kwargs.get("tool_executor")
        if tool_executor:
            tool_executor("file_write", {"path": "README.md", "content": "hello"})
            tool_executor("pass_turn", {"reason": "wrote file, passing"})
        return {
            "content": "",
            "operations": [
                {"name": "file_write", "input": {"path": "README.md", "content": "hello"}, "result": "pending approval"},
                {"name": "pass_turn", "input": {"reason": "wrote file, passing"}},
            ],
        }

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), fileguard=fg,
                         approval_store=store)

    # Should have paused (returned early) due to pending approval
    messages = read_log(iter_dir / "conversation.jsonl")
    # Only 1 agent turn should have executed before pause
    pass_notes = [m for m in messages if m.get("pass_turn")]
    assert len(pass_notes) <= 1


def test_pass_turn_with_file_ops_logs_ops(tmp_path):
    """File operations are logged even when the agent also passes."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 1,
    }

    def mock_agent(**kwargs):
        return {
            "content": "",
            "operations": [
                {"name": "file_read", "input": {"path": "src/main.py"}, "result": "contents"},
                {"name": "pass_turn", "input": {"reason": "just reading"}},
            ],
        }

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    messages = read_log(iter_dir / "conversation.jsonl")
    # Should have: file_read op (system), pass note (system) — ignore any kickoff
    op_msgs = [m for m in messages if m["from"] == "system" and "file_read" in m["content"]]
    pass_msgs = [m for m in messages if m.get("pass_turn")]
    assert len(op_msgs) == 1
    assert len(pass_msgs) == 1
    assert "passes:" in pass_msgs[0]["content"]


def test_agent_always_has_pass_turn_tool(tmp_path):
    """agentic_completion receives tools including pass_turn even without fileguard."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 1,
    }

    captured_tools = []
    def mock_agent(**kwargs):
        captured_tools.append(kwargs.get("tools", []))
        return {"content": "response", "operations": []}

    with patch("gotg.cli.agentic_completion", side_effect=mock_agent):
        run_conversation(iter_dir, _default_agents(), iteration, _default_model_config())

    assert len(captured_tools) == 1
    tool_names = [t["name"] for t in captured_tools[0]]
    assert "pass_turn" in tool_names


# --- ask_pm behavior ---

def test_ask_pm_pauses_conversation(tmp_path, capsys):
    """Coach calls ask_pm → conversation pauses with question printed."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 4,
    }

    def mock_coach(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        return {
            "content": "We need PM input on the scope.",
            "tool_calls": [{"name": "ask_pm", "input": {"question": "Should we include auth?"}}],
        }

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=mock_coach):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    output = capsys.readouterr().out
    assert "Should we include auth?" in output
    assert "gotg continue -m" in output

    # Conversation should have stopped (only 1 rotation + coach)
    messages = read_log(iter_dir / "conversation.jsonl")
    agent_msgs = [m for m in messages if m["from"] not in ("system", "coach")]
    assert len(agent_msgs) == 2  # agent-1, agent-2, then coach paused


def test_ask_pm_empty_text_gets_fallback(tmp_path):
    """Empty coach text with ask_pm gets fallback text."""
    iter_dir = _make_iter_dir(tmp_path)
    iteration = {
        "id": "iter-1", "description": "A task",
        "status": "in-progress", "max_turns": 4,
    }

    def mock_coach(base_url, model, messages, api_key=None, provider="ollama", tools=None):
        return {
            "content": "",
            "tool_calls": [{"name": "ask_pm", "input": {"question": "What's the priority?"}}],
        }

    with patch("gotg.cli.agentic_completion", return_value={"content": "response", "operations": []}), \
         patch("gotg.cli.chat_completion", side_effect=mock_coach):
        run_conversation(iter_dir, _default_agents(), iteration,
                         _default_model_config(), coach=_default_coach())

    messages = read_log(iter_dir / "conversation.jsonl")
    coach_msgs = [m for m in messages if m["from"] == "coach"]
    assert len(coach_msgs) == 1
    assert "(Requesting PM input: What's the priority?)" == coach_msgs[0]["content"]


def test_ask_pm_resume_with_continue(tmp_path):
    """After ask_pm pause, continue -m injects the PM's answer into history."""
    # Setup: team dir with a conversation that has a coach ask_pm pause
    team = tmp_path / ".team"
    team.mkdir()
    _write_team_json(team)
    team_config = json.loads((team / "team.json").read_text())
    team_config["coach"] = {"name": "coach", "role": "Agile Coach"}
    (team / "team.json").write_text(json.dumps(team_config, indent=2))
    _write_iteration_json(team, iterations=[
        {"id": "iter-1", "title": "", "description": "A task",
         "status": "in-progress", "phase": "refinement", "max_turns": 10},
    ])
    iter_dir = team / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    log_path = iter_dir / "conversation.jsonl"

    # Pre-populate with conversation up to ask_pm pause
    append_message(log_path, {"from": "agent-1", "iteration": "iter-1", "content": "idea"})
    append_message(log_path, {"from": "agent-2", "iteration": "iter-1", "content": "agreed"})
    append_message(log_path, {"from": "coach", "iteration": "iter-1",
                              "content": "(Requesting PM input: Should we include auth?)"})

    # Continue with PM's answer
    def mock_agent(**kwargs):
        return {"content": "response", "operations": []}

    with patch("sys.argv", ["gotg", "continue", "-m", "Yes, include auth", "--max-turns", "1"]):
        with patch("gotg.cli.find_team_dir", return_value=team):
            with patch("gotg.cli.agentic_completion", side_effect=mock_agent), \
                 patch("gotg.cli.chat_completion", side_effect=_mock_chat_with_tools):
                main()

    messages = read_log(log_path)
    human_msgs = [m for m in messages if m["from"] == "human"]
    assert len(human_msgs) == 1
    assert "Yes, include auth" in human_msgs[0]["content"]
