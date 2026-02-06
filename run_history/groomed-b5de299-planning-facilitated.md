# Scope Summary: CLI Pomodoro Timer

## Summary
The team is building a terminal-native Pomodoro timer for developers who value focus and structured work sessions. The tool will manage automated work/break cycles with standard Pomodoro intervals (25/5/15 minutes), persist independently of terminal sessions, and provide optional session logging. The design emphasizes non-interruptive flow while respecting user agency through explicit override commands.

## Agreed Requirements

**Target User**
- Developers who want terminal-native focus tool with discipline and structure
- Values workflow integration that adapts to real-world interruptions

**Core Timer Mechanics**
- Standard defaults: 25 min work / 5 min short break / 15 min long break
- Auto-advancement: work sessions → breaks auto-start, then wait for user to continue next work session
- Complete cycle = 4 pomodoros + 3 short breaks + 1 long break
- After cycle completes, stop and wait for user to start new cycle
- No pause feature - cancel/restart only
- Ctrl+C cancels the timer

**Configuration System**
- Config file as single source of truth
- Environment variables for one-off overrides
- `pomodoro config --show` displays effective settings including env var overrides
- Environment variables documented in help text
- Standard intervals configurable

**Commands**
- `pomodoro start` - begin new cycle or work session
- `pomodoro continue` - start next work session after break
- `pomodoro skip` - skip current break, start work immediately
- `pomodoro cancel` - stop current timer
- `pomodoro status` - show current state, time remaining, available actions
- `pomodoro log` - add description to completed session (supports retroactive logging)
- Must prevent concurrent timers with clear error messaging

**Notifications**
- Desktop notifications at: work session end, break end, cycle complete
- Include context: what just ended, what's next, relevant commands
- Must work when terminal is closed/detached
- Cross-platform support: Linux, macOS, Windows

**Session Logging**
- Automatic timestamp logging for all sessions
- Task descriptions completely optional
- Manual logging via `pomodoro log` command available anytime (opt-in)
- Optional cycle-end prompt for summary notes
- Support logging to recent sessions, not just current

**Resilience & Reliability**
- Timer state must survive terminal closure
- Handle system sleep/wake gracefully
- Timer continues running when terminal detached
- Clear error messages for edge cases (concurrent starts, state corruption)

**Discoverability**
- Override commands (`skip`, `continue`) prominently documented in help
- Notifications hint at available commands
- `pomodoro status` shows context-appropriate actions

## Open Questions
None - all core requirements resolved through discussion.

## Assumptions

- Users are comfortable with command-line interfaces and basic terminal concepts
- Desktop notification systems are available on target platforms
- Users working in flow states can take 2 seconds to run override commands when needed
- A complete Pomodoro cycle (2+ hours) is a natural stopping point for reflection
- Users who want detailed time-tracking will proactively use `pomodoro log` after sessions
- Terminal closure (accidental or intentional) is common enough to require resilience
- System sleep/wake during timers is a realistic scenario worth handling

## Out of Scope

**Explicitly Deferred**
- Analytics/reporting dashboards beyond basic logs
- Integration with external tools (calendars, task trackers)
- Audio alerts (desktop notifications only for MVP)
- Session tagging/categorization systems beyond basic descriptions
- Graphical user interface
- Multi-user or team features
- Cloud sync or remote access
- Pause/resume functionality (methodology decision)

**Implementation Details (for Planning Phase)**
- Daemon vs. state file architecture
- Specific notification libraries/APIs
- Lock file vs. socket for concurrent prevention
- Exact handling of sleep/wake cycles
- Log storage format and location
- Specific platform compatibility details
