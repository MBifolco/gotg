"""Schema versioning and migration — pure data transformations only.

No I/O, no prints, no sys imports. Warnings collected via optional
``warnings: list[str]`` parameter; callers print at the I/O boundary.
"""
from __future__ import annotations

CURRENT_ITERATION_VERSION = 1
CURRENT_TEAM_VERSION = 1
CURRENT_TASKS_VERSION = 1
CURRENT_GROOMING_VERSION = 2

# ── Helpers ───────────────────────────────────────────────────

_PHASE_ALIASES = {"grooming": "refinement"}


def normalize_phase(phase: str) -> str:
    """Normalize legacy phase names (e.g. 'grooming' → 'refinement')."""
    return _PHASE_ALIASES.get(phase, phase)


def _safe_version(value) -> int:
    """Coerce schema_version to a non-negative int. Returns 0 for invalid values."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


# ── Generic pipeline runner ───────────────────────────────────

def _run_pipeline(
    data: dict,
    pipeline: list,
    current_version: int,
    schema_label: str,
    warnings: list[str] | None = None,
) -> dict:
    """Run migration steps. Forward-version data passes through unchanged."""
    version = _safe_version(data.get("schema_version", 0))
    if version > current_version:
        if warnings is not None:
            warnings.append(
                f"{schema_label} has schema_version {version}, "
                f"this gotg version supports up to {current_version}. "
                "Data will be passed through as-is."
            )
        return data
    for step in pipeline[version:]:
        data = step(data)
    return data


# ── iteration.json ────────────────────────────────────────────

def _migrate_iteration_v0_to_v1(data: dict) -> dict:
    data = dict(data)
    for it in data.get("iterations", []):
        if "phase" in it:
            it["phase"] = normalize_phase(it["phase"])
        it.setdefault("title", "")
        it.setdefault("status", "pending")
    data["schema_version"] = 1
    return data


_ITERATION_PIPELINE = [_migrate_iteration_v0_to_v1]


def migrate_iteration_data(data: dict, warnings: list[str] | None = None) -> dict:
    """Migrate iteration.json data to the current version."""
    return _run_pipeline(
        data, _ITERATION_PIPELINE, CURRENT_ITERATION_VERSION,
        "iteration.json", warnings,
    )


# ── team.json ─────────────────────────────────────────────────

def _migrate_team_v0_to_v1(data: dict) -> dict:
    data = dict(data)
    data.setdefault("streaming", False)
    data["schema_version"] = 1
    return data


_TEAM_PIPELINE = [_migrate_team_v0_to_v1]


def migrate_team_config(data: dict, warnings: list[str] | None = None) -> dict:
    """Migrate team.json data to the current version."""
    return _run_pipeline(
        data, _TEAM_PIPELINE, CURRENT_TEAM_VERSION,
        "team.json", warnings,
    )


# ── tasks.json ────────────────────────────────────────────────

def _migrate_tasks_v0_to_v1(tasks: list[dict]) -> list[dict]:
    for task in tasks:
        task.setdefault("status", "pending")
        task.setdefault("assigned_to", None)
        task.setdefault("depends_on", [])
    return tasks


def migrate_tasks_data(
    data: list | dict, warnings: list[str] | None = None,
) -> list[dict]:
    """Accept both bare array (v0) and wrapped dict (v1+). Returns task list."""
    if isinstance(data, list):
        return _migrate_tasks_v0_to_v1(data)
    version = _safe_version(data.get("schema_version", 0))
    tasks = data.get("tasks", [])
    if version > CURRENT_TASKS_VERSION:
        if warnings is not None:
            warnings.append(
                f"tasks.json has schema_version {version}, "
                f"this gotg version supports up to {CURRENT_TASKS_VERSION}. "
                "Data will be passed through as-is."
            )
        return tasks
    if version < 1:
        tasks = _migrate_tasks_v0_to_v1(tasks)
    return tasks


def stamp_tasks_for_write(
    tasks: list[dict], existing_wrapper: dict | None = None,
) -> dict:
    """Wrap task list for writing. Preserves unknown root keys from existing_wrapper.

    Never down-stamps: uses max(existing_version, CURRENT).
    """
    wrapper = dict(existing_wrapper) if existing_wrapper else {}
    existing_v = _safe_version(wrapper.get("schema_version", 0))
    wrapper["schema_version"] = max(existing_v, CURRENT_TASKS_VERSION)
    wrapper["tasks"] = tasks
    return wrapper


# ── grooming.json ─────────────────────────────────────────────

def _migrate_grooming_v0_to_v1(data: dict) -> dict:
    data = dict(data)
    data.setdefault("status", "active")
    data["schema_version"] = 1
    return data


def _migrate_grooming_v1_to_v2(data: dict) -> dict:
    data = dict(data)
    data.setdefault("context_from", None)
    data["schema_version"] = 2
    return data


_GROOMING_PIPELINE = [_migrate_grooming_v0_to_v1, _migrate_grooming_v1_to_v2]


def migrate_grooming_metadata(data: dict, warnings: list[str] | None = None) -> dict:
    """Migrate grooming.json data to the current version."""
    return _run_pipeline(
        data, _GROOMING_PIPELINE, CURRENT_GROOMING_VERSION,
        "grooming.json", warnings,
    )
