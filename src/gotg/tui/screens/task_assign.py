"""Task assignment screen for assigning agents to iteration tasks."""

from __future__ import annotations

import json
from pathlib import Path

from rich.markup import escape
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from gotg.tasks import compute_layers
from gotg.tui.helpers import get_selected_row_key
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.content_viewer import ContentViewer


class TaskAssignScreen(Screen):
    """Assign agents to tasks from tasks.json."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("a", "cycle_agent", "Assign"),
        Binding("A", "auto_assign", "Auto-Assign", show=False),
        Binding("ctrl+s", "save", "Save", show=True),
    ]

    def __init__(self, iter_dir: Path, agents: list[dict]) -> None:
        super().__init__()
        self._iter_dir = iter_dir
        self._agents = agents
        self._agent_names = [a["name"] for a in agents]
        # Cycle options: None (unassigned) then each agent name
        self._cycle = [None] + self._agent_names
        self._tasks: list[dict] = []
        self._dirty = False

    def compose(self):
        yield Header()
        with Vertical(id="task-layout"):
            yield DataTable(id="task-table", cursor_type="row")
            yield ActionBar(id="task-action-bar")
            yield ContentViewer(id="task-viewer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#task-table", DataTable)
        table.add_column("Layer", key="layer", width=6)
        table.add_column("Task ID", key="id")
        table.add_column("Description", key="desc")
        table.add_column("Assigned To", key="assigned", width=14)

        self._load_tasks()
        self._update_action_bar()

    def _load_tasks(self) -> None:
        """Load tasks.json and populate the table."""
        tasks_path = self._iter_dir / "tasks.json"
        if not tasks_path.exists():
            self.query_one("#task-action-bar", ActionBar).show(
                "No tasks.json found."
            )
            return

        self._tasks = json.loads(tasks_path.read_text())

        # Compute layers if missing
        if self._tasks and "layer" not in self._tasks[0]:
            try:
                layers = compute_layers(self._tasks)
                for t in self._tasks:
                    t["layer"] = layers[t["id"]]
            except (ValueError, KeyError):
                pass

        self._tasks.sort(key=lambda t: (t.get("layer", 0), t["id"]))
        self._populate_table()

        # Show first task details
        if self._tasks:
            table = self.query_one("#task-table", DataTable)
            table.focus()
            self._show_task_detail(self._tasks[0])

    def _populate_table(self) -> None:
        """Rebuild DataTable from self._tasks."""
        table = self.query_one("#task-table", DataTable)
        table.clear()
        for task in self._tasks:
            desc = task.get("description", "")
            if len(desc) > 40:
                desc = desc[:37] + "..."
            assigned = task.get("assigned_to") or "[dim]unassigned[/dim]"
            table.add_row(
                str(task.get("layer", "?")),
                task["id"],
                desc,
                assigned,
                key=task["id"],
            )

    def _show_task_detail(self, task: dict) -> None:
        """Display full task details in the ContentViewer."""
        viewer = self.query_one("#task-viewer", ContentViewer)
        viewer.remove_children()

        from textual.widgets import Static

        lines = [
            f"[bold]{escape(task['id'])}[/bold]",
            "",
            f"[bold]Description:[/bold] {escape(task.get('description', ''))}",
            "",
            f"[bold]Done criteria:[/bold] {escape(task.get('done_criteria', ''))}",
            "",
        ]
        deps = task.get("depends_on", [])
        lines.append(f"[bold]Depends on:[/bold] {', '.join(deps) if deps else 'none'}")
        lines.append(f"[bold]Status:[/bold] {task.get('status', 'pending')}")
        lines.append(f"[bold]Layer:[/bold] {task.get('layer', '?')}")
        assigned = task.get("assigned_to") or "unassigned"
        lines.append(f"[bold]Assigned to:[/bold] {assigned}")

        notes = task.get("notes")
        if notes:
            lines.extend(["", f"[bold]Notes:[/bold] {escape(notes)}"])

        viewer.mount(Static("\n".join(lines), classes="cv-content"))

    def _get_selected_task(self) -> dict | None:
        """Get the task dict for the currently selected row."""
        table = self.query_one("#task-table", DataTable)
        key_str = get_selected_row_key(table)
        if key_str is None:
            return None
        for task in self._tasks:
            if task["id"] == key_str:
                return task
        return None

    def _update_action_bar(self) -> None:
        """Update the action bar with assignment status."""
        bar = self.query_one("#task-action-bar", ActionBar)
        if not self._tasks:
            bar.show("No tasks loaded.")
            return
        unassigned = sum(1 for t in self._tasks if not t.get("assigned_to"))
        total = len(self._tasks)
        dirty = " [unsaved]" if self._dirty else ""
        if unassigned == 0:
            bar.show(
                f"All {total} tasks assigned.{dirty} "
                "Ctrl+S=save  A=cycle  Shift+A=auto-assign  Esc=back"
            )
        else:
            bar.show(
                f"{unassigned}/{total} unassigned.{dirty} "
                "A=cycle  Shift+A=auto-assign  Ctrl+S=save  Esc=back"
            )

    # ── DataTable events ──────────────────────────────────────

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key_str = event.row_key.value
        for task in self._tasks:
            if task["id"] == key_str:
                self._show_task_detail(task)
                break

    # ── Actions ───────────────────────────────────────────────

    def action_cycle_agent(self) -> None:
        """Cycle the assigned agent for the selected task."""
        task = self._get_selected_task()
        if task is None:
            return

        current = task.get("assigned_to")
        try:
            idx = self._cycle.index(current)
        except ValueError:
            idx = 0
        next_idx = (idx + 1) % len(self._cycle)
        task["assigned_to"] = self._cycle[next_idx]
        self._dirty = True

        # Update just the assignment column
        table = self.query_one("#task-table", DataTable)
        assigned_display = task["assigned_to"] or "[dim]unassigned[/dim]"
        table.update_cell(task["id"], "assigned", assigned_display)
        self._show_task_detail(task)
        self._update_action_bar()

    def action_auto_assign(self) -> None:
        """Round-robin assign all unassigned tasks across agents."""
        if not self._agent_names:
            return
        unassigned = [t for t in self._tasks if not t.get("assigned_to")]
        if not unassigned:
            self.notify("All tasks already assigned.", severity="warning")
            return

        for i, task in enumerate(unassigned):
            task["assigned_to"] = self._agent_names[i % len(self._agent_names)]

        self._dirty = True
        self._populate_table()
        # Re-show selected task detail
        task = self._get_selected_task()
        if task:
            self._show_task_detail(task)
        self._update_action_bar()

    def action_save(self) -> None:
        """Write updated tasks to tasks.json and pop screen."""
        if not self._tasks:
            self.app.pop_screen()
            return

        tasks_path = self._iter_dir / "tasks.json"
        tasks_path.write_text(json.dumps(self._tasks, indent=2) + "\n")
        self._dirty = False
        self.notify("Tasks saved.")
        self.app.pop_screen()

    def action_go_back(self) -> None:
        """Pop screen, confirming if there are unsaved changes."""
        if self._dirty:
            from gotg.tui.modals.confirm import ConfirmModal
            self.app.push_screen(
                ConfirmModal("Discard unsaved task assignments?"),
                callback=self._on_discard_confirmed,
            )
        else:
            self.app.pop_screen()

    def _on_discard_confirmed(self, confirmed: bool) -> None:
        if confirmed:
            self.app.pop_screen()
