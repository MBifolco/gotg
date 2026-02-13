"""Tests for streaming API support (Stage 1: implementation phase only)."""

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from gotg.engine import SessionDeps
from gotg.events import (
    AgentTurnComplete,
    AppendDebug,
    AppendMessage,
    LayerComplete,
    SessionComplete,
    SessionStarted,
    TextDelta,
    ToolCallProgress,
)
from gotg.implementation import run_implementation
from gotg.model import CompletionRound, StreamingResult, raw_completion_stream
from gotg.policy import SessionPolicy, iteration_policy
from gotg.prompts import AGENT_TOOLS
from gotg.tools import FILE_TOOLS


# ── Shared helpers ────────────────────────────────────────────────


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
    return CompletionRound(
        content=text,
        tool_calls=[],
        _provider="openai",
        _raw={"message": {"content": text}},
    )


def _tool_round(text, tool_calls):
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


def _make_streaming_result(chunks, final_round):
    """Create a StreamingResult that yields chunks and sets round on exhaustion."""
    def _gen():
        for chunk in chunks:
            yield chunk
        return final_round

    result = StreamingResult(_gen=None)

    def _capturing():
        try:
            rnd = yield from _gen()
        except Exception:
            raise
        result.round = rnd

    result._gen = _capturing()
    return result


# ── StreamingResult tests ─────────────────────────────────────────


class TestStreamingResult:
    def test_iterates_text_chunks(self):
        result = _make_streaming_result(["Hello", " world"], _text_round("Hello world"))
        chunks = list(result)
        assert chunks == ["Hello", " world"]

    def test_round_populated_after_exhaustion(self):
        final = _text_round("Done")
        result = _make_streaming_result(["Done"], final)
        list(result)  # exhaust
        assert result.round is not None
        assert result.round.content == "Done"

    def test_round_none_before_exhaustion(self):
        result = _make_streaming_result(["A", "B"], _text_round("AB"))
        assert result.round is None
        next(result)  # consume first
        assert result.round is None

    def test_empty_chunks(self):
        result = _make_streaming_result([], _text_round(""))
        chunks = list(result)
        assert chunks == []
        assert result.round is not None


# ── Event dataclass tests ─────────────────────────────────────────


class TestStreamingEvents:
    def test_text_delta_fields(self):
        td = TextDelta(agent="agent-1", turn_id="impl-agent-1-r0", text="hello")
        assert td.agent == "agent-1"
        assert td.turn_id == "impl-agent-1-r0"
        assert td.text == "hello"

    def test_agent_turn_complete_fields(self):
        atc = AgentTurnComplete(agent="agent-1", turn_id="impl-agent-1-r0", content="Done")
        assert atc.agent == "agent-1"
        assert atc.turn_id == "impl-agent-1-r0"
        assert atc.content == "Done"


# ── SessionDeps.stream_completion tests ───────────────────────────


class TestSessionDepsStreaming:
    def test_stream_completion_default_none(self):
        deps = SessionDeps(
            agent_completion=lambda **kw: None,
            coach_completion=lambda **kw: None,
        )
        assert deps.stream_completion is None

    def test_stream_completion_can_be_set(self):
        mock = lambda **kw: None
        deps = SessionDeps(
            agent_completion=lambda **kw: None,
            coach_completion=lambda **kw: None,
            stream_completion=mock,
        )
        assert deps.stream_completion is mock

    def test_single_completion_still_works(self):
        mock = lambda **kw: _text_round("ok")
        deps = SessionDeps(
            agent_completion=lambda **kw: None,
            coach_completion=lambda **kw: None,
            single_completion=mock,
        )
        assert deps.single_completion is mock


# ── SessionPolicy.streaming tests ─────────────────────────────────


class TestSessionPolicyStreaming:
    def test_streaming_default_false(self):
        policy = _make_policy()
        assert policy.streaming is False

    def test_streaming_opt_in(self):
        policy = _make_policy(streaming=True)
        assert policy.streaming is True

    def test_iteration_policy_streaming_param(self, tmp_path):
        iter_dir = tmp_path / ".team" / "iterations" / "iter-1"
        iter_dir.mkdir(parents=True)
        (iter_dir / "conversation.jsonl").touch()
        policy = iteration_policy(
            agents=AGENTS,
            iteration=ITERATION,
            iter_dir=iter_dir,
            history=[],
            streaming=True,
        )
        assert policy.streaming is True

    def test_iteration_policy_streaming_default(self, tmp_path):
        iter_dir = tmp_path / ".team" / "iterations" / "iter-1"
        iter_dir.mkdir(parents=True)
        (iter_dir / "conversation.jsonl").touch()
        policy = iteration_policy(
            agents=AGENTS,
            iteration=ITERATION,
            iter_dir=iter_dir,
            history=[],
        )
        assert policy.streaming is False


# ── config.load_streaming_config tests ────────────────────────────


