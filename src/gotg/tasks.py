from __future__ import annotations

"""Task file I/O, dependency layering, and prompt formatting.

load_tasks_file / save_tasks_file handle tasks.json persistence (bare array).
compute_layers builds execution layers from dependency graphs. TaskRepo wraps
persistence with an OO interface. Used by implementation.py and policy.py.
"""

import json
from pathlib import Path


def load_tasks_file(path: Path) -> list[dict]:
    """Read tasks.json. Returns task list (bare JSON array)."""
    return json.loads(path.read_text())


def save_tasks_file(path: Path, tasks: list[dict]) -> None:
    """Write tasks.json as a bare JSON array."""
    path.write_text(json.dumps(tasks, indent=2) + "\n")


def compute_layers(tasks: list[dict]) -> dict[str, int]:
    """Compute execution layers from task dependency graph.

    Layer 0 = tasks with no dependencies.
    Layer N = max(layer of dependencies) + 1.

    Returns dict mapping task_id to layer number.
    Raises ValueError on cycles or missing dependency references.
    """
    task_ids = {t["id"] for t in tasks}
    deps = {t["id"]: t["depends_on"] for t in tasks}

    for tid, dep_list in deps.items():
        for dep in dep_list:
            if dep not in task_ids:
                raise ValueError(
                    f"Task '{tid}' depends on '{dep}' which does not exist."
                )

    layers = {}
    remaining = set(task_ids)

    while remaining:
        ready = {
            tid for tid in remaining
            if all(d in layers for d in deps[tid])
        }

        if not ready:
            raise ValueError(
                f"Dependency cycle detected among tasks: {remaining}"
            )

        for tid in ready:
            if not deps[tid]:
                layers[tid] = 0
            else:
                layers[tid] = max(layers[d] for d in deps[tid]) + 1

        remaining -= ready

    return layers


def format_tasks_summary(tasks: list[dict], layer: int | None = None) -> str:
    """Format task list with computed layers for injection into agent prompts.

    When layer is set, filter to that layer only (skip compute_layers, use stored 'layer' field).
    When layer is None, show all tasks grouped by computed layers.
    """
    if not tasks:
        return "No tasks defined."

    if layer is not None:
        layer_tasks = [t for t in tasks if t.get("layer") == layer]
        if not layer_tasks:
            return "No tasks defined."
        parts = [f"### Layer {layer} (parallel)"]
        for t in layer_tasks:
            status = t.get("status", "pending")
            assigned = t.get("assigned_to") or "unassigned"
            dep_str = ", ".join(t["depends_on"]) if t["depends_on"] else "none"
            entry = (
                f"- **{t['id']}** [{status}] (assigned: {assigned})\n"
                f"  {t['description']}\n"
                f"  Done when: {t['done_criteria']}\n"
                f"  Depends on: {dep_str}"
            )
            approach = t.get("approach")
            if approach:
                entry += f"\n  Approach: {approach}"
            anti = t.get("anti_patterns")
            if anti:
                entry += "\n  MUST NOT: " + "; ".join(anti)
            files = t.get("files")
            if isinstance(files, list):
                str_files = [f.strip() for f in files if isinstance(f, str) and f.strip()]
                if str_files:
                    entry += "\n  Files: " + ", ".join(str_files)
            notes = t.get("notes")
            if notes:
                entry += f"\n  Notes: {notes}"
            parts.append(entry)
        return "\n".join(parts)

    layers = compute_layers(tasks)
    max_layer = max(layers.values())

    parts = []
    for layer_num in range(max_layer + 1):
        layer_tasks = [t for t in tasks if layers[t["id"]] == layer_num]
        parts.append(f"### Layer {layer_num} (parallel)")
        for t in layer_tasks:
            status = t.get("status", "pending")
            assigned = t.get("assigned_to") or "unassigned"
            dep_str = ", ".join(t["depends_on"]) if t["depends_on"] else "none"
            entry = (
                f"- **{t['id']}** [{status}] (assigned: {assigned})\n"
                f"  {t['description']}\n"
                f"  Done when: {t['done_criteria']}\n"
                f"  Depends on: {dep_str}"
            )
            approach = t.get("approach")
            if approach:
                entry += f"\n  Approach: {approach}"
            anti = t.get("anti_patterns")
            if anti:
                entry += "\n  MUST NOT: " + "; ".join(anti)
            files = t.get("files")
            if isinstance(files, list):
                str_files = [f.strip() for f in files if isinstance(f, str) and f.strip()]
                if str_files:
                    entry += "\n  Files: " + ", ".join(str_files)
            notes = t.get("notes")
            if notes:
                entry += f"\n  Notes: {notes}"
            parts.append(entry)

    return "\n".join(parts)


class TaskRepo:
    """tasks.json persistence. Binds path at construction."""

    def __init__(self, tasks_path: Path):
        self.tasks_path = tasks_path

    def load(self) -> list[dict]:
        return load_tasks_file(self.tasks_path)

    def save(self, tasks: list[dict]) -> None:
        save_tasks_file(self.tasks_path, tasks)

    def exists(self) -> bool:
        return self.tasks_path.exists()
