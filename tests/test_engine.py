import json

from gotg.engine import SessionDeps, run_session, _classify_tool_result
from gotg.events import (
    AgentTurnComplete,
    AppendDebug,
    AppendMessage,
    CoachAskedPM,
    PauseForApprovals,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
    TextDelta,
    ToolCallProgress,
)
from gotg.model import CompletionRound, StreamingResult
from gotg.policy import SessionPolicy
from gotg.prompts import AGENT_TOOLS, COACH_TOOLS


# --- Helpers ---

AGENTS = [
    {"name": "agent-1", "role": "Software Engineer"},
    {"name": "agent-2", "role": "Software Engineer"},
]

ITERATION = {
    "id": "iter-1",
    "description": "Build a thing",
    "phase": "refinement",
    "max_turns": 10,
}

MODEL_CONFIG = {
    "provider": "ollama",
    "base_url": "http://localhost:11434",
    "model": "test-model",
}

COACH = {"name": "coach", "role": "Agile Coach"}


def _make_deps(agent_response=None, coach_response=None):
    """Build SessionDeps with simple mock callables."""
    def mock_agent(**kw):
        return agent_response or {"content": "hello", "operations": []}
    def mock_coach(**kw):
        return coach_response or {"content": "coach says", "tool_calls": []}
    return SessionDeps(agent_completion=mock_agent, coach_completion=mock_coach)


def _make_policy(**overrides):
    """Build a SessionPolicy with test defaults."""
    defaults = dict(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=True, stop_on_ask_pm=True,
        agent_tools=tuple(AGENT_TOOLS), coach_tools=tuple(COACH_TOOLS),
        groomed_summary=None, tasks_summary=None, diffs_summary=None,
        kickoff_text=None, fileguard=None, approval_store=None,
        worktree_map=None, system_supplement=None, coach_system_prompt=None,
    )
    defaults.update(overrides)
    return SessionPolicy(**defaults)


def _collect(events):
    """Collect all events into a list."""
    return list(events)


def _events_of_type(events, cls):
    """Filter events to a specific type."""
    return [e for e in events if isinstance(e, cls)]


# --- SessionStarted ---

def test_session_started_event():
    deps = _make_deps()
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=0),
    ))
    assert len(events) >= 1
    e = events[0]
    assert isinstance(e, SessionStarted)
    assert e.iteration_id == "iter-1"
    assert e.description == "Build a thing"
    assert e.phase == "refinement"
    assert e.agents == ["agent-1", "agent-2"]
    assert e.coach is None
    assert e.turn == 0
    assert e.max_turns == 0


def test_session_started_with_coach():
    deps = _make_deps()
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=0, coach=COACH, coach_cadence=2),
    ))
    assert events[0].coach == "coach"


# --- Agent turns ---

def test_agent_turn_yields_append_message():
    deps = _make_deps(agent_response={"content": "my thoughts", "operations": []})
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=1),
    ))
    msgs = _events_of_type(events, AppendMessage)
    assert len(msgs) == 1
    assert msgs[0].msg["from"] == "agent-1"
    assert msgs[0].msg["content"] == "my thoughts"


def test_agent_pass_turn():
    deps = _make_deps(agent_response={
        "content": "",
        "operations": [{"name": "pass_turn", "input": {"reason": "agree"}, "result": "Turn passed."}],
    })
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=1),
    ))
    msgs = _events_of_type(events, AppendMessage)
    assert len(msgs) == 1
    assert msgs[0].msg.get("pass_turn") is True
    assert "passes: agree" in msgs[0].msg["content"]


def test_file_operation_logged():
    deps = _make_deps(agent_response={
        "content": "done",
        "operations": [
            {"name": "file_read", "input": {"path": "src/main.py"}, "result": "content"},
        ],
    })
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=1),
    ))
    msgs = _events_of_type(events, AppendMessage)
    # First msg is the file op system message, second is the agent message
    assert len(msgs) == 2
    assert msgs[0].msg["from"] == "system"
    assert "[agent-1]" in msgs[0].msg["content"]
    assert "[file_read]" in msgs[0].msg["content"]
    assert msgs[1].msg["from"] == "agent-1"


# --- Max turns / SessionComplete ---

def test_max_turns_yields_session_complete():
    deps = _make_deps()
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=2),
    ))
    complete = _events_of_type(events, SessionComplete)
    assert len(complete) == 1
    assert complete[0].total_turns == 2


# --- Coach turns ---

