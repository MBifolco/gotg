"""Tests for exploration context injection — mechanisms 0-3."""

import json
from pathlib import Path

import pytest

from gotg.explore import write_exploration_metadata, load_exploration_metadata
from gotg.policy import exploration_policy
from gotg.prompts import (
    AGENT_TOOLS,
    EXPLORATION_KICKOFF_TEMPLATE,
    EXPLORATION_KICKOFF_WITH_CONTEXT_AND_TOOLS_TEMPLATE,
    EXPLORATION_KICKOFF_WITH_CONTEXT_TEMPLATE,
    EXPLORATION_SYSTEM_SUPPLEMENT,
    EXPLORATION_SYSTEM_SUPPLEMENT_WITH_CONTEXT,
)
from gotg.tools import READ_ONLY_FILE_TOOLS, FILE_TOOLS
from gotg.agent import build_prompt, build_coach_prompt
from gotg.iteration_store import IterationStore
from gotg.session_setup import load_iteration_context
from gotg.session_types import SessionSetupError


# --- Helpers ---

AGENTS = [
    {"name": "agent-1", "role": "Software Engineer"},
    {"name": "agent-2", "role": "Software Engineer"},
]
COACH = {"name": "coach", "role": "Agile Coach"}
ITERATION_EXPLORE = {"id": "test-slug", "description": "test topic", "phase": None}


def _make_team_dir(tmp_path, iterations=None):
    """Create a minimal .team dir with iteration.json and iteration dirs."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    if iterations is None:
        iterations = []
    iter_data = {
        "schema_version": 1,
        "current": iterations[0]["id"] if iterations else "iter-1",
        "iterations": iterations,
    }
    (team_dir / "iteration.json").write_text(json.dumps(iter_data))
    iters_dir = team_dir / "iterations"
    iters_dir.mkdir()
    for it in iterations:
        d = iters_dir / it["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "conversation.jsonl").touch()
    return team_dir


def _add_refinement_summary(team_dir, iter_id, content="## Summary\nTest summary."):
    path = team_dir / "iterations" / iter_id / "refinement_summary.md"
    path.write_text(content)


def _add_tasks_json(team_dir, iter_id, tasks=None):
    if tasks is None:
        tasks = [{"id": "t1", "description": "Task 1", "done_criteria": "Task is done", "depends_on": [], "status": "pending", "assigned_to": None}]
    path = team_dir / "iterations" / iter_id / "tasks.json"
    path.write_text(json.dumps(tasks))


# ══════════════════════════════════════════════════════════════
# Mechanism 0: exploration.json Linkage
# ══════════════════════════════════════════════════════════════


def test_write_exploration_metadata_with_context_from(tmp_path):
    """context_from string is persisted in exploration.json."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "exploration").mkdir(parents=True)

    explore_dir = write_exploration_metadata(
        team_dir, "test-slug", "test topic",
        coach=True, max_turns=30, context_from="iter-1",
    )
    meta = json.loads((explore_dir / "exploration.json").read_text())
    assert meta["context_from"] == "iter-1"


def test_write_exploration_metadata_no_context(tmp_path):
    """context_from=False (--no-context) is persisted as false in JSON."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "exploration").mkdir(parents=True)

    explore_dir = write_exploration_metadata(
        team_dir, "test-slug", "test topic",
        coach=False, max_turns=30, context_from=False,
    )
    meta = json.loads((explore_dir / "exploration.json").read_text())
    assert meta["context_from"] is False


def test_write_exploration_metadata_null_context(tmp_path):
    """Default context_from=None is persisted as null in JSON."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "exploration").mkdir(parents=True)

    explore_dir = write_exploration_metadata(
        team_dir, "test-slug", "test topic",
        coach=False, max_turns=30,
    )
    meta = json.loads((explore_dir / "exploration.json").read_text())
    assert meta["context_from"] is None