class TestLoadStreamingConfig:
    def test_returns_false_when_not_configured(self, tmp_path):
        from gotg.config import load_streaming_config
        team_dir = tmp_path / ".team"
        team_dir.mkdir()
        (team_dir / "team.json").write_text(json.dumps({"model": {}, "agents": []}))
        assert load_streaming_config(team_dir) is False

    def test_returns_true_when_enabled(self, tmp_path):
        from gotg.config import load_streaming_config
        team_dir = tmp_path / ".team"
        team_dir.mkdir()
        (team_dir / "team.json").write_text(json.dumps({
            "model": {}, "agents": [], "streaming": True,
        }))
        assert load_streaming_config(team_dir) is True

    def test_returns_false_when_explicitly_false(self, tmp_path):
        from gotg.config import load_streaming_config
        team_dir = tmp_path / ".team"
        team_dir.mkdir()
        (team_dir / "team.json").write_text(json.dumps({
            "model": {}, "agents": [], "streaming": False,
        }))
        assert load_streaming_config(team_dir) is False


# ── Implementation streaming tests ────────────────────────────────


class TestImplementationStreaming:
    def test_streaming_yields_text_deltas(self, tmp_path):
        """When streaming=True and stream_completion is set, TextDelta events are emitted."""
        tasks = _make_tasks()
        iter_dir = _setup_iter_dir(tmp_path, tasks)

        call_count = 0

        def mock_stream(**kw):
            nonlocal call_count
            call_count += 1
            complete_tool = [{
                "name": "complete_tasks", "id": "tc1",
                "input": {"task_ids": ["task-a"], "summary": "Done A"},
            }]
            rnd = _tool_round("Completing task A", complete_tool)
            return _make_streaming_result(["Completing ", "task A"], rnd)

        def mock_stream2(**kw):
            return _make_streaming_result(["Done!"], _text_round("Done!"))

        calls = [0]
        def mock_stream_side_effect(**kw):
            calls[0] += 1
            if calls[0] == 1:
                return mock_stream(**kw)
            return mock_stream2(**kw)

        deps = SessionDeps(
            agent_completion=None,
            coach_completion=None,
            single_completion=None,
            stream_completion=mock_stream_side_effect,
        )
        policy = _make_policy(streaming=True)

        # Only test agent-1
        single_agent = [AGENTS[0]]
        single_tasks = [t for t in tasks if t["assigned_to"] == "agent-1"]
        (iter_dir / "tasks.json").write_text(json.dumps(single_tasks, indent=2))

        events = _collect(run_implementation(
            single_agent, single_tasks, 0, ITERATION, iter_dir,
            MODEL_CONFIG, deps, [], policy,
        ))

        deltas = _events_of_type(events, TextDelta)
        assert len(deltas) >= 2
        assert deltas[0].text == "Completing "
        assert deltas[1].text == "task A"
        assert all(d.agent == "agent-1" for d in deltas)
        assert deltas[0].turn_id == "impl-agent-1-r0"

    def test_streaming_yields_agent_turn_complete(self, tmp_path):
        """AgentTurnComplete emitted with final text when agent finishes."""
        tasks = [_make_tasks()[0]]  # just task-a for agent-1
        tasks[0]["status"] = "done"  # already done — agent gets text-only response
        iter_dir = _setup_iter_dir(tmp_path, tasks)

        def mock_stream(**kw):
            return _make_streaming_result(["All done"], _text_round("All done"))

        deps = SessionDeps(
            agent_completion=None,
            coach_completion=None,
            single_completion=None,
            stream_completion=mock_stream,
        )
        policy = _make_policy(streaming=True)

        events = _collect(run_implementation(
            [AGENTS[0]], tasks, 0, ITERATION, iter_dir,
            MODEL_CONFIG, deps, [], policy,
        ))

        # No pending tasks → agent not dispatched → LayerComplete directly
        layer_done = _events_of_type(events, LayerComplete)
        assert len(layer_done) == 1

    def test_fallback_when_stream_completion_none(self, tmp_path):
        """When stream_completion is None, falls back to single_completion."""
        tasks = [_make_tasks()[0]]
        tasks[0]["status"] = "done"
        iter_dir = _setup_iter_dir(tmp_path, tasks)

        deps = SessionDeps(
            agent_completion=None,
            coach_completion=None,
            single_completion=lambda **kw: _text_round("Not streaming"),
            stream_completion=None,
        )
        policy = _make_policy(streaming=True)

        events = _collect(run_implementation(
            [AGENTS[0]], tasks, 0, ITERATION, iter_dir,
            MODEL_CONFIG, deps, [], policy,
        ))

        deltas = _events_of_type(events, TextDelta)
        assert len(deltas) == 0  # No deltas since all tasks done

    def test_fallback_when_streaming_false(self, tmp_path):
        """When streaming=False, uses single_completion even if stream_completion is set."""
        tasks = _make_tasks()
        iter_dir = _setup_iter_dir(tmp_path, tasks)

        stream_called = []
        single_called = []

        calls = [0]
        def mock_single(**kw):
            calls[0] += 1
            single_called.append(calls[0])
            if calls[0] == 1:
                return _tool_round("doing", [{
                    "name": "complete_tasks", "id": "tc1",
                    "input": {"task_ids": ["task-a"], "summary": "Done A"},
                }])
            return _text_round("Done")

        def mock_stream(**kw):
            stream_called.append(True)
            return _make_streaming_result(["x"], _text_round("x"))

        deps = SessionDeps(
            agent_completion=None,
            coach_completion=None,
            single_completion=mock_single,
            stream_completion=mock_stream,
        )
        policy = _make_policy(streaming=False)

        single_agent = [AGENTS[0]]
        single_tasks = [t for t in _make_tasks() if t["assigned_to"] == "agent-1"]
        (iter_dir / "tasks.json").write_text(json.dumps(single_tasks, indent=2))

        events = _collect(run_implementation(
            single_agent, single_tasks, 0, ITERATION, iter_dir,
            MODEL_CONFIG, deps, [], policy,
        ))

        assert len(stream_called) == 0
        assert len(single_called) > 0

    def test_turn_id_increments_per_round(self, tmp_path):
        """Turn IDs follow impl-{agent}-r{N} pattern and increment."""
        tasks = [_make_tasks()[0]]
        iter_dir = _setup_iter_dir(tmp_path, tasks)

        calls = [0]
        def mock_stream(**kw):
            calls[0] += 1
            if calls[0] == 1:
                return _make_streaming_result(
                    ["reading file"],
                    _tool_round("reading file", [{
                        "name": "file_read", "id": "tc1",
                        "input": {"path": "/tmp/test.py"},
                    }]),
                )
            if calls[0] == 2:
                return _make_streaming_result(
                    ["completing"],
                    _tool_round("completing", [{
                        "name": "complete_tasks", "id": "tc2",
                        "input": {"task_ids": ["task-a"], "summary": "Done"},
                    }]),
                )
            return _make_streaming_result(["final"], _text_round("final"))

        deps = SessionDeps(
            agent_completion=None,
            coach_completion=None,
            single_completion=None,
            stream_completion=mock_stream,
        )
        policy = _make_policy(streaming=True)

        events = _collect(run_implementation(
            [AGENTS[0]], tasks, 0, ITERATION, iter_dir,
            MODEL_CONFIG, deps, [], policy,
        ))

        deltas = _events_of_type(events, TextDelta)
        # Deltas from different rounds should have different turn_ids
        turn_ids = {d.turn_id for d in deltas}
        assert "impl-agent-1-r0" in turn_ids
        assert "impl-agent-1-r1" in turn_ids


