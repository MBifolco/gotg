"""Tests for the implementation phase executor."""

import json
from pathlib import Path

import pytest

from gotg.events import (
    AppendDebug,
    AppendMessage,
    LayerComplete,
    PauseForApprovals,
    SessionComplete,
    SessionStarted,
    TaskBlocked,
    ToolCallProgress,
)
from gotg.implementation import (
    run_implementation,
    _agents_with_pending_work,
    _format_agent_tasks,
    _handle_complete_tasks,
    _handle_report_blocked,
)
from gotg.model import CompletionRound
from gotg.engine import SessionDeps
from gotg.policy import SessionPolicy
from gotg.prompts import AGENT_TOOLS
from gotg.tools import FILE_TOOLS


# --- Helpers ---

AGENTS = [
    {"name": "agent-1", "role": "Software Engineer"},
    {"name": "agent-2", "role": "Software Engineer"},
]

ITERATION = {
    "id": "iter-1",
    "description": "Build a thing",
    "phase": "implementation",
    "max_turns": 30,
    "current_layer": 0,
}

MODEL_CONFIG = {
    "provider": "ollama",
    "base_url": "http://localhost:11434",
    "model": "test-model",
}


def _make_tasks(layer=0):
    return [
        {
            "id": "task-a", "description": "Do A", "done_criteria": "A done",
            "depends_on": [], "assigned_to": "agent-1", "status": "pending",
            "layer": layer,
        },
        {
            "id": "task-b", "description": "Do B", "done_criteria": "B done",
            "depends_on": [], "assigned_to": "agent-2", "status": "pending",
            "layer": layer,
        },
    ]


def _make_multi_layer_tasks():
    return [
        {
            "id": "task-a", "description": "Do A", "done_criteria": "A done",
            "depends_on": [], "assigned_to": "agent-1", "status": "pending",
            "layer": 0,
        },
        {
            "id": "task-b", "description": "Do B", "done_criteria": "B done",
            "depends_on": [], "assigned_to": "agent-2", "status": "pending",
            "layer": 0,
        },
        {
            "id": "task-c", "description": "Do C", "done_criteria": "C done",
            "depends_on": ["task-a"], "assigned_to": "agent-1", "status": "pending",
            "layer": 1,
        },
    ]


def _setup_iter_dir(tmp_path, tasks):
    iter_dir = tmp_path / ".team" / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "tasks.json").write_text(json.dumps(tasks, indent=2))
    (iter_dir / "conversation.jsonl").touch()
    return iter_dir


def _make_policy(**overrides):
    defaults = dict(
        max_turns=30, coach=None, coach_cadence=None,
        stop_on_phase_complete=False, stop_on_ask_pm=False,
        agent_tools=tuple(list(AGENT_TOOLS) + list(FILE_TOOLS)),
        coach_tools=None,
        groomed_summary=None, tasks_summary=None, diffs_summary=None,
        kickoff_text=None, fileguard=None, approval_store=None,
        worktree_map=None, system_supplement=None, coach_system_prompt=None,
    )
    defaults.update(overrides)
    return SessionPolicy(**defaults)


def _text_round(text):
    """Create a CompletionRound with no tool calls (text-only response)."""
    return CompletionRound(
        content=text,
        tool_calls=[],
        _provider="openai",
        _raw={"message": {"content": text}},
    )


def _tool_round(text, tool_calls):
    """Create a CompletionRound with tool calls."""
    raw_tc = [
        {"id": tc["id"], "function": {"name": tc["name"], "arguments": json.dumps(tc["input"])}}
        for tc in tool_calls
    ]
    return CompletionRound(
        content=text,
        tool_calls=tool_calls,
        _provider="openai",
        _raw={"message": {"content": text, "tool_calls": raw_tc}},
    )


def _collect(gen):
    return list(gen)


def _events_of_type(events, cls):
    return [e for e in events if isinstance(e, cls)]


# --- Unit tests for helpers ---


def test_agents_with_pending_work():
    tasks = _make_tasks()
    active = _agents_with_pending_work(AGENTS, tasks, layer=0)
    assert len(active) == 2
    assert active[0]["name"] == "agent-1"


def test_agents_with_pending_work_skips_done():
    tasks = _make_tasks()
    tasks[0]["status"] = "done"
    active = _agents_with_pending_work(AGENTS, tasks, layer=0)
    assert len(active) == 1
    assert active[0]["name"] == "agent-2"


def test_agents_with_pending_work_wrong_layer():
    tasks = _make_tasks(layer=0)
    active = _agents_with_pending_work(AGENTS, tasks, layer=1)
    assert len(active) == 0


