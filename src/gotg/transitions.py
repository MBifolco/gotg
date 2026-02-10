from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from gotg.scaffold import (
    COACH_GROOMING_PROMPT, COACH_PLANNING_PROMPT, COACH_NOTES_EXTRACTION_PROMPT,
)
from gotg.tasks import compute_layers


def strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def extract_conversation_for_coach(history: list[dict], coach_name: str) -> str:
    """Filter and format conversation for coach extraction.

    Excludes system and coach messages.  Returns RAW text — no transcript
    markers.  Callers add their own framing.
    """
    return "\n\n".join(
        f"[{m['from']}]: {m['content']}"
        for m in history
        if m["from"] not in ("system", coach_name)
    )


# --- Extraction functions (bridge pattern — chat_call parameter) ---


def extract_grooming_summary(
    history: list[dict],
    model_config: dict,
    coach_name: str,
    chat_call: Callable,
) -> str:
    """One-shot LLM call to summarize grooming conversation.  Returns markdown."""
    conversation_text = extract_conversation_for_coach(history, coach_name)
    messages = [
        {"role": "system", "content": COACH_GROOMING_PROMPT},
        {"role": "user", "content": f"=== TRANSCRIPT START ===\n{conversation_text}\n=== TRANSCRIPT END ==="},
    ]
    return chat_call(
        base_url=model_config["base_url"],
        model=model_config["model"],
        messages=messages,
        api_key=model_config.get("api_key"),
        provider=model_config.get("provider", "ollama"),
    )


def extract_tasks(
    history: list[dict],
    model_config: dict,
    coach_name: str,
    chat_call: Callable,
) -> tuple[list[dict] | None, str | None, str | None]:
    """One-shot LLM call to extract tasks.

    Returns (tasks_with_layers, raw_text, error_msg).
    On success: (tasks, None, None).  On failure: (None, raw_text, error_msg).
    """
    conversation_text = extract_conversation_for_coach(history, coach_name)
    messages = [
        {"role": "system", "content": COACH_PLANNING_PROMPT},
        {"role": "user", "content": f"=== TRANSCRIPT START ===\n{conversation_text}\n=== TRANSCRIPT END ==="},
    ]
    tasks_json_text = chat_call(
        base_url=model_config["base_url"],
        model=model_config["model"],
        messages=messages,
        api_key=model_config.get("api_key"),
        provider=model_config.get("provider", "ollama"),
    )
    text = strip_code_fences(tasks_json_text)
    try:
        tasks_data = json.loads(text)
        layers = compute_layers(tasks_data)
        for task in tasks_data:
            task["layer"] = layers[task["id"]]
        return tasks_data, None, None
    except json.JSONDecodeError as e:
        return None, tasks_json_text, f"Coach produced invalid JSON: {e}"
    except (ValueError, KeyError) as e:
        return None, tasks_json_text, f"Coach produced valid JSON but bad task structure: {e}"


def extract_task_notes(
    history: list[dict],
    tasks_data: list[dict],
    model_config: dict,
    coach_name: str,
    chat_call: Callable,
) -> tuple[dict[str, str] | None, str | None, str | None]:
    """One-shot LLM call to extract implementation notes.

    Returns (notes_map, raw_text, error_msg).
    On success: ({task_id: notes}, None, None).  On failure: (None, raw_text, error_msg).
    """
    conversation_text = extract_conversation_for_coach(history, coach_name)
    tasks_json_str = json.dumps(tasks_data, indent=2)
    prompt = COACH_NOTES_EXTRACTION_PROMPT.format(
        tasks_json=tasks_json_str,
        conversation=conversation_text,
    )
    notes_text = chat_call(
        base_url=model_config["base_url"],
        model=model_config["model"],
        messages=[{"role": "user", "content": prompt}],
        api_key=model_config.get("api_key"),
        provider=model_config.get("provider", "ollama"),
    )
    text = strip_code_fences(notes_text)
    try:
        notes_data = json.loads(text)
        notes_map = {n["id"]: n["notes"] for n in notes_data if n.get("notes")}
        return notes_map, None, None
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return None, notes_text, f"Could not parse task notes: {e}"


# --- Worktree auto-commit ---


def auto_commit_layer_worktrees(
    project_root: Path,
    layer: int,
) -> list[tuple[str, str | None, str | None]]:
    """Auto-commit dirty worktrees for a layer.

    Returns [(branch, commit_hash_or_None, error_msg_or_None)].
    Filters by branch.endswith(f"/layer-{layer}").  Clean worktrees are skipped.
    """
    from gotg.worktree import (
        list_active_worktrees, commit_worktree, is_worktree_dirty, WorktreeError,
    )
    results = []
    layer_suffix = f"/layer-{layer}"
    for wt in list_active_worktrees(project_root):
        branch = wt.get("branch", "")
        if not branch.endswith(layer_suffix):
            continue
        wt_path = Path(wt["path"])
        if is_worktree_dirty(wt_path):
            try:
                commit_hash = commit_worktree(wt_path, "Implementation complete")
                if commit_hash:
                    results.append((branch, commit_hash, None))
            except WorktreeError as e:
                results.append((branch, None, str(e)))
    return results


# --- Boundary/transition messages ---


def build_transition_messages(
    iteration_id: str,
    from_phase: str,
    to_phase: str,
    tasks_written: bool = False,
    coach_ran: bool = False,
) -> tuple[dict, dict]:
    """Build boundary marker and transition message dicts.

    Returns (boundary_msg, transition_msg).
    """
    boundary_msg = {
        "from": "system",
        "iteration": iteration_id,
        "content": "--- HISTORY BOUNDARY ---",
        "phase_boundary": True,
        "from_phase": from_phase,
        "to_phase": to_phase,
    }
    if tasks_written:
        transition_content = f"--- Phase advanced: {from_phase} → {to_phase}. Task list written to tasks.json ---"
    elif coach_ran and from_phase == "grooming":
        transition_content = f"--- Phase advanced: {from_phase} → {to_phase}. Scope summary written to groomed.md ---"
    else:
        transition_content = f"--- Phase advanced: {from_phase} → {to_phase} ---"
    transition_msg = {
        "from": "system",
        "iteration": iteration_id,
        "content": transition_content,
    }
    return boundary_msg, transition_msg
