"""Tests for grooming outcomes: iteration proposals + summary generation."""

import json
from pathlib import Path

import pytest

from gotg.engine import SessionDeps, run_session
from gotg.events import (
    AppendMessage,
    CoachAskedPM,
    IterationsProposed,
    SessionComplete,
    SessionStarted,
)
from gotg.policy import SessionPolicy
from gotg.prompts import (
    AGENT_TOOLS,
    COACH_TOOLS,
    GROOMING_COACH_TOOLS,
    GROOMING_SUMMARY_EXTRACTION_PROMPT,
    PROPOSE_ITERATIONS_TOOL,
)
from gotg.session_types import PauseReason, ResumeState, reconstruct_resume_state


# ── Helpers ──────────────────────────────────────────────────────

AGENTS = [
    {"name": "agent-1", "role": "Software Engineer"},
    {"name": "agent-2", "role": "Software Engineer"},
]

ITERATION = {
    "id": "test-slug",
    "description": "test topic",
    "phase": None,
}

MODEL_CONFIG = {
    "provider": "ollama",
    "base_url": "http://localhost:11434",
    "model": "test-model",
}

COACH = {"name": "coach", "role": "Agile Coach"}


def _make_deps(agent_response=None, coach_response=None):
    def mock_agent(**kw):
        return agent_response or {"content": "hello", "operations": []}
    def mock_coach(**kw):
        return coach_response or {"content": "coach says", "tool_calls": []}
    return SessionDeps(agent_completion=mock_agent, coach_completion=mock_coach)


def _make_policy(**overrides):
    defaults = dict(
        max_turns=10, coach=None, coach_cadence=None,
        stop_on_phase_complete=False, stop_on_ask_pm=True,
        agent_tools=tuple(AGENT_TOOLS), coach_tools=tuple(GROOMING_COACH_TOOLS),
        groomed_summary=None, tasks_summary=None, diffs_summary=None,
        kickoff_text=None, fileguard=None, approval_store=None,
        worktree_map=None, system_supplement=None, coach_system_prompt=None,
        phase_skeleton=None,
    )
    defaults.update(overrides)
    return SessionPolicy(**defaults)


def _collect(events):
    return list(events)


def _events_of_type(events, cls):
    return [e for e in events if isinstance(e, cls)]


_SAMPLE_PROPOSALS = [
    {
        "action": "create",
        "title": "Calculator MVP",
        "description": "Build basic calculator with +,-,*,/ operations",
    },
    {
        "action": "create",
        "title": "State persistence",
        "description": "Add save/load state to calculator",
    },
]

_PROPOSE_TOOL_CALL = {
    "name": "propose_iterations",
    "input": {
        "proposals": _SAMPLE_PROPOSALS,
        "rationale": "Natural scope boundaries",
    },
}


def _make_team_dir(tmp_path, iterations=None):
    """Create a minimal .team dir with iteration.json and team.json."""
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
    # team.json for TeamContext
    (team_dir / "team.json").write_text(json.dumps({
        "schema_version": 1,
        "agents": AGENTS,
        "model": MODEL_CONFIG,
    }))
    return team_dir


# ══════════════════════════════════════════════════════════════
# Part 1: Engine Tests — propose_iterations
# ══════════════════════════════════════════════════════════════


