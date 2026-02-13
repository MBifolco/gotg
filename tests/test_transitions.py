import json

import pytest

from gotg.scaffold import COACH_REFINEMENT_PROMPT, COACH_PLANNING_PROMPT
from gotg.transitions import (
    strip_code_fences,
    extract_conversation_for_coach,
    extract_refinement_summary,
    extract_tasks,
    extract_task_notes,
    resolve_merge_conflict,
    build_transition_messages,
)


MODEL_CONFIG = {
    "provider": "ollama",
    "base_url": "http://localhost:11434",
    "model": "test-model",
}


# --- strip_code_fences ---

def test_strip_code_fences_basic():
    assert strip_code_fences("```json\n[1, 2]\n```") == "[1, 2]"


def test_strip_code_fences_no_fences():
    assert strip_code_fences("plain text") == "plain text"


def test_strip_code_fences_nested():
    text = "```\nouter\n```inner```\n```"
    result = strip_code_fences(text)
    assert "inner" in result


# --- extract_conversation_for_coach ---

def test_extract_conversation_excludes_system_and_coach():
    history = [
        {"from": "agent-1", "content": "Hello"},
        {"from": "system", "content": "kickoff"},
        {"from": "coach", "content": "Good job"},
        {"from": "agent-2", "content": "World"},
    ]
    result = extract_conversation_for_coach(history, "coach")
    assert "[agent-1]: Hello" in result
    assert "[agent-2]: World" in result
    assert "kickoff" not in result
    assert "Good job" not in result


def test_extract_conversation_transcript_format():
    """Regression guard: exact format is [speaker]: content with \\n\\n separators, no markers."""
    history = [
        {"from": "agent-1", "content": "First"},
        {"from": "agent-2", "content": "Second"},
    ]
    result = extract_conversation_for_coach(history, "coach")
    assert result == "[agent-1]: First\n\n[agent-2]: Second"
    assert "TRANSCRIPT" not in result


# --- extract_refinement_summary ---

def test_extract_refinement_summary():
    captured = []

    def mock_chat(**kwargs):
        captured.append(kwargs)
        return "## Summary\nDone."

    history = [
        {"from": "agent-1", "content": "We should build X"},
        {"from": "system", "content": "kickoff"},
    ]
    result = extract_refinement_summary(history, MODEL_CONFIG, "coach", mock_chat)
    assert result == "## Summary\nDone."
    assert len(captured) == 1
    msgs = captured[0]["messages"]
    assert msgs[0]["content"] == COACH_REFINEMENT_PROMPT
    assert msgs[1]["content"].startswith("=== TRANSCRIPT START ===")
    assert msgs[1]["content"].endswith("=== TRANSCRIPT END ===")
    assert "We should build X" in msgs[1]["content"]
    assert "kickoff" not in msgs[1]["content"]


# --- extract_tasks ---

def test_extract_tasks_success():
    tasks_json = json.dumps([
        {"id": "t1", "description": "Do thing", "done_criteria": "Done",
         "depends_on": [], "assigned_to": None, "status": "pending"},
    ])

    def mock_chat(**kwargs):
        return tasks_json

    history = [{"from": "agent-1", "content": "Plan: do thing"}]
    tasks, raw, error = extract_tasks(history, MODEL_CONFIG, "coach", mock_chat)
    assert tasks is not None
    assert raw is None
    assert error is None
    assert tasks[0]["id"] == "t1"
    assert "layer" in tasks[0]


def test_extract_tasks_preserves_approach_field():
    """approach field from LLM output survives compute_layers and is stored."""
    tasks_json = json.dumps([
        {"id": "t1", "description": "Do thing", "done_criteria": "Done",
         "depends_on": [], "assigned_to": None, "status": "pending",
         "approach": "Use eval() after validation."},
    ])

    def mock_chat(**kwargs):
        return tasks_json

    history = [{"from": "agent-1", "content": "Plan: use eval"}]
    tasks, raw, error = extract_tasks(history, MODEL_CONFIG, "coach", mock_chat)
    assert tasks is not None
    assert error is None
    assert tasks[0]["approach"] == "Use eval() after validation."
    assert "layer" in tasks[0]


def test_extract_tasks_invalid_json():
    def mock_chat(**kwargs):
        return "not json at all"

    history = [{"from": "agent-1", "content": "Plan"}]
    tasks, raw, error = extract_tasks(history, MODEL_CONFIG, "coach", mock_chat)
    assert tasks is None
    assert raw == "not json at all"
    assert "Coach produced invalid JSON:" in error
    assert not error.startswith("Warning:")


def test_extract_tasks_bad_structure():
    # Valid JSON but compute_layers will fail (no "id" or "depends_on")
    def mock_chat(**kwargs):
        return json.dumps([{"foo": "bar"}])

    history = [{"from": "agent-1", "content": "Plan"}]
    tasks, raw, error = extract_tasks(history, MODEL_CONFIG, "coach", mock_chat)
    assert tasks is None
    assert raw is not None
    assert "bad task structure" in error
    assert not error.startswith("Warning:")