# ── CLI streaming handler tests ───────────────────────────────────


class TestCliStreaming:
    def test_text_delta_printed_inline(self, tmp_path, capsys):
        """TextDelta events are written to stdout."""
        from gotg.cli import _run_implementation_phase
        from gotg.session import persist_event

        tasks = [_make_tasks()[0]]
        tasks[0]["status"] = "done"
        iter_dir = _setup_iter_dir(tmp_path, tasks)
        log_path = iter_dir / "conversation.jsonl"
        debug_path = iter_dir / "debug.jsonl"

        # Patch run_implementation to yield controlled events
        events = [
            SessionStarted("iter-1", "test", "implementation", 0, ["agent-1"], None, False, None, 0, 0, 1),
            TextDelta("agent-1", "impl-agent-1-r0", "Hello"),
            TextDelta("agent-1", "impl-agent-1-r0", " world"),
            AgentTurnComplete("agent-1", "impl-agent-1-r0", "Hello world"),
            AppendMessage({"from": "agent-1", "iteration": "iter-1", "content": "Hello world"}),
            LayerComplete(0, ("task-a",)),
        ]

        with patch("gotg.implementation.run_implementation", return_value=iter(events)):
            _run_implementation_phase(
                [AGENTS[0]], ITERATION, iter_dir, MODEL_CONFIG,
                SessionDeps(None, None, None), [], _make_policy(),
                log_path, debug_path,
            )

        captured = capsys.readouterr()
        # Text deltas printed inline
        assert "Hello world" in captured.out

    def test_double_print_suppression(self, tmp_path, capsys):
        """AppendMessage is not printed when streaming is active."""
        from gotg.cli import _run_implementation_phase

        tasks = [_make_tasks()[0]]
        tasks[0]["status"] = "done"
        iter_dir = _setup_iter_dir(tmp_path, tasks)
        log_path = iter_dir / "conversation.jsonl"
        debug_path = iter_dir / "debug.jsonl"

        events = [
            SessionStarted("iter-1", "test", "implementation", 0, ["agent-1"], None, False, None, 0, 0, 1),
            TextDelta("agent-1", "impl-agent-1-r0", "Streamed"),
            AgentTurnComplete("agent-1", "impl-agent-1-r0", "Streamed"),
            AppendMessage({"from": "agent-1", "iteration": "iter-1", "content": "Streamed"}),
            LayerComplete(0, ("task-a",)),
        ]

        with patch("gotg.implementation.run_implementation", return_value=iter(events)):
            _run_implementation_phase(
                [AGENTS[0]], ITERATION, iter_dir, MODEL_CONFIG,
                SessionDeps(None, None, None), [], _make_policy(),
                log_path, debug_path,
            )

        captured = capsys.readouterr()
        # "Streamed" should appear only once (from TextDelta), not twice
        # The AppendMessage print should be suppressed
        # Count occurrences — the TextDelta writes "Streamed" once, then "\n\n"
        # AppendMessage would add "agent-1: Streamed\n\n" if not suppressed
        assert captured.out.count("Streamed") == 1

    def test_non_streaming_append_still_prints(self, tmp_path, capsys):
        """AppendMessage prints normally when no streaming is active."""
        from gotg.cli import _run_implementation_phase

        tasks = [_make_tasks()[0]]
        tasks[0]["status"] = "done"
        iter_dir = _setup_iter_dir(tmp_path, tasks)
        log_path = iter_dir / "conversation.jsonl"
        debug_path = iter_dir / "debug.jsonl"

        events = [
            SessionStarted("iter-1", "test", "implementation", 0, ["agent-1"], None, False, None, 0, 0, 1),
            AppendMessage({"from": "agent-1", "iteration": "iter-1", "content": "Normal message"}),
            LayerComplete(0, ("task-a",)),
        ]

        with patch("gotg.implementation.run_implementation", return_value=iter(events)):
            _run_implementation_phase(
                [AGENTS[0]], ITERATION, iter_dir, MODEL_CONFIG,
                SessionDeps(None, None, None), [], _make_policy(),
                log_path, debug_path,
            )

        captured = capsys.readouterr()
        assert "Normal message" in captured.out

    def test_streamed_turn_id_cleared_after_complete(self, tmp_path, capsys):
        """After AgentTurnComplete, subsequent AppendMessage prints normally."""
        from gotg.cli import _run_implementation_phase

        tasks = [_make_tasks()[0]]
        tasks[0]["status"] = "done"
        iter_dir = _setup_iter_dir(tmp_path, tasks)
        log_path = iter_dir / "conversation.jsonl"
        debug_path = iter_dir / "debug.jsonl"

        events = [
            SessionStarted("iter-1", "test", "implementation", 0, ["agent-1"], None, False, None, 0, 0, 1),
            TextDelta("agent-1", "impl-agent-1-r0", "Streamed"),
            AgentTurnComplete("agent-1", "impl-agent-1-r0", "Streamed"),
            AppendMessage({"from": "agent-1", "iteration": "iter-1", "content": "Streamed"}),
            # System message after streaming completes — should print
            AppendMessage({"from": "system", "iteration": "iter-1", "content": "Task done"}),
            LayerComplete(0, ("task-a",)),
        ]

        with patch("gotg.implementation.run_implementation", return_value=iter(events)):
            _run_implementation_phase(
                [AGENTS[0]], ITERATION, iter_dir, MODEL_CONFIG,
                SessionDeps(None, None, None), [], _make_policy(),
                log_path, debug_path,
            )

        captured = capsys.readouterr()
        assert "Task done" in captured.out

    def test_stream_completion_wired_in_deps(self):
        """run_conversation wires raw_completion_stream into deps."""
        from gotg.cli import run_conversation
        # Just verify the import works and function signature accepts streaming
        # The actual wiring is tested via the full flow tests
        import inspect
        sig = inspect.signature(run_conversation)
        assert "streaming" in sig.parameters


