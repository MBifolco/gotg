from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from gotg.prompts import (
    COACH_REFINEMENT_PROMPT, COACH_PLANNING_PROMPT, COACH_NOTES_EXTRACTION_PROMPT,
    MERGE_CONFLICT_PROMPT,
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


_DECISION_MARKERS = re.compile(
    r"(?:agreed|decided|will use|let's go with|consensus|approved|settled on|"
    r"we'll|approach:|plan is|ruling out|excluding|not going to|won't|must not|"
    r"instead of|rather than|`[^`]+`)",
    re.IGNORECASE,
)

_MAX_INDEX_LINES = 15


def build_phase_skeleton(history: list[dict], phase: str, coach_name: str) -> str:
    """Deterministic compression of phase conversation.

    Two sections:
    1. DECISIONS — sentences containing agreement/decision/rejection language,
       plus sentences with backtick-quoted code references.
    2. INDEX — one line per message (last 15): [speaker]: truncated first line

    No LLM call. Filters out system messages and pass_turn messages.
    """
    decisions: list[str] = []
    index_lines: list[str] = []
    for msg in history:
        sender = msg.get("from", "")
        if sender == "system" or msg.get("pass_turn"):
            continue
        content = msg.get("content", "").strip()
        if not content:
            continue

        first_line = content.split("\n")[0]
        if len(first_line) > 100:
            first_line = first_line[:97] + "..."
        index_lines.append(f"[{sender}]: {first_line}")

        for sentence in re.split(r'(?<=[.!?])\s+', content):
            if _DECISION_MARKERS.search(sentence):
                decisions.append(f"[{sender}]: {sentence.strip()}")

    if len(index_lines) > _MAX_INDEX_LINES:
        index_lines = index_lines[-_MAX_INDEX_LINES:]

    parts = [f"## {phase.upper()} phase"]
    if decisions:
        parts.append("Decisions:")
        parts.extend(f"- {d}" for d in decisions)
    parts.append("\nConversation index:")
    parts.extend(index_lines)
    return "\n".join(parts)


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


def extract_refinement_summary(
    history: list[dict],
    model_config: dict,
    coach_name: str,
    chat_call: Callable,
) -> str:
    """One-shot LLM call to summarize refinement conversation.  Returns markdown."""
    conversation_text = extract_conversation_for_coach(history, coach_name)
    messages = [
        {"role": "system", "content": COACH_REFINEMENT_PROMPT},
        {"role": "user", "content": f"=== TRANSCRIPT START ===\n{conversation_text}\n=== TRANSCRIPT END ==="},
    ]
    return chat_call(
        base_url=model_config["base_url"],
        model=model_config["model"],
        messages=messages,
        api_key=model_config.get("api_key"),
        provider=model_config.get("provider", "ollama"),
    )


extract_grooming_summary = extract_refinement_summary  # backward-compat alias


def extract_tasks(
    history: list[dict],
    model_config: dict,
    coach_name: str,
    chat_call: Callable,
    refinement_summary: str | None = None,
) -> tuple[list[dict] | None, str | None, str | None]:
    """One-shot LLM call to extract tasks.

    Returns (tasks_with_layers, raw_text, error_msg).
    On success: (tasks, None, None).  On failure: (None, raw_text, error_msg).

    When refinement_summary is provided, it is appended so the LLM has scope
    context (including Out of Scope items) when extracting anti_patterns.
    """
    conversation_text = extract_conversation_for_coach(history, coach_name)
    user_content = f"=== TRANSCRIPT START ===\n{conversation_text}\n=== TRANSCRIPT END ==="
    if refinement_summary:
        user_content += f"\n\n=== SCOPE SUMMARY ===\n{refinement_summary}\n=== END SCOPE SUMMARY ==="
    messages = [
        {"role": "system", "content": COACH_PLANNING_PROMPT},
        {"role": "user", "content": user_content},
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


# --- Merge conflict resolution ---


def resolve_merge_conflict(
    file_path: str,
    branch: str,
    base_content: str | None,
    ours_content: str,
    theirs_content: str,
    task_context: str,
    model_config: dict,
    chat_call: Callable,
) -> tuple[str, str]:
    """One-shot LLM call to resolve a merge conflict.

    Returns (resolved_content, explanation) on success.
    Raises ValueError on LLM or parse failure.
    """
    if base_content is not None:
        base_section = (
            f"=== BASE (common ancestor) START ===\n"
            f"{base_content}\n"
            f"=== BASE (common ancestor) END ==="
        )
    else:
        base_section = "(No common ancestor — both branches added this file independently.)"

    prompt = MERGE_CONFLICT_PROMPT.format(
        file_path=file_path,
        branch=branch,
        base_section=base_section,
        ours_content=ours_content,
        theirs_content=theirs_content,
        task_context=task_context,
    )

    raw = chat_call(
        base_url=model_config["base_url"],
        model=model_config["model"],
        messages=[{"role": "user", "content": prompt}],
        api_key=model_config.get("api_key"),
        provider=model_config.get("provider", "ollama"),
    )
    raw = strip_code_fences(raw)

    try:
        data = json.loads(raw)
        content = data["content"]
        explanation = data.get("explanation", "")
        return content, explanation
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ValueError(f"Could not parse AI resolution: {e}") from e


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
    elif coach_ran and from_phase == "refinement":
        transition_content = f"--- Phase advanced: {from_phase} → {to_phase}. Scope summary written to refinement_summary.md ---"
    else:
        transition_content = f"--- Phase advanced: {from_phase} → {to_phase} ---"
    transition_msg = {
        "from": "system",
        "iteration": iteration_id,
        "content": transition_content,
    }
    return boundary_msg, transition_msg