def test_format_agent_tasks():
    tasks = _make_tasks()
    result = _format_agent_tasks(tasks, "agent-1", 0)
    assert "task-a" in result
    assert "task-b" not in result
    assert "layer 0" in result


def test_handle_complete_tasks_success(tmp_path):
    tasks = _make_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)
    result = _handle_complete_tasks(
        {"task_ids": ["task-a"], "summary": "Did A"},
        "agent-1", tasks, 0, iter_dir,
    )
    assert "Completed" in result
    assert "task-a" in result
    # Verify persistence
    saved = json.loads((iter_dir / "tasks.json").read_text())
    done_task = next(t for t in saved if t["id"] == "task-a")
    assert done_task["status"] == "done"
    assert done_task["completed_by"] == "agent-1"
    assert done_task["completion_summary"] == "Did A"


def test_handle_complete_tasks_wrong_agent(tmp_path):
    tasks = _make_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)
    result = _handle_complete_tasks(
        {"task_ids": ["task-a"], "summary": "Did A"},
        "agent-2", tasks, 0, iter_dir,
    )
    assert result.startswith("Error:")
    assert "not assigned to you" in result


def test_handle_complete_tasks_wrong_layer(tmp_path):
    tasks = _make_tasks(layer=0)
    iter_dir = _setup_iter_dir(tmp_path, tasks)
    result = _handle_complete_tasks(
        {"task_ids": ["task-a"], "summary": "Did A"},
        "agent-1", tasks, 1, iter_dir,
    )
    assert result.startswith("Error:")
    assert "not in layer" in result


def test_handle_complete_tasks_already_done(tmp_path):
    tasks = _make_tasks()
    tasks[0]["status"] = "done"
    iter_dir = _setup_iter_dir(tmp_path, tasks)
    result = _handle_complete_tasks(
        {"task_ids": ["task-a"], "summary": "Did A"},
        "agent-1", tasks, 0, iter_dir,
    )
    assert "already" in result.lower()


def test_handle_complete_tasks_empty_ids(tmp_path):
    tasks = _make_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)
    result = _handle_complete_tasks(
        {"task_ids": [], "summary": "Did nothing"},
        "agent-1", tasks, 0, iter_dir,
    )
    assert result.startswith("Error:")


def test_handle_report_blocked_success(tmp_path):
    tasks = _make_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)
    result, blocked_ids = _handle_report_blocked(
        {"task_ids": ["task-a"], "reason": "Need parser contract"},
        "agent-1", tasks, 0, iter_dir,
    )
    assert "Blocked tasks:" in result
    assert blocked_ids == ("task-a",)
    saved = json.loads((iter_dir / "tasks.json").read_text())
    blocked = next(t for t in saved if t["id"] == "task-a")
    assert blocked["status"] == "blocked"
    assert blocked["blocked_by"] == "agent-1"
    assert "parser contract" in blocked["blocked_reason"]


# --- Integration tests for run_implementation ---


def test_dispatch_only_current_layer_agents(tmp_path):
    """Only agents with pending tasks in current layer are dispatched."""
    tasks = _make_multi_layer_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    call_log = []

    def mock_single(**kw):
        call_log.append(kw)
        return _text_round("Done implementing.")

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(),
    ))

    # SessionStarted should list both agents (both have layer-0 tasks)
    started = _events_of_type(events, SessionStarted)
    assert len(started) == 1
    assert set(started[0].agents) == {"agent-1", "agent-2"}

    # Should end with SessionComplete (agents didn't call complete_tasks)
    assert isinstance(events[-1], SessionComplete)


def test_agents_with_done_tasks_skipped(tmp_path):
    """Agents whose tasks are already done are skipped."""
    tasks = _make_tasks()
    tasks[0]["status"] = "done"  # agent-1's task is done
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    call_log = []

    def mock_single(**kw):
        call_log.append("called")
        return _text_round("Done.")

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(),
    ))

    started = _events_of_type(events, SessionStarted)
    assert "agent-1" not in started[0].agents
    assert "agent-2" in started[0].agents
    # Only one agent called
    assert len(call_log) == 1


def test_tool_progress_emitted(tmp_path):
    """ToolCallProgress is emitted for each tool call."""
    tasks = _make_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    call_count = [0]

    def mock_single(**kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return _tool_round("Reading...", [
                {"name": "file_read", "input": {"path": "src/main.py"}, "id": "tc1"},
            ])
        return _text_round("Done.")

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(),
    ))

    progress = _events_of_type(events, ToolCallProgress)
    assert len(progress) >= 1
    assert progress[0].tool_name == "file_read"
    assert progress[0].path == "src/main.py"
    assert progress[0].agent == "agent-1"


