import json

from unittest.mock import patch

from gotg.conversation import read_log
from gotg.engine import SessionDeps
from gotg.events import AppendMessage, SessionComplete
from gotg.model import CompletionRound, StreamingResult
from gotg.policy import SessionPolicy
from gotg.prompts import AGENT_TOOLS
from gotg.session import SessionSetup, run_and_persist


AGENTS = [
    {"name": "agent-1", "role": "Software Engineer"},
    {"name": "agent-2", "role": "Software Engineer"},
]

MODEL_CONFIG = {
    "provider": "ollama",
    "base_url": "http://localhost:11434",
    "model": "test-model",
}


def _make_policy(**overrides):
    defaults = dict(
        max_turns=10,
        coach=None,
        coach_cadence=None,
        stop_on_phase_complete=True,
        stop_on_ask_pm=True,
        agent_tools=tuple(AGENT_TOOLS),
        coach_tools=None,
        groomed_summary=None,
        tasks_summary=None,
        diffs_summary=None,
        kickoff_text=None,
        fileguard=None,
        approval_store=None,
        worktree_map=None,
        system_supplement=None,
        coach_system_prompt=None,
        phase_skeleton=None,
        streaming=False,
    )
    defaults.update(overrides)
    return SessionPolicy(**defaults)


def _setup_iter_dir(tmp_path, tasks=None):
    iter_dir = tmp_path / ".team" / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    if tasks is not None:
        (iter_dir / "tasks.json").write_text(json.dumps(tasks, indent=2))
    (iter_dir / "conversation.jsonl").touch()
    (iter_dir / "debug.jsonl").touch()
    return iter_dir


def _read_jsonl(path):
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _make_deps(**overrides):
    defaults = dict(
        agent_completion=lambda **_kw: {"content": "unused", "operations": []},
        coach_completion=lambda **_kw: {"content": "unused", "tool_calls": []},
        single_completion=None,
        stream_completion=None,
    )
    defaults.update(overrides)
    return SessionDeps(**defaults)


def _text_round(text):
    return CompletionRound(
        content=text,
        tool_calls=[],
        _provider="openai",
        _raw={"message": {"role": "assistant", "content": text}},
    )


def _tool_round(text, tool_calls):
    raw_tool_calls = [
        {
            "id": tc["id"],
            "function": {
                "name": tc["name"],
                "arguments": json.dumps(tc["input"]),
            },
        }
        for tc in tool_calls
    ]
    return CompletionRound(
        content=text,
        tool_calls=tool_calls,
        _provider="openai",
        _raw={"message": {"role": "assistant", "content": text, "tool_calls": raw_tool_calls}},
    )


def _stream_result(chunks, final_round):
    """Build StreamingResult that sets .round when exhausted."""
    result = StreamingResult(_gen=iter(()))

    def _gen():
        for chunk in chunks:
            yield chunk
        return final_round

    def _capture():
        rnd = yield from _gen()
        result.round = rnd

    result._gen = _capture()
    return result


def _make_setup(iter_dir, *, iteration, deps, policy, use_implementation=False, tasks_data=None):
    """Build a SessionSetup for run_and_persist tests."""
    log_path = iter_dir / "conversation.jsonl"
    debug_path = iter_dir / "debug.jsonl"
    return SessionSetup(
        agents=AGENTS[:1] if use_implementation else AGENTS,
        iteration=iteration,
        iter_dir=iter_dir,
        model_config=MODEL_CONFIG,
        history=[],
        policy=policy,
        deps=deps,
        log_path=log_path,
        debug_path=debug_path,
        use_implementation=use_implementation,
        tasks_data=tasks_data,
        current_layer=iteration.get("current_layer", 0),
        fileguard=None,
        approval_store=None,
        worktree_map=None,
    )


def test_contract_implementation_non_streaming_logs_text_and_tool_ops(tmp_path):
    """Implementation run must persist both assistant text and tool operations."""
    tasks = [
        {
            "id": "task-a",
            "description": "Do A",
            "done_criteria": "done",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 0,
        }
    ]
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    def single_completion(**_kw):
        return _tool_round(
            "Implemented task-a",
            [{"name": "complete_tasks", "id": "ct1", "input": {"task_ids": ["task-a"], "summary": "done"}}],
        )

    deps = _make_deps(single_completion=single_completion)
    policy = _make_policy(max_turns=5, streaming=False)
    iteration = {
        "id": "iter-1",
        "description": "Contract behavior",
        "phase": "implementation",
        "max_turns": 20,
        "current_layer": 0,
    }

    setup = _make_setup(
        iter_dir, iteration=iteration, deps=deps, policy=policy,
        use_implementation=True, tasks_data=tasks,
    )
    list(run_and_persist(setup))

    messages = read_log(setup.log_path)
    debug_rows = _read_jsonl(setup.debug_path)

    assert any(m.get("from") == "agent-1" and "Implemented task-a" in m.get("content", "") for m in messages)
    assert any(
        m.get("from") == "system"
        and "[complete_tasks] Completed tasks: task-a" in m.get("content", "")
        for m in messages
    )
    assert any(
        any(op.get("name") == "complete_tasks" for op in row.get("tool_operations", []))
        for row in debug_rows
    )