def test_explore_continue_reads_context_from_string(tmp_path):
    """String context_from is loadable after write + load cycle."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "exploration").mkdir(parents=True)

    write_exploration_metadata(
        team_dir, "test-slug", "test topic",
        coach=True, max_turns=30, context_from="iter-1",
    )
    meta, _ = load_exploration_metadata(team_dir, "test-slug")
    assert meta["context_from"] == "iter-1"


def test_explore_continue_context_from_null_skips(tmp_path):
    """null context_from is preserved through write+load cycle."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "exploration").mkdir(parents=True)

    write_exploration_metadata(
        team_dir, "test-slug", "test topic",
        coach=False, max_turns=30, context_from=None,
    )
    meta, _ = load_exploration_metadata(team_dir, "test-slug")
    assert meta["context_from"] is None


def test_explore_continue_context_from_false_skips(tmp_path):
    """false context_from is preserved through write+load cycle."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "exploration").mkdir(parents=True)

    write_exploration_metadata(
        team_dir, "test-slug", "test topic",
        coach=False, max_turns=30, context_from=False,
    )
    meta, _ = load_exploration_metadata(team_dir, "test-slug")
    assert meta["context_from"] is False


# ══════════════════════════════════════════════════════════════
# IterationStore.list_all
# ══════════════════════════════════════════════════════════════


def test_iteration_store_list_all(tmp_path):
    """list_all returns all iterations in order, uses migration path."""
    iters = [
        {"id": "iter-1", "title": "", "description": "First", "status": "in-progress", "phase": "refinement", "max_turns": 30},
        {"id": "iter-2", "title": "", "description": "Second", "status": "pending", "phase": "refinement", "max_turns": 30},
    ]
    team_dir = _make_team_dir(tmp_path, iters)
    store = IterationStore(team_dir)
    result = store.list_all()
    assert len(result) == 2
    assert result[0]["id"] == "iter-1"
    assert result[1]["id"] == "iter-2"


# ══════════════════════════════════════════════════════════════
# Mechanism 1: Iteration Context Loading
# ══════════════════════════════════════════════════════════════


def test_load_iteration_context_explicit(tmp_path):
    """context_from='iter-1' loads correct artifacts."""
    iters = [{"id": "iter-1", "title": "", "description": "First", "status": "in-progress", "phase": "planning", "max_turns": 30}]
    team_dir = _make_team_dir(tmp_path, iters)
    _add_refinement_summary(team_dir, "iter-1", "## Summary\nWe agreed to build X.")
    _add_tasks_json(team_dir, "iter-1")

    result = load_iteration_context(team_dir, context_from="iter-1")
    assert result is not None
    assert "Refinement Summary" in result
    assert "We agreed to build X." in result
    assert "Task Breakdown" in result


def test_load_iteration_context_auto_detect(tmp_path):
    """Auto-detect picks latest non-pending iteration with artifacts."""
    iters = [
        {"id": "iter-1", "title": "", "description": "First", "status": "done", "phase": "planning", "max_turns": 30},
        {"id": "iter-2", "title": "", "description": "Second", "status": "in-progress", "phase": "refinement", "max_turns": 30},
    ]
    team_dir = _make_team_dir(tmp_path, iters)
    _add_refinement_summary(team_dir, "iter-1", "Iter 1 summary")
    _add_refinement_summary(team_dir, "iter-2", "Iter 2 summary")

    result = load_iteration_context(team_dir)
    assert result is not None
    # Should pick iter-2 (last match wins)
    assert "iter-2" in result
    assert "Iter 2 summary" in result


def test_load_iteration_context_skips_pending(tmp_path):
    """Pending iterations are skipped during auto-detect."""
    iters = [
        {"id": "iter-1", "title": "", "description": "First", "status": "done", "phase": "planning", "max_turns": 30},
        {"id": "iter-2", "title": "", "description": "Second", "status": "pending", "phase": "refinement", "max_turns": 30},
    ]
    team_dir = _make_team_dir(tmp_path, iters)
    _add_refinement_summary(team_dir, "iter-1", "Iter 1 summary")
    _add_refinement_summary(team_dir, "iter-2", "Iter 2 summary")

    result = load_iteration_context(team_dir)
    assert result is not None
    assert "iter-1" in result  # iter-2 is pending, so iter-1 is picked


def test_load_iteration_context_no_iterations(tmp_path):
    """Returns None when no iterations exist."""
    team_dir = _make_team_dir(tmp_path, [])
    result = load_iteration_context(team_dir)
    assert result is None


def test_load_iteration_context_no_artifacts(tmp_path):
    """Returns None when iteration has no artifacts."""
    iters = [{"id": "iter-1", "title": "", "description": "First", "status": "in-progress", "phase": "refinement", "max_turns": 30}]
    team_dir = _make_team_dir(tmp_path, iters)
    result = load_iteration_context(team_dir)
    assert result is None


def test_load_iteration_context_tasks_only(tmp_path):
    """Works with tasks.json but no refinement_summary."""
    iters = [{"id": "iter-1", "title": "", "description": "First", "status": "in-progress", "phase": "planning", "max_turns": 30}]
    team_dir = _make_team_dir(tmp_path, iters)
    _add_tasks_json(team_dir, "iter-1")

    result = load_iteration_context(team_dir, context_from="iter-1")
    assert result is not None
    assert "Task Breakdown" in result
    assert "Refinement Summary" not in result


def test_load_iteration_context_explicit_not_found(tmp_path):
    """strict=True raises SessionSetupError when iteration not found."""
    iters = [{"id": "iter-1", "title": "", "description": "First", "status": "in-progress", "phase": "refinement", "max_turns": 30}]
    team_dir = _make_team_dir(tmp_path, iters)

    with pytest.raises(SessionSetupError, match="iteration 'iter-3' not found"):
        load_iteration_context(team_dir, context_from="iter-3", strict=True)


def test_load_iteration_context_explicit_no_artifacts(tmp_path):
    """strict=True raises SessionSetupError when iteration has no artifacts."""
    iters = [{"id": "iter-1", "title": "", "description": "First", "status": "in-progress", "phase": "refinement", "max_turns": 30}]
    team_dir = _make_team_dir(tmp_path, iters)

    with pytest.raises(SessionSetupError, match="no artifacts"):
        load_iteration_context(team_dir, context_from="iter-1", strict=True)


def test_no_context_flag_suppresses_injection(tmp_path):
    """--no-context → context_from=False is respected on continue."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "exploration").mkdir(parents=True)

    write_exploration_metadata(
        team_dir, "test-slug", "test topic",
        coach=False, max_turns=30, context_from=False,
    )
    meta, _ = load_exploration_metadata(team_dir, "test-slug")
    context_from = meta.get("context_from")
    # False → skip loading
    assert context_from is False
    assert not isinstance(context_from, str)