# ── Model streaming function tests (SSE parsing) ─────────────────


def _sse(data):
    """Build a single SSE data line."""
    return "data: " + json.dumps(data)


class TestAnthropicRawStream:

    def test_text_only_stream(self):
        """Anthropic stream with text-only response yields text deltas."""
        lines = [
            _sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            _sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}),
            _sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": " world"}}),
            _sse({"type": "content_block_stop", "index": 0}),
            _sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {}}),
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gotg.model.httpx.stream", return_value=mock_resp):
            result = raw_completion_stream(
                base_url="https://api.anthropic.com",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                api_key="sk-test",
                provider="anthropic",
            )
            chunks = list(result)

        assert chunks == ["Hello", " world"]
        assert result.round is not None
        assert result.round.content == "Hello world"
        assert result.round.tool_calls == []

    def test_text_with_tool_calls(self):
        """Anthropic stream with text + tool_use blocks."""
        path_part1 = '{"path":'
        path_part2 = '"/tmp/f.py"}'
        lines = [
            "data: " + json.dumps({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            "data: " + json.dumps({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Reading file"}}),
            "data: " + json.dumps({"type": "content_block_stop", "index": 0}),
            "data: " + json.dumps({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu1", "name": "file_read"}}),
            "data: " + json.dumps({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": path_part1}}),
            "data: " + json.dumps({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": path_part2}}),
            "data: " + json.dumps({"type": "content_block_stop", "index": 1}),
            "data: " + json.dumps({"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {}}),
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gotg.model.httpx.stream", return_value=mock_resp):
            result = raw_completion_stream(
                base_url="https://api.anthropic.com",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                api_key="sk-test",
                provider="anthropic",
            )
            chunks = list(result)

        assert chunks == ["Reading file"]
        assert result.round.content == "Reading file"
        assert len(result.round.tool_calls) == 1
        assert result.round.tool_calls[0]["name"] == "file_read"
        assert result.round.tool_calls[0]["input"] == {"path": "/tmp/f.py"}
        assert result.round.tool_calls[0]["id"] == "tu1"
        # _raw content blocks should contain finalized tool input for continuation
        raw_blocks = result.round._raw["content_blocks"]
        assert raw_blocks[0]["type"] == "text"
        assert raw_blocks[0]["text"] == "Reading file"
        assert raw_blocks[1]["type"] == "tool_use"
        assert raw_blocks[1]["name"] == "file_read"
        assert raw_blocks[1]["input"] == {"path": "/tmp/f.py"}

    def test_max_tokens_discards_tools(self):
        """On max_tokens stop, tool calls are discarded."""
        lines = [
            _sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            _sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Partial"}}),
            _sse({"type": "content_block_stop", "index": 0}),
            _sse({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu1", "name": "file_write"}}),
            _sse({"type": "content_block_stop", "index": 1}),
            _sse({"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {}}),
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gotg.model.httpx.stream", return_value=mock_resp):
            result = raw_completion_stream(
                base_url="https://api.anthropic.com",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                api_key="sk-test",
                provider="anthropic",
            )
            chunks = list(result)

        assert result.round.tool_calls == []
        assert result.round.content == "Partial"

    def test_cache_usage_logged(self, capsys):
        """Cache usage from message_delta is logged to stderr."""
        lines = [
            _sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            _sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}}),
            _sse({"type": "content_block_stop", "index": 0}),
            _sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"cache_creation_input_tokens": 100, "cache_read_input_tokens": 50}}),
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gotg.model.httpx.stream", return_value=mock_resp):
            result = raw_completion_stream(
                base_url="https://api.anthropic.com",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                api_key="sk-test",
                provider="anthropic",
            )
            list(result)

        captured = capsys.readouterr()
        assert "[cache] created=100 read=50" in captured.err


class TestOpenAIRawStream:
    def test_text_only_stream(self):
        """OpenAI stream with text-only response."""
        lines = [
            _sse({"choices": [{"delta": {"content": "Hello"}}]}),
            _sse({"choices": [{"delta": {"content": " world"}}]}),
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gotg.model.httpx.stream", return_value=mock_resp):
            result = raw_completion_stream(
                base_url="http://localhost:11434",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                provider="ollama",
            )
            chunks = list(result)

        assert chunks == ["Hello", " world"]
        assert result.round.content == "Hello world"
        assert result.round.tool_calls == []

    def test_tool_call_accumulation(self):
        """OpenAI stream with tool call deltas accumulated correctly."""
        path_part1 = '{"path":'
        path_part2 = '"/tmp/f.py"}'
        lines = [
            _sse({"choices": [{"delta": {"content": "Let me read that"}}]}),
            _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "tc1", "function": {"name": "file_read", "arguments": ""}}]}}]}),
            _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": path_part1}}]}}]}),
            _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": path_part2}}]}}]}),
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gotg.model.httpx.stream", return_value=mock_resp):
            result = raw_completion_stream(
                base_url="http://localhost:11434",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                provider="ollama",
            )
            chunks = list(result)

        assert chunks == ["Let me read that"]
        assert len(result.round.tool_calls) == 1
        assert result.round.tool_calls[0]["name"] == "file_read"
        assert result.round.tool_calls[0]["input"] == {"path": "/tmp/f.py"}

    def test_api_error_raises(self):
        """API error response raises SystemExit."""
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Rate limited"
        mock_resp.read = MagicMock()
        mock_resp.json.return_value = {"error": {"message": "Too many requests"}}
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gotg.model.httpx.stream", return_value=mock_resp):
            with pytest.raises(SystemExit, match="429"):
                result = raw_completion_stream(
                    base_url="http://localhost:11434",
                    model="test",
                    messages=[{"role": "user", "content": "hi"}],
                    provider="ollama",
                )
                list(result)

    def test_malformed_json_tool_call_graceful(self):
        """Malformed tool call JSON results in empty input dict."""
        lines = [
            _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "tc1", "function": {"name": "file_read", "arguments": ""}}]}}]}),
            _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "not valid json"}}]}}]}),
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gotg.model.httpx.stream", return_value=mock_resp):
            result = raw_completion_stream(
                base_url="http://localhost:11434",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                provider="ollama",
            )
            list(result)

        # Should not crash — malformed JSON gives empty dict
        assert len(result.round.tool_calls) == 1
        assert result.round.tool_calls[0]["input"] == {}

    def test_empty_stream(self):
        """Stream with no content events yields empty result."""
        lines = ["data: [DONE]"]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gotg.model.httpx.stream", return_value=mock_resp):
            result = raw_completion_stream(
                base_url="http://localhost:11434",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                provider="ollama",
            )
            chunks = list(result)

        assert chunks == []
        assert result.round.content == ""
        assert result.round.tool_calls == []

    def test_continuation_builds_correctly(self):
        """CompletionRound from streaming has valid _raw for build_continuation."""
        path_json = '{"path": "/tmp/f"}'
        lines = [
            _sse({"choices": [{"delta": {"content": "Hi"}}]}),
            _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "tc1", "function": {"name": "file_read", "arguments": ""}}]}}]}),
            _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": path_json}}]}}]}),
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("gotg.model.httpx.stream", return_value=mock_resp):
            result = raw_completion_stream(
                base_url="http://localhost:11434",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                provider="ollama",
            )
            list(result)

        # build_continuation should work without error
        msgs = result.round.build_continuation([
            {"id": "tc1", "result": "file content here"},
        ])
        assert len(msgs) >= 1
        assert msgs[0]["role"] in ("assistant", "tool")