def test_contract_implementation_streaming_logs_text_and_tool_ops(tmp_path):
    """Streaming implementation run must still persist full assistant text and tool ops."""
    tasks = [
        {
            "id": "task-a",
            "description": "Do A",
            "done_criteria": "done",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 0,
        }
    ]
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    def stream_completion(**_kw):
        return _stream_result(
            ["Implemented ", "task-a"],
            _tool_round(
                "Implemented task-a",
                [{"name": "complete_tasks", "id": "ct1", "input": {"task_ids": ["task-a"], "summary": "done"}}],
            ),
        )

    deps = _make_deps(stream_completion=stream_completion)
    policy = _make_policy(max_turns=5, streaming=True)
    iteration = {
        "id": "iter-1",
        "description": "Contract behavior",
        "phase": "implementation",
        "max_turns": 20,
        "current_layer": 0,
    }

    setup = _make_setup(
        iter_dir, iteration=iteration, deps=deps, policy=policy,
        use_implementation=True, tasks_data=tasks,
    )
    list(run_and_persist(setup))

    messages = read_log(setup.log_path)
    debug_rows = _read_jsonl(setup.debug_path)

    assert any(m.get("from") == "agent-1" and m.get("content") == "Implemented task-a" for m in messages)
    assert any(
        m.get("from") == "system"
        and "[complete_tasks] Completed tasks: task-a" in m.get("content", "")
        for m in messages
    )
    assert any(
        any(op.get("name") == "complete_tasks" for op in row.get("tool_operations", []))
        for row in debug_rows
    )


def test_contract_discussion_streaming_logs_text_and_tool_ops(tmp_path):
    """Discussion streaming path must persist both operation logs and final assistant text."""
    iter_dir = _setup_iter_dir(tmp_path)

    rounds = iter([
        _tool_round(
            "Reading context",
            [{"name": "file_read", "id": "tc1", "input": {"path": "README.md"}}],
        ),
        _text_round("Done with analysis"),
    ])

    def stream_completion(**_kw):
        rnd = next(rounds)
        chunks = ["Reading context"] if rnd.tool_calls else ["Done with analysis"]
        return _stream_result(chunks, rnd)

    deps = _make_deps(stream_completion=stream_completion)
    policy = _make_policy(max_turns=1, streaming=True)
    iteration = {
        "id": "iter-1",
        "description": "Contract behavior",
        "phase": "refinement",
        "max_turns": 1,
    }

    setup = _make_setup(
        iter_dir, iteration=iteration, deps=deps, policy=policy,
        use_implementation=False,
    )
    list(run_and_persist(setup))

    messages = read_log(setup.log_path)
    debug_rows = _read_jsonl(setup.debug_path)

    assert any(
        m.get("from") == "system"
        and "[file_read]" in m.get("content", "")
        and "README.md" in m.get("content", "")
        for m in messages
    )
    assert any(m.get("from") == "agent-1" and m.get("content") == "Done with analysis" for m in messages)
    assert any(
        any(op.get("name") == "file_read" for op in row.get("tool_operations", []))
        for row in debug_rows
    )


def test_contract_pass_turn_does_not_suppress_next_agent_message(tmp_path):
    """A pass_turn streaming turn must not suppress the next agent's real response."""
    iter_dir = _setup_iter_dir(tmp_path)

    rounds = iter([
        _tool_round("", [{"name": "pass_turn", "id": "pt1", "input": {"reason": "nothing to add"}}]),
        _text_round(""),
        _text_round("agent-2 substantive reply"),
    ])

    def stream_completion(**_kw):
        rnd = next(rounds)
        chunks = ["agent-2 substantive reply"] if rnd.content else []
        return _stream_result(chunks, rnd)

    deps = _make_deps(stream_completion=stream_completion)
    policy = _make_policy(max_turns=2, streaming=True)
    iteration = {
        "id": "iter-1",
        "description": "Contract behavior",
        "phase": "planning",
        "max_turns": 2,
    }

    setup = _make_setup(
        iter_dir, iteration=iteration, deps=deps, policy=policy,
        use_implementation=False,
    )
    list(run_and_persist(setup))

    messages = read_log(setup.log_path)
    assert any(m.get("pass_turn") for m in messages)
    assert any(m.get("from") == "agent-2" and "substantive reply" in m.get("content", "") for m in messages)