def test_coach_after_full_rotation():
    call_count = {"agent": 0, "coach": 0}

    def mock_agent(**kw):
        call_count["agent"] += 1
        return {"content": f"agent says {call_count['agent']}", "operations": []}

    def mock_coach(**kw):
        call_count["coach"] += 1
        return {"content": "coach summary", "tool_calls": []}

    deps = SessionDeps(agent_completion=mock_agent, coach_completion=mock_coach)
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    assert call_count["agent"] == 2
    assert call_count["coach"] == 1
    msgs = _events_of_type(events, AppendMessage)
    coach_msgs = [m for m in msgs if m.msg["from"] == "coach"]
    assert len(coach_msgs) == 1
    assert coach_msgs[0].msg["content"] == "coach summary"


def test_coach_signal_phase_complete():
    deps = _make_deps(
        coach_response={
            "content": "All done.",
            "tool_calls": [{"name": "signal_phase_complete", "input": {"summary": "done"}}],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    signals = _events_of_type(events, PhaseCompleteSignaled)
    assert len(signals) == 1
    assert signals[0].phase == "refinement"
    # Should NOT have SessionComplete (stopped early)
    assert len(_events_of_type(events, SessionComplete)) == 0


def test_coach_ask_pm():
    deps = _make_deps(
        coach_response={
            "content": "Need PM decision.",
            "tool_calls": [{"name": "ask_pm", "input": {"question": "What color?"}}],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    asks = _events_of_type(events, CoachAskedPM)
    assert len(asks) == 1
    assert asks[0].question == "What color?"
    assert len(_events_of_type(events, SessionComplete)) == 0


def test_coach_empty_text_fallback_signal():
    deps = _make_deps(
        coach_response={
            "content": "",
            "tool_calls": [{"name": "signal_phase_complete", "input": {"summary": "done"}}],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    coach_msgs = [e for e in _events_of_type(events, AppendMessage) if e.msg["from"] == "coach"]
    assert len(coach_msgs) == 1
    assert coach_msgs[0].msg["content"] == "(Phase complete signal sent.)"


def test_coach_empty_text_fallback_ask_pm():
    deps = _make_deps(
        coach_response={
            "content": "  ",
            "tool_calls": [{"name": "ask_pm", "input": {"question": "Budget?"}}],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    coach_msgs = [e for e in _events_of_type(events, AppendMessage) if e.msg["from"] == "coach"]
    assert len(coach_msgs) == 1
    assert "Requesting PM input: Budget?" in coach_msgs[0].msg["content"]


# --- Approvals ---

def test_approval_pause():
    class MockApprovalStore:
        def get_pending(self):
            return [{"id": "a1", "path": "foo.py"}]

    deps = _make_deps()
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=2, approval_store=MockApprovalStore()),
    ))
    pauses = _events_of_type(events, PauseForApprovals)
    assert len(pauses) == 1
    assert pauses[0].pending_count == 1
    assert len(_events_of_type(events, SessionComplete)) == 0


# --- Kickoff ---

def test_kickoff_injection():
    deps = _make_deps()
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=1, kickoff_text="Welcome to grooming!"),
    ))
    msgs = _events_of_type(events, AppendMessage)
    # First AppendMessage should be the kickoff
    assert msgs[0].msg["from"] == "system"
    assert msgs[0].msg["content"] == "Welcome to grooming!"


def test_no_kickoff_when_none():
    deps = _make_deps()
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=1),
    ))
    msgs = _events_of_type(events, AppendMessage)
    # First AppendMessage should be the agent message, not a kickoff
    assert msgs[0].msg["from"] == "agent-1"


# --- Debug entries ---

def test_debug_entries_for_prompt():
    deps = _make_deps()
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=1),
    ))
    debugs = _events_of_type(events, AppendDebug)
    assert len(debugs) >= 1
    assert "messages" in debugs[0].entry
    assert debugs[0].entry["agent"] == "agent-1"


# --- No coach ---

def test_no_coach_when_none():
    call_count = {"coach": 0}

    def mock_coach(**kw):
        call_count["coach"] += 1
        return {"content": "x", "tool_calls": []}

    deps = SessionDeps(
        agent_completion=lambda **kw: {"content": "x", "operations": []},
        coach_completion=mock_coach,
    )
    _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=2),
    ))
    assert call_count["coach"] == 0


# --- Streaming agent turn ---

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