# ══════════════════════════════════════════════════════════════
# Policy: project_context field
# ══════════════════════════════════════════════════════════════


def test_exploration_policy_with_project_context():
    """project_context field is set on policy when provided."""
    p = exploration_policy(
        AGENTS, "Discuss feature X", history=[],
        project_context="=== Refinement Summary ===\nTest context",
    )
    assert p.project_context == "=== Refinement Summary ===\nTest context"


def test_exploration_policy_without_project_context():
    """project_context remains None by default (backward compat)."""
    p = exploration_policy(AGENTS, "Discuss feature X", history=[])
    assert p.project_context is None


# ══════════════════════════════════════════════════════════════
# Prompt rendering: project_context
# ══════════════════════════════════════════════════════════════


def test_build_prompt_project_context():
    """PROJECT CONTEXT block is rendered in agent system prompt."""
    msgs = build_prompt(
        AGENTS[0], ITERATION_EXPLORE, [],
        project_context="=== Refinement Summary ===\nTest context",
    )
    system_content = msgs[0]["content"]
    assert "PROJECT CONTEXT:" in system_content
    assert "Test context" in system_content


def test_build_prompt_no_project_context():
    """No PROJECT CONTEXT block when project_context is None."""
    msgs = build_prompt(AGENTS[0], ITERATION_EXPLORE, [])
    system_content = msgs[0]["content"]
    assert "PROJECT CONTEXT:" not in system_content