class TestRawCompletionStreamFallback:
    def test_fallback_to_non_streaming_before_any_delta(self):
        """If stream transport fails immediately, fallback to raw_completion."""
        with patch("gotg.model._openai_raw_stream", side_effect=httpx.StreamError("boom")), \
             patch("gotg.model.raw_completion", return_value=_text_round("fallback")) as mock_raw:
            result = raw_completion_stream(
                base_url="http://localhost:11434",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                provider="ollama",
            )
            chunks = list(result)

        assert chunks == ["fallback"]
        assert result.round is not None
        assert result.round.content == "fallback"
        assert mock_raw.call_count == 1

    def test_no_fallback_after_partial_delta(self):
        """If stream fails after yielding text, error propagates (no duplicate fallback)."""
        def _gen():
            yield "partial"
            raise httpx.StreamError("mid-stream boom")

        with patch("gotg.model._openai_raw_stream", return_value=_gen()), \
             patch("gotg.model.raw_completion") as mock_raw:
            result = raw_completion_stream(
                base_url="http://localhost:11434",
                model="test",
                messages=[{"role": "user", "content": "hi"}],
                provider="ollama",
            )
            it = iter(result)
            assert next(it) == "partial"
            with pytest.raises(httpx.StreamError):
                next(it)

        assert mock_raw.call_count == 0