def test_streaming_agent_turn_text_only():
    """Streaming agent turn with no tools yields TextDelta + AgentTurnComplete + AppendMessage."""
    calls = [0]
    def mock_stream(**kw):
        calls[0] += 1
        return _make_streaming_result(["Hello", " world"], _text_round("Hello world"))

    deps = _make_deps()
    deps.stream_completion = mock_stream

    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=1, streaming=True),
    ))

    deltas = _events_of_type(events, TextDelta)
    assert len(deltas) == 2
    assert deltas[0].text == "Hello"
    assert deltas[1].text == " world"
    assert deltas[0].agent == "agent-1"
    assert deltas[0].turn_id == "turn-0-agent-1"

    completes = _events_of_type(events, AgentTurnComplete)
    assert len(completes) == 1
    assert completes[0].agent == "agent-1"
    assert completes[0].content == "Hello world"

    msgs = _events_of_type(events, AppendMessage)
    agent_msgs = [m for m in msgs if m.msg["from"] == "agent-1"]
    assert len(agent_msgs) == 1
    assert agent_msgs[0].msg["content"] == "Hello world"


def test_streaming_agent_turn_with_tools():
    """Streaming agent turn with tool calls yields ToolCallProgress."""
    calls = [0]
    def mock_stream(**kw):
        calls[0] += 1
        if calls[0] == 1:
            return _make_streaming_result(
                ["Reading"],
                _tool_round("Reading", [
                    {"name": "pass_turn", "id": "tc1", "input": {"reason": "done"}},
                ]),
            )
        return _make_streaming_result(["Done"], _text_round("Done"))

    deps = _make_deps()
    deps.stream_completion = mock_stream

    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=1, streaming=True),
    ))

    # pass_turn yields ToolCallProgress
    progress = _events_of_type(events, ToolCallProgress)
    assert len(progress) == 1
    assert progress[0].tool_name == "pass_turn"

    # pass_turn message should be yielded
    msgs = _events_of_type(events, AppendMessage)
    pass_msgs = [m for m in msgs if m.msg.get("pass_turn")]
    assert len(pass_msgs) == 1
    assert "passes: done" in pass_msgs[0].msg["content"]

    # P1 regression: pass_turn must NOT emit AgentTurnComplete
    # (otherwise suppression lingers and eats the next real agent message)
    completes = _events_of_type(events, AgentTurnComplete)
    assert len(completes) == 0


def test_streaming_non_streaming_path_untouched():
    """When streaming=False, existing agent_completion path is used."""
    stream_called = []
    def mock_stream(**kw):
        stream_called.append(True)
        return _make_streaming_result(["x"], _text_round("x"))

    deps = _make_deps(agent_response={"content": "non-streaming", "operations": []})
    deps.stream_completion = mock_stream

    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=1, streaming=False),
    ))

    assert len(stream_called) == 0
    msgs = _events_of_type(events, AppendMessage)
    assert msgs[0].msg["content"] == "non-streaming"
    assert len(_events_of_type(events, TextDelta)) == 0


def test_streaming_multi_round_tool_loop():
    """Streaming agent turn with two tool rounds accumulates operations."""
    calls = [0]
    def mock_stream(**kw):
        calls[0] += 1
        if calls[0] == 1:
            return _make_streaming_result(
                ["round1"],
                _tool_round("round1", [
                    {"name": "file_read", "id": "tc1", "input": {"path": "/tmp/a.py"}},
                ]),
            )
        if calls[0] == 2:
            return _make_streaming_result(
                ["round2"],
                _tool_round("round2", [
                    {"name": "file_read", "id": "tc2", "input": {"path": "/tmp/b.py"}},
                ]),
            )
        return _make_streaming_result(["final"], _text_round("final"))

    deps = _make_deps()
    deps.stream_completion = mock_stream

    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[], policy=_make_policy(max_turns=1, streaming=True),
    ))

    progress = _events_of_type(events, ToolCallProgress)
    assert len(progress) == 2
    assert progress[0].path == "/tmp/a.py"
    assert progress[1].path == "/tmp/b.py"

    # Tool op system messages
    msgs = _events_of_type(events, AppendMessage)
    sys_msgs = [m for m in msgs if m.msg["from"] == "system" and "[file_read]" in m.msg["content"]]
    assert len(sys_msgs) == 2
    assert all("[agent-1]" in m.msg["content"] for m in sys_msgs)