def test_build_coach_prompt_project_context():
    """PROJECT CONTEXT block is rendered in coach system prompt."""
    msgs = build_coach_prompt(
        COACH, ITERATION_EXPLORE, [],
        project_context="=== Task Breakdown ===\nTask data",
    )
    system_content = msgs[0]["content"]
    assert "PROJECT CONTEXT:" in system_content
    assert "Task data" in system_content


# ══════════════════════════════════════════════════════════════
# Mechanism 2: Read-Only File Tools
# ══════════════════════════════════════════════════════════════


def test_read_only_file_tools_excludes_write():
    """READ_ONLY_FILE_TOOLS has file_read + file_list but not file_write."""
    names = {t["name"] for t in READ_ONLY_FILE_TOOLS}
    assert "file_read" in names
    assert "file_list" in names
    assert "file_write" not in names


def test_exploration_policy_with_file_access(tmp_path):
    """fileguard is set and read-only tools in agent_tools when file_access provided."""
    p = exploration_policy(
        AGENTS, "Discuss feature X", history=[],
        project_root=tmp_path,
        file_access={"writable_paths": ["src/"]},
    )
    assert p.fileguard is not None
    # Fileguard should have empty writable_paths (read-only)
    assert p.fileguard.writable_paths == []
    # Agent tools should include file_read and file_list
    tool_names = {t["name"] for t in p.agent_tools}
    assert "file_read" in tool_names
    assert "file_list" in tool_names
    assert "file_write" not in tool_names


def test_exploration_policy_without_file_access():
    """No fileguard or file tools when file_access not provided (backward compat)."""
    p = exploration_policy(AGENTS, "Discuss feature X", history=[])
    assert p.fileguard is None
    tool_names = {t["name"] for t in p.agent_tools}
    assert "file_read" not in tool_names


def test_exploration_fileguard_blocks_writes(tmp_path):
    """FileGuard with empty writable_paths rejects writes."""
    from gotg.fileguard import FileGuard, SecurityError

    config = {"writable_paths": [], "enable_approvals": False}
    fg = FileGuard(tmp_path, config)
    with pytest.raises(SecurityError):
        fg.validate_write("src/main.py")


def test_exploration_file_read_works(tmp_path):
    """file_read succeeds through read-only fileguard."""
    from gotg.fileguard import FileGuard

    (tmp_path / "test.txt").write_text("hello")
    config = {"writable_paths": [], "enable_approvals": False}
    fg = FileGuard(tmp_path, config)
    resolved = fg.validate_read("test.txt")
    assert resolved.read_text() == "hello"


def test_build_prompt_exploration_file_access(tmp_path):
    """Read-only file access prompt injected for phase=None with fileguard."""
    from gotg.fileguard import FileGuard

    config = {"writable_paths": [], "enable_approvals": False}
    fg = FileGuard(tmp_path, config)

    msgs = build_prompt(AGENTS[0], ITERATION_EXPLORE, [], fileguard=fg)
    system_content = msgs[0]["content"]
    assert "FILE ACCESS (read-only)" in system_content
    assert "file_read" in system_content


def test_build_prompt_no_file_access_exploration():
    """No file access prompt when no fileguard for exploration."""
    msgs = build_prompt(AGENTS[0], ITERATION_EXPLORE, [])
    system_content = msgs[0]["content"]
    assert "FILE ACCESS" not in system_content


# ══════════════════════════════════════════════════════════════
# Mechanism 3: Bootstrap Kickoff Variants
# ══════════════════════════════════════════════════════════════


