"""Behavior-first integration tests for quality-gate coverage.

These tests intentionally exercise real engine/executor flows with deterministic
model stubs instead of injecting synthetic event streams.
"""

from __future__ import annotations

import json
import re

from gotg.approvals import ApprovalStore
from gotg.cli import run_conversation
from gotg.config import get_current_iteration
from gotg.conversation import read_log
from gotg.fileguard import FileGuard
from gotg.model import CompletionRound, StreamingResult
from gotg.session import apply_and_inject
from gotg.session import advance_next_layer, advance_phase


def _make_team(tmp_path, *, phase="refinement", current_layer=None, max_turns=1, streaming=False):
    team_dir = tmp_path / ".team"
    team_dir.mkdir()

    team = {
        "model": {
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "test-model",
        },
        "agents": [
            {"name": "agent-1", "role": "Software Engineer"},
            {"name": "agent-2", "role": "Software Engineer"},
        ],
        "coach": {"name": "coach", "role": "Agile Coach"},
        "streaming": streaming,
    }
    (team_dir / "team.json").write_text(json.dumps(team, indent=2))

    iteration = {
        "id": "iter-1",
        "title": "",
        "description": "Build a CLI calculator",
        "status": "in-progress",
        "phase": phase,
        "max_turns": max_turns,
    }
    if current_layer is not None:
        iteration["current_layer"] = current_layer

    (team_dir / "iteration.json").write_text(
        json.dumps({"iterations": [iteration], "current": "iter-1"}, indent=2) + "\n"
    )

    iter_dir = team_dir / "iterations" / "iter-1"
    iter_dir.mkdir(parents=True)
    (iter_dir / "conversation.jsonl").touch()
    (iter_dir / "debug.jsonl").touch()
    return team_dir, iter_dir


def _text_round(text: str) -> CompletionRound:
    return CompletionRound(
        content=text,
        tool_calls=[],
        _provider="openai",
        _raw={"message": {"role": "assistant", "content": text}},
    )


def _tool_round(text: str, tool_calls: list[dict]) -> CompletionRound:
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


def _stream_result(chunks: list[str], final_round: CompletionRound) -> StreamingResult:
    """Create a StreamingResult that captures .round on exhaustion."""
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


def _tasks_payload():
    return [
        {
            "id": "task-1",
            "description": "Build evaluator",
            "done_criteria": "works",
            "depends_on": [],
            "assigned_to": "agent-1",
            "approach": "Use eval() with restricted builtins.",
            "anti_patterns": ["Do not add extra features."],
        },
        {
            "id": "task-2",
            "description": "Build repl loop",
            "done_criteria": "works",
            "depends_on": [],
            "assigned_to": "agent-2",
            "approach": "Create main loop and exit handling.",
            "anti_patterns": ["Do not add history."],
        },
    ]


def _notes_payload():
    return [
        {"id": "task-1", "notes": "Create src/evaluator.py and tests."},
        {"id": "task-2", "notes": "Create main.py with placeholder for integration."},
    ]


def _chat_refinement_summary(**_kw):
    return "# Refinement Summary\n\nScope locked for calculator."


def _chat_tasks(**_kw):
    return json.dumps(_tasks_payload(), indent=2)


def _chat_notes(**_kw):
    return json.dumps(_notes_payload(), indent=2)


def _task_id_from_prompt(messages: list[dict], agent_name: str) -> str:
    """Extract first task id for the agent from implementation system prompt."""
    for msg in messages:
        if msg.get("role") != "system":
            continue
        content = msg.get("content", "")
        if f"You are {agent_name}" not in content:
            continue
        match = re.search(r"TASK 1 ID:\s*([^\n]+)", content)
        if match:
            return match.group(1).strip()
    return "unknown-task"