def test_complete_tasks_persists_and_emits_layer_complete(tmp_path):
    """complete_tasks updates tasks.json and triggers LayerComplete."""
    tasks = _make_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    agent_calls = {"agent-1": 0, "agent-2": 0}

    def mock_single(**kw):
        # Determine which agent based on "Your name is X" in prompt
        msgs = kw.get("messages", [])
        system_text = msgs[0]["content"] if msgs else ""
        if "Your name is agent-1" in system_text:
            agent_calls["agent-1"] += 1
            if agent_calls["agent-1"] == 1:
                return _tool_round("Completing tasks.", [
                    {"name": "complete_tasks", "input": {
                        "task_ids": ["task-a"], "summary": "Implemented A",
                    }, "id": "tc1"},
                ])
            return _text_round("Task A done.")
        else:
            agent_calls["agent-2"] += 1
            if agent_calls["agent-2"] == 1:
                return _tool_round("Completing tasks.", [
                    {"name": "complete_tasks", "input": {
                        "task_ids": ["task-b"], "summary": "Implemented B",
                    }, "id": "tc2"},
                ])
            return _text_round("Task B done.")

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(),
    ))

    # Check LayerComplete emitted
    layer_done = _events_of_type(events, LayerComplete)
    assert len(layer_done) == 1
    assert layer_done[0].layer == 0
    assert set(layer_done[0].completed_tasks) == {"task-a", "task-b"}

    # Verify persistence
    saved = json.loads((iter_dir / "tasks.json").read_text())
    for t in saved:
        assert t["status"] == "done"


def test_complete_tasks_validation_rejects_wrong_agent(tmp_path):
    """complete_tasks rejects task IDs not assigned to the calling agent."""
    tasks = _make_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    call_count = [0]

    def mock_single(**kw):
        call_count[0] += 1
        if call_count[0] == 1:
            # agent-1 tries to complete agent-2's task
            return _tool_round("Completing wrong task.", [
                {"name": "complete_tasks", "input": {
                    "task_ids": ["task-b"], "summary": "Stole B",
                }, "id": "tc1"},
            ])
        return _text_round("Ok.")

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(),
    ))

    # The completion message should contain the error
    progress = _events_of_type(events, ToolCallProgress)
    ct_progress = [p for p in progress if p.tool_name == "complete_tasks"]
    assert len(ct_progress) >= 1
    assert ct_progress[0].status == "error"

    # task-b should still be pending
    saved = json.loads((iter_dir / "tasks.json").read_text())
    task_b = next(t for t in saved if t["id"] == "task-b")
    assert task_b["status"] == "pending"


def test_single_agent_layer(tmp_path):
    """Layer with only one agent works correctly."""
    tasks = [
        {
            "id": "task-a", "description": "Do A", "done_criteria": "A done",
            "depends_on": [], "assigned_to": "agent-1", "status": "pending",
            "layer": 0,
        },
    ]
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    call_count = [0]

    def mock_single(**kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return _tool_round("Done.", [
                {"name": "complete_tasks", "input": {
                    "task_ids": ["task-a"], "summary": "Did A",
                }, "id": "tc1"},
            ])
        return _text_round("All done.")

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(),
    ))

    layer_done = _events_of_type(events, LayerComplete)
    assert len(layer_done) == 1


def test_max_rounds_session_complete(tmp_path):
    """Agent that never calls complete_tasks hits max rounds → SessionComplete."""
    tasks = _make_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    def mock_single(**kw):
        # Always returns tool calls that aren't complete_tasks
        return _tool_round("Still working...", [
            {"name": "file_read", "input": {"path": "src/main.py"}, "id": "tc1"},
        ])

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(), max_tool_rounds=3,
    ))

    # Should end with SessionComplete (not LayerComplete)
    assert isinstance(events[-1], SessionComplete)


def test_all_tasks_done_immediate_layer_complete(tmp_path):
    """If all layer tasks are already done, immediate LayerComplete."""
    tasks = _make_tasks()
    for t in tasks:
        t["status"] = "done"
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=lambda **kw: _text_round("Should not be called"),
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(),
    ))

    # Should get SessionStarted then LayerComplete immediately
    started = _events_of_type(events, SessionStarted)
    assert len(started) == 1
    layer_done = _events_of_type(events, LayerComplete)
    assert len(layer_done) == 1
    assert set(layer_done[0].completed_tasks) == {"task-a", "task-b"}


