"""Home screen with iteration and grooming session lists."""

from __future__ import annotations

from pathlib import Path

from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from gotg.groom import list_grooming_sessions
from gotg.tui.data import list_iterations, load_session_metadata, relative_time
from gotg.tui.screens.chat import ChatScreen


class HomeScreen(Screen):
    """Home screen showing iterations and grooming sessions."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
    ]

    def compose(self):
        yield Header()
        with TabbedContent():
            with TabPane("Iterations", id="tab-iterations"):
                yield DataTable(id="iter-table", cursor_type="row")
            with TabPane("Grooming", id="tab-grooming"):
                yield DataTable(id="groom-table", cursor_type="row")
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
        for it in list_iterations(team_dir):
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

        # Grooming sessions
        self._grooming_data = {}
        groom_table = self.query_one("#groom-table", DataTable)
        groom_table.clear()
        for s in list_grooming_sessions(team_dir):
            row_key = s["slug"]
            groom_dir = team_dir / "grooming" / s["slug"]
            # Count messages
            log_path = groom_dir / "conversation.jsonl"
            msg_count = 0
            mtime = None
            if log_path.exists():
                msg_count = sum(
                    1 for line in log_path.read_text().splitlines() if line.strip()
                )
                mtime = log_path.stat().st_mtime
            self._grooming_data[row_key] = (s, groom_dir)
            groom_table.add_row(
                s["slug"],
                s.get("topic", ""),
                "yes" if s.get("coach") else "",
                str(msg_count),
                relative_time(mtime),
                key=row_key,
            )

    def action_refresh(self) -> None:
        self._load_data()

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