def test_e2e_iteration_lifecycle_refinement_to_code_review(tmp_path, monkeypatch):
    """Covers full phase progression with real run/advance flows."""
    team_dir, iter_dir = _make_team(tmp_path, phase="refinement", max_turns=1, streaming=False)
    model_config = json.loads((team_dir / "team.json").read_text())["model"]
    agents = json.loads((team_dir / "team.json").read_text())["agents"]

    # Discussion phases: deterministic one-message turns.
    monkeypatch.setattr(
        "gotg.cli.agentic_completion",
        lambda **_kw: {"content": "phase output", "operations": []},
    )
    monkeypatch.setattr(
        "gotg.cli.chat_completion",
        lambda **_kw: {"content": "coach output", "tool_calls": []},
    )

    # Implementation phase: complete assigned tasks in one tool round.
    def _raw_completion(**kw):
        tools = kw.get("tools") or []
        has_complete_tasks = any(t.get("name") == "complete_tasks" for t in tools)
        if not has_complete_tasks:
            # Drift-check path in implementation uses single_completion too.
            return _text_round("[]")

        messages = kw.get("messages", [])
        agent_name = "agent-1"
        for m in messages:
            if m.get("role") == "system":
                match = re.search(r"You are (agent-\d+)", m.get("content", ""))
                if match:
                    agent_name = match.group(1)
                    break
        task_id = _task_id_from_prompt(messages, agent_name)
        return _tool_round(
            f"Implemented {task_id}",
            [
                {
                    "name": "complete_tasks",
                    "id": "ct1",
                    "input": {"task_ids": [task_id], "summary": f"done by {agent_name}"},
                }
            ],
        )

    monkeypatch.setattr("gotg.cli.raw_completion", _raw_completion)

    # refinement -> run + advance
    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=False)
    advance_phase(team_dir, iteration, iter_dir, chat_call=_chat_refinement_summary)

    # planning -> run + advance
    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=False)
    advance_phase(team_dir, iteration, iter_dir, chat_call=_chat_tasks)

    # pre-code-review -> run + advance
    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=False)
    advance_phase(team_dir, iteration, iter_dir, chat_call=_chat_notes)

    # implementation -> run + advance to code-review
    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=False)
    advance_phase(team_dir, iteration, iter_dir, chat_call=lambda **_kw: "")

    # Assertions on lifecycle artifacts and final state
    iteration, _ = get_current_iteration(team_dir)
    messages = read_log(iter_dir / "conversation.jsonl")
    tasks = json.loads((iter_dir / "tasks.json").read_text())

    assert iteration["phase"] == "code-review"
    assert (iter_dir / "refinement_summary.md").exists()
    assert (iter_dir / "phase_skeleton.md").exists()
    assert any(m.get("phase_boundary") for m in messages)
    assert any("pre-code-review → implementation" in m.get("content", "") for m in messages)
    assert all(t.get("status") == "done" for t in tasks if t.get("layer") == 0)


