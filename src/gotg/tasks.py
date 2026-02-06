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


def format_tasks_summary(tasks: list[dict]) -> str:
    """Format task list with computed layers for injection into agent prompts."""
    if not tasks:
        return "No tasks defined."

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
            parts.append(
                f"- **{t['id']}** [{status}] (assigned: {assigned})\n"
                f"  {t['description']}\n"
                f"  Done when: {t['done_criteria']}\n"
                f"  Depends on: {dep_str}"
            )

    return "\n".join(parts)