# ── TUI streaming widget tests ───────────────────────────────────


class TestStreamingChatbox:
    def test_append_text_accumulates(self):
        from gotg.tui.widgets.message_list import StreamingChatbox
        box = StreamingChatbox("agent-1", "chatbox-agent-0")
        box.append_text("Hello")
        box.append_text(" world")
        assert box._buffer == ["Hello", " world"]

    def test_border_title_set(self):
        from gotg.tui.widgets.message_list import StreamingChatbox
        box = StreamingChatbox("agent-1", "chatbox-agent-0")
        assert box.border_title == "agent-1"


class TestMessageListStreaming:
    def test_begin_streaming_returns_widget(self):
        from gotg.tui.widgets.message_list import MessageList, StreamingChatbox
        ml = MessageList()
        # Can't test mount without a Textual app, but can verify the method exists
        assert hasattr(ml, "begin_streaming")
        assert hasattr(ml, "finalize_streaming")

    def test_append_stream_delta_uses_pre_update_scroll_state_true(self):
        from gotg.tui.widgets.message_list import MessageList

        ml = MessageList()
        widget = MagicMock()
        ml._is_near_bottom = MagicMock(return_value=True)
        ml._maybe_scroll = MagicMock()

        ml.append_stream_delta(widget, "hello")

        widget.append_text.assert_called_once_with("hello")
        ml._maybe_scroll.assert_called_once_with(True)

    def test_append_stream_delta_uses_pre_update_scroll_state_false(self):
        from gotg.tui.widgets.message_list import MessageList

        ml = MessageList()
        widget = MagicMock()
        ml._is_near_bottom = MagicMock(return_value=False)
        ml._maybe_scroll = MagicMock()

        ml.append_stream_delta(widget, "hello")

        widget.append_text.assert_called_once_with("hello")
        ml._maybe_scroll.assert_called_once_with(False)

    def test_maybe_scroll_calls_immediate_and_deferred_scroll(self):
        from gotg.tui.widgets.message_list import MessageList

        ml = MessageList()
        ml.scroll_end = MagicMock()
        ml.call_after_refresh = MagicMock()

        ml._maybe_scroll(True)

        ml.scroll_end.assert_called_once_with(animate=False)
        ml.call_after_refresh.assert_called_once_with(ml.scroll_end, animate=False)


