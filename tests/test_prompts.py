"""Tests for gotg.prompts — loading infrastructure, not prompt content."""

from gotg.prompts import (
    _DEFAULTS,
    DEFAULT_SYSTEM_PROMPT,
    PHASE_PROMPTS,
    COACH_FACILITATION_PROMPT,
    COACH_FACILITATION_PROMPTS,
    COACH_REFINEMENT_PROMPT,
    COACH_GROOMING_PROMPT,
    COACH_PLANNING_PROMPT,
    COACH_NOTES_EXTRACTION_PROMPT,
    PHASE_KICKOFF_MESSAGES,
    AGENT_TOOLS,
    COACH_TOOLS,
)


def test_defaults_loaded():
    assert _DEFAULTS
    assert "system" in _DEFAULTS
    assert "phases" in _DEFAULTS
    assert "extraction" in _DEFAULTS
    assert "tools" in _DEFAULTS


def test_system_prompt_is_string():
    assert isinstance(DEFAULT_SYSTEM_PROMPT, str)
    assert len(DEFAULT_SYSTEM_PROMPT) > 0


def test_phase_prompts_has_all_phases():
    expected = {"refinement", "planning", "pre-code-review", "implementation", "code-review"}
    assert set(PHASE_PROMPTS.keys()) == expected


def test_dashed_phase_keys_present():
    """Regression guard: TOML table headers with dashes parse correctly."""
    assert "pre-code-review" in _DEFAULTS["phases"]
    assert "code-review" in _DEFAULTS["phases"]


def test_coach_facilitation_prompts_has_all_phases():
    expected = {"refinement", "planning", "pre-code-review", "implementation", "code-review"}
    assert set(COACH_FACILITATION_PROMPTS.keys()) == expected


def test_kickoff_messages_has_all_phases():
    expected = {"refinement", "planning", "pre-code-review", "implementation", "code-review"}
    assert set(PHASE_KICKOFF_MESSAGES.keys()) == expected


def test_extraction_prompts_exist():
    assert isinstance(COACH_REFINEMENT_PROMPT, str) and COACH_REFINEMENT_PROMPT
    assert COACH_GROOMING_PROMPT is COACH_REFINEMENT_PROMPT  # backward-compat alias
    assert isinstance(COACH_PLANNING_PROMPT, str) and COACH_PLANNING_PROMPT
    assert isinstance(COACH_NOTES_EXTRACTION_PROMPT, str) and COACH_NOTES_EXTRACTION_PROMPT


def test_agent_tools_structure():
    assert len(AGENT_TOOLS) == 1
    tool = AGENT_TOOLS[0]
    assert tool["name"] == "pass_turn"
    assert "description" in tool
    assert "input_schema" in tool
    assert tool["input_schema"]["type"] == "object"


def test_coach_tools_structure():
    assert len(COACH_TOOLS) == 2
    names = {t["name"] for t in COACH_TOOLS}
    assert names == {"signal_phase_complete", "ask_pm"}


def test_tool_descriptions_from_toml():
    for tool in AGENT_TOOLS + COACH_TOOLS:
        assert isinstance(tool["description"], str)
        assert len(tool["description"]) > 0


def test_task_extraction_prompt_mentions_approach():
    assert "approach" in COACH_PLANNING_PROMPT.lower()


def test_pre_code_review_coach_mentions_approach():
    prompt = COACH_FACILITATION_PROMPTS["pre-code-review"]
    assert "approach" in prompt.lower()


def test_implementation_coach_mentions_approach():
    prompt = COACH_FACILITATION_PROMPTS["implementation"]
    assert "approach" in prompt.lower()