def test_exploration_kickoff_context_and_tools(tmp_path):
    """Uses context+tools kickoff template when both available."""
    p = exploration_policy(
        AGENTS, "Building a calculator UI", history=[],
        project_context="Some context",
        project_root=tmp_path,
        file_access={"writable_paths": ["src/"]},
    )
    assert p.kickoff_text is not None
    assert "file_list" in p.kickoff_text
    assert "file_read" in p.kickoff_text
    assert "Building a calculator UI" in p.kickoff_text
    assert "agent-1" in p.kickoff_text


def test_exploration_kickoff_context_only():
    """Uses context-only template when context but no file tools."""
    p = exploration_policy(
        AGENTS, "Building a calculator UI", history=[],
        project_context="Some context",
    )
    assert p.kickoff_text is not None
    assert "iteration context" in p.kickoff_text.lower()
    assert "file_list" not in p.kickoff_text
    assert "agent-1" in p.kickoff_text


def test_exploration_kickoff_generic():
    """Uses original generic template (backward compat) when no context."""
    p = exploration_policy(AGENTS, "Building a calculator UI", history=[])
    assert p.kickoff_text is not None
    assert "open exploration" in p.kickoff_text.lower()
    assert "agent-1" in p.kickoff_text


def test_exploration_system_supplement_with_context():
    """Uses context-aware system supplement when project_context set."""
    p = exploration_policy(
        AGENTS, "test", history=[],
        project_context="Some context",
    )
    assert "EXPLORATION" in p.system_supplement
    assert "Previous iteration context" in p.system_supplement


def test_exploration_system_supplement_without_context():
    """Uses default system supplement when no project_context."""
    p = exploration_policy(AGENTS, "test", history=[])
    assert p.system_supplement == EXPLORATION_SYSTEM_SUPPLEMENT


# ══════════════════════════════════════════════════════════════
# Finding 2: Corrupt artifact handling
# ══════════════════════════════════════════════════════════════


def test_load_iteration_context_corrupt_tasks_auto(tmp_path):
    """Auto-detect skips corrupt tasks.json and still returns summary."""
    iters = [{"id": "iter-1", "title": "", "description": "First", "status": "in-progress", "phase": "planning", "max_turns": 30}]
    team_dir = _make_team_dir(tmp_path, iters)
    _add_refinement_summary(team_dir, "iter-1", "Good summary")
    # Write corrupt tasks.json
    (team_dir / "iterations" / "iter-1" / "tasks.json").write_text("{corrupt")

    result = load_iteration_context(team_dir, context_from="iter-1")
    assert result is not None
    assert "Good summary" in result
    # Tasks section absent due to corrupt file
    assert "Task Breakdown" not in result


def test_load_iteration_context_corrupt_tasks_strict(tmp_path):
    """strict=True raises SessionSetupError on corrupt tasks.json."""
    iters = [{"id": "iter-1", "title": "", "description": "First", "status": "in-progress", "phase": "planning", "max_turns": 30}]
    team_dir = _make_team_dir(tmp_path, iters)
    # Only tasks.json, and it's corrupt
    (team_dir / "iterations" / "iter-1" / "tasks.json").write_text("{corrupt")

    with pytest.raises(SessionSetupError, match="failed to load tasks.json"):
        load_iteration_context(team_dir, context_from="iter-1", strict=True)


# ══════════════════════════════════════════════════════════════
# Finding 3: Command-level end-to-end tests
# ══════════════════════════════════════════════════════════════


def _make_full_team_dir(tmp_path, with_artifacts=True):
    """Create a .team dir with team.json, iteration.json, and optional artifacts."""
    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    team_config = {
        "model": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "m"},
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
    }
    (team_dir / "team.json").write_text(json.dumps(team_config))

    iters = [{"id": "iter-1", "title": "", "description": "First", "status": "in-progress", "phase": "planning", "max_turns": 30}]
    iter_data = {"schema_version": 1, "current": "iter-1", "iterations": iters}
    (team_dir / "iteration.json").write_text(json.dumps(iter_data))

    iter_dir = team_dir / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()

    if with_artifacts:
        _add_refinement_summary(team_dir, "iter-1", "## Summary\nBuild a calculator.")
        _add_tasks_json(team_dir, "iter-1")

    return team_dir