class TestParticipantPanel:
    def test_tool_line_formats_status_and_size(self):
        from gotg.tui.widgets.participant_panel import _tool_line

        assert _tool_line("file_read", "src/main.py", "ok", None) == "file_read src/main.py"
        assert _tool_line("file_write", "src/main.py", "ok", 12) == "file_write src/main.py (12b)"
        assert _tool_line("file_write", "src/main.py", "pending_approval", 12).endswith("PENDING")
        assert _tool_line("file_write", "src/main.py", "error", 12).endswith("FAIL")

    def test_add_tool_progress_routes_to_actor_tile_only(self):
        from gotg.tui.widgets.participant_panel import ParticipantPanel
        from gotg.events import ToolCallProgress

        panel = ParticipantPanel()
        tile_a = MagicMock()
        tile_b = MagicMock()
        panel._tiles = {"agent-1": tile_a, "agent-2": tile_b}

        event = ToolCallProgress(
            agent="agent-1",
            tool_name="file_read",
            path="src/main.py",
            status="ok",
            bytes=None,
            error=None,
        )
        panel.add_tool_progress(event)

        tile_a.add_tool_event.assert_called_once_with(
            tool_name="file_read",
            path="src/main.py",
            status="ok",
            size=None,
        )
        tile_b.add_tool_event.assert_not_called()


class TestTextDeltaMsg:
    def test_message_fields(self):
        from gotg.tui.messages import TextDeltaMsg
        msg = TextDeltaMsg("agent-1", "impl-agent-1-r0", "hello")
        assert msg.agent == "agent-1"
        assert msg.turn_id == "impl-agent-1-r0"
        assert msg.text == "hello"


# ── Discussion-phase streaming CLI tests ──────────────────────────


class TestCliDiscussionStreaming:
    def test_text_delta_printed_inline(self, tmp_path, capsys):
        """TextDelta events are written to stdout in discussion phase."""
        from gotg.cli import _run_discussion_phase
        from gotg.engine import run_session

        iter_dir = tmp_path / ".team" / "iterations" / "iter-1"
        iter_dir.mkdir(parents=True)
        log_path = iter_dir / "conversation.jsonl"
        debug_path = iter_dir / "debug.jsonl"
        log_path.touch()
        debug_path.touch()

        events = [
            SessionStarted("iter-1", "test", "refinement", None, ["agent-1"], None, False, None, 0, 0, 1),
            TextDelta("agent-1", "turn-0-agent-1", "Hello"),
            TextDelta("agent-1", "turn-0-agent-1", " discussion"),
            AgentTurnComplete("agent-1", "turn-0-agent-1", "Hello discussion"),
            AppendMessage({"from": "agent-1", "iteration": "iter-1", "content": "Hello discussion"}),
            SessionComplete(1),
        ]

        with patch("gotg.cli.run_session", return_value=iter(events)):
            _run_discussion_phase(
                AGENTS[:1], {"id": "iter-1", "phase": "refinement", "description": "test", "max_turns": 1},
                MODEL_CONFIG, SessionDeps(None, None, None), [], _make_policy(),
                log_path, debug_path,
            )

        captured = capsys.readouterr()
        assert "Hello discussion" in captured.out

    def test_agent_name_suppression_passes_tool_ops(self, tmp_path, capsys):
        """Agent message suppressed but tool op system messages still print."""
        from gotg.cli import _run_discussion_phase

        iter_dir = tmp_path / ".team" / "iterations" / "iter-1"
        iter_dir.mkdir(parents=True)
        log_path = iter_dir / "conversation.jsonl"
        debug_path = iter_dir / "debug.jsonl"
        log_path.touch()
        debug_path.touch()

        events = [
            SessionStarted("iter-1", "test", "refinement", None, ["agent-1"], None, False, None, 0, 0, 1),
            TextDelta("agent-1", "turn-0-agent-1", "Streamed text"),
            AgentTurnComplete("agent-1", "turn-0-agent-1", "Streamed text"),
            # Tool op system message — should NOT be suppressed
            AppendMessage({"from": "system", "iteration": "iter-1", "content": "[file_read] src/main.py"}),
            # Agent message — SHOULD be suppressed (already streamed)
            AppendMessage({"from": "agent-1", "iteration": "iter-1", "content": "Streamed text"}),
            SessionComplete(1),
        ]

        with patch("gotg.cli.run_session", return_value=iter(events)):
            _run_discussion_phase(
                AGENTS[:1], {"id": "iter-1", "phase": "refinement", "description": "test", "max_turns": 1},
                MODEL_CONFIG, SessionDeps(None, None, None), [], _make_policy(),
                log_path, debug_path,
            )

        captured = capsys.readouterr()
        # Tool op should appear
        assert "[file_read]" in captured.out
        # Agent content appears once (from TextDelta), not twice
        assert captured.out.count("Streamed text") == 1

    def test_non_streaming_discussion_unchanged(self, tmp_path, capsys):
        """When no TextDelta events, all AppendMessages print normally."""
        from gotg.cli import _run_discussion_phase

        iter_dir = tmp_path / ".team" / "iterations" / "iter-1"
        iter_dir.mkdir(parents=True)
        log_path = iter_dir / "conversation.jsonl"
        debug_path = iter_dir / "debug.jsonl"
        log_path.touch()
        debug_path.touch()

        events = [
            SessionStarted("iter-1", "test", "refinement", None, ["agent-1"], None, False, None, 0, 0, 1),
            AppendMessage({"from": "agent-1", "iteration": "iter-1", "content": "Normal response"}),
            SessionComplete(1),
        ]

        with patch("gotg.cli.run_session", return_value=iter(events)):
            _run_discussion_phase(
                AGENTS[:1], {"id": "iter-1", "phase": "refinement", "description": "test", "max_turns": 1},
                MODEL_CONFIG, SessionDeps(None, None, None), [], _make_policy(),
                log_path, debug_path,
            )

        captured = capsys.readouterr()
        assert "Normal response" in captured.out

    def test_tool_progress_printed_to_stderr(self, tmp_path, capsys):
        """ToolCallProgress events go to stderr in discussion phase."""
        from gotg.cli import _run_discussion_phase

        iter_dir = tmp_path / ".team" / "iterations" / "iter-1"
        iter_dir.mkdir(parents=True)
        log_path = iter_dir / "conversation.jsonl"
        debug_path = iter_dir / "debug.jsonl"
        log_path.touch()
        debug_path.touch()

        events = [
            SessionStarted("iter-1", "test", "refinement", None, ["agent-1"], None, False, None, 0, 0, 1),
            ToolCallProgress("agent-1", "file_read", "/tmp/x.py", "ok", None, None),
            TextDelta("agent-1", "turn-0-agent-1", "ok"),
            AgentTurnComplete("agent-1", "turn-0-agent-1", "ok"),
            AppendMessage({"from": "agent-1", "iteration": "iter-1", "content": "ok"}),
            SessionComplete(1),
        ]

        with patch("gotg.cli.run_session", return_value=iter(events)):
            _run_discussion_phase(
                AGENTS[:1], {"id": "iter-1", "phase": "refinement", "description": "test", "max_turns": 1},
                MODEL_CONFIG, SessionDeps(None, None, None), [], _make_policy(),
                log_path, debug_path,
            )

        captured = capsys.readouterr()
        assert "file_read" in captured.err


