from gotg.engine import SessionDeps, run_session
from gotg.events import (
    AppendDebug,
    AppendMessage,
    CoachAskedPM,
    PauseForApprovals,
    PhaseCompleteSignaled,
    SessionComplete,
    SessionStarted,
)
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
        worktree_map=None,
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
