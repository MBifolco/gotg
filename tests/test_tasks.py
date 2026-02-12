import pytest

from gotg.tasks import compute_layers, format_tasks_summary


# --- compute_layers ---

def test_no_tasks_returns_empty():
    assert compute_layers([]) == {}


def test_single_task_no_deps():
    tasks = [{"id": "a", "depends_on": []}]
    assert compute_layers(tasks) == {"a": 0}


def test_two_independent_tasks():
    tasks = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": []},
    ]
    assert compute_layers(tasks) == {"a": 0, "b": 0}


def test_linear_chain():
    tasks = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["b"]},
    ]
    assert compute_layers(tasks) == {"a": 0, "b": 1, "c": 2}


def test_diamond_dependency():
    tasks = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["a"]},
        {"id": "d", "depends_on": ["b", "c"]},
    ]
    assert compute_layers(tasks) == {"a": 0, "b": 1, "c": 1, "d": 2}


def test_multiple_deps_max_layer():
    """Task with deps at different layers gets max(dep layers) + 1."""
    tasks = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["a", "b"]},
    ]
    layers = compute_layers(tasks)
    assert layers["c"] == 2


def test_cycle_raises():
    tasks = [
        {"id": "a", "depends_on": ["b"]},
        {"id": "b", "depends_on": ["a"]},
    ]
    with pytest.raises(ValueError, match="cycle"):
        compute_layers(tasks)


def test_self_cycle_raises():
    tasks = [{"id": "a", "depends_on": ["a"]}]
    with pytest.raises(ValueError, match="cycle"):
        compute_layers(tasks)


def test_missing_dependency_raises():
    tasks = [{"id": "a", "depends_on": ["nonexistent"]}]
    with pytest.raises(ValueError, match="does not exist"):
        compute_layers(tasks)


def test_complex_graph():
    """a(0)->b(1)->d(2), a(0)->c(1)->e(2), d(2)->f(3), e(2)->f(3)"""
    tasks = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["a"]},
        {"id": "d", "depends_on": ["b"]},
        {"id": "e", "depends_on": ["c"]},
        {"id": "f", "depends_on": ["d", "e"]},
    ]
    assert compute_layers(tasks) == {"a": 0, "b": 1, "c": 1, "d": 2, "e": 2, "f": 3}


# --- format_tasks_summary ---

def test_format_empty():
    assert format_tasks_summary([]) == "No tasks defined."


def test_format_groups_by_layer():
    tasks = [
        {"id": "a", "depends_on": [], "description": "Do A",
         "done_criteria": "A done", "assigned_to": None, "status": "pending"},
        {"id": "b", "depends_on": ["a"], "description": "Do B",
         "done_criteria": "B done", "assigned_to": "agent-1", "status": "pending"},
    ]
    result = format_tasks_summary(tasks)
    assert "Layer 0" in result
    assert "Layer 1" in result
    assert result.index("Layer 0") < result.index("Layer 1")


def test_format_shows_assigned():
    tasks = [
        {"id": "t1", "depends_on": [], "description": "Task",
         "done_criteria": "Done", "assigned_to": "agent-2", "status": "pending"},
    ]
    result = format_tasks_summary(tasks)
    assert "agent-2" in result


def test_format_shows_unassigned():
    tasks = [
        {"id": "t1", "depends_on": [], "description": "Task",
         "done_criteria": "Done", "assigned_to": None, "status": "pending"},
    ]
    result = format_tasks_summary(tasks)
    assert "unassigned" in result


def test_format_tasks_summary_includes_notes():
    tasks = [
        {"id": "t1", "depends_on": [], "description": "Task",
         "done_criteria": "Done", "assigned_to": "agent-1", "status": "pending",
         "notes": "File: src/main.py. main() -> None."},
    ]
    result = format_tasks_summary(tasks)
    assert "Notes: File: src/main.py. main() -> None." in result


def test_format_tasks_summary_omits_notes_when_absent():
    tasks = [
        {"id": "t1", "depends_on": [], "description": "Task",
         "done_criteria": "Done", "assigned_to": "agent-1", "status": "pending"},
    ]
    result = format_tasks_summary(tasks)
    assert "Notes:" not in result


# --- Layer-filtered summary ---

def test_format_tasks_summary_layer_filter():
    """layer=N filters to tasks with stored layer field == N."""
    tasks = [
        {"id": "a", "depends_on": [], "description": "Do A",
         "done_criteria": "A done", "assigned_to": "agent-1", "status": "pending", "layer": 0},
        {"id": "b", "depends_on": ["a"], "description": "Do B",
         "done_criteria": "B done", "assigned_to": "agent-2", "status": "pending", "layer": 1},
    ]
    result = format_tasks_summary(tasks, layer=0)
    assert "Layer 0" in result
    assert "**a**" in result
    assert "**b**" not in result
    assert "Layer 1" not in result


def test_format_tasks_summary_layer_no_match():
    """layer=N with no matching tasks returns 'No tasks defined.'"""
    tasks = [
        {"id": "a", "depends_on": [], "description": "Do A",
         "done_criteria": "A done", "assigned_to": "agent-1", "status": "pending", "layer": 0},
    ]
    result = format_tasks_summary(tasks, layer=5)
    assert result == "No tasks defined."


def test_format_tasks_summary_layer_none_shows_all():
    """layer=None (default) shows all tasks grouped by computed layers."""
    tasks = [
        {"id": "a", "depends_on": [], "description": "Do A",
         "done_criteria": "A done", "assigned_to": "agent-1", "status": "pending"},
        {"id": "b", "depends_on": ["a"], "description": "Do B",
         "done_criteria": "B done", "assigned_to": "agent-2", "status": "pending"},
    ]
    result = format_tasks_summary(tasks, layer=None)
    assert "Layer 0" in result
    assert "Layer 1" in result
    assert "**a**" in result
    assert "**b**" in result
