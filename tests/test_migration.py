"""Tests for gotg.migration — pure data transformation tests."""

from gotg.migration import (
    CURRENT_EXPLORATION_VERSION,
    CURRENT_ITERATION_VERSION,
    CURRENT_TASKS_VERSION,
    CURRENT_TEAM_VERSION,
    _safe_version,
    migrate_exploration_metadata,
    migrate_iteration_data,
    migrate_tasks_data,
    migrate_team_config,
    normalize_phase,
    stamp_tasks_for_write,
)


# ── normalize_phase ───────────────────────────────────────────

def test_normalize_phase_public():
    assert normalize_phase("grooming") == "refinement"
    assert normalize_phase("refinement") == "refinement"
    assert normalize_phase("planning") == "planning"


# ── _safe_version ─────────────────────────────────────────────

def test_safe_version_valid():
    assert _safe_version(0) == 0
    assert _safe_version(1) == 1
    assert _safe_version(99) == 99


def test_safe_version_string():
    assert _safe_version("1") == 0


def test_safe_version_none():
    assert _safe_version(None) == 0


def test_safe_version_bool_true():
    assert _safe_version(True) == 0


def test_safe_version_bool_false():
    assert _safe_version(False) == 0


def test_safe_version_negative():
    assert _safe_version(-1) == 0


def test_safe_version_float():
    assert _safe_version(1.5) == 0


# ── iteration.json ────────────────────────────────────────────

def test_migrate_iteration_v0_no_version():
    data = {
        "iterations": [{"id": "iter-1", "phase": "planning", "max_turns": 10}],
        "current": "iter-1",
    }
    result = migrate_iteration_data(data)
    assert result["schema_version"] == CURRENT_ITERATION_VERSION
    it = result["iterations"][0]
    assert it["title"] == ""
    assert it["status"] == "pending"


def test_migrate_iteration_v0_normalizes_legacy_grooming_phase():
    data = {
        "iterations": [{"id": "iter-1", "phase": "grooming", "max_turns": 10}],
        "current": "iter-1",
    }
    result = migrate_iteration_data(data)
    assert result["iterations"][0]["phase"] == "refinement"


def test_migrate_iteration_v0_defaults_missing_fields():
    data = {
        "iterations": [{"id": "iter-1", "phase": "refinement", "max_turns": 10}],
        "current": "iter-1",
    }
    result = migrate_iteration_data(data)
    it = result["iterations"][0]
    assert it["title"] == ""
    assert it["status"] == "pending"
    # Existing fields preserved
    assert it["id"] == "iter-1"
    assert it["max_turns"] == 10


def test_migrate_iteration_v1_passthrough():
    data = {
        "schema_version": 1,
        "iterations": [
            {"id": "iter-1", "phase": "planning", "title": "My Title", "status": "in-progress"}
        ],
        "current": "iter-1",
    }
    result = migrate_iteration_data(data)
    assert result["schema_version"] == 1
    assert result["iterations"][0]["title"] == "My Title"
    assert result["iterations"][0]["status"] == "in-progress"


def test_migrate_iteration_preserves_unknown_fields():
    data = {
        "iterations": [{"id": "iter-1", "phase": "planning", "custom_field": 42}],
        "current": "iter-1",
        "extra_root": True,
    }
    result = migrate_iteration_data(data)
    assert result["extra_root"] is True
    assert result["iterations"][0]["custom_field"] == 42


def test_migrate_iteration_forward_version_warns():
    data = {
        "schema_version": 99,
        "iterations": [{"id": "iter-1", "phase": "grooming"}],
        "current": "iter-1",
    }
    warnings: list[str] = []
    result = migrate_iteration_data(data, warnings=warnings)
    assert len(warnings) == 1
    assert "schema_version 99" in warnings[0]
    # Data passed through unchanged — grooming NOT normalized
    assert result["iterations"][0]["phase"] == "grooming"
    assert result["schema_version"] == 99


# ── team.json ─────────────────────────────────────────────────

def test_migrate_team_v0_adds_streaming():
    data = {"model": {"provider": "anthropic"}, "agents": []}
    result = migrate_team_config(data)
    assert result["schema_version"] == CURRENT_TEAM_VERSION
    assert result["streaming"] is False


def test_migrate_team_v0_preserves_existing_streaming():
    data = {"model": {"provider": "anthropic"}, "agents": [], "streaming": True}
    result = migrate_team_config(data)
    assert result["streaming"] is True


def test_migrate_team_v1_passthrough():
    data = {"schema_version": 1, "model": {}, "agents": [], "streaming": True}
    result = migrate_team_config(data)
    assert result["schema_version"] == 1
    assert result["streaming"] is True


def test_migrate_team_preserves_unknown_fields():
    data = {"model": {}, "agents": [], "custom": "value"}
    result = migrate_team_config(data)
    assert result["custom"] == "value"


def test_migrate_team_forward_version_warns():
    data = {"schema_version": 99, "model": {}, "agents": []}
    warnings: list[str] = []
    result = migrate_team_config(data, warnings=warnings)
    assert len(warnings) == 1
    assert "schema_version 99" in warnings[0]
    assert result["schema_version"] == 99