def test_coach_propose_iterations_yields_event():
    """Coach propose_iterations tool call → IterationsProposed event + session stops."""
    deps = _make_deps(
        coach_response={
            "content": "Here are my proposals.",
            "tool_calls": [_PROPOSE_TOOL_CALL],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[],
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    proposals = _events_of_type(events, IterationsProposed)
    assert len(proposals) == 1
    assert proposals[0].batch_id == "p1"
    assert len(proposals[0].proposals) == 2
    assert proposals[0].rationale == "Natural scope boundaries"
    # Session should stop — no SessionComplete
    assert len(_events_of_type(events, SessionComplete)) == 0


def test_coach_propose_iterations_stored_in_message():
    """Proposals + batch_id stored in coach message dict."""
    deps = _make_deps(
        coach_response={
            "content": "Proposing iterations.",
            "tool_calls": [_PROPOSE_TOOL_CALL],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[],
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    coach_msgs = [
        e for e in _events_of_type(events, AppendMessage)
        if e.msg.get("from") == "coach"
    ]
    assert len(coach_msgs) == 1
    pi = coach_msgs[0].msg.get("propose_iterations")
    assert pi is not None
    assert pi["batch_id"] == "p1"
    assert len(pi["proposals"]) == 2


def test_coach_propose_iterations_fallback_text():
    """Empty coach text gets fallback when propose_iterations called."""
    deps = _make_deps(
        coach_response={
            "content": "  ",
            "tool_calls": [_PROPOSE_TOOL_CALL],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[],
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    coach_msgs = [
        e for e in _events_of_type(events, AppendMessage)
        if e.msg.get("from") == "coach"
    ]
    assert "(Iteration proposals submitted for PM review.)" in coach_msgs[0].msg["content"]


def test_coach_propose_iterations_priority_over_ask_pm():
    """When coach calls both propose_iterations and ask_pm, proposals win."""
    deps = _make_deps(
        coach_response={
            "content": "Proposals and question.",
            "tool_calls": [
                _PROPOSE_TOOL_CALL,
                {"name": "ask_pm", "input": {"question": "What do you think?"}},
            ],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[],
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    proposals = _events_of_type(events, IterationsProposed)
    asks = _events_of_type(events, CoachAskedPM)
    assert len(proposals) == 1
    assert len(asks) == 0
    # ask_pm should NOT be attached to coach_msg
    coach_msgs = [
        e for e in _events_of_type(events, AppendMessage)
        if e.msg.get("from") == "coach"
    ]
    assert "ask_pm" not in coach_msgs[0].msg


def test_coach_propose_iterations_batch_id_increments():
    """Second proposal gets p2 (existing history has p1)."""
    existing_history = [
        {"from": "coach", "iteration": "test-slug", "content": "First proposals.",
         "propose_iterations": {"batch_id": "p1", "proposals": [], "rationale": ""}},
    ]
    deps = _make_deps(
        coach_response={
            "content": "More proposals.",
            "tool_calls": [_PROPOSE_TOOL_CALL],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=list(existing_history),
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    proposals = _events_of_type(events, IterationsProposed)
    assert len(proposals) == 1
    assert proposals[0].batch_id == "p2"


# ══════════════════════════════════════════════════════════════
# Part 1: Apply Logic Tests
# ══════════════════════════════════════════════════════════════


def test_apply_iteration_proposals_create(tmp_path):
    """Creates new iteration with auto-ID, pending status."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.conversation import ConversationStore
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    store = ConversationStore(groom_dir / "conversation.jsonl")

    from gotg.session_setup import apply_iteration_proposals
    results = apply_iteration_proposals(
        team_dir,
        [{"action": "create", "title": "My Iteration", "description": "Build stuff"}],
        batch_id="p1", groom_slug="test-slug", store=store,
    )

    # Should have a create message + approval marker
    assert any("[iterations] Created iter-1: My Iteration" in r["content"] for r in results)
    assert any(r.get("iterations_batch_approved") == "p1" for r in results)

    # Verify iteration was actually created on disk
    from gotg.config import IterationStore
    iters = IterationStore(team_dir).list_all()
    new = [it for it in iters if it["id"] == "iter-1"]
    assert len(new) == 1
    assert new[0]["status"] == "pending"


def test_apply_iteration_proposals_create_batch_ids(tmp_path):
    """3 creates in one batch get iter-1, iter-2, iter-3."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.conversation import ConversationStore
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    store = ConversationStore(groom_dir / "conversation.jsonl")

    from gotg.session_setup import apply_iteration_proposals
    proposals = [
        {"action": "create", "title": f"Iter {i}", "description": f"Build {i}"}
        for i in range(1, 4)
    ]
    results = apply_iteration_proposals(
        team_dir, proposals, batch_id="p1", groom_slug="test-slug", store=store,
    )

    from gotg.config import IterationStore
    iters = IterationStore(team_dir).list_all()
    ids = {it["id"] for it in iters}
    assert "iter-1" in ids
    assert "iter-2" in ids
    assert "iter-3" in ids


def test_apply_iteration_proposals_update(tmp_path):
    """Updates existing iteration fields."""
    team_dir = _make_team_dir(tmp_path, iterations=[
        {"id": "iter-1", "title": "Old", "description": "Old desc", "status": "in-progress", "phase": "refinement"},
    ])
    from gotg.conversation import ConversationStore
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    store = ConversationStore(groom_dir / "conversation.jsonl")

    from gotg.session_setup import apply_iteration_proposals
    results = apply_iteration_proposals(
        team_dir,
        [{"action": "update", "iteration_id": "iter-1", "title": "New Title", "description": "New desc"}],
        batch_id="p1", groom_slug="test-slug", store=store,
    )

    assert any("[iterations] Updated iter-1: New Title" in r["content"] for r in results)

    from gotg.config import IterationStore
    iters = IterationStore(team_dir).list_all()
    updated = [it for it in iters if it["id"] == "iter-1"][0]
    assert updated["title"] == "New Title"
    assert updated["description"] == "New desc"


def test_apply_iteration_proposals_update_not_found(tmp_path):
    """Soft error message for update of non-existent iteration."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.conversation import ConversationStore
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    store = ConversationStore(groom_dir / "conversation.jsonl")

    from gotg.session_setup import apply_iteration_proposals
    results = apply_iteration_proposals(
        team_dir,
        [{"action": "update", "iteration_id": "iter-99", "title": "X", "description": "Y"}],
        batch_id="p1", groom_slug="test-slug", store=store,
    )

    assert any("not found" in r["content"] for r in results)


def test_apply_iteration_proposals_mixed(tmp_path):
    """Creates + updates in one batch."""
    team_dir = _make_team_dir(tmp_path, iterations=[
        {"id": "iter-1", "title": "Existing", "description": "Old", "status": "in-progress", "phase": "refinement"},
    ])
    from gotg.conversation import ConversationStore
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    store = ConversationStore(groom_dir / "conversation.jsonl")

    from gotg.session_setup import apply_iteration_proposals
    results = apply_iteration_proposals(
        team_dir,
        [
            {"action": "create", "title": "New One", "description": "Build new"},
            {"action": "update", "iteration_id": "iter-1", "title": "Updated", "description": "Changed"},
        ],
        batch_id="p1", groom_slug="test-slug", store=store,
    )

    assert any("Created iter-2" in r["content"] for r in results)
    assert any("Updated iter-1" in r["content"] for r in results)


def test_apply_iteration_proposals_injects_messages(tmp_path):
    """System messages persisted to conversation store."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.conversation import ConversationStore
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    log_path = groom_dir / "conversation.jsonl"
    store = ConversationStore(log_path)

    from gotg.session_setup import apply_iteration_proposals
    apply_iteration_proposals(
        team_dir,
        [{"action": "create", "title": "Test", "description": "Desc"}],
        batch_id="p1", groom_slug="test-slug", store=store,
    )

    messages = store.read_full()
    assert len(messages) >= 2  # create msg + approval msg
    assert all(m["from"] == "system" for m in messages)


def test_apply_iteration_proposals_idempotent(tmp_path):
    """Re-applying same batch_id has no effect (approval marker blocks)."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.conversation import ConversationStore
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    store = ConversationStore(groom_dir / "conversation.jsonl")

    # Seed a real coach message with propose_iterations (as engine would write)
    coach_msg = {
        "from": "coach", "iteration": "test-slug",
        "content": "Here are my proposals.",
        "propose_iterations": {
            "batch_id": "p1",
            "proposals": [{"action": "create", "title": "Test", "description": "Desc"}],
            "rationale": "",
        },
    }
    store.append(coach_msg)

    from gotg.session_setup import apply_iteration_proposals

    # First apply — should find the unapproved batch
    apply_iteration_proposals(
        team_dir,
        [{"action": "create", "title": "Test", "description": "Desc"}],
        batch_id="p1", groom_slug="test-slug", store=store,
    )

    # Now scan for unapproved batches — p1 should be marked approved
    history = store.read_full()
    approved_batches = {
        m["iterations_batch_approved"] for m in history
        if "iterations_batch_approved" in m
    }
    assert "p1" in approved_batches

    # The propose_iterations message exists but its batch is approved
    proposals_msg = None
    for msg in reversed(history):
        pi = msg.get("propose_iterations")
        if pi and pi.get("batch_id") not in approved_batches:
            proposals_msg = pi
            break

    assert proposals_msg is None  # p1 already approved — no unapproved batch found


def test_apply_iteration_proposals_validation_bad_action(tmp_path):
    """Unknown action → soft error, others proceed."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.conversation import ConversationStore
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    store = ConversationStore(groom_dir / "conversation.jsonl")

    from gotg.session_setup import apply_iteration_proposals
    results = apply_iteration_proposals(
        team_dir,
        [
            {"action": "delete", "title": "Bad", "description": "Nope"},
            {"action": "create", "title": "Good", "description": "Works"},
        ],
        batch_id="p1", groom_slug="test-slug", store=store,
    )

    assert any("unknown action" in r["content"] for r in results)
    assert any("Created iter-1" in r["content"] for r in results)


def test_apply_iteration_proposals_validation_missing_fields(tmp_path):
    """Empty title/description → soft error."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.conversation import ConversationStore
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    store = ConversationStore(groom_dir / "conversation.jsonl")

    from gotg.session_setup import apply_iteration_proposals
    results = apply_iteration_proposals(
        team_dir,
        [{"action": "create", "title": "", "description": "Has desc"}],
        batch_id="p1", groom_slug="test-slug", store=store,
    )

    assert any("missing title or description" in r["content"] for r in results)


def test_apply_iteration_proposals_validation_update_no_id(tmp_path):
    """Update without iteration_id → soft error."""
    team_dir = _make_team_dir(tmp_path)
    from gotg.conversation import ConversationStore
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    store = ConversationStore(groom_dir / "conversation.jsonl")

    from gotg.session_setup import apply_iteration_proposals
    results = apply_iteration_proposals(
        team_dir,
        [{"action": "update", "title": "X", "description": "Y"}],
        batch_id="p1", groom_slug="test-slug", store=store,
    )

    assert any("missing iteration_id" in r["content"] for r in results)


# ══════════════════════════════════════════════════════════════
# Part 1: CLI / Console Events Tests
# ══════════════════════════════════════════════════════════════


def test_console_events_iterations_proposed(capsys):
    """Console handler displays proposals correctly."""
    from gotg.console_events import handle_console_events

    events = [
        SessionStarted("test-slug", "test topic", None, None, ["a1"], None,
                       False, None, 0, 0, 30),
        IterationsProposed(
            batch_id="p1",
            proposals=tuple(_SAMPLE_PROPOSALS),
            rationale="Natural scope boundaries",
        ),
    ]

    handle_console_events(
        iter(events),
        resume_hint="gotg groom continue test-slug",
    )

    captured = capsys.readouterr()
    assert "proposes 2 iteration(s)" in captured.out
    assert "[NEW] Calculator MVP" in captured.out
    assert "[NEW] State persistence" in captured.out
    assert "Natural scope boundaries" in captured.out
    assert "--approve-iterations" in captured.out


def test_console_events_grooming_complete_hint(capsys):
    """Summarize hint printed on session complete."""
    from gotg.console_events import handle_console_events
    from gotg.events import SessionComplete

    events = [
        SessionStarted("test-slug", "test topic", None, None, ["a1"], None,
                       False, None, 0, 0, 30),
        SessionComplete(total_turns=10),
    ]

    handle_console_events(
        iter(events),
        summarize_hint="gotg groom summarize test-slug",
        complete_label="Grooming",
    )

    captured = capsys.readouterr()
    assert "gotg groom summarize test-slug" in captured.out
    assert "Grooming complete" in captured.out


# ══════════════════════════════════════════════════════════════
# Part 1: Session State Tests
# ══════════════════════════════════════════════════════════════


def test_reconstruct_resume_state_iterations_proposed():
    """Detects proposals in coach message."""
    messages = [
        {"from": "coach", "iteration": "s", "content": "Here are proposals.",
         "propose_iterations": {"batch_id": "p1", "proposals": _SAMPLE_PROPOSALS, "rationale": ""}},
    ]
    state = reconstruct_resume_state(messages, None)
    assert state.pause_reason == PauseReason.ITERATIONS_PROPOSED
    assert state.iteration_proposals is not None
    assert state.iteration_proposals["batch_id"] == "p1"


def test_reconstruct_resume_state_proposals_already_approved():
    """Approved batch not detected as paused."""
    messages = [
        {"from": "coach", "iteration": "s", "content": "Proposals.",
         "propose_iterations": {"batch_id": "p1", "proposals": _SAMPLE_PROPOSALS, "rationale": ""}},
        {"from": "system", "iteration": "s", "content": "[iterations] Batch p1 approved: 2 applied.",
         "iterations_batch_approved": "p1"},
    ]
    state = reconstruct_resume_state(messages, None)
    assert state.pause_reason is None


def test_pause_reason_iterations_proposed():
    """Enum value exists and is distinct."""
    assert PauseReason.ITERATIONS_PROPOSED != PauseReason.COACH_QUESTION
    assert PauseReason.ITERATIONS_PROPOSED != PauseReason.PHASE_COMPLETE
    assert PauseReason.ITERATIONS_PROPOSED != PauseReason.APPROVALS


# ══════════════════════════════════════════════════════════════
# Part 1: Prompt Tests
# ══════════════════════════════════════════════════════════════


def test_propose_iterations_tool_in_grooming_coach_tools():
    """Tool present in GROOMING_COACH_TOOLS."""
    names = {t["name"] for t in GROOMING_COACH_TOOLS}
    assert "propose_iterations" in names


def test_propose_iterations_tool_in_iteration_coach_tools():
    """Tool IS in COACH_TOOLS (iteration coach can update sibling iterations)."""
    names = {t["name"] for t in COACH_TOOLS}
    assert "propose_iterations" in names


def test_grooming_system_supplement_mentions_iterations():
    """Iteration awareness text present in grooming supplements."""
    from gotg.prompts import GROOMING_SYSTEM_SUPPLEMENT, GROOMING_SYSTEM_SUPPLEMENT_WITH_CONTEXT
    assert "ITERATIONS:" in GROOMING_SYSTEM_SUPPLEMENT
    assert "ITERATIONS:" in GROOMING_SYSTEM_SUPPLEMENT_WITH_CONTEXT


# ══════════════════════════════════════════════════════════════
# Part 2: Summary Extraction
# ══════════════════════════════════════════════════════════════


def test_extract_grooming_summary_doc():
    """Extraction function returns summary text."""
    from gotg.transitions import extract_grooming_summary_doc

    def mock_chat(**kw):
        return "## Topic\nTest summary."

    result = extract_grooming_summary_doc(
        [{"from": "agent-1", "content": "Hello"}, {"from": "coach", "content": "Interesting"}],
        MODEL_CONFIG, "coach", chat_call=mock_chat, topic="Test topic",
    )
    assert "Test summary." in result


def test_extract_grooming_summary_doc_strips_fences():
    """Code fences stripped from LLM output."""
    from gotg.transitions import extract_grooming_summary_doc

    def mock_chat(**kw):
        return "```markdown\n## Topic\nContent\n```"

    result = extract_grooming_summary_doc(
        [{"from": "agent-1", "content": "Hello"}],
        MODEL_CONFIG, None, chat_call=mock_chat, topic="Test topic",
    )
    assert "```" not in result
    assert "## Topic" in result


def test_extract_grooming_summary_doc_includes_coach():
    """Coach messages included in transcript (unlike other extractions)."""
    from gotg.transitions import extract_grooming_summary_doc

    captured_messages = []

    def mock_chat(**kw):
        captured_messages.append(kw["messages"])
        return "Summary"

    extract_grooming_summary_doc(
        [
            {"from": "agent-1", "content": "Agent says"},
            {"from": "system", "content": "System note"},
            {"from": "coach", "content": "Coach says"},
        ],
        MODEL_CONFIG, "coach", chat_call=mock_chat, topic="Test",
    )

    transcript = captured_messages[0][1]["content"]
    assert "[agent-1]: Agent says" in transcript
    assert "[coach]: Coach says" in transcript
    assert "System note" not in transcript


def test_grooming_summary_extraction_prompt_loaded():
    """TOML constant accessible."""
    assert "{topic}" in GROOMING_SUMMARY_EXTRACTION_PROMPT
    assert "Decisions Against" in GROOMING_SUMMARY_EXTRACTION_PROMPT


# ══════════════════════════════════════════════════════════════
# Part 2: CLI groom summarize
# ══════════════════════════════════════════════════════════════


def test_cmd_groom_summarize(tmp_path, monkeypatch, capsys):
    """gotg groom summarize writes summary.md."""
    team_dir = _make_team_dir(tmp_path)
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    (groom_dir / "grooming.json").write_text(json.dumps({
        "schema_version": 2, "slug": "test-slug", "topic": "Test topic",
        "coach": False, "max_turns": 30, "status": "active", "context_from": None,
    }))
    # Write a conversation message
    from gotg.conversation import ConversationStore
    store = ConversationStore(groom_dir / "conversation.jsonl")
    store.append({"from": "agent-1", "iteration": "test-slug", "content": "Hello"})

    monkeypatch.chdir(tmp_path)

    # Mock the chat_completion and TeamContext
    monkeypatch.setattr("gotg.commands.groom.TeamContext", type("TC", (), {
        "from_team_dir": staticmethod(lambda td: type("Ctx", (), {
            "coach": None, "model_config": MODEL_CONFIG,
        })()),
    }))
    import gotg.model
    monkeypatch.setattr(gotg.model, "chat_completion", lambda **kw: "## Topic\nTest summary.")

    import argparse
    args = argparse.Namespace(slug="test-slug")
    from gotg.commands.groom import cmd_groom_summarize
    cmd_groom_summarize(args)

    assert (groom_dir / "summary.md").exists()
    assert "Test summary." in (groom_dir / "summary.md").read_text()
    captured = capsys.readouterr()
    assert "Summary written to" in captured.out


def test_cmd_groom_summarize_empty(tmp_path, monkeypatch, capsys):
    """Error on empty conversation."""
    team_dir = _make_team_dir(tmp_path)
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    (groom_dir / "grooming.json").write_text(json.dumps({
        "schema_version": 2, "slug": "test-slug", "topic": "Test topic",
        "coach": False, "max_turns": 30, "status": "active", "context_from": None,
    }))
    (groom_dir / "conversation.jsonl").touch()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("gotg.commands.groom.TeamContext", type("TC", (), {
        "from_team_dir": staticmethod(lambda td: type("Ctx", (), {
            "coach": None, "model_config": MODEL_CONFIG,
        })()),
    }))

    import argparse
    args = argparse.Namespace(slug="test-slug")
    from gotg.commands.groom import cmd_groom_summarize
    with pytest.raises(SystemExit):
        cmd_groom_summarize(args)

    captured = capsys.readouterr()
    assert "No messages to summarize" in captured.err


# ══════════════════════════════════════════════════════════════
# Part 1: CLI groom continue --approve-iterations
# ══════════════════════════════════════════════════════════════


def test_groom_continue_approve_no_proposals(tmp_path, monkeypatch, capsys):
    """Error when no pending proposals exist."""
    team_dir = _make_team_dir(tmp_path)
    groom_dir = team_dir / "grooming" / "test-slug"
    groom_dir.mkdir(parents=True)
    (groom_dir / "grooming.json").write_text(json.dumps({
        "schema_version": 2, "slug": "test-slug", "topic": "Test topic",
        "coach": True, "max_turns": 30, "status": "active", "context_from": None,
    }))
    (groom_dir / "conversation.jsonl").touch()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("gotg.commands.groom.TeamContext", type("TC", (), {
        "from_team_dir": staticmethod(lambda td: type("Ctx", (), {
            "agents": AGENTS, "coach": COACH, "model_config": MODEL_CONFIG,
            "project_root": tmp_path, "file_access": None, "model_resolver": None,
        })()),
    }))

    import argparse
    args = argparse.Namespace(
        slug="test-slug", approve_iterations=True, message=None, max_turns=None,
    )
    from gotg.commands.groom import cmd_groom_continue
    with pytest.raises(SystemExit):
        cmd_groom_continue(args)

    captured = capsys.readouterr()
    assert "no pending iteration proposals" in captured.err


def test_groom_continue_approve_and_message_exclusive():
    """--approve-iterations and -m can't be combined (argparse mutual exclusion)."""
    from gotg.cli import main
    import sys

    with pytest.raises(SystemExit) as exc_info:
        sys.argv = ["gotg", "groom", "continue", "test", "--approve-iterations", "-m", "hello"]
        main()

    assert exc_info.value.code == 2  # argparse exits with 2 on error


# ══════════════════════════════════════════════════════════════
# end_grooming Coach Tool
# ══════════════════════════════════════════════════════════════

_END_GROOMING_TOOL_CALL = {
    "name": "end_grooming",
    "input": {"summary": "Discussed calculator UI — agreed on REPL-first approach."},
}


def test_coach_end_grooming_yields_session_complete():
    """Coach end_grooming tool call → SessionComplete event."""
    deps = _make_deps(
        coach_response={
            "content": "Great discussion. Wrapping up.",
            "tool_calls": [_END_GROOMING_TOOL_CALL],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[],
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    completes = _events_of_type(events, SessionComplete)
    assert len(completes) == 1
    # Coach message should still be appended before SessionComplete
    coach_msgs = [
        e for e in _events_of_type(events, AppendMessage)
        if e.msg.get("from") == "coach"
    ]
    assert len(coach_msgs) == 1
    assert "Wrapping up" in coach_msgs[0].msg["content"]


def test_coach_end_grooming_fallback_text():
    """Empty coach text gets fallback when end_grooming called."""
    deps = _make_deps(
        coach_response={
            "content": "",
            "tool_calls": [_END_GROOMING_TOOL_CALL],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[],
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    coach_msgs = [
        e for e in _events_of_type(events, AppendMessage)
        if e.msg.get("from") == "coach"
    ]
    assert "(Grooming concluded.)" in coach_msgs[0].msg["content"]


def test_coach_end_grooming_priority_over_ask_pm():
    """When coach calls both end_grooming and ask_pm, end_grooming wins."""
    deps = _make_deps(
        coach_response={
            "content": "Wrapping up.",
            "tool_calls": [
                _END_GROOMING_TOOL_CALL,
                {"name": "ask_pm", "input": {"question": "Anything else?"}},
            ],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[],
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    completes = _events_of_type(events, SessionComplete)
    asks = _events_of_type(events, CoachAskedPM)
    assert len(completes) == 1
    assert len(asks) == 0
    # ask_pm should NOT be attached to coach_msg
    coach_msgs = [
        e for e in _events_of_type(events, AppendMessage)
        if e.msg.get("from") == "coach"
    ]
    assert "ask_pm" not in coach_msgs[0].msg


def test_propose_iterations_priority_over_end_grooming():
    """When coach calls both propose_iterations and end_grooming, proposals win."""
    deps = _make_deps(
        coach_response={
            "content": "Final proposals before wrapping up.",
            "tool_calls": [_PROPOSE_TOOL_CALL, _END_GROOMING_TOOL_CALL],
        },
    )
    events = _collect(run_session(
        agents=AGENTS, iteration=ITERATION, model_config=MODEL_CONFIG,
        deps=deps, history=[],
        policy=_make_policy(max_turns=2, coach=COACH, coach_cadence=2),
    ))
    proposals = _events_of_type(events, IterationsProposed)
    completes = _events_of_type(events, SessionComplete)
    assert len(proposals) == 1
    assert len(completes) == 0  # proposals take priority, session pauses for review


def test_end_grooming_tool_in_grooming_coach_tools():
    """Tool present in GROOMING_COACH_TOOLS."""
    names = {t["name"] for t in GROOMING_COACH_TOOLS}
    assert "end_grooming" in names


def test_end_grooming_tool_not_in_iteration_coach_tools():
    """Tool NOT in COACH_TOOLS (iteration coach)."""
    names = {t["name"] for t in COACH_TOOLS}
    assert "end_grooming" not in names
