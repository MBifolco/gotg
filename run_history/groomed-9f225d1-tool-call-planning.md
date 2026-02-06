# Grooming Summary: Terminal-Native Pomodoro Timer

## Summary

The team is building a terminal-native Pomodoro timer for developers that runs as a single-instance TUI application with state persistence to disk. The timer enforces the standard 4-session Pomodoro cycle (25/5/25/5/25/5/25/15 minutes) with blocking transitions requiring user acknowledgment. The tool includes basic pause/resume functionality for work sessions, allowing users to recover from terminal crashes or brief interruptions while maintaining cycle position across sessions.

## Agreed Requirements

**Core Functionality:**
- Single TUI application with state saved to disk (no background daemon for Phase 1)
- Standard 4-session cycle enforced: 25-min work, 5-min short break (×3), 25-min work, 15-min long break
- Cycle position persists indefinitely until manual reset or long break completion
- Blocking transitions - user must acknowledge (press Enter) before advancing to next session
- Terminal bell notifications when sessions complete
- Clear visual distinction between work mode and break mode in TUI
- Session history automatically logged in Unix-parseable format

**Pause/Resume Behavior:**
- Work sessions: terminal close or Ctrl+C saves state → restart prompts "Resume or Void?" with void as default
- Break interruptions: breaks considered complete → restart prompts to start next work session (no resume/void for breaks)
- Resumed work sessions flagged in history log

**Commands:**
- `pomodoro` - main interface (interactive: starts, resumes, or shows status based on current state)
- `pomodoro status` - read-only status check (session type, time remaining, cycle position, what's next)
- `pomodoro reset` - reset cycle to session 1 (prompts for confirmation if session active)
- `pomodoro void` - void current work session only (not available for breaks)
- `pomodoro help` / `--help` - show usage information
- `pomodoro --version` - show version

**Platform & Environment:**
- Linux and macOS support for Phase 1
- Windows support deferred to Phase 2 (WSL users can use Linux version)
- Zero-config design with hardcoded sensible defaults
- No configuration file support in Phase 1
- Fail fast on file write failures with clear error messages
- Standard file locations for state and history (exact paths deferred to planning)
- No backwards compatibility guarantees between Phase 1 versions

**Error Handling:**
- File write failures at startup or during operation: error and exit with clear message
- Corrupted state file: log warning, reset to clean state, continue
- Concurrent instances: detect and error (only one active session allowed)
- Graceful shutdown on SIGINT/SIGTERM with state save

**Edge Cases:**
- First-time user: show brief intro and prompt to start first session
- Reset during active session: prompt for confirmation before voiding
- Multiple concurrent instances: detect and prevent (file locking or error)
- Between sessions (no active timer): prompt to start next session in cycle
- After long break completion: require explicit "Start new cycle" action (don't auto-start)

## Open Questions

None - team reached complete consensus on Phase 1 scope.

## Assumptions

- **Adapted Pomodoro methodology**: The tool adapts traditional Pomodoro for developer workflows (allows resume after interruptions) rather than strictly enforcing "interrupted session = void"
- **"Persist independently of terminal sessions"** interpreted as: state saves to disk and can be resumed in any terminal, but does NOT mean background daemon or real-time multi-terminal sync (deferred to Phase 2)
- **Target users**: Developers working in terminal-heavy environments with multiple windows/tabs, frequent context switches, and occasional production interruptions
- Developers typically use Unix-like systems (Linux/macOS) and modern terminals with ANSI color support
- Users understand basic Pomodoro technique concepts (work sessions, breaks, cycles)
- File system is writable and has adequate space for small state/log files
- No need for tutorial/extensive help text - minimal intro is sufficient
- Standard terminal capabilities assumed (80×24 minimum, ANSI colors, terminal bell)

## Out of Scope

**Deferred to Phase 2 or Later:**
- Background daemon with multi-terminal real-time synchronization
- History viewing command (`pomodoro history`)
- Custom interval configuration (non-standard session/break lengths)
- Session notes/tags (user annotations on what they worked on)
- System desktop notifications (beyond terminal bell)
- Configuration file support (customizable notification sounds, defaults, etc.)
- Windows native support (non-WSL)
- Explicit pause command (only implicit via terminal close)
- Session statistics/analytics/reports
- IDE integrations or external tool integration
- Auto-start on system boot or daemon auto-restart
- Idle detection or activity monitoring
- Time-based automatic cycle resets
- Survive machine reboot (daemon lifecycle independent of user session)
- Backwards compatibility for state file format changes
- Tutorial or interactive help system beyond basic usage text
- Environment variable overrides for file locations