def test_cmd_explore_start_no_context_suppresses_injection(tmp_path, monkeypatch):
    """--no-context flag persists context_from=False and skips loading."""
    team_dir = _make_full_team_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    from unittest.mock import patch, MagicMock
    import argparse

    args = argparse.Namespace(
        topic="test topic",
        slug=None,
        coach=False,
        max_turns=None,
        no_context=True,
        context_from=None,
    )

    with patch("gotg.commands.explore._cli") as mock_cli:
        mock_cli.find_team_dir.return_value = team_dir
        with patch("gotg.commands.explore.TeamContext") as MockCtx:
            ctx = MagicMock()
            ctx.agents = [
                {"name": "agent-1", "role": "Software Engineer"},
                {"name": "agent-2", "role": "Software Engineer"},
            ]
            ctx.coach = None
            ctx.model_config = {"provider": "test"}
            ctx.project_root = tmp_path
            ctx.file_access = None
            ctx.model_resolver = None
            MockCtx.from_team_dir.return_value = ctx
            with patch("gotg.commands.explore.run_exploration_conversation") as mock_run:
                with patch("gotg.config.load_streaming_config", return_value=False):
                    from gotg.commands.explore import cmd_explore_start
                    cmd_explore_start(args)

    # Verify context_from=False was persisted
    from gotg.explore import list_exploration_sessions
    sessions = list_exploration_sessions(team_dir)
    assert len(sessions) == 1
    assert sessions[0]["context_from"] is False

    # Verify run_exploration_conversation was called with project_context=None
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["project_context"] is None


def test_cmd_explore_start_auto_detect_persists_context_from(tmp_path, monkeypatch):
    """Default auto-detect persists resolved iteration ID in context_from."""
    team_dir = _make_full_team_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    from unittest.mock import patch, MagicMock
    import argparse

    args = argparse.Namespace(
        topic="test topic",
        slug=None,
        coach=False,
        max_turns=None,
        no_context=False,
        context_from=None,
    )

    with patch("gotg.commands.explore._cli") as mock_cli:
        mock_cli.find_team_dir.return_value = team_dir
        with patch("gotg.commands.explore.TeamContext") as MockCtx:
            ctx = MagicMock()
            ctx.agents = [
                {"name": "agent-1", "role": "Software Engineer"},
                {"name": "agent-2", "role": "Software Engineer"},
            ]
            ctx.coach = None
            ctx.model_config = {"provider": "test"}
            ctx.project_root = tmp_path
            ctx.file_access = None
            ctx.model_resolver = None
            MockCtx.from_team_dir.return_value = ctx
            with patch("gotg.commands.explore.run_exploration_conversation") as mock_run:
                with patch("gotg.config.load_streaming_config", return_value=False):
                    from gotg.commands.explore import cmd_explore_start
                    cmd_explore_start(args)

    # Verify context_from="iter-1" was persisted (auto-detected)
    from gotg.explore import list_exploration_sessions
    sessions = list_exploration_sessions(team_dir)
    assert len(sessions) == 1
    assert sessions[0]["context_from"] == "iter-1"

    # Verify project_context was passed
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["project_context"] is not None
    assert "calculator" in call_kwargs["project_context"].lower()


