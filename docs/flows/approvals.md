# Flow: File Write Approvals

Traces how agent file writes are gated, queued, and resolved.

## Setup

Enabled by `file_access.enable_approvals: true` in team.json. Built during session infrastructure setup by `session_setup.py::build_file_infra()`.

## Real-time Write Path (during session)

1. Agent calls `file_write` (or `file_delete`, `file_rename`) tool
2. `engine.py::build_tool_executor` routes to `tools.py::execute_file_tool`
3. `fileguard.check_write(path)` returns 3-way decision:
   - **ALLOWED** -- write immediately via FileGuard, return success message
   - **APPROVAL_REQUIRED** -- queue in `ApprovalStore`, return pending message to agent
   - **DENIED** -- return error string (hard-deny zone: `.team/`, `.git/`, `.env*`)
4. Write count tracked per turn via closure in `build_tool_executor`; exceeding `max_files_per_turn` returns error
5. If worktrees are active, `fileguard.with_root(worktree_path)` scopes writes to agent's worktree
6. If any writes are pending at end of agent turn, engine yields `PauseForApprovals`
7. `console_events.py` / TUI transitions to PAUSED state

## CLI Resolution

### Viewing (`gotg approvals`)
- `commands/admin.py::cmd_approvals` loads `ApprovalStore` from `iter_dir/approvals.json`
- Lists pending requests with ID, path, content preview, and requesting agent

### Approving (`gotg approve <id>` or `gotg approve all`)
- `commands/admin.py::cmd_approve` calls `store.approve(id)` or `store.approve_all()`
- Marks request(s) as approved in `approvals.json`
- Writes are NOT applied yet -- deferred to `gotg continue`

### Denying (`gotg deny <id> -m 'reason'`)
- `commands/admin.py::cmd_deny` calls `store.deny(id, reason)`
- Marks request as denied with reason in `approvals.json`
- Denial injection deferred to `gotg continue`

## On Continue (`gotg continue`)

1. `commands/run.py::cmd_continue` calls `session_setup.py::prepare_continue()`
2. `prepare_continue()` calls `apply_and_inject()`:
   - `apply_approved_writes()` executes approved writes through FileGuard (still validated)
   - If worktrees active, `fileguard_for_agent` callback routes writes to correct worktree
   - Each result (success or failure) becomes a system message appended to conversation log
   - Denied requests: `get_denied_uninjected()` finds uninjected denials, creates system messages with denial reason, calls `mark_injected(id)`
3. `prepare_continue()` checks for remaining pending approvals, warns user if any
4. Agent sees approval/denial system messages in subsequent turns and adjusts behavior

## TUI Resolution

- `PauseForApprovals` event transitions ChatScreen to PAUSED state
- `A` key binding opens `tui/screens/approval.py::ApprovalScreen`
- DataTable + ContentViewer split-view for reviewing file content
- Approve/deny individual requests
- On resume, `apply_and_inject` runs in `_run_engine` worker before engine restart

## Files Touched

| Module | Responsibility |
|--------|---------------|
| `tools.py` | `execute_file_tool`: 3-way write decision at tool call time |
| `fileguard.py` | Path validation, allow/require/deny logic, `with_root()` for worktrees |
| `approvals.py` | `ApprovalStore` CRUD, `apply_approved_writes` execution |
| `commands/admin.py` | CLI commands: `cmd_approvals`, `cmd_approve`, `cmd_deny` |
| `session_setup.py` | `build_file_infra`, `apply_and_inject`, `prepare_continue` |
| `engine.py` | `build_tool_executor` (write counting, worktree routing), yields `PauseForApprovals` |
| `tui/screens/approval.py` | TUI approval management screen |