def test_extract_tasks_strips_code_fences():
    tasks_json = json.dumps([
        {"id": "t1", "description": "Do thing", "done_criteria": "Done",
         "depends_on": [], "assigned_to": None, "status": "pending"},
    ])

    def mock_chat(**kwargs):
        return f"```json\n{tasks_json}\n```"

    history = [{"from": "agent-1", "content": "Plan"}]
    tasks, raw, error = extract_tasks(history, MODEL_CONFIG, "coach", mock_chat)
    assert tasks is not None
    assert tasks[0]["id"] == "t1"


# --- extract_task_notes ---

def test_extract_task_notes_success():
    def mock_chat(**kwargs):
        return json.dumps([{"id": "t1", "notes": "Use src/main.py"}])

    history = [{"from": "agent-1", "content": "Proposal"}]
    tasks_data = [{"id": "t1", "description": "Do thing"}]
    notes_map, raw, error = extract_task_notes(
        history, tasks_data, MODEL_CONFIG, "coach", mock_chat,
    )
    assert notes_map == {"t1": "Use src/main.py"}
    assert raw is None
    assert error is None


def test_extract_task_notes_bad_json():
    def mock_chat(**kwargs):
        return "not json"

    history = [{"from": "agent-1", "content": "Proposal"}]
    tasks_data = [{"id": "t1", "description": "Do thing"}]
    notes_map, raw, error = extract_task_notes(
        history, tasks_data, MODEL_CONFIG, "coach", mock_chat,
    )
    assert notes_map is None
    assert raw == "not json"
    assert "Could not parse task notes:" in error
    assert not error.startswith("Warning:")


# --- build_transition_messages ---

def test_build_transition_messages_basic():
    boundary, transition = build_transition_messages("iter-1", "refinement", "planning")
    assert boundary["content"] == "--- HISTORY BOUNDARY ---"
    assert boundary["phase_boundary"] is True
    assert boundary["from_phase"] == "refinement"
    assert boundary["to_phase"] == "planning"
    assert boundary["from"] == "system"
    assert boundary["iteration"] == "iter-1"
    assert transition["content"] == "--- Phase advanced: refinement → planning ---"
    assert transition["from"] == "system"
    assert transition["iteration"] == "iter-1"


def test_build_transition_messages_tasks_written():
    _, transition = build_transition_messages(
        "iter-1", "planning", "pre-code-review", tasks_written=True,
    )
    assert transition["content"] == "--- Phase advanced: planning → pre-code-review. Task list written to tasks.json ---"


def test_build_transition_messages_refinement_coach():
    _, transition = build_transition_messages(
        "iter-1", "refinement", "planning", coach_ran=True,
    )
    assert transition["content"] == "--- Phase advanced: refinement → planning. Scope summary written to refinement_summary.md ---"


# ── resolve_merge_conflict ───────────────────────────────────


def test_resolve_merge_conflict_parses_json():
    """Returns (content, explanation) when LLM returns valid JSON."""
    llm_response = json.dumps({
        "content": "merged code here",
        "explanation": "Combined both changes",
    })

    def mock_chat(**kwargs):
        return llm_response

    content, explanation = resolve_merge_conflict(
        "src/main.py", "agent-1/layer-0",
        base_content="original", ours_content="ours", theirs_content="theirs",
        task_context="Task context", model_config=MODEL_CONFIG, chat_call=mock_chat,
    )
    assert content == "merged code here"
    assert explanation == "Combined both changes"


def test_resolve_merge_conflict_strips_fences():
    """Strips markdown code fences from LLM response."""
    llm_response = '```json\n{"content": "clean", "explanation": "merged"}\n```'

    def mock_chat(**kwargs):
        return llm_response

    content, _ = resolve_merge_conflict(
        "f.py", "b", None, "ours", "theirs", "ctx",
        MODEL_CONFIG, mock_chat,
    )
    assert content == "clean"


def test_resolve_merge_conflict_raises_on_bad_json():
    """Raises ValueError on invalid JSON from LLM."""
    def mock_chat(**kwargs):
        return "I cannot resolve this conflict."

    with pytest.raises(ValueError, match="Could not parse AI resolution"):
        resolve_merge_conflict(
            "f.py", "b", "base", "ours", "theirs", "ctx",
            MODEL_CONFIG, mock_chat,
        )


def test_resolve_merge_conflict_base_none_no_crash():
    """Works when base_content is None (add/add conflict)."""
    llm_response = json.dumps({"content": "merged", "explanation": "ok"})

    def mock_chat(**kwargs):
        # Verify the prompt contains the no-ancestor message
        msg = kwargs.get("messages", [{}])[0].get("content", "")
        assert "No common ancestor" in msg
        return llm_response

    content, _ = resolve_merge_conflict(
        "f.py", "b", None, "ours", "theirs", "ctx",
        MODEL_CONFIG, mock_chat,
    )


# --- extract_tasks with refinement_summary ---

