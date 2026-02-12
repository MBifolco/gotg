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
COACH_GROOMING_PROMPT = COACH_REFINEMENT_PROMPT  # backward-compat alias
COACH_PLANNING_PROMPT: str = _DEFAULTS["extraction"]["task_extraction"]["prompt"]
COACH_NOTES_EXTRACTION_PROMPT: str = _DEFAULTS["extraction"]["notes_extraction"]["prompt"]
MERGE_CONFLICT_PROMPT: str = _DEFAULTS["extraction"]["merge_conflict"]["prompt"]

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

COACH_TOOLS: list[dict] = [
    {
        "name": "signal_phase_complete",
        "description": _DEFAULTS["tools"]["signal_phase_complete"]["description"],
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of what was resolved in this phase",
                }
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

# ── Grooming mode constants ──────────────────────────────────────

GROOMING_SYSTEM_SUPPLEMENT: str = _DEFAULTS["grooming"]["system"]
GROOMING_COACH_PROMPT: str = _DEFAULTS["grooming"]["coach"]
GROOMING_KICKOFF_TEMPLATE: str = _DEFAULTS["grooming"]["kickoff"]
GROOMING_COACH_TOOLS: list[dict] = [t for t in COACH_TOOLS if t["name"] == "ask_pm"]
