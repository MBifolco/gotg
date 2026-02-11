"""Review screen for viewing diffs, merging branches, and advancing layers."""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from gotg.session import (
    MergeResult,
    NextLayerResult,
    ReviewError,
    ReviewResult,
    advance_next_layer,
    load_review_branches,
    merge_branches,
)
from gotg.tui.helpers import get_selected_row_key
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.content_viewer import ContentViewer


# ── Local Textual messages ────────────────────────────────────


class _ReviewLoaded(Message):
    def __init__(self, result: ReviewResult) -> None:
        super().__init__()
        self.result = result


class _MergeDone(Message):
    def __init__(self, results: list[MergeResult]) -> None:
        super().__init__()
        self.results = results


class _NextLayerDone(Message):
    def __init__(self, result: NextLayerResult) -> None:
        super().__init__()
        self.result = result


class _ReviewScreenError(Message):
    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


# ── ReviewScreen ──────────────────────────────────────────────


class ReviewScreen(Screen):
    """View diffs, merge branches, and advance to the next layer."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("m", "merge_selected", "Merge", show=False),
        Binding("y", "merge_all", "Merge All", show=False),
        Binding("n", "next_layer", "Next Layer", show=False),
        Binding("f", "finish_iteration", "Finish", show=False),
        Binding("r", "refresh", "Refresh", show=False),
    ]

    def __init__(
        self,
        team_dir: Path,
        iteration: dict,
        iter_dir: Path,
    ) -> None:
        super().__init__()
        self._team_dir = team_dir
        self._iteration = iteration
        self._iter_dir = iter_dir
        self._project_root = team_dir.parent
        self._review: ReviewResult | None = None
        self._merging = False
        self._all_layers_done = False
        self._branches: dict[str, dict] = {}

    def compose(self):
        yield Header()
        with Horizontal(id="review-layout"):
            with Vertical(id="review-left"):
                yield DataTable(id="review-table", cursor_type="row")
                yield ActionBar(id="review-action-bar")
            with Vertical(id="review-right"):
                yield ContentViewer(id="review-viewer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.add_column("Branch", key="branch")
        table.add_column("Status", key="status", width=12)
        table.add_column("Files", key="files", width=8)
        table.add_column("+Lines", key="ins", width=8)
        table.add_column("-Lines", key="del", width=8)

        self.query_one("#review-action-bar", ActionBar).show("Loading branches...")
        self._load_review()

    def _load_review(self) -> None:
        """Load branch data in a worker thread."""
        def _worker() -> None:
            try:
                result = load_review_branches(self._team_dir, self._iteration)
                self.post_message(_ReviewLoaded(result))
            except ReviewError as e:
                self.post_message(_ReviewScreenError(str(e)))

        self.run_worker(_worker, thread=True)

    def _populate_table(self, review: ReviewResult) -> None:
        """Fill the DataTable from ReviewResult."""
        table = self.query_one("#review-table", DataTable)
        table.clear()
        self._branches.clear()

        for br in review.branches:
            if br.merged:
                status = "[green]merged[/green]"
            elif br.empty:
                status = "[dim]empty[/dim]"
            else:
                status = "[yellow]unmerged[/yellow]"

            self._branches[br.branch] = {
                "branch": br.branch,
                "merged": br.merged,
                "empty": br.empty,
                "diff": br.diff,
                "stat": br.stat,
            }

            table.add_row(
                br.branch,
                status,
                str(br.files_changed),
                str(br.insertions),
                str(br.deletions),
                key=br.branch,
            )

        if review.branches:
            table.focus()
            # Show first branch diff
            first = review.branches[0]
            self.query_one("#review-viewer", ContentViewer).show_diff(
                first.branch, first.diff or first.stat or "(no changes)"
            )

        self._update_action_bar()

    def _update_action_bar(self) -> None:
        """Update action bar based on current state."""
        bar = self.query_one("#review-action-bar", ActionBar)
        if not self._review:
            bar.show("Loading...")
            return

        unmerged = [b for b in self._review.branches if not b.merged and not b.empty]
        merged = [b for b in self._review.branches if b.merged]

        if not unmerged and merged:
            bar.show(
                f"All {len(merged)} branch(es) merged. "
                "Press N to advance to next layer, R to refresh."
            )
        elif unmerged:
            bar.show(
                f"{len(unmerged)} unmerged, {len(merged)} merged. "
                "M=merge selected  Y=merge all  R=refresh  Esc=back"
            )
        else:
            bar.show("No branches to merge. Esc=back")

    def _get_selected_branch(self) -> dict | None:
        """Get branch info for the currently selected table row."""
        table = self.query_one("#review-table", DataTable)
        key_str = get_selected_row_key(table)
        if key_str is None:
            return None
        return self._branches.get(key_str)

    # ── DataTable events ──────────────────────────────────────

    def on_data_table_cursor_moved(self, event: DataTable.CursorMoved) -> None:
        br = self._get_selected_branch()
        if br:
            viewer = self.query_one("#review-viewer", ContentViewer)
            viewer.show_diff(
                br["branch"],
                br["diff"] or br["stat"] or "(no changes)",
            )

    # ── Message handlers ──────────────────────────────────────

    def on__review_loaded(self, message: _ReviewLoaded) -> None:
        self._review = message.result
        layer = message.result.layer
        total = message.result.total_files
        self.sub_title = f"Layer {layer} - {total} file(s) changed"
        self._populate_table(message.result)

    def on__review_screen_error(self, message: _ReviewScreenError) -> None:
        self.notify(message.error, severity="error")
        self.app.pop_screen()

    def on__merge_done(self, message: _MergeDone) -> None:
        self._merging = False
        bar = self.query_one("#review-action-bar", ActionBar)

        failed = [r for r in message.results if not r.success]
        succeeded = [r for r in message.results if r.success]

        if failed:
            conflict = failed[0]
            conflicts_str = ", ".join(conflict.conflicts[:3])
            bar.show(
                f"CONFLICT on {conflict.branch}: {conflicts_str}. "
                "Resolve in terminal, then press R to refresh."
            )
        elif succeeded:
            names = ", ".join(r.branch for r in succeeded)
            bar.show(f"Merged: {names}. Refreshing...")
            self._load_review()
        else:
            bar.show("Nothing to merge.")

    def on__next_layer_done(self, message: _NextLayerDone) -> None:
        self._merging = False
        result = message.result
        bar = self.query_one("#review-action-bar", ActionBar)

        if result.all_done:
            self._all_layers_done = True
            bar.show(
                f"All layers complete (through layer {result.from_layer}). "
                "Press F to mark done, Esc to go back."
            )
        else:
            bar.show(
                f"Advanced to layer {result.to_layer} (implementation). "
                "Press Esc to go back."
            )
            self.app.pop_screen()

    # ── Actions ───────────────────────────────────────────────

    def action_go_back(self) -> None:
        if self._merging:
            return
        self.app.pop_screen()

    def action_merge_selected(self) -> None:
        if self._merging:
            return
        br = self._get_selected_branch()
        if not br or br["merged"] or br["empty"]:
            self.notify("Select an unmerged branch to merge.", severity="warning")
            return
        self._merging = True
        self.query_one("#review-action-bar", ActionBar).show(
            f"Merging {br['branch']}..."
        )
        branch_name = br["branch"]

        def _worker() -> None:
            try:
                results = merge_branches(
                    self._project_root, self._review.layer,
                    branches=[branch_name],
                    on_progress=lambda msg: None,
                )
                self.post_message(_MergeDone(results))
            except ReviewError as e:
                self.post_message(_ReviewScreenError(str(e)))
                self._merging = False

        self.run_worker(_worker, thread=True)

    def action_merge_all(self) -> None:
        if self._merging or not self._review:
            return
        unmerged = [b for b in self._review.branches if not b.merged and not b.empty]
        if not unmerged:
            self.notify("All branches already merged.", severity="warning")
            return
        self._merging = True
        self.query_one("#review-action-bar", ActionBar).show(
            f"Merging {len(unmerged)} branch(es)..."
        )

        def _worker() -> None:
            try:
                results = merge_branches(
                    self._project_root, self._review.layer,
                    on_progress=lambda msg: None,
                )
                self.post_message(_MergeDone(results))
            except ReviewError as e:
                self.post_message(_ReviewScreenError(str(e)))
                self._merging = False

        self.run_worker(_worker, thread=True)

    def action_next_layer(self) -> None:
        if self._merging or not self._review:
            return
        unmerged = [b for b in self._review.branches if not b.merged and not b.empty]
        if unmerged:
            self.notify(
                f"{len(unmerged)} branch(es) still unmerged. Merge first.",
                severity="warning",
            )
            return
        self._merging = True
        self.query_one("#review-action-bar", ActionBar).show("Advancing to next layer...")

        def _worker() -> None:
            try:
                result = advance_next_layer(
                    self._team_dir, self._iteration, self._iter_dir,
                    on_progress=lambda msg: None,
                )
                self.post_message(_NextLayerDone(result))
            except ReviewError as e:
                self.post_message(_ReviewScreenError(str(e)))
                self._merging = False

        self.run_worker(_worker, thread=True)

    def action_finish_iteration(self) -> None:
        if not self._all_layers_done:
            return
        from gotg.config import save_iteration_fields
        save_iteration_fields(self._team_dir, self._iteration["id"], status="done")
        self.notify(f"Iteration {self._iteration['id']} marked as done.")
        self.app.pop_screen()

    def action_refresh(self) -> None:
        if self._merging:
            return
        self.query_one("#review-action-bar", ActionBar).show("Refreshing...")
        self._load_review()