def test_streaming_max_rounds():
    """When max_rounds is reached, streaming turn still completes."""
    def mock_stream(**kw):
        return _make_streaming_result(
            ["loop"],
            _tool_round("loop", [
                {"name": "file_list", "id": "tc1", "input": {"path": "/tmp"}},
            ]),
        )

    deps = _make_deps()
    deps.stream_completion = mock_stream

    # Use max_rounds=2 via _do_streaming_agent_turn directly
    from gotg.engine import _do_streaming_agent_turn, build_tool_executor
    agent = AGENTS[0]
    policy = _make_policy(streaming=True)
    agent_tools, tool_executor = build_tool_executor(agent, policy)

    events = list(_do_streaming_agent_turn(
        agent, ITERATION, MODEL_CONFIG, deps, [], [],
        agent_tools, tool_executor, 0, max_rounds=2,
    ))

    # Should get AgentTurnComplete even after max rounds
    completes = [e for e in events if isinstance(e, AgentTurnComplete)]
    assert len(completes) == 1


def test_streaming_with_coach():
    """Streaming applies to coach turns when stream_completion is available."""
    calls = {"agent": 0, "coach_stream": 0, "coach_non_stream": 0}

    def mock_stream(**kw):
        tool_names = {t["name"] for t in (kw.get("tools") or [])}
        if "ask_pm" in tool_names:
            calls["coach_stream"] += 1
            return _make_streaming_result(["coach summary"], _text_round("coach summary"))
        calls["agent"] += 1
        return _make_streaming_result([f"agent says {calls['agent']}"], _text_round(f"agent says {calls['agent']}"))

    def mock_coach(**kw):
        calls["coach_non_stream"] += 1
        return {"content": "coach non-stream", "tool_calls": []}

    deps = SessionDeps(
        agent_completion=lambda **kw: None,  # unused when streaming
        coach_completion=mock_coach,
        stream_completion=mock_stream,
    )

    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[],
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2, streaming=True),
    ))

    # Should have TextDelta events from agents and coach
    deltas = _events_of_type(events, TextDelta)
    assert any(d.agent == "agent-1" for d in deltas)
    assert any(d.agent == "agent-2" for d in deltas)
    assert any(d.agent == "coach" for d in deltas)
    assert calls["coach_stream"] == 1
    assert calls["coach_non_stream"] == 0

    # Coach message is still persisted as AppendMessage for history/log continuity.
    coach_msgs = [e for e in _events_of_type(events, AppendMessage) if e.msg["from"] == "coach"]
    assert len(coach_msgs) == 1
    assert coach_msgs[0].msg["content"] == "coach summary"


def test_streaming_coach_tool_only_response_keeps_fallback_visible():
    """Tool-only coach responses should not emit AgentTurnComplete suppression."""
    def mock_stream(**kw):
        tool_names = {t["name"] for t in (kw.get("tools") or [])}
        if "ask_pm" in tool_names:
            return _make_streaming_result(
                [],
                _tool_round("", [{"name": "ask_pm", "id": "c1", "input": {"question": "Budget?"}}]),
            )
        return _make_streaming_result(["agent"], _text_round("agent"))

    deps = SessionDeps(
        agent_completion=lambda **kw: None,  # unused when streaming
        coach_completion=lambda **kw: {"content": "unused", "tool_calls": []},
        stream_completion=mock_stream,
    )

    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[],
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2, streaming=True),
    ))

    # No streamed coach text means no coach AgentTurnComplete (prevents suppression bugs).
    coach_completes = [e for e in _events_of_type(events, AgentTurnComplete) if e.agent == "coach"]
    assert coach_completes == []

    coach_msgs = [e for e in _events_of_type(events, AppendMessage) if e.msg["from"] == "coach"]
    assert len(coach_msgs) == 1
    assert "Requesting PM input: Budget?" in coach_msgs[0].msg["content"]

    asks = _events_of_type(events, CoachAskedPM)
    assert len(asks) == 1
    assert asks[0].question == "Budget?"


def test_streaming_history_mutation():
    """Streaming branch mutates history correctly."""
    history = []
    def mock_stream(**kw):
        return _make_streaming_result(["hello"], _text_round("hello"))

    deps = _make_deps()
    deps.stream_completion = mock_stream

    _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=history, policy=_make_policy(max_turns=1, streaming=True),
    ))

    agent_msgs = [m for m in history if m.get("from") == "agent-1"]
    assert len(agent_msgs) == 1
    assert agent_msgs[0]["content"] == "hello"


# --- _classify_tool_result ---

def test_classify_tool_result_ok():
    assert _classify_tool_result("File content here") == "ok"

def test_classify_tool_result_error():
    assert _classify_tool_result("Error: file not found") == "error"

def test_classify_tool_result_pending():
    assert _classify_tool_result("Pending approval (a1): /tmp/x.py") == "pending_approval"