def test_resume_reads_tasks_from_disk(tmp_path):
    """On resume, tasks.json state determines which agents run."""
    tasks = _make_tasks()
    tasks[0]["status"] = "done"  # agent-1 already finished
    tasks[0]["completed_by"] = "agent-1"
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    call_log = []

    def mock_single(**kw):
        call_log.append("called")
        return _tool_round("Done.", [
            {"name": "complete_tasks", "input": {
                "task_ids": ["task-b"], "summary": "Did B",
            }, "id": "tc1"},
        ])

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(),
    ))

    # Only agent-2 should have been called
    started = _events_of_type(events, SessionStarted)
    assert "agent-1" not in started[0].agents
    layer_done = _events_of_type(events, LayerComplete)
    assert len(layer_done) == 1


def test_tool_call_progress_metadata(tmp_path):
    """ToolCallProgress has correct metadata for file_write."""
    tasks = _make_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    call_count = [0]

    def mock_single(**kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return _tool_round("Writing...", [
                {"name": "file_write", "input": {
                    "path": "src/main.py", "content": "print('hello')",
                }, "id": "tc1"},
            ])
        return _text_round("Done.")

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(),
    ))

    progress = _events_of_type(events, ToolCallProgress)
    write_progress = [p for p in progress if p.tool_name == "file_write"]
    assert len(write_progress) >= 1
    p = write_progress[0]
    assert p.path == "src/main.py"
    assert p.bytes == len("print('hello')".encode())
    assert p.agent == "agent-1"


def test_auto_commit_worktrees_on_layer_complete(tmp_path):
    """Worktrees are auto-committed when LayerComplete is emitted."""
    from unittest.mock import patch, call
    tasks = _make_tasks()
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    wt_path_1 = tmp_path / "wt1"
    wt_path_2 = tmp_path / "wt2"

    call_count = {"agent-1": 0, "agent-2": 0}

    def mock_single(**kw):
        system_text = kw["messages"][0]["content"]
        if "Your name is agent-1" in system_text:
            agent = "agent-1"
            task_id = "task-a"
        else:
            agent = "agent-2"
            task_id = "task-b"

        call_count[agent] += 1
        if call_count[agent] == 1:
            return _tool_round("Done.", [
                {"name": "complete_tasks", "input": {
                    "task_ids": [task_id], "summary": f"Did {task_id}",
                }, "id": f"tc-{agent}"},
            ])
        return _text_round("Finished.")

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )
    policy = _make_policy(worktree_map={
        "agent-1": wt_path_1,
        "agent-2": wt_path_2,
    })

    with patch("gotg.worktree.is_worktree_dirty", return_value=True) as mock_dirty, \
         patch("gotg.worktree.commit_worktree") as mock_commit:
        events = _collect(run_implementation(
            AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
            deps, [], policy,
        ))

    layer_done = _events_of_type(events, LayerComplete)
    assert len(layer_done) == 1

    # Auto-commit should have been called for both worktrees
    assert mock_dirty.call_count == 2
    assert mock_commit.call_count == 2
    commit_paths = {c.args[0] for c in mock_commit.call_args_list}
    assert commit_paths == {wt_path_1, wt_path_2}


def test_report_blocked_emits_task_blocked_event(tmp_path):
    tasks = [
        {
            "id": "task-a", "description": "Do A", "done_criteria": "A done",
            "depends_on": [], "assigned_to": "agent-1", "status": "pending",
            "layer": 0,
        },
    ]
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    def mock_single(**kw):
        return _tool_round("Blocked.", [
            {"name": "report_blocked", "input": {
                "task_ids": ["task-a"], "reason": "Missing dependency output",
            }, "id": "tc1"},
        ])

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(),
    ))

    blocked = _events_of_type(events, TaskBlocked)
    assert len(blocked) == 1
    assert blocked[0].agent == "agent-1"
    assert blocked[0].task_ids == ("task-a",)
    assert "Missing dependency output" in blocked[0].reason
    assert isinstance(events[-1], SessionComplete)


def test_text_only_after_tool_gets_single_nudge_retry(tmp_path):
    tasks = [
        {
            "id": "task-a", "description": "Do A", "done_criteria": "A done",
            "depends_on": [], "assigned_to": "agent-1", "status": "pending",
            "layer": 0,
        },
    ]
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    call_count = [0]

    def mock_single(**kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return _tool_round("Looking.", [
                {"name": "file_read", "input": {"path": "src/main.py"}, "id": "tc1"},
            ])
        return _text_round("Still thinking.")

    deps = SessionDeps(
        agent_completion=None, coach_completion=None,
        single_completion=mock_single,
    )

    events = _collect(run_implementation(
        AGENTS, tasks, 0, ITERATION, iter_dir, MODEL_CONFIG,
        deps, [], _make_policy(), max_tool_rounds=12,
    ))

    assert call_count[0] == 3  # initial tool round + one retry + stop round
    assert isinstance(events[-1], SessionComplete)