# ── tasks.json ────────────────────────────────────────────────

def test_migrate_tasks_bare_array():
    tasks = [{"id": "t1", "description": "do thing"}]
    result = migrate_tasks_data(tasks)
    assert isinstance(result, list)
    assert result[0]["status"] == "pending"
    assert result[0]["assigned_to"] is None
    assert result[0]["depends_on"] == []


def test_migrate_tasks_wrapped_dict():
    data = {
        "schema_version": 1,
        "tasks": [{"id": "t1", "status": "done", "assigned_to": "a1", "depends_on": []}],
    }
    result = migrate_tasks_data(data)
    assert isinstance(result, list)
    assert result[0]["status"] == "done"


def test_migrate_tasks_defaults_per_task():
    tasks = [{"id": "t1"}, {"id": "t2", "status": "done"}]
    result = migrate_tasks_data(tasks)
    assert result[0]["status"] == "pending"
    assert result[1]["status"] == "done"  # Not overwritten


def test_migrate_tasks_preserves_unknown_task_fields():
    tasks = [{"id": "t1", "custom": 42}]
    result = migrate_tasks_data(tasks)
    assert result[0]["custom"] == 42


def test_migrate_tasks_forward_version_warns():
    data = {"schema_version": 99, "tasks": [{"id": "t1"}]}
    warnings: list[str] = []
    result = migrate_tasks_data(data, warnings=warnings)
    assert len(warnings) == 1
    assert "schema_version 99" in warnings[0]
    assert result[0]["id"] == "t1"


def test_stamp_tasks_for_write():
    tasks = [{"id": "t1"}]
    result = stamp_tasks_for_write(tasks)
    assert result["schema_version"] == CURRENT_TASKS_VERSION
    assert result["tasks"] is tasks


def test_stamp_tasks_preserves_existing_wrapper_metadata():
    tasks = [{"id": "t1"}]
    existing = {"schema_version": 1, "tasks": [], "custom_meta": "keep"}
    result = stamp_tasks_for_write(tasks, existing_wrapper=existing)
    assert result["custom_meta"] == "keep"
    assert result["tasks"] is tasks


def test_stamp_tasks_no_downstamp():
    tasks = [{"id": "t1"}]
    existing = {"schema_version": 99, "tasks": []}
    result = stamp_tasks_for_write(tasks, existing_wrapper=existing)
    assert result["schema_version"] == 99


# ── exploration.json ───────────────────────────────────────────

def test_migrate_exploration_v0_adds_status():
    data = {"slug": "test", "topic": "hello"}
    result = migrate_exploration_metadata(data)
    assert result["schema_version"] == CURRENT_EXPLORATION_VERSION
    assert result["status"] == "active"


def test_migrate_exploration_v0_preserves_existing_status():
    data = {"slug": "test", "topic": "hello", "status": "closed"}
    result = migrate_exploration_metadata(data)
    assert result["status"] == "closed"


def test_migrate_exploration_v1_to_v2_adds_context_from():
    data = {"schema_version": 1, "slug": "test", "status": "active"}
    result = migrate_exploration_metadata(data)
    assert result["schema_version"] == 2
    assert result["context_from"] is None


def test_migrate_exploration_v2_passthrough():
    data = {"schema_version": 2, "slug": "test", "status": "active", "context_from": "iter-1"}
    result = migrate_exploration_metadata(data)
    assert result["schema_version"] == 2
    assert result["context_from"] == "iter-1"


def test_migrate_exploration_forward_version_warns():
    data = {"schema_version": 99, "slug": "test"}
    warnings: list[str] = []
    result = migrate_exploration_metadata(data, warnings=warnings)
    assert len(warnings) == 1
    assert "schema_version 99" in warnings[0]


# ── Pipeline pattern ──────────────────────────────────────────

def test_pipeline_skips_completed_steps():
    """v1 data should not re-run v0→v1 step."""
    data = {
        "schema_version": 1,
        "iterations": [{"id": "iter-1", "phase": "grooming", "title": "x", "status": "done"}],
        "current": "iter-1",
    }
    result = migrate_iteration_data(data)
    # grooming is NOT normalized because v1 data skips the v0→v1 step
    assert result["iterations"][0]["phase"] == "grooming"


def test_migrate_with_string_schema_version():
    """String schema_version treated as v0, runs full pipeline."""
    data = {
        "schema_version": "1",
        "iterations": [{"id": "iter-1", "phase": "grooming"}],
        "current": "iter-1",
    }
    result = migrate_iteration_data(data)
    # "1" is not int → _safe_version returns 0 → runs v0→v1
    assert result["iterations"][0]["phase"] == "refinement"
    assert result["schema_version"] == 1


def test_migrate_wrapped_tasks_v0_no_version():
    """Wrapped dict without schema_version runs v0 migration."""
    data = {"tasks": [{"id": "t1"}]}
    result = migrate_tasks_data(data)
    assert result[0]["status"] == "pending"
    assert result[0]["assigned_to"] is None