def test_cmd_explore_continue_context_from_false_skips(tmp_path, monkeypatch):
    """On continue, context_from=False means no context loading."""
    team_dir = _make_full_team_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    from gotg.explore import write_exploration_metadata
    write_exploration_metadata(
        team_dir, "test-slug", "test topic",
        coach=False, max_turns=30, context_from=False,
    )

    from unittest.mock import patch, MagicMock
    import argparse

    args = argparse.Namespace(
        slug="test-slug",
        message=None,
        max_turns=None,
    )

    with patch("gotg.commands.explore._cli") as mock_cli:
        mock_cli.find_team_dir.return_value = team_dir
        with patch("gotg.commands.explore.TeamContext") as MockCtx:
            ctx = MagicMock()
            ctx.agents = [
                {"name": "agent-1", "role": "Software Engineer"},
                {"name": "agent-2", "role": "Software Engineer"},
            ]
            ctx.coach = None
            ctx.model_config = {"provider": "test"}
            ctx.project_root = tmp_path
            ctx.file_access = None
            ctx.model_resolver = None
            MockCtx.from_team_dir.return_value = ctx
            with patch("gotg.commands.explore.run_exploration_conversation") as mock_run:
                with patch("gotg.config.load_streaming_config", return_value=False):
                    from gotg.commands.explore import cmd_explore_continue
                    cmd_explore_continue(args)

    # Verify project_context=None even though artifacts exist
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["project_context"] is None


def test_cmd_explore_continue_context_from_string_loads(tmp_path, monkeypatch):
    """On continue, context_from='iter-1' loads that iteration's artifacts."""
    team_dir = _make_full_team_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    from gotg.explore import write_exploration_metadata
    write_exploration_metadata(
        team_dir, "test-slug", "test topic",
        coach=False, max_turns=30, context_from="iter-1",
    )

    from unittest.mock import patch, MagicMock
    import argparse

    args = argparse.Namespace(
        slug="test-slug",
        message=None,
        max_turns=None,
    )

    with patch("gotg.commands.explore._cli") as mock_cli:
        mock_cli.find_team_dir.return_value = team_dir
        with patch("gotg.commands.explore.TeamContext") as MockCtx:
            ctx = MagicMock()
            ctx.agents = [
                {"name": "agent-1", "role": "Software Engineer"},
                {"name": "agent-2", "role": "Software Engineer"},
            ]
            ctx.coach = None
            ctx.model_config = {"provider": "test"}
            ctx.project_root = tmp_path
            ctx.file_access = None
            ctx.model_resolver = None
            MockCtx.from_team_dir.return_value = ctx
            with patch("gotg.commands.explore.run_exploration_conversation") as mock_run:
                with patch("gotg.config.load_streaming_config", return_value=False):
                    from gotg.commands.explore import cmd_explore_continue
                    cmd_explore_continue(args)

    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["project_context"] is not None
    assert "calculator" in call_kwargs["project_context"].lower()


# ══════════════════════════════════════════════════════════════
# TUI parity: HomeScreen exploration creation
# ══════════════════════════════════════════════════════════════


def test_tui_new_exploration_persists_context_from(tmp_path):
    """TUI _on_new_exploration auto-detects and persists context_from."""
    team_dir = _make_full_team_dir(tmp_path)

    from unittest.mock import patch, MagicMock

    # We can't easily run the full TUI, but we can test the logic
    # by calling write_exploration_metadata with the same auto-detect
    # pattern that _on_new_exploration now uses.
    from gotg.session_setup import load_iteration_context
    from gotg.iteration_store import IterationStore
    from gotg.explore import generate_slug, existing_slugs, write_exploration_metadata

    topic = "test TUI exploration"
    slug = generate_slug(topic, existing_slugs(team_dir))

    # Replicate TUI auto-detect logic
    context_from_value = None
    project_context = load_iteration_context(team_dir)
    if project_context:
        all_iters = IterationStore(team_dir).list_all()
        for it in all_iters:
            if it.get("status") == "pending":
                continue
            d = IterationStore(team_dir).get_dir(it["id"])
            if (d / "refinement_summary.md").exists() or (d / "tasks.json").exists():
                context_from_value = it["id"]

    write_exploration_metadata(
        team_dir, slug, topic=topic, coach=True, max_turns=30,
        context_from=context_from_value,
    )

    # Verify persisted
    from gotg.explore import load_exploration_metadata
    meta, _ = load_exploration_metadata(team_dir, slug)
    assert meta["context_from"] == "iter-1"
