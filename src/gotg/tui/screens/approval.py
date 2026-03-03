"""Approval management screen for reviewing and resolving file write requests."""

from __future__ import annotations

from pathlib import Path

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input

from gotg.approvals import ApprovalStore
from gotg.tui.helpers import format_size, get_selected_row_key
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.content_viewer import ContentViewer


class ApprovalScreen(Screen):
    """Review and resolve pending file write approval requests."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("a", "approve_selected", "Approve"),
        Binding("y", "approve_all", "Approve All"),
        Binding("d", "deny_selected", "Deny"),
    ]

    def __init__(self, approvals_path: Path) -> None:
        super().__init__()
        self._approvals_path = approvals_path
        self._store = ApprovalStore(approvals_path)
        self._requests: dict[str, dict] = {}
        self._deny_target_id: str | None = None

    def compose(self):
        yield Header()
        with Horizontal(id="approval-layout"):
            with Vertical(id="approval-left"):
                yield DataTable(id="approval-table", cursor_type="row")
                yield ActionBar(id="approval-action-bar")
                yield Input(
                    placeholder="Enter denial reason (Enter to confirm, Escape to cancel)...",
                    id="denial-input",
                )
            with Vertical(id="approval-right"):
                yield ContentViewer(id="content-viewer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#approval-table", DataTable)
        table.add_column("ID", key="id", width=6)
        table.add_column("Op", key="op", width=8)
        table.add_column("Path", key="path")
        table.add_column("Agent", key="agent", width=12)
        table.add_column("Size", key="size", width=8)
        table.add_column("Status", key="status", width=10)
        self._load_data()

        self.query_one("#denial-input", Input).display = False
        self.query_one("#approval-action-bar", ActionBar).show(
            "A=approve  D=deny  Y=approve all  Esc=back"
        )
        table.focus()

    def _load_data(self) -> None:
        """Reload approval data from disk and refresh table."""
        self._store = ApprovalStore(self._approvals_path)
        table = self.query_one("#approval-table", DataTable)
        table.clear()
        self._requests.clear()

        all_requests = self._store._data["requests"]
        for req in all_requests:
            row_key = req["id"]
            self._requests[row_key] = req
            status = req["status"]
            if status == "pending":
                status_display = "[yellow]pending[/yellow]"
            elif status == "approved":
                status_display = "[green]approved[/green]"
            elif status == "denied":
                status_display = "[red]denied[/red]"
            else:
                status_display = status

            operation = req.get("operation", "write")

            # Path display: rename shows src -> dst
            dest = req.get("destination", "")
            path_display = f"{req['path']} -> {dest}" if dest else req["path"]

            # Size: only show for write operations
            size_display = format_size(req["content_size"]) if operation == "write" else ""

            table.add_row(
                req["id"],
                operation,
                path_display,
                req["requested_by"],
                size_display,
                status_display,
                key=row_key,
            )

        viewer = self.query_one("#content-viewer", ContentViewer)
        if all_requests:
            self._show_request_content(viewer, all_requests[0])
        else:
            viewer.clear_content()

        pending_count = len(self._store.get_pending())
        self.sub_title = f"{pending_count} pending approval(s)"

    def _show_request_content(self, viewer: ContentViewer, req: dict) -> None:
        """Show content appropriate to the operation type."""
        operation = req.get("operation", "write")
        if operation == "delete":
            viewer.show_content(req["path"], "(file will be deleted)")
        elif operation == "rename":
            dest = req.get("destination", "")
            reason = req.get("tool_input", {}).get("reason", "")
            content = f"Rename: {req['path']} -> {dest}"
            if reason:
                content += f"\nReason: {reason}"
            viewer.show_content(req["path"], content)
        else:
            viewer.show_content(req["path"], req.get("content", ""))

    def _get_selected_request(self) -> dict | None:
        """Get the request dict for the currently selected table row."""
        table = self.query_one("#approval-table", DataTable)
        key_str = get_selected_row_key(table)
        if key_str is None:
            return None
        return self._requests.get(key_str)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key_str = event.row_key.value
        req = self._requests.get(key_str)
        if req:
            viewer = self.query_one("#content-viewer", ContentViewer)
            self._show_request_content(viewer, req)

    # -- Actions --

    def action_go_back(self) -> None:
        if self._deny_target_id is not None:
            self._cancel_deny()
            return
        self.app.pop_screen()

    def _path_display(self, req: dict) -> str:
        """Build a display path — rename shows src -> dst."""
        dest = req.get("destination", "")
        return f"{req['path']} -> {dest}" if dest else req["path"]

    def action_approve_selected(self) -> None:
        if self._deny_target_id is not None:
            return
        req = self._get_selected_request()
        if not req or req["status"] != "pending":
            self.notify("Select a pending request to approve.", severity="warning")
            return
        try:
            self._store.approve(req["id"])
            self.notify(f"Approved: {self._path_display(req)}")
            self._load_data()
        except ValueError as e:
            self.notify(str(e), severity="error")

    def action_approve_all(self) -> None:
        if self._deny_target_id is not None:
            return
        approved = self._store.approve_all()
        if not approved:
            self.notify("No pending approvals.", severity="warning")
            return
        self.notify(f"Approved {len(approved)} request(s).")
        self._load_data()

    def action_deny_selected(self) -> None:
        if self._deny_target_id is not None:
            return
        req = self._get_selected_request()
        if not req or req["status"] != "pending":
            self.notify("Select a pending request to deny.", severity="warning")
            return
        self._deny_target_id = req["id"]
        denial_input = self.query_one("#denial-input", Input)
        denial_input.display = True
        denial_input.value = ""
        denial_input.focus()
        self.query_one("#approval-action-bar", ActionBar).show(
            f"Denying {req['id']} ({self._path_display(req)}). Enter reason and press Enter."
        )

    def _cancel_deny(self) -> None:
        self._deny_target_id = None
        denial_input = self.query_one("#denial-input", Input)
        denial_input.display = False
        denial_input.value = ""
        self.query_one("#approval-action-bar", ActionBar).show(
            "A=approve  D=deny  Y=approve all  Esc=back"
        )
        self.query_one("#approval-table", DataTable).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._deny_target_id is None:
            return
        reason = event.value.strip()
        try:
            req = self._requests.get(self._deny_target_id, {})
            self._store.deny(self._deny_target_id, reason)
            display = self._path_display(req) if req else ""
            self.notify(f"Denied: {display}" + (f" ({reason})" if reason else ""))
        except ValueError as e:
            self.notify(str(e), severity="error")
        self._deny_target_id = None
        event.input.display = False
        event.input.value = ""
        self.query_one("#approval-action-bar", ActionBar).show(
            "A=approve  D=deny  Y=approve all  Esc=back"
        )
        self._load_data()
        self.query_one("#approval-table", DataTable).focus()
