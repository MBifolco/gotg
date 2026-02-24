import json

from gotg.cli import _run_discussion_phase, _run_implementation_phase
from gotg.conversation import read_log
from gotg.engine import SessionDeps
from gotg.model import CompletionRound, StreamingResult
from gotg.policy import SessionPolicy
from gotg.prompts import AGENT_TOOLS


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
    log_path = iter_dir / "conversation.jsonl"
    debug_path = iter_dir / "debug.jsonl"

    def single_completion(**_kw):
        return _tool_round(
            "Implemented task-a",
            [{"name": "complete_tasks", "id": "ct1", "input": {"task_ids": ["task-a"], "summary": "done"}}],
        )

    deps = SessionDeps(
        agent_completion=lambda **_kw: {"content": "unused", "operations": []},
        coach_completion=lambda **_kw: {"content": "unused", "tool_calls": []},
        single_completion=single_completion,
        stream_completion=None,
    )
    policy = _make_policy(max_turns=5, streaming=False)
    iteration = {
        "id": "iter-1",
        "description": "Contract behavior",
        "phase": "implementation",
        "max_turns": 20,
        "current_layer": 0,
    }

    _run_implementation_phase(
        [AGENTS[0]],
        iteration,
        iter_dir,
        MODEL_CONFIG,
        deps,
        history=[],
        policy=policy,
        log_path=log_path,
        debug_path=debug_path,
    )

    messages = read_log(log_path)
    debug_rows = _read_jsonl(debug_path)

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
    log_path = iter_dir / "conversation.jsonl"
    debug_path = iter_dir / "debug.jsonl"

    def stream_completion(**_kw):
        return _stream_result(
            ["Implemented ", "task-a"],
            _tool_round(
                "Implemented task-a",
                [{"name": "complete_tasks", "id": "ct1", "input": {"task_ids": ["task-a"], "summary": "done"}}],
            ),
        )

    deps = SessionDeps(
        agent_completion=lambda **_kw: {"content": "unused", "operations": []},
        coach_completion=lambda **_kw: {"content": "unused", "tool_calls": []},
        single_completion=lambda **_kw: _text_round("drift-check"),
        stream_completion=stream_completion,
    )
    policy = _make_policy(max_turns=5, streaming=True)
    iteration = {
        "id": "iter-1",
        "description": "Contract behavior",
        "phase": "implementation",
        "max_turns": 20,
        "current_layer": 0,
    }

    _run_implementation_phase(
        [AGENTS[0]],
        iteration,
        iter_dir,
        MODEL_CONFIG,
        deps,
        history=[],
        policy=policy,
        log_path=log_path,
        debug_path=debug_path,
    )

    messages = read_log(log_path)
    debug_rows = _read_jsonl(debug_path)

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
    log_path = iter_dir / "conversation.jsonl"
    debug_path = iter_dir / "debug.jsonl"

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

    deps = SessionDeps(
        agent_completion=lambda **_kw: {"content": "unused", "operations": []},
        coach_completion=lambda **_kw: {"content": "unused", "tool_calls": []},
        single_completion=None,
        stream_completion=stream_completion,
    )
    policy = _make_policy(max_turns=1, streaming=True)
    iteration = {
        "id": "iter-1",
        "description": "Contract behavior",
        "phase": "refinement",
        "max_turns": 1,
    }

    _run_discussion_phase(
        [AGENTS[0]],
        iteration,
        MODEL_CONFIG,
        deps,
        history=[],
        policy=policy,
        log_path=log_path,
        debug_path=debug_path,
    )

    messages = read_log(log_path)
    debug_rows = _read_jsonl(debug_path)

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
    log_path = iter_dir / "conversation.jsonl"
    debug_path = iter_dir / "debug.jsonl"

    rounds = iter([
        _tool_round("", [{"name": "pass_turn", "id": "pt1", "input": {"reason": "nothing to add"}}]),
        _text_round(""),
        _text_round("agent-2 substantive reply"),
    ])

    def stream_completion(**_kw):
        rnd = next(rounds)
        chunks = ["agent-2 substantive reply"] if rnd.content else []
        return _stream_result(chunks, rnd)

    deps = SessionDeps(
        agent_completion=lambda **_kw: {"content": "unused", "operations": []},
        coach_completion=lambda **_kw: {"content": "unused", "tool_calls": []},
        single_completion=None,
        stream_completion=stream_completion,
    )
    policy = _make_policy(max_turns=2, streaming=True)
    iteration = {
        "id": "iter-1",
        "description": "Contract behavior",
        "phase": "planning",
        "max_turns": 2,
    }

    _run_discussion_phase(
        AGENTS,
        iteration,
        MODEL_CONFIG,
        deps,
        history=[],
        policy=policy,
        log_path=log_path,
        debug_path=debug_path,
    )

    messages = read_log(log_path)
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
    log_path = iter_dir / "conversation.jsonl"
    debug_path = iter_dir / "debug.jsonl"

    call_count = {"single": 0}

    def single_completion(**_kw):
        call_count["single"] += 1
        return _tool_round(
            "Complete current layer",
            [{"name": "complete_tasks", "id": "ct1", "input": {"task_ids": ["layer0-task"], "summary": "done"}}],
        )

    deps = SessionDeps(
        agent_completion=lambda **_kw: {"content": "unused", "operations": []},
        coach_completion=lambda **_kw: {"content": "unused", "tool_calls": []},
        single_completion=single_completion,
        stream_completion=None,
    )
    policy = _make_policy(max_turns=5, streaming=False)
    iteration = {
        "id": "iter-1",
        "description": "Contract behavior",
        "phase": "implementation",
        "max_turns": 20,
        "current_layer": 0,
    }

    _run_implementation_phase(
        AGENTS,
        iteration,
        iter_dir,
        MODEL_CONFIG,
        deps,
        history=[],
        policy=policy,
        log_path=log_path,
        debug_path=debug_path,
    )

    saved_tasks = json.loads((iter_dir / "tasks.json").read_text())
    t0 = next(t for t in saved_tasks if t["id"] == "layer0-task")
    t1 = next(t for t in saved_tasks if t["id"] == "layer1-task")

    assert call_count["single"] == 1
    assert t0["status"] == "done"
    assert t1["status"] == "pending"
