"""Tests for load_tasks_file / save_tasks_file in gotg.tasks."""

import json

from gotg.tasks import load_tasks_file, save_tasks_file


def test_load_tasks_file_bare_array(tmp_path):
    """Old bare-array format loads correctly."""
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps([{"id": "t1", "depends_on": []}]))
    tasks = load_tasks_file(path)
    assert isinstance(tasks, list)
    assert tasks[0]["id"] == "t1"
    assert tasks[0]["status"] == "pending"  # default added


def test_load_tasks_file_wrapped_format(tmp_path):
    """New wrapped format loads correctly."""
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "tasks": [{"id": "t1", "status": "done", "assigned_to": "a1", "depends_on": []}],
    }))
    tasks = load_tasks_file(path)
    assert tasks[0]["status"] == "done"


def test_load_tasks_file_forward_version_warns(tmp_path, capsys):
    """Forward version prints warning to stderr."""
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"schema_version": 99, "tasks": [{"id": "t1"}]}))
    tasks = load_tasks_file(path)
    assert tasks[0]["id"] == "t1"
    captured = capsys.readouterr()
    assert "schema_version 99" in captured.err


def test_save_tasks_file_creates_wrapper(tmp_path):
    """Writing to a new file creates wrapped format."""
    path = tmp_path / "tasks.json"
    save_tasks_file(path, [{"id": "t1"}])
    raw = json.loads(path.read_text())
    assert isinstance(raw, dict)
    assert raw["schema_version"] == 1
    assert raw["tasks"] == [{"id": "t1"}]


def test_save_tasks_file_preserves_existing_wrapper(tmp_path):
    """Round-trip preserves unknown root keys."""
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "tasks": [{"id": "old"}],
        "custom_meta": "keep_me",
    }))
    save_tasks_file(path, [{"id": "new"}])
    raw = json.loads(path.read_text())
    assert raw["custom_meta"] == "keep_me"
    assert raw["tasks"] == [{"id": "new"}]


def test_save_tasks_file_no_downstamp(tmp_path):
    """Existing v99 file keeps schema_version=99 on write."""
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"schema_version": 99, "tasks": []}))
    save_tasks_file(path, [{"id": "t1"}])
    raw = json.loads(path.read_text())
    assert raw["schema_version"] == 99


def test_save_tasks_file_round_trip_unknown_fields(tmp_path):
    """Write then read preserves extra per-task fields."""
    path = tmp_path / "tasks.json"
    tasks = [{"id": "t1", "custom": 42}]
    save_tasks_file(path, tasks)
    loaded = load_tasks_file(path)
    assert loaded[0]["custom"] == 42