def test_extract_tasks_passes_refinement_summary():
    """refinement_summary appears in LLM user message when provided."""
    captured = []

    def mock_chat(**kwargs):
        captured.append(kwargs)
        return '[{"id": "t1", "description": "Do thing", "done_criteria": "Done", "depends_on": [], "assigned_to": null, "status": "pending"}]'

    history = [
        {"from": "agent-1", "content": "Let's build the timer"},
    ]
    extract_tasks(history, MODEL_CONFIG, "coach", mock_chat, refinement_summary="## Out of Scope\n- No pause/resume")
    assert len(captured) == 1
    user_msg = captured[0]["messages"][1]["content"]
    assert "SCOPE SUMMARY" in user_msg
    assert "No pause/resume" in user_msg


def test_extract_tasks_no_summary_backward_compat():
    """extract_tasks works without refinement_summary (backward compat)."""
    captured = []

    def mock_chat(**kwargs):
        captured.append(kwargs)
        return '[{"id": "t1", "description": "Do thing", "done_criteria": "Done", "depends_on": [], "assigned_to": null, "status": "pending"}]'

    history = [{"from": "agent-1", "content": "Build it"}]
    tasks, _, _ = extract_tasks(history, MODEL_CONFIG, "coach", mock_chat)
    assert tasks is not None
    user_msg = captured[0]["messages"][1]["content"]
    assert "SCOPE SUMMARY" not in user_msg


def test_extract_tasks_preserves_anti_patterns():
    """anti_patterns array survives extract_tasks."""
    def mock_chat(**kwargs):
        return json.dumps([{
            "id": "t1", "description": "Do thing",
            "done_criteria": "Done", "depends_on": [],
            "assigned_to": None, "status": "pending",
            "anti_patterns": ["Do not use eval()"],
        }])

    tasks, _, _ = extract_tasks(
        [{"from": "agent-1", "content": "Build it"}],
        MODEL_CONFIG, "coach", mock_chat,
    )
    assert tasks[0]["anti_patterns"] == ["Do not use eval()"]


# --- build_phase_skeleton ---

from gotg.transitions import build_phase_skeleton


def test_build_phase_skeleton_basic():
    history = [
        {"from": "agent-1", "content": "We agreed to use eval()."},
        {"from": "agent-2", "content": "Sounds good."},
    ]
    result = build_phase_skeleton(history, "refinement", "coach")
    assert "Decisions:" in result
    assert "Conversation index:" in result
    assert "## REFINEMENT phase" in result


def test_build_phase_skeleton_extracts_decisions():
    history = [
        {"from": "agent-1", "content": "We agreed to use eval(). Let's go with Python."},
        {"from": "agent-2", "content": "I will use the standard library."},
    ]
    result = build_phase_skeleton(history, "planning", "coach")
    assert "agreed" in result.lower()
    assert "will use" in result.lower()


def test_build_phase_skeleton_filters_system_and_pass_turn():
    history = [
        {"from": "system", "content": "kickoff msg"},
        {"from": "agent-1", "content": "We agreed on X.", "pass_turn": True},
        {"from": "agent-2", "content": "We decided to use Y."},
    ]
    result = build_phase_skeleton(history, "refinement", "coach")
    assert "kickoff" not in result
    assert "agreed on X" not in result
    assert "decided to use Y" in result


def test_build_phase_skeleton_truncates_long_messages():
    long_msg = "A" * 200 + ". We agreed on this."
    history = [{"from": "agent-1", "content": long_msg}]
    result = build_phase_skeleton(history, "planning", "coach")
    # Index line should be truncated
    index_section = result.split("Conversation index:")[1]
    for line in index_section.strip().split("\n"):
        if line.startswith("["):
            assert len(line) <= 120  # [agent-1]: + 97 + ... = ~110


def test_build_phase_skeleton_empty_history():
    result = build_phase_skeleton([], "refinement", "coach")
    assert "## REFINEMENT phase" in result
    assert "Conversation index:" in result


def test_build_phase_skeleton_no_decisions():
    history = [
        {"from": "agent-1", "content": "Hello there."},
        {"from": "agent-2", "content": "Good morning."},
    ]
    result = build_phase_skeleton(history, "planning", "coach")
    assert "Decisions:" not in result
    assert "Conversation index:" in result


def test_build_phase_skeleton_caps_index_at_15():
    history = [
        {"from": f"agent-{i % 2 + 1}", "content": f"Message {i}."}
        for i in range(20)
    ]
    result = build_phase_skeleton(history, "refinement", "coach")
    index_section = result.split("Conversation index:")[1].strip()
    index_lines = [l for l in index_section.split("\n") if l.strip().startswith("[")]
    assert len(index_lines) == 15


def test_build_phase_skeleton_captures_instead_of():
    history = [
        {"from": "agent-1", "content": "We should use X instead of Y."},
        {"from": "agent-2", "content": "Rather than building custom code, let's import."},
    ]
    result = build_phase_skeleton(history, "planning", "coach")
    decisions = result.split("Decisions:")[1].split("Conversation index:")[0]
    assert "instead of" in decisions.lower()
    assert "rather than" in decisions.lower()


def test_build_phase_skeleton_captures_backtick_code():
    history = [
        {"from": "agent-1", "content": "We should implement `parse_expression()` for this."},
    ]
    result = build_phase_skeleton(history, "planning", "coach")
    assert "parse_expression" in result
