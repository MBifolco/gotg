"""Tests for load_tasks_file / save_tasks_file in gotg.tasks."""

import json

from gotg.tasks import load_tasks_file, save_tasks_file


def test_load_tasks_file_bare_array(tmp_path):
    """Bare-array format loads correctly."""
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps([{"id": "t1", "depends_on": []}]))
    tasks = load_tasks_file(path)
    assert isinstance(tasks, list)
    assert tasks[0]["id"] == "t1"


def test_save_tasks_file_creates_bare_array(tmp_path):
    """Writing to a new file creates a bare JSON array."""
    path = tmp_path / "tasks.json"
    save_tasks_file(path, [{"id": "t1"}])
    raw = json.loads(path.read_text())
    assert isinstance(raw, list)
    assert raw == [{"id": "t1"}]


def test_save_tasks_file_round_trip_unknown_fields(tmp_path):
    """Write then read preserves extra per-task fields."""
    path = tmp_path / "tasks.json"
    tasks = [{"id": "t1", "custom": 42}]
    save_tasks_file(path, tasks)
    loaded = load_tasks_file(path)
    assert loaded[0]["custom"] == 42