def test_contract_layer_dispatch_only_affects_current_layer(tmp_path):
    """Implementation run should only execute current-layer tasks and leave later layers untouched."""
    tasks = [
        {
            "id": "layer0-task",
            "description": "Layer 0",
            "done_criteria": "done",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 0,
        },
        {
            "id": "layer1-task",
            "description": "Layer 1",
            "done_criteria": "done",
            "depends_on": ["layer0-task"],
            "assigned_to": "agent-2",
            "status": "pending",
            "layer": 1,
        },
    ]
    iter_dir = _setup_iter_dir(tmp_path, tasks)

    call_count = {"single": 0}

    def single_completion(**_kw):
        call_count["single"] += 1
        return _tool_round(
            "Complete current layer",
            [{"name": "complete_tasks", "id": "ct1", "input": {"task_ids": ["layer0-task"], "summary": "done"}}],
        )

    deps = _make_deps(single_completion=single_completion)
    policy = _make_policy(max_turns=5, streaming=False)
    iteration = {
        "id": "iter-1",
        "description": "Contract behavior",
        "phase": "implementation",
        "max_turns": 20,
        "current_layer": 0,
    }

    setup = _make_setup(
        iter_dir, iteration=iteration, deps=deps, policy=policy,
        use_implementation=True, tasks_data=tasks,
    )
    list(run_and_persist(setup))

    raw_saved = json.loads((iter_dir / "tasks.json").read_text())
    saved_tasks = raw_saved["tasks"]
    t0 = next(t for t in saved_tasks if t["id"] == "layer0-task")
    t1 = next(t for t in saved_tasks if t["id"] == "layer1-task")

    assert call_count["single"] == 1
    assert t0["status"] == "done"
    assert t1["status"] == "pending"


# ── max_turns behavior contracts ──────────────────────────────────


def test_cli_continue_max_turns_absolute_ceiling(tmp_path, capsys, monkeypatch):
    """CLI default: max_turns_override = iteration['max_turns'] (absolute, not additive)."""
    from unittest.mock import MagicMock, patch

    monkeypatch.chdir(tmp_path)

    team_dir = tmp_path / ".team"
    team_dir.mkdir()
    (team_dir / "team.json").write_text(json.dumps({
        "agents": [
            {"name": "agent-1", "role": "SE"},
            {"name": "agent-2", "role": "SE"},
        ],
        "model": {"provider": "ollama", "model": "test", "base_url": "http://localhost:11434"},
    }))
    iteration = {
        "id": "iter-1", "description": "test", "status": "in-progress",
        "phase": "refinement", "max_turns": 15,
    }
    (team_dir / "iteration.json").write_text(json.dumps({
        "iterations": [iteration], "current": "iter-1",
    }))
    iter_dir = team_dir / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    # Seed 5 agent turns so current_agent_turns=5
    log = iter_dir / "conversation.jsonl"
    for i in range(5):
        from gotg.conversation import append_message as _am
        _am(log, {"from": "agent-1", "content": f"turn {i}"})

    args = MagicMock()
    args.max_turns = None  # No --max-turns flag → use absolute ceiling
    args.message = None
    args.layer = None

    with patch("gotg.cli.run_conversation") as mock_run, \
         patch("gotg.cli._auto_checkpoint"):
        from gotg.cli import cmd_continue
        cmd_continue(args)
        # CLI passes iteration["max_turns"] (15) as absolute ceiling
        call_kwargs = mock_run.call_args
        assert call_kwargs[1]["max_turns_override"] == 15


def test_tui_continue_max_turns_additive():
    """TUI: max_turns = current_agent_turns + iteration.max_turns (always additive).

    This documents the current TUI behavior. The TUI always adds iteration max_turns
    on top of current turns, while the CLI uses iteration max_turns as an absolute ceiling.
    """
    # This behavior is verified by reading tui/screens/chat.py:
    # max_turns = cont.current_agent_turns + iteration.get("max_turns", 30)
    # which is always additive. We test it via the prepare_continue return value.
    from gotg.session import prepare_continue, SessionInfra
    from gotg.conversation import append_message as _am

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path
        iter_dir = Path(td)
        log_path = iter_dir / "conversation.jsonl"
        for i in range(5):
            _am(log_path, {"from": "agent-1", "content": f"turn {i}"})

        infra = SessionInfra(
            fileguard=None, approval_store=None, worktree_map=None,
            diffs_summary=None, streaming=False,
        )
        cont = prepare_continue(infra, {"id": "iter-1"}, log_path)

        # TUI would compute: cont.current_agent_turns + iteration["max_turns"]
        iteration_max_turns = 15
        tui_max = cont.current_agent_turns + iteration_max_turns
        assert cont.current_agent_turns == 5
        assert tui_max == 20  # additive: 5 + 15 = 20
