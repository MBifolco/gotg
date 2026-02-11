"""Home screen with iteration and grooming session lists."""

from __future__ import annotations

import json
from pathlib import Path

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from gotg.groom import list_grooming_sessions
from gotg.tui.data import list_iterations, load_session_metadata, relative_time
from gotg.tui.helpers import count_jsonl_lines, get_selected_row_key
from gotg.tui.screens.chat import ChatScreen


class HomeScreen(Screen):
    """Home screen showing iterations and grooming sessions."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("R", "run_session", "Run", show=False),
        Binding("c", "continue_session", "Continue", show=False),
        Binding("n", "new_item", "New", show=False),
        Binding("e", "edit_item", "Edit", show=False),
        Binding("s", "open_settings", "Settings", show=False),
    ]

    def compose(self):
        yield Header()
        with TabbedContent():
            with TabPane("Iterations", id="tab-iterations"):
                yield Static(
                    "[dim]No iterations yet. Press N to create one.[/dim]",
                    id="iter-empty",
                    classes="empty-state",
                )
                yield DataTable(id="iter-table", cursor_type="row")
            with TabPane("Grooming", id="tab-grooming"):
                yield Static(
                    "[dim]No grooming sessions. Press G to start one.[/dim]",
                    id="groom-empty",
                    classes="empty-state",
                )
                yield DataTable(id="groom-table", cursor_type="row")
            with TabPane("Info", id="tab-info"):
                yield Static(id="info-content")
        yield Footer()

    def on_mount(self) -> None:
        self._setup_tables()
        self._load_data()
        self.query_one("#iter-table", DataTable).focus()

    def _setup_tables(self) -> None:
        iter_table = self.query_one("#iter-table", DataTable)
        iter_table.add_column("ID", key="id")
        iter_table.add_column("Description", key="desc")
        iter_table.add_column("Phase", key="phase")
        iter_table.add_column("Status", key="status")
        iter_table.add_column("Msgs", key="msgs")
        iter_table.add_column("Activity", key="activity")

        groom_table = self.query_one("#groom-table", DataTable)
        groom_table.add_column("Slug", key="slug")
        groom_table.add_column("Topic", key="topic")
        groom_table.add_column("Coach", key="coach")
        groom_table.add_column("Msgs", key="msgs")
        groom_table.add_column("Activity", key="activity")

    def _load_data(self) -> None:
        team_dir = self.app.team_dir

        # Iterations
        self._iteration_data = {}
        iter_table = self.query_one("#iter-table", DataTable)
        iter_table.clear()
        iterations = list_iterations(team_dir)
        for it in iterations:
            row_key = it["id"]
            it_dir = team_dir / "iterations" / it["id"]
            self._iteration_data[row_key] = (it, it_dir)
            marker = "> " if it.get("is_current") else "  "
            desc = it.get("description", "") or it.get("title", "")
            if len(desc) > 50:
                desc = desc[:47] + "..."
            iter_table.add_row(
                f"{marker}{it['id']}",
                desc,
                it.get("phase", ""),
                it.get("status", ""),
                str(it.get("message_count", 0)),
                relative_time(it.get("last_modified")),
                key=row_key,
            )

        # Show/hide empty state
        self.query_one("#iter-empty").display = len(iterations) == 0
        iter_table.display = len(iterations) > 0

        # Grooming sessions
        self._grooming_data = {}
        groom_table = self.query_one("#groom-table", DataTable)
        groom_table.clear()
        sessions = list_grooming_sessions(team_dir)
        for s in sessions:
            row_key = s["slug"]
            groom_dir = team_dir / "grooming" / s["slug"]
            log_path = groom_dir / "conversation.jsonl"
            msg_count = count_jsonl_lines(log_path)
            mtime = log_path.stat().st_mtime if log_path.exists() else None
            self._grooming_data[row_key] = (s, groom_dir)
            groom_table.add_row(
                s["slug"],
                s.get("topic", ""),
                "yes" if s.get("coach") else "",
                str(msg_count),
                relative_time(mtime),
                key=row_key,
            )

        # Show/hide empty state
        self.query_one("#groom-empty").display = len(sessions) == 0
        groom_table.display = len(sessions) > 0

        # Info tab
        self._load_info()

    def _load_info(self) -> None:
        """Load project info for the Info tab."""
        team_dir = self.app.team_dir
        info_widget = self.query_one("#info-content", Static)

        try:
            team_config = json.loads((team_dir / "team.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            info_widget.update("[dim]Could not load team.json[/dim]")
            return

        model = team_config.get("model", {})
        agents = team_config.get("agents", [])
        coach = team_config.get("coach")
        file_access = team_config.get("file_access")
        worktrees = team_config.get("worktrees")

        lines = [
            "[bold]Project Info[/bold]",
            "",
            f"  Model:      {model.get('provider', '?')} / {model.get('model', '?')}",
            f"  Agents:     {len(agents)} ({', '.join(a['name'] for a in agents)})",
        ]
        if coach:
            lines.append(f"  Coach:      {coach.get('name', 'coach')}")
        else:
            lines.append("  Coach:      disabled")
        if file_access:
            writable = file_access.get("writable_paths", [])
            approvals = file_access.get("enable_approvals", False)
            lines.append(
                f"  File tools: {len(writable)} writable path(s)"
                + (", approvals on" if approvals else "")
            )
        else:
            lines.append("  File tools: disabled")
        if worktrees and worktrees.get("enabled"):
            lines.append("  Worktrees:  enabled")
        else:
            lines.append("  Worktrees:  disabled")

        lines.append("")
        lines.append(f"  Iterations: {len(self._iteration_data)}")
        lines.append(f"  Grooming:   {len(self._grooming_data)}")
        lines.append("")
        lines.append("[dim]Press S to open settings, N to create iteration, G for grooming[/dim]")

        info_widget.update("\n".join(lines))

    def action_refresh(self) -> None:
        self._load_data()

    def _get_selected_data(self) -> tuple[dict, Path, str] | None:
        """Get metadata, data_dir, and kind for the focused table's selected row."""
        for table_id, data_store, kind in [
            ("#iter-table", "_iteration_data", "iteration"),
            ("#groom-table", "_grooming_data", "grooming"),
        ]:
            try:
                table = self.query_one(table_id, DataTable)
                if not table.has_focus:
                    continue
                key_str = get_selected_row_key(table)
                if key_str is None:
                    return None
                store = getattr(self, data_store, {})
                if key_str in store:
                    meta, data_dir = store[key_str]
                    return meta, data_dir, kind
            except Exception:
                continue
        return None

    def _active_tab(self) -> str:
        """Return which tab is active: 'iterations', 'grooming', or 'info'."""
        tc = self.query_one(TabbedContent)
        active = tc.active
        if active == "tab-grooming":
            return "grooming"
        if active == "tab-info":
            return "info"
        return "iterations"

    # ── Row selection / view ──────────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key.value
        team_dir = self.app.team_dir

        if row_key in self._iteration_data:
            meta, data_dir = self._iteration_data[row_key]
            full_meta = load_session_metadata(team_dir, meta)
            self.app.push_screen(ChatScreen(data_dir, full_meta))
        elif row_key in self._grooming_data:
            meta, data_dir = self._grooming_data[row_key]
            full_meta = load_session_metadata(team_dir, meta)
            self.app.push_screen(ChatScreen(data_dir, full_meta))

    def on_screen_resume(self) -> None:
        """Refresh data when returning from a pushed screen."""
        self._load_data()

    # ── Run / Continue ────────────────────────────────────────

    def action_run_session(self) -> None:
        """Start a fresh run for the selected iteration/grooming."""
        data = self._get_selected_data()
        if data is None:
            return
        meta, data_dir, kind = data
        team_dir = self.app.team_dir

        # Switch current if running a non-current iteration
        if kind == "iteration" and not meta.get("is_current"):
            from gotg.config import switch_current_iteration
            switch_current_iteration(team_dir, meta["id"])
            self.notify(f"Switched to {meta['id']}")

        # If iteration is pending and has no description, prompt for one
        if kind == "iteration" and meta.get("status") == "pending":
            self._start_pending_iteration(meta, data_dir)
            return

        full_meta = load_session_metadata(team_dir, meta)
        self.app.push_screen(ChatScreen(data_dir, full_meta, mode="run", session_kind=kind))

    def _start_pending_iteration(self, meta: dict, data_dir: Path) -> None:
        """Handle starting a pending iteration — prompt for description if missing."""
        from gotg.config import save_iteration_fields

        desc = meta.get("description", "") or meta.get("title", "")
        if not desc.strip():
            from gotg.tui.modals.text_input import TextInputModal
            self.app.push_screen(
                TextInputModal(
                    "Enter iteration description:",
                    placeholder="What should the team build?",
                ),
                callback=lambda result: self._on_pending_description(result, meta, data_dir),
            )
        else:
            # Has description — just start it
            team_dir = self.app.team_dir
            save_iteration_fields(team_dir, meta["id"], status="in-progress")
            meta["status"] = "in-progress"
            full_meta = load_session_metadata(team_dir, meta)
            self.app.push_screen(ChatScreen(data_dir, full_meta, mode="run", session_kind="iteration"))

    def _on_pending_description(self, result: str | None, meta: dict, data_dir: Path) -> None:
        """Callback after TextInputModal for pending iteration description."""
        if result is None:
            return
        from gotg.config import save_iteration_fields
        team_dir = self.app.team_dir
        save_iteration_fields(team_dir, meta["id"], description=result, status="in-progress")
        meta["description"] = result
        meta["status"] = "in-progress"
        full_meta = load_session_metadata(team_dir, meta)
        self.app.push_screen(ChatScreen(data_dir, full_meta, mode="run", session_kind="iteration"))

    def action_continue_session(self) -> None:
        """Continue the selected iteration/grooming."""
        data = self._get_selected_data()
        if data is None:
            return
        meta, data_dir, kind = data
        team_dir = self.app.team_dir
        full_meta = load_session_metadata(team_dir, meta)
        self.app.push_screen(ChatScreen(data_dir, full_meta, mode="continue", session_kind=kind))

    # ── New item (N key) ──────────────────────────────────────

    def action_new_item(self) -> None:
        """Create a new iteration or grooming session depending on active tab."""
        tab = self._active_tab()
        if tab == "iterations":
            self._new_iteration()
        elif tab == "grooming":
            self._new_grooming()

    def _new_iteration(self) -> None:
        """Prompt for iteration description, then create it."""
        from gotg.tui.modals.text_input import TextInputModal
        self.app.push_screen(
            TextInputModal(
                "New iteration — enter description:",
                placeholder="What should the team build?",
            ),
            callback=self._on_new_iteration,
        )

    def _on_new_iteration(self, result: str | None) -> None:
        if result is None:
            return
        from gotg.config import create_iteration
        team_dir = self.app.team_dir

        # Auto-generate next ID
        existing = list(self._iteration_data.keys())
        next_num = 1
        while f"iter-{next_num}" in existing:
            next_num += 1
        iter_id = f"iter-{next_num}"

        try:
            create_iteration(team_dir, iter_id, description=result)
            self.notify(f"Created {iter_id}")
            self._load_data()
        except ValueError as e:
            self.notify(str(e), severity="error")

    def _new_grooming(self) -> None:
        """Prompt for grooming topic, then create it."""
        from gotg.tui.modals.text_input import TextInputModal
        self.app.push_screen(
            TextInputModal(
                "New grooming session — enter topic:",
                placeholder="What would you like to explore?",
            ),
            callback=self._on_new_grooming,
        )

    def _on_new_grooming(self, result: str | None) -> None:
        if result is None:
            return
        from gotg.groom import existing_slugs, generate_slug, write_grooming_metadata
        team_dir = self.app.team_dir
        slug = generate_slug(result, existing_slugs(team_dir))
        try:
            write_grooming_metadata(team_dir, slug, topic=result, coach=True, max_turns=30)
            self.notify(f"Created grooming: {slug}")
            self._load_data()
        except FileExistsError:
            self.notify(f"Slug '{slug}' already exists.", severity="error")

    # ── Edit item (E key) ─────────────────────────────────────

    def action_edit_item(self) -> None:
        """Edit the selected iteration's properties."""
        data = self._get_selected_data()
        if data is None:
            return
        meta, data_dir, kind = data

        if kind == "iteration":
            from gotg.tui.modals.edit_iteration import EditIterationModal
            self.app.push_screen(
                EditIterationModal(meta),
                callback=lambda result: self._on_edit_iteration(result, meta["id"]),
            )
        elif kind == "grooming":
            self.notify("Grooming sessions can't be edited yet.", severity="warning")

    def _on_edit_iteration(self, result: dict | None, iteration_id: str) -> None:
        if result is None:
            return
        from gotg.config import save_iteration_fields
        save_iteration_fields(self.app.team_dir, iteration_id, **result)
        self.notify(f"Updated {iteration_id}")
        self._load_data()

    # ── Settings (S key) ──────────────────────────────────────

    def action_open_settings(self) -> None:
        """Open settings screen."""
        from gotg.tui.screens.settings import SettingsScreen

        self.app.push_screen(SettingsScreen())