def test_e2e_layer_progression_next_layer_contract(tmp_path, monkeypatch):
    """Covers implementation layer-0 run, next-layer advance, layer-1 run, and all-done."""
    team_dir, iter_dir = _make_team(
        tmp_path,
        phase="implementation",
        current_layer=0,
        max_turns=1,
        streaming=False,
    )
    model_config = json.loads((team_dir / "team.json").read_text())["model"]
    agents = json.loads((team_dir / "team.json").read_text())["agents"]

    tasks = [
        {
            "id": "layer0-a",
            "description": "L0 work",
            "done_criteria": "done",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 0,
        },
        {
            "id": "layer1-a",
            "description": "L1 work",
            "done_criteria": "done",
            "depends_on": ["layer0-a"],
            "assigned_to": "agent-2",
            "status": "pending",
            "layer": 1,
        },
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n")

    monkeypatch.setattr(
        "gotg.cli.agentic_completion",
        lambda **_kw: {"content": "unused", "operations": []},
    )
    monkeypatch.setattr(
        "gotg.cli.chat_completion",
        lambda **_kw: {"content": "unused", "tool_calls": []},
    )

    def _raw_completion(**kw):
        tools = kw.get("tools") or []
        has_complete_tasks = any(t.get("name") == "complete_tasks" for t in tools)
        if not has_complete_tasks:
            return _text_round("[]")
        messages = kw.get("messages", [])
        agent_name = "agent-1"
        for m in messages:
            if m.get("role") == "system":
                match = re.search(r"You are (agent-\d+)", m.get("content", ""))
                if match:
                    agent_name = match.group(1)
                    break
        task_id = _task_id_from_prompt(messages, agent_name)
        return _tool_round(
            f"impl {task_id}",
            [{"name": "complete_tasks", "id": "ct1", "input": {"task_ids": [task_id], "summary": "done"}}],
        )

    monkeypatch.setattr("gotg.cli.raw_completion", _raw_completion)

    # Run implementation on layer 0.
    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=False)

    # Advance to next layer and verify state.
    result = advance_next_layer(team_dir, iteration, iter_dir)
    assert result.all_done is False
    assert result.to_layer == 1

    iteration, _ = get_current_iteration(team_dir)
    assert iteration["phase"] == "implementation"
    assert iteration["current_layer"] == 1

    # Run implementation on layer 1.
    run_conversation(iter_dir, agents, iteration, model_config, streaming=False)

    # No further layers should remain.
    result = advance_next_layer(team_dir, iteration, iter_dir)
    assert result.all_done is True
    assert result.to_layer is None

    saved_tasks = json.loads((iter_dir / "tasks.json").read_text())
    assert all(t.get("status") == "done" for t in saved_tasks)
    assert any(m.get("phase_boundary") and m.get("layer") == 1 for m in read_log(iter_dir / "conversation.jsonl"))


def test_e2e_streaming_parity_discussion_and_implementation(tmp_path, monkeypatch):
    """Streaming output should be persisted with same final content as non-streaming logs."""
    team_dir, iter_dir = _make_team(tmp_path, phase="refinement", max_turns=1, streaming=True)
    model_config = json.loads((team_dir / "team.json").read_text())["model"]
    agents = json.loads((team_dir / "team.json").read_text())["agents"]

    # Discussion non-streaming fallback should not be used in this test.
    monkeypatch.setattr(
        "gotg.cli.agentic_completion",
        lambda **_kw: {"content": "fallback-discussion", "operations": []},
    )
    monkeypatch.setattr(
        "gotg.cli.chat_completion",
        lambda **_kw: {"content": "fallback-coach", "tool_calls": []},
    )
    monkeypatch.setattr("gotg.cli.raw_completion", lambda **_kw: _text_round("[]"))

    def _raw_stream(**kw):
        tools = kw.get("tools") or []
        has_complete_tasks = any(t.get("name") == "complete_tasks" for t in tools)
        if has_complete_tasks:
            return _stream_result(
                ["Implementing ", "task"],
                _tool_round(
                    "Implementing task",
                    [
                        {
                            "name": "complete_tasks",
                            "id": "ct1",
                            "input": {"task_ids": ["stream-task"], "summary": "done"},
                        }
                    ],
                ),
            )
        return _stream_result(["Hello ", "streaming"], _text_round("Hello streaming"))

    monkeypatch.setattr("gotg.cli.raw_completion_stream", _raw_stream)

    # Discussion streaming run.
    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=True)

    # Move to implementation directly for parity check.
    from gotg.config import save_iteration_fields

    save_iteration_fields(team_dir, "iter-1", phase="implementation", current_layer=0)
    (iter_dir / "tasks.json").write_text(
        json.dumps(
            [
                {
                    "id": "stream-task",
                    "description": "Streaming impl",
                    "done_criteria": "done",
                    "depends_on": [],
                    "assigned_to": "agent-1",
                    "status": "pending",
                    "layer": 0,
                }
            ],
            indent=2,
        )
        + "\n"
    )

    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=True)

    messages = read_log(iter_dir / "conversation.jsonl")
    debug_rows = [
        json.loads(line)
        for line in (iter_dir / "debug.jsonl").read_text().splitlines()
        if line.strip()
    ]

    assert any(m.get("from") == "agent-1" and m.get("content") == "Hello streaming" for m in messages)
    assert any(m.get("from") == "agent-1" and m.get("content") == "Implementing task" for m in messages)
    assert any("[complete_tasks] Completed tasks: stream-task" in m.get("content", "") for m in messages)
    assert any(
        any(op.get("name") == "complete_tasks" for op in row.get("tool_operations", []))
        for row in debug_rows
    )


