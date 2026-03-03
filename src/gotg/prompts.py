from __future__ import annotations

import tomllib
from importlib import resources


def _load_builtin() -> dict:
    """Load builtin default prompts via importlib.resources (wheel-safe)."""
    ref = resources.files("gotg.data").joinpath("default_prompts.toml")
    with resources.as_file(ref) as path:
        with open(path, "rb") as f:
            return tomllib.load(f)


_DEFAULTS = _load_builtin()

# ── Module-level constants (same names as scaffold.py) ───────────

DEFAULT_SYSTEM_PROMPT: str = _DEFAULTS["system"]["prompt"]

PHASE_PROMPTS: dict[str, str] = {
    phase: data["prompt"]
    for phase, data in _DEFAULTS["phases"].items()
    if "prompt" in data
}

COACH_FACILITATION_PROMPT: str = _DEFAULTS["phases"]["refinement"]["coach"]["facilitation"]

COACH_FACILITATION_PROMPTS: dict[str, str] = {
    phase: data["coach"]["facilitation"]
    for phase, data in _DEFAULTS["phases"].items()
    if "coach" in data and "facilitation" in data["coach"]
}

COACH_REFINEMENT_PROMPT: str = _DEFAULTS["extraction"]["refinement_summary"]["prompt"]
COACH_PLANNING_PROMPT: str = _DEFAULTS["extraction"]["task_extraction"]["prompt"]
COACH_NOTES_EXTRACTION_PROMPT: str = _DEFAULTS["extraction"]["notes_extraction"]["prompt"]
EXPLORATION_SUMMARY_EXTRACTION_PROMPT: str = _DEFAULTS["extraction"]["exploration_summary"]["prompt"]
MERGE_CONFLICT_PROMPT: str = _DEFAULTS["extraction"]["merge_conflict"]["prompt"]
REVIEW_FEEDBACK_EXTRACTION_PROMPT: str = _DEFAULTS["extraction"]["review_feedback"]["prompt"]
DRIFT_CHECK_PROMPT: str = _DEFAULTS["verification"]["drift_check"]["prompt"]

PHASE_KICKOFF_MESSAGES: dict[str, str] = {
    phase: data["kickoff"]
    for phase, data in _DEFAULTS["phases"].items()
    if "kickoff" in data
}


# ── Tool definitions (descriptions from TOML, schemas in Python) ─

AGENT_TOOLS: list[dict] = [
    {
        "name": "pass_turn",
        "description": _DEFAULTS["tools"]["pass_turn"]["description"],
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason for passing (e.g., 'agree with proposal', 'waiting for layer 2')",
                }
            },
            "required": ["reason"],
        },
    }
]

COACH_PASS_TURN_TOOL: dict = {
    "name": "coach_pass_turn",
    "description": _DEFAULTS["tools"]["coach_pass_turn"]["description"],
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

GUIDE_DISCUSSION_TOOL: dict = {
    "name": "guide_discussion",
    "description": _DEFAULTS["tools"]["guide_discussion"]["description"],
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Your facilitation message — redirect, summarize, assign speakers, or focus the team.",
            },
        },
        "required": ["message"],
    },
}

COACH_TOOLS: list[dict] = [
    COACH_PASS_TURN_TOOL,
    GUIDE_DISCUSSION_TOOL,
    {
        "name": "signal_phase_complete",
        "description": _DEFAULTS["tools"]["signal_phase_complete"]["description"],
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of what was resolved in this phase",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["approved", "changes_requested"],
                    "description": (
                        "For code-review: 'approved' when all concerns resolved, "
                        "'changes_requested' when rework needed. Defaults to 'approved'."
                    ),
                },
            },
            "required": ["summary"],
        },
    },
    {
        "name": "ask_pm",
        "description": _DEFAULTS["tools"]["ask_pm"]["description"],
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "What you need the PM to decide or clarify",
                },
                "response_type": {
                    "type": "string",
                    "enum": ["feedback", "decision"],
                    "description": (
                        "Use 'feedback' for open-ended questions. "
                        "Use 'decision' when offering the PM a fixed set of choices."
                    ),
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "When response_type is 'decision', provide 2-5 concise "
                        "option labels for the PM to choose from."
                    ),
                },
            },
            "required": ["question"],
        },
    },
]

# ── Exploration mode constants ──────────────────────────────────────

EXPLORATION_SYSTEM_SUPPLEMENT: str = _DEFAULTS["exploration"]["system"]
EXPLORATION_SYSTEM_SUPPLEMENT_WITH_CONTEXT: str = _DEFAULTS["exploration"]["system_with_context"]
EXPLORATION_COACH_PROMPT: str = _DEFAULTS["exploration"]["coach"]
EXPLORATION_KICKOFF_TEMPLATE: str = _DEFAULTS["exploration"]["kickoff"]
EXPLORATION_KICKOFF_WITH_CONTEXT_AND_TOOLS_TEMPLATE: str = _DEFAULTS["exploration"]["kickoff_with_context_and_tools"]
EXPLORATION_KICKOFF_WITH_CONTEXT_TEMPLATE: str = _DEFAULTS["exploration"]["kickoff_with_context"]
COMPLETE_TASKS_TOOL: dict = {
    "name": "complete_tasks",
    "description": _DEFAULTS["tools"]["complete_tasks"]["description"],
    "input_schema": {
        "type": "object",
        "properties": {
            "task_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "IDs of tasks you completed in this layer",
            },
            "summary": {
                "type": "string",
                "description": "Brief summary of what you built/changed",
            },
        },
        "required": ["task_ids", "summary"],
    },
}

REPORT_BLOCKED_TOOL: dict = {
    "name": "report_blocked",
    "description": _DEFAULTS["tools"]["report_blocked"]["description"],
    "input_schema": {
        "type": "object",
        "properties": {
            "task_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "IDs of tasks you are blocked on in this layer",
            },
            "reason": {
                "type": "string",
                "description": "Concise blocker reason",
            },
        },
        "required": ["task_ids", "reason"],
    },
}

PROPOSE_ITERATIONS_TOOL: dict = {
    "name": "propose_iterations",
    "description": _DEFAULTS["tools"]["propose_iterations"]["description"],
    "input_schema": {
        "type": "object",
        "properties": {
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["create", "update"],
                        },
                        "iteration_id": {
                            "type": "string",
                            "description": "Required for 'update'. The ID of the existing iteration to modify.",
                        },
                        "title": {"type": "string"},
                        "description": {
                            "type": "string",
                            "description": "What this iteration should accomplish — scope, key requirements, acceptance criteria",
                        },
                    },
                    "required": ["action", "title", "description"],
                },
            },
            "rationale": {
                "type": "string",
                "description": "Brief explanation of why these iterations are proposed",
            },
        },
        "required": ["proposals", "rationale"],
    },
}

END_EXPLORATION_TOOL: dict = {
    "name": "end_exploration",
    "description": _DEFAULTS["tools"]["end_exploration"]["description"],
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Brief summary of what was discussed and any key outcomes",
            },
        },
        "required": ["summary"],
    },
}

# Add propose_iterations to iteration coach tools (update sibling iterations during any phase)
COACH_TOOLS.append(PROPOSE_ITERATIONS_TOOL)

EXPLORATION_COACH_TOOLS: list[dict] = [
    COACH_PASS_TURN_TOOL,
    GUIDE_DISCUSSION_TOOL,
] + [
    t for t in COACH_TOOLS if t["name"] == "ask_pm"
] + [PROPOSE_ITERATIONS_TOOL, END_EXPLORATION_TOOL]