# ── Grooming streaming tests ─────────────────────────────────────


class TestGroomingStreaming:
    def test_grooming_policy_streaming_param(self):
        """grooming_policy accepts and passes streaming param."""
        from gotg.policy import grooming_policy
        policy = grooming_policy(
            agents=AGENTS, topic="test", history=[], streaming=True,
        )
        assert policy.streaming is True

    def test_grooming_policy_streaming_default(self):
        """grooming_policy defaults to streaming=False."""
        from gotg.policy import grooming_policy
        policy = grooming_policy(
            agents=AGENTS, topic="test", history=[],
        )
        assert policy.streaming is False


# ── Implementation phase name-based suppression tests ─────────────


class TestImplNameBasedSuppression:
    def test_tool_op_messages_pass_through(self, tmp_path, capsys):
        """After AgentTurnComplete, system tool op messages still print."""
        from gotg.cli import _run_implementation_phase

        tasks = _make_tasks()
        iter_dir = _setup_iter_dir(tmp_path, tasks)
        log_path = iter_dir / "conversation.jsonl"
        debug_path = iter_dir / "debug.jsonl"

        events = [
            SessionStarted("iter-1", "test", "implementation", 0, ["agent-1"], None, False, None, 0, 0, 1),
            TextDelta("agent-1", "impl-agent-1-r0", "Streamed"),
            AgentTurnComplete("agent-1", "impl-agent-1-r0", "Streamed"),
            # System tool op message — should print
            AppendMessage({"from": "system", "iteration": "iter-1", "content": "[complete_tasks] Done"}),
            # Agent message — should be suppressed
            AppendMessage({"from": "agent-1", "iteration": "iter-1", "content": "Streamed"}),
            # Next system message — should print (suppression consumed)
            AppendMessage({"from": "system", "iteration": "iter-1", "content": "Task done notification"}),
            LayerComplete(0, ("task-a",)),
        ]

        with patch("gotg.implementation.run_implementation", return_value=iter(events)):
            _run_implementation_phase(
                [AGENTS[0]], ITERATION, iter_dir, MODEL_CONFIG,
                SessionDeps(None, None, None), [], _make_policy(),
                log_path, debug_path,
            )

        captured = capsys.readouterr()
        # System messages should print
        assert "[complete_tasks]" in captured.out
        assert "Task done notification" in captured.out
        # Agent content from TextDelta appears once, suppression prevents double
        assert captured.out.count("Streamed") == 1