def test_e2e_approval_pause_resume_implementation(tmp_path, monkeypatch):
    """Implementation should pause for approvals, then resume and complete after approval."""
    team_dir, iter_dir = _make_team(
        tmp_path,
        phase="implementation",
        current_layer=0,
        max_turns=4,
        streaming=False,
    )
    model_config = json.loads((team_dir / "team.json").read_text())["model"]
    agents = json.loads((team_dir / "team.json").read_text())["agents"]

    tasks = [
        {
            "id": "approval-task",
            "description": "Write root file with approval and then complete",
            "done_criteria": "done",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 0,
        }
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n")

    # Writable only under src/** so writing main.py requires approval.
    fileguard = FileGuard(
        tmp_path,
        {
            "writable_paths": ["src/**"],
            "max_file_size_bytes": 1_048_576,
            "max_files_per_turn": 10,
            "enable_approvals": True,
        },
    )
    approval_store = ApprovalStore(iter_dir / "approvals.json")

    monkeypatch.setattr("gotg.cli.agentic_completion", lambda **_kw: {"content": "unused", "operations": []})
    monkeypatch.setattr("gotg.cli.chat_completion", lambda **_kw: {"content": "unused", "tool_calls": []})

    state = {"first_run_done": False}

    def _raw_completion(**kw):
        tools = kw.get("tools") or []
        has_complete_tasks = any(t.get("name") == "complete_tasks" for t in tools)
        if not has_complete_tasks:
            # Drift-check and other internal one-shot calls.
            return _text_round("[]")

        if not state["first_run_done"]:
            state["first_run_done"] = True
            return _tool_round(
                "Writing file that requires approval",
                [
                    {
                        "name": "file_write",
                        "id": "fw1",
                        "input": {"path": "main.py", "content": "print('approved write')\n"},
                    }
                ],
            )

        return _tool_round(
            "Completing task",
            [
                {
                    "name": "complete_tasks",
                    "id": "ct1",
                    "input": {"task_ids": ["approval-task"], "summary": "write approved and task complete"},
                }
            ],
        )

    monkeypatch.setattr("gotg.cli.raw_completion", _raw_completion)

    iteration, _ = get_current_iteration(team_dir)

    # First run should pause on pending approval.
    run_conversation(
        iter_dir,
        agents,
        iteration,
        model_config,
        fileguard=fileguard,
        approval_store=approval_store,
        streaming=False,
    )

    pending = approval_store.get_pending()
    assert len(pending) == 1
    assert pending[0]["path"] == "main.py"

    # Approve and apply write (mirrors continue path).
    approval_store.approve("a1")
    applied_msgs = apply_and_inject(
        approval_store,
        fileguard,
        iteration,
        iter_dir / "conversation.jsonl",
    )
    assert any("APPROVED" in m["content"] for m in applied_msgs)
    assert (tmp_path / "main.py").exists()

    # Second run should complete task.
    run_conversation(
        iter_dir,
        agents,
        iteration,
        model_config,
        fileguard=fileguard,
        approval_store=approval_store,
        streaming=False,
    )

    saved_tasks = json.loads((iter_dir / "tasks.json").read_text())
    assert next(t for t in saved_tasks if t["id"] == "approval-task")["status"] == "done"
    messages = read_log(iter_dir / "conversation.jsonl")
    assert any("[file_write] PENDING APPROVAL: main.py" in m.get("content", "") for m in messages)
    assert any("[file_write] APPROVED: Written: main.py" in m.get("content", "") for m in messages)
    assert any("[complete_tasks] Completed tasks: approval-task" in m.get("content", "") for m in messages)


def test_e2e_implementation_state_resume_contract(tmp_path, monkeypatch):
    """Implementation pause/resume should persist and consume implementation_state.json."""
    team_dir, iter_dir = _make_team(
        tmp_path,
        phase="implementation",
        current_layer=0,
        max_turns=4,
        streaming=False,
    )
    model_config = json.loads((team_dir / "team.json").read_text())["model"]
    agents = json.loads((team_dir / "team.json").read_text())["agents"]

    tasks = [
        {
            "id": "resume-task",
            "description": "Write root file with approval, then complete on resume",
            "done_criteria": "done",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 0,
        }
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n")

    # Writable only under src/** so writing main.py requires approval.
    fileguard = FileGuard(
        tmp_path,
        {
            "writable_paths": ["src/**"],
            "max_file_size_bytes": 1_048_576,
            "max_files_per_turn": 10,
            "enable_approvals": True,
        },
    )
    approval_store = ApprovalStore(iter_dir / "approvals.json")

    monkeypatch.setattr("gotg.cli.agentic_completion", lambda **_kw: {"content": "unused", "operations": []})
    monkeypatch.setattr("gotg.cli.chat_completion", lambda **_kw: {"content": "unused", "tool_calls": []})

    state = {"saw_resume_continuation": False}

    def _raw_completion(**kw):
        tools = kw.get("tools") or []
        has_complete_tasks = any(t.get("name") == "complete_tasks" for t in tools)
        if not has_complete_tasks:
            return _text_round("[]")

        messages = kw.get("messages", [])
        saw_tool_continuation = any(
            m.get("role") == "tool" and "Pending approval" in str(m.get("content", ""))
            for m in messages
        )
        if saw_tool_continuation:
            state["saw_resume_continuation"] = True
            return _tool_round(
                "Resuming after approval pause.",
                [
                    {
                        "name": "complete_tasks",
                        "id": "ct1",
                        "input": {"task_ids": ["resume-task"], "summary": "completed after resume"},
                    }
                ],
            )

        return _tool_round(
            "Writing file that requires approval.",
            [
                {
                    "name": "file_write",
                    "id": "fw1",
                    "input": {"path": "main.py", "content": "print('resume')\n"},
                }
            ],
        )

    monkeypatch.setattr("gotg.cli.raw_completion", _raw_completion)

    iteration, _ = get_current_iteration(team_dir)

    # First run should pause and persist implementation_state.json.
    run_conversation(
        iter_dir,
        agents,
        iteration,
        model_config,
        fileguard=fileguard,
        approval_store=approval_store,
        streaming=False,
    )

    state_path = iter_dir / "implementation_state.json"
    assert state_path.exists()
    saved_state = json.loads(state_path.read_text())
    assert saved_state.get("layer") == 0
    assert saved_state.get("agent_name") == "agent-1"
    assert isinstance(saved_state.get("llm_messages"), list)
    assert saved_state.get("round_num", 0) >= 1

    pending = approval_store.get_pending()
    assert len(pending) == 1
    assert pending[0]["path"] == "main.py"

    # Approve and apply write.
    approval_store.approve("a1")
    apply_and_inject(
        approval_store,
        fileguard,
        iteration,
        iter_dir / "conversation.jsonl",
    )

    # Second run should resume from saved continuation and complete the task.
    run_conversation(
        iter_dir,
        agents,
        iteration,
        model_config,
        fileguard=fileguard,
        approval_store=approval_store,
        streaming=False,
    )

    assert state["saw_resume_continuation"] is True
    assert not state_path.exists()
    saved_tasks = json.loads((iter_dir / "tasks.json").read_text())
    assert next(t for t in saved_tasks if t["id"] == "resume-task")["status"] == "done"


def test_e2e_drift_check_reverts_completion_on_must_not_violation(tmp_path, monkeypatch):
    """Drift-check contract: MUST NOT violations revert done -> pending and emit diagnostics."""
    team_dir, iter_dir = _make_team(
        tmp_path,
        phase="implementation",
        current_layer=0,
        max_turns=1,
        streaming=False,
    )
    model_config = json.loads((team_dir / "team.json").read_text())["model"]
    agents = json.loads((team_dir / "team.json").read_text())["agents"]

    tasks = [
        {
            "id": "drift-task",
            "description": "Implement evaluator without eval",
            "done_criteria": "Evaluator works for arithmetic",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 0,
            "approach": "Use ast.parse and whitelist nodes.",
            "anti_patterns": ["Do not use eval()"],
        }
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n")

    monkeypatch.setattr("gotg.cli.agentic_completion", lambda **_kw: {"content": "unused", "operations": []})
    monkeypatch.setattr("gotg.cli.chat_completion", lambda **_kw: {"content": "unused", "tool_calls": []})

    def _raw_completion(**kw):
        tools = kw.get("tools") or []
        has_complete_tasks = any(t.get("name") == "complete_tasks" for t in tools)
        if has_complete_tasks:
            return _tool_round(
                "Implemented and completing.",
                [
                    {
                        "name": "file_write",
                        "id": "fw1",
                        "input": {
                            "path": "src/evaluator.py",
                            "content": "def evaluate(expr):\n    return eval(expr)\n",
                        },
                    },
                    {
                        "name": "complete_tasks",
                        "id": "ct1",
                        "input": {"task_ids": ["drift-task"], "summary": "done"},
                    },
                ],
            )

        # Drift-check call (no tools): return strict verifier output with MUST NOT violation.
        return _text_round(
            json.dumps(
                [
                    {
                        "task_id": "drift-task",
                        "approach_ok": False,
                        "anti_pattern_violations": ["Do not use eval()"],
                        "done_criteria_ok": True,
                        "notes": "Used eval() despite explicit prohibition.",
                    }
                ]
            )
        )

    monkeypatch.setattr("gotg.cli.raw_completion", _raw_completion)

    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=False)

    saved_tasks = json.loads((iter_dir / "tasks.json").read_text())
    messages = read_log(iter_dir / "conversation.jsonl")
    debug_rows = [
        json.loads(line)
        for line in (iter_dir / "debug.jsonl").read_text().splitlines()
        if line.strip()
    ]

    task = next(t for t in saved_tasks if t["id"] == "drift-task")
    assert task["status"] == "pending"
    assert "completed_by" not in task
    assert "completion_summary" not in task
    assert any("[drift-check] task drift-task: MUST NOT violated" in m.get("content", "") for m in messages)
    assert any("Drift detected — completion reverted" in m.get("content", "") for m in messages)
    assert any(
        any(
            op.get("name") == "complete_tasks"
            for op in row.get("tool_operations", [])
        )
        for row in debug_rows
    )


def test_replay_streamed_text_only_round_is_persisted_for_traceability(tmp_path, monkeypatch):
    """Replay guard: streamed assistant text should be persisted even when no tools are called.

    This captures the incident pattern where UI showed agent text but logs captured only tool ops.
    """
    team_dir, iter_dir = _make_team(
        tmp_path,
        phase="implementation",
        current_layer=0,
        max_turns=2,
        streaming=True,
    )
    model_config = json.loads((team_dir / "team.json").read_text())["model"]
    agents = json.loads((team_dir / "team.json").read_text())["agents"]

    tasks = [
        {
            "id": "trace-task",
            "description": "No-op text round before completion",
            "done_criteria": "done",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 0,
        }
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n")

    monkeypatch.setattr("gotg.cli.agentic_completion", lambda **_kw: {"content": "unused", "operations": []})
    monkeypatch.setattr("gotg.cli.chat_completion", lambda **_kw: {"content": "unused", "tool_calls": []})
    monkeypatch.setattr("gotg.cli.raw_completion", lambda **_kw: _text_round("[]"))

    state = {"calls": 0}

    def _raw_stream(**kw):
        tools = kw.get("tools") or []
        has_complete_tasks = any(t.get("name") == "complete_tasks" for t in tools)
        if not has_complete_tasks:
            return _stream_result(["[]"], _text_round("[]"))
        state["calls"] += 1
        if state["calls"] == 1:
            # Text-only streamed round (no tools) while task is still pending.
            return _stream_result(["I ", "am ", "about ", "to ", "work"], _text_round("I am about to work"))
        # Follow-up completion round.
        return _stream_result(
            ["Done"],
            _tool_round(
                "Done",
                [{"name": "complete_tasks", "id": "ct1", "input": {"task_ids": ["trace-task"], "summary": "done"}}],
            ),
        )

    monkeypatch.setattr("gotg.cli.raw_completion_stream", _raw_stream)

    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=True)

    messages = read_log(iter_dir / "conversation.jsonl")
    # Expected traceability contract: if text was streamed to the UI, it should be in conversation log.
    assert any(m.get("from") == "agent-1" and m.get("content") == "I am about to work" for m in messages)


def test_replay_test9_attestation_payload_mismatch_does_not_block_completion(tmp_path, monkeypatch):
    """Replay guard from test9: mismatched approach_attestation must not deadlock completion."""
    team_dir, iter_dir = _make_team(
        tmp_path,
        phase="implementation",
        current_layer=0,
        max_turns=2,
        streaming=False,
    )
    model_config = json.loads((team_dir / "team.json").read_text())["model"]
    agents = json.loads((team_dir / "team.json").read_text())["agents"]

    tasks = [
        {
            "id": "project-setup-repl",
            "description": "Create REPL skeleton",
            "done_criteria": "loop runs and exits cleanly",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 0,
            "approach": "Build a loop that reads input and handles exit commands.",
        }
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n")

    monkeypatch.setattr("gotg.cli.agentic_completion", lambda **_kw: {"content": "unused", "operations": []})
    monkeypatch.setattr("gotg.cli.chat_completion", lambda **_kw: {"content": "unused", "tool_calls": []})

    state = {"completion_calls": 0}

    def _raw_completion(**kw):
        tools = kw.get("tools") or []
        has_complete_tasks = any(t.get("name") == "complete_tasks" for t in tools)
        if not has_complete_tasks:
            return _text_round("[]")

        state["completion_calls"] += 1
        return _tool_round(
            "Implementation complete.",
            [
                {
                    "name": "complete_tasks",
                    "id": "ct1",
                    "input": {
                        "task_ids": ["project-setup-repl"],
                        "summary": "Implemented loop and tests",
                        # Intentionally different from tasks[0]["approach"].
                        "approach_attestation": [
                            {
                                "task_id": "project-setup-repl",
                                "followed_approach": True,
                                "agreed_approach": "Different attestation text",
                                "notes": "Replay strict matcher regression",
                            }
                        ],
                    },
                }
            ],
        )

    monkeypatch.setattr("gotg.cli.raw_completion", _raw_completion)

    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=False)

    saved_tasks = json.loads((iter_dir / "tasks.json").read_text())
    messages = read_log(iter_dir / "conversation.jsonl")

    task = next(t for t in saved_tasks if t["id"] == "project-setup-repl")
    assert state["completion_calls"] == 1
    assert task["status"] == "done"
    assert any("[complete_tasks] Completed tasks: project-setup-repl" in m.get("content", "") for m in messages)
    assert not any("approach attestation mismatch" in m.get("content", "") for m in messages)
    assert not any("[report_blocked]" in m.get("content", "") for m in messages)


def test_replay_test10_file_writes_do_not_complete_task_until_complete_tasks(tmp_path, monkeypatch):
    """Replay guard from test10: file activity alone must not mark implementation task done."""
    team_dir, iter_dir = _make_team(
        tmp_path,
        phase="implementation",
        current_layer=0,
        max_turns=4,
        streaming=False,
    )
    model_config = json.loads((team_dir / "team.json").read_text())["model"]
    agents = json.loads((team_dir / "team.json").read_text())["agents"]

    tasks = [
        {
            "id": "integration-testing",
            "description": "Validate integrated behavior",
            "done_criteria": "validation completed",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 0,
        }
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n")

    monkeypatch.setattr("gotg.cli.agentic_completion", lambda **_kw: {"content": "unused", "operations": []})
    monkeypatch.setattr("gotg.cli.chat_completion", lambda **_kw: {"content": "unused", "tool_calls": []})

    state = {"round": 0}

    def _raw_completion(**kw):
        tools = kw.get("tools") or []
        has_complete_tasks = any(t.get("name") == "complete_tasks" for t in tools)
        if not has_complete_tasks:
            return _text_round("[]")

        state["round"] += 1
        if state["round"] == 1:
            return _tool_round(
                "Writing validation artifacts.",
                [
                    {
                        "name": "file_write",
                        "id": "fw1",
                        "input": {"path": "docs/VALIDATION_REPORT.md", "content": "validation details\n"},
                    }
                ],
            )
        return _tool_round(
            "Validation done.",
            [
                {
                    "name": "complete_tasks",
                    "id": "ct1",
                    "input": {"task_ids": ["integration-testing"], "summary": "validated scenarios"},
                }
            ],
        )

    monkeypatch.setattr("gotg.cli.raw_completion", _raw_completion)

    iteration, _ = get_current_iteration(team_dir)
    run_conversation(iter_dir, agents, iteration, model_config, streaming=False)

    saved_tasks = json.loads((iter_dir / "tasks.json").read_text())
    messages = read_log(iter_dir / "conversation.jsonl")
    debug_rows = [
        json.loads(line)
        for line in (iter_dir / "debug.jsonl").read_text().splitlines()
        if line.strip()
    ]

    task = next(t for t in saved_tasks if t["id"] == "integration-testing")
    assert task["status"] == "done"
    assert any(
        "[file_write]" in m.get("content", "") and "docs/VALIDATION_REPORT.md" in m.get("content", "")
        for m in messages
    )
    assert any("[complete_tasks] Completed tasks: integration-testing" in m.get("content", "") for m in messages)
    assert any(
        any(op.get("name") == "file_write" for op in row.get("tool_operations", []))
        for row in debug_rows
    )
    assert any(
        any(op.get("name") == "complete_tasks" for op in row.get("tool_operations", []))
        for row in debug_rows
    )


def test_replay_test16_next_layer_boundary_uses_implementation_phase(tmp_path):
    """Replay guard from test16: implementation layer-advance boundary should stay in implementation phase."""
    team_dir, iter_dir = _make_team(
        tmp_path,
        phase="implementation",
        current_layer=0,
        max_turns=1,
        streaming=False,
    )

    tasks = [
        {
            "id": "layer0-task",
            "description": "Layer 0 complete",
            "done_criteria": "done",
            "depends_on": [],
            "assigned_to": "agent-1",
            "status": "done",
            "layer": 0,
        },
        {
            "id": "layer1-task",
            "description": "Layer 1 pending",
            "done_criteria": "done",
            "depends_on": ["layer0-task"],
            "assigned_to": "agent-1",
            "status": "pending",
            "layer": 1,
        },
    ]
    (iter_dir / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n")

    iteration, _ = get_current_iteration(team_dir)
    result = advance_next_layer(team_dir, iteration, iter_dir)
    assert result.all_done is False
    assert result.to_layer == 1

    messages = read_log(iter_dir / "conversation.jsonl")
    layer_boundary = next(m for m in messages if m.get("phase_boundary") and m.get("layer") == 1)

    # Contract: moving between implementation layers should log implementation→implementation.
    assert layer_boundary.get("from_phase") == "implementation"
    assert layer_boundary.get("to_phase") == "implementation"
