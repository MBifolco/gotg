"""Conflict resolution screen for resolving merge conflicts."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Callable

from rich.markup import escape
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from gotg.session import (
    AiResolutionResult,
    ConflictFileInfo,
    ConflictInfo,
    MergeResult,
    ResolutionStrategy,
    ReviewError,
    ai_resolve_conflict,
    finalize_merge,
    load_conflict_info,
    resolve_conflict_file,
)
from gotg.tui.helpers import get_selected_row_key
from gotg.tui.widgets.action_bar import ActionBar
from gotg.tui.widgets.content_viewer import ContentViewer


# ── State machine ────────────────────────────────────────────


class _State(Enum):
    LOADING = "loading"
    BROWSING = "browsing"
    AI_REQUESTING = "ai_requesting"
    AI_PREVIEW = "ai_preview"
    COMPLETING = "completing"
    ABORTING = "aborting"


# ── Local Textual messages ───────────────────────────────────


class _ConflictLoaded(Message):
    def __init__(self, info: ConflictInfo) -> None:
        super().__init__()
        self.info = info


class _AiResolved(Message):
    def __init__(self, result: AiResolutionResult) -> None:
        super().__init__()
        self.result = result


class _AiResolveFailed(Message):
    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


class _MergeCompleted(Message):
    def __init__(self, result: MergeResult) -> None:
        super().__init__()
        self.result = result


class _MergeAborted(Message):
    pass


class _ConflictError(Message):
    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


# ── ConflictScreen ───────────────────────────────────────────


class ConflictScreen(Screen):
    """Resolve merge conflicts with ours/theirs/AI strategies."""

    BINDINGS = [
        Binding("escape", "abort_or_back", "Back/Abort"),
        Binding("o", "resolve_ours", "Ours", show=False),
        Binding("t", "resolve_theirs", "Theirs", show=False),
        Binding("a", "resolve_ai", "AI Resolve", show=False),
        Binding("y", "accept_ai", "Accept", show=False),
        Binding("n", "reject_ai", "Reject", show=False),
        Binding("c", "complete_merge", "Complete", show=False),
    ]

    def __init__(
        self,
        project_root: Path,
        branch: str,
        conflict_paths: list[str],
        team_dir: Path,
        task_context: str,
    ) -> None:
        super().__init__()
        self._project_root = project_root
        self._branch = branch
        self._conflict_paths = conflict_paths
        self._team_dir = team_dir
        self._task_context = task_context

        self._state = _State.LOADING
        self._conflict_info: ConflictInfo | None = None
        self._file_map: dict[str, ConflictFileInfo] = {}
        self._resolutions: dict[str, ResolutionStrategy] = {}
        self._ai_result: AiResolutionResult | None = None
        self._model_config: dict | None = None
        self._chat_call: Callable | None = None

    def compose(self):
        yield Header()
        with Horizontal(id="conflict-layout"):
            with Vertical(id="conflict-left"):
                yield DataTable(id="conflict-table", cursor_type="row")
                yield ActionBar(id="conflict-action-bar")
            with Vertical(id="conflict-right"):
                yield ContentViewer(id="conflict-viewer")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"Conflicts: {self._branch}"
        table = self.query_one("#conflict-table", DataTable)
        table.add_column("File", key="file")
        table.add_column("Status", key="status", width=14)
        table.add_column("Strategy", key="strategy", width=12)

        self.query_one("#conflict-action-bar", ActionBar).show("Loading conflict data...")
        self._load_conflicts()

    def _load_conflicts(self) -> None:
        def _worker() -> None:
            try:
                info = load_conflict_info(
                    self._project_root, self._branch, self._conflict_paths,
                )
                self.post_message(_ConflictLoaded(info))
            except ReviewError as e:
                self.post_message(_ConflictError(str(e)))

        self.run_worker(_worker, thread=True)

    def _populate_table(self) -> None:
        table = self.query_one("#conflict-table", DataTable)
        table.clear()
        if not self._conflict_info:
            return

        for f in self._conflict_info.files:
            strategy = self._resolutions.get(f.path)
            if strategy:
                status = "[green]resolved[/green]"
                strat_str = strategy.value
            else:
                status = "[red]conflict[/red]"
                strat_str = "-"
            table.add_row(f.path, status, strat_str, key=f.path)

        if self._conflict_info.files:
            table.focus()
            first = self._conflict_info.files[0]
            self._show_file_content(first)

    def _show_file_content(self, f: ConflictFileInfo) -> None:
        viewer = self.query_one("#conflict-viewer", ContentViewer)
        viewer.show_content(f.path, f.working_content)

    def _update_action_bar(self) -> None:
        bar = self.query_one("#conflict-action-bar", ActionBar)
        if self._state == _State.LOADING:
            bar.show("Loading...")
            return
        if self._state == _State.AI_REQUESTING:
            bar.show("AI resolving... please wait.")
            return
        if self._state == _State.AI_PREVIEW:
            bar.show("AI resolution preview. Y=accept  N=reject")
            return
        if self._state == _State.COMPLETING:
            bar.show("Completing merge...")
            return
        if self._state == _State.ABORTING:
            bar.show("Aborting merge...")
            return

        # BROWSING
        total = len(self._file_map)
        resolved = len(self._resolutions)
        remaining = total - resolved
        if remaining == 0:
            bar.show(
                f"All {total} file(s) resolved. "
                "C=complete merge  Esc=abort"
            )
        else:
            bar.show(
                f"{remaining}/{total} unresolved. "
                "O=ours  T=theirs  A=AI resolve  Esc=abort"
            )

    def _get_selected_file(self) -> ConflictFileInfo | None:
        table = self.query_one("#conflict-table", DataTable)
        key_str = get_selected_row_key(table)
        if key_str is None:
            return None
        return self._file_map.get(key_str)

    def _update_row(self, path: str, strategy: ResolutionStrategy) -> None:
        table = self.query_one("#conflict-table", DataTable)
        table.update_cell(path, "status", "[green]resolved[/green]")
        table.update_cell(path, "strategy", strategy.value)

    def _ensure_model_config(self) -> None:
        if self._model_config is None:
            from gotg.config import load_model_config
            self._model_config = load_model_config(self._team_dir)
        if self._chat_call is None:
            from gotg.model import chat_completion
            self._chat_call = chat_completion

    # ── DataTable events ─────────────────────────────────────

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._state not in (_State.BROWSING,):
            return
        f = self._file_map.get(event.row_key.value)
        if f:
            self._show_file_content(f)

    # ── Message handlers ─────────────────────────────────────

    def on__conflict_loaded(self, message: _ConflictLoaded) -> None:
        self._conflict_info = message.info
        self._file_map = {f.path: f for f in message.info.files}
        self._state = _State.BROWSING
        self._populate_table()
        self._update_action_bar()

    def on__conflict_error(self, message: _ConflictError) -> None:
        self.notify(message.error, severity="error")
        self.app.pop_screen()

    def on__ai_resolved(self, message: _AiResolved) -> None:
        self._ai_result = message.result
        self._state = _State.AI_PREVIEW
        # Show resolved content in viewer
        viewer = self.query_one("#conflict-viewer", ContentViewer)
        viewer.show_content(message.result.path, message.result.resolved_content)
        self._update_action_bar()

    def on__ai_resolve_failed(self, message: _AiResolveFailed) -> None:
        self._state = _State.BROWSING
        self.notify(message.error, severity="error")
        self._update_action_bar()

    def on__merge_completed(self, message: _MergeCompleted) -> None:
        self.dismiss(message.result)

    def on__merge_aborted(self, message: _MergeAborted) -> None:
        self.dismiss(None)

    # ── Actions ──────────────────────────────────────────────

    def action_abort_or_back(self) -> None:
        if self._state == _State.AI_PREVIEW:
            # Cancel preview, go back to browsing
            self._ai_result = None
            self._state = _State.BROWSING
            f = self._get_selected_file()
            if f:
                self._show_file_content(f)
            self._update_action_bar()
            return

        if self._state not in (_State.BROWSING,):
            return

        # If any files resolved, confirm abort
        if self._resolutions:
            from gotg.tui.modals import ConfirmModal
            self.app.push_screen(
                ConfirmModal(
                    f"{len(self._resolutions)} file(s) already resolved. Abort merge?"
                ),
                callback=self._on_abort_confirmed,
            )
        else:
            self._do_abort()

    def _on_abort_confirmed(self, confirmed: bool) -> None:
        if confirmed:
            self._do_abort()

    def _do_abort(self) -> None:
        self._state = _State.ABORTING
        self._update_action_bar()

        def _worker() -> None:
            try:
                from gotg.worktree import abort_merge
                abort_merge(self._project_root)
                self.post_message(_MergeAborted())
            except Exception as e:
                self.post_message(_ConflictError(f"Abort failed: {e}"))

        self.run_worker(_worker, thread=True)

    def action_resolve_ours(self) -> None:
        if self._state != _State.BROWSING:
            return
        f = self._get_selected_file()
        if not f or f.path in self._resolutions:
            return

        try:
            resolve_conflict_file(
                self._project_root, f.path, ResolutionStrategy.OURS,
            )
        except ReviewError as e:
            self.notify(str(e), severity="error")
            return

        self._resolutions[f.path] = ResolutionStrategy.OURS
        self._update_row(f.path, ResolutionStrategy.OURS)
        self._update_action_bar()

    def action_resolve_theirs(self) -> None:
        if self._state != _State.BROWSING:
            return
        f = self._get_selected_file()
        if not f or f.path in self._resolutions:
            return

        try:
            resolve_conflict_file(
                self._project_root, f.path, ResolutionStrategy.THEIRS,
            )
        except ReviewError as e:
            self.notify(str(e), severity="error")
            return

        self._resolutions[f.path] = ResolutionStrategy.THEIRS
        self._update_row(f.path, ResolutionStrategy.THEIRS)
        self._update_action_bar()

    def action_resolve_ai(self) -> None:
        if self._state != _State.BROWSING:
            return
        f = self._get_selected_file()
        if not f or f.path in self._resolutions:
            return

        self._state = _State.AI_REQUESTING
        self._update_action_bar()
        self._ensure_model_config()

        file_path = f.path
        base = f.base_content
        ours = f.ours_content
        theirs = f.theirs_content
        model_config = self._model_config
        chat_call = self._chat_call

        def _worker() -> None:
            try:
                result = ai_resolve_conflict(
                    file_path, self._branch,
                    base, ours, theirs,
                    self._task_context,
                    model_config, chat_call,
                )
                self.post_message(_AiResolved(result))
            except ReviewError as e:
                self.post_message(_AiResolveFailed(str(e)))

        self.run_worker(_worker, thread=True)

    def action_accept_ai(self) -> None:
        if self._state != _State.AI_PREVIEW or not self._ai_result:
            return

        try:
            resolve_conflict_file(
                self._project_root, self._ai_result.path,
                ResolutionStrategy.AI, content=self._ai_result.resolved_content,
            )
        except ReviewError as e:
            self.notify(str(e), severity="error")
            self._state = _State.BROWSING
            self._ai_result = None
            self._update_action_bar()
            return

        self._resolutions[self._ai_result.path] = ResolutionStrategy.AI
        self._update_row(self._ai_result.path, ResolutionStrategy.AI)
        self._ai_result = None
        self._state = _State.BROWSING
        self._update_action_bar()

    def action_reject_ai(self) -> None:
        if self._state != _State.AI_PREVIEW:
            return
        self._ai_result = None
        self._state = _State.BROWSING
        f = self._get_selected_file()
        if f:
            self._show_file_content(f)
        self._update_action_bar()

    def action_complete_merge(self) -> None:
        if self._state != _State.BROWSING:
            return
        total = len(self._file_map)
        resolved = len(self._resolutions)
        if resolved < total:
            self.notify(
                f"{total - resolved} file(s) still unresolved.",
                severity="warning",
            )
            return

        self._state = _State.COMPLETING
        self._update_action_bar()

        def _worker() -> None:
            try:
                result = finalize_merge(self._project_root, self._branch)
                self.post_message(_MergeCompleted(result))
            except ReviewError as e:
                self.post_message(_ConflictError(str(e)))

        self.run_worker(_worker, thread=True)
