import json

from gotg.scaffold import COACH_GROOMING_PROMPT, COACH_PLANNING_PROMPT
from gotg.transitions import (
    strip_code_fences,
    extract_conversation_for_coach,
    extract_grooming_summary,
    extract_tasks,
    extract_task_notes,
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


# --- extract_grooming_summary ---

def test_extract_grooming_summary():
    captured = []

    def mock_chat(**kwargs):
        captured.append(kwargs)
        return "## Summary\nDone."

    history = [
        {"from": "agent-1", "content": "We should build X"},
        {"from": "system", "content": "kickoff"},
    ]
    result = extract_grooming_summary(history, MODEL_CONFIG, "coach", mock_chat)
    assert result == "## Summary\nDone."
    assert len(captured) == 1
    msgs = captured[0]["messages"]
    assert msgs[0]["content"] == COACH_GROOMING_PROMPT
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
    boundary, transition = build_transition_messages("iter-1", "grooming", "planning")
    assert boundary["content"] == "--- HISTORY BOUNDARY ---"
    assert boundary["phase_boundary"] is True
    assert boundary["from_phase"] == "grooming"
    assert boundary["to_phase"] == "planning"
    assert boundary["from"] == "system"
    assert boundary["iteration"] == "iter-1"
    assert transition["content"] == "--- Phase advanced: grooming → planning ---"
    assert transition["from"] == "system"
    assert transition["iteration"] == "iter-1"


def test_build_transition_messages_tasks_written():
    _, transition = build_transition_messages(
        "iter-1", "planning", "pre-code-review", tasks_written=True,
    )
    assert transition["content"] == "--- Phase advanced: planning → pre-code-review. Task list written to tasks.json ---"


def test_build_transition_messages_grooming_coach():
    _, transition = build_transition_messages(
        "iter-1", "grooming", "planning", coach_ran=True,
    )
    assert transition["content"] == "--- Phase advanced: grooming → planning. Scope summary written to groomed.md ---"
