# TUI Manual Test Plan

Exhaustive walkthrough covering every screen, binding, action, and user-visible behavior.

## Prerequisites

- **Python 3.11+**
- Installed from source: `pip install -e ".[tui]"` (from the gotg repo root)
- Project initialized with `gotg init` (`.team/` directory exists)
- A working model config in `team.json` (for live session tests)
- At least one iteration with conversation history (for viewing tests)
- Ideally a second project in various states (pending iteration, completed phases, approvals pending) to avoid needing to reach every state from scratch

---

## 1. App Launch

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 1.1 | Basic launch | `gotg ui` from project root | App opens, header shows "gotg", footer shows keybindings, HomeScreen displayed |
| 1.2 | Launch without textual | Uninstall textual, run `gotg ui` | Graceful error message suggesting `pip install gotg[tui]` |
| 1.3 | Launch outside project | `gotg ui` from a directory with no `.team/` | Graceful error (not unhandled exception) |
| 1.4 | Quit | Press `q` | App exits cleanly |

---

## 2. Help Screen

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 2.1 | Open from home | Press `?` on HomeScreen | Modal opens with title "Help — HomeScreen", lists all bindings |
| 2.2 | Open from chat | Press `?` on ChatScreen | Modal shows ChatScreen-specific bindings |
| 2.3 | Bindings listed | Read help content | Shows both screen-specific and global (q, ?) bindings |
| 2.4 | Close with ? | Press `?` again | Modal closes |
| 2.5 | Close with Esc | Press `Escape` | Modal closes |
| 2.6 | Key formatting | Check binding labels | "Esc" not "escape", "Ctrl+S" not "ctrl+s", "?" not "question_mark", "Del" not "delete" |

---

## 3. Home Screen — Iterations Tab

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 3.1 | Default tab | Launch app | "Iterations" tab is selected, DataTable is focused |
| 3.2 | Table columns | View iteration table | Columns: ID, Description, Phase, Status, Msgs, Activity |
| 3.3 | Current marker | View rows | Current iteration marked with ">" prefix or similar indicator |
| 3.4 | Status display | View rows with different statuses | Shows pending, in-progress, done |
| 3.5 | Message count | View Msgs column | Shows correct count of lines in conversation.jsonl |
| 3.6 | Activity column | View Activity column | Shows relative time: "just now", "1m ago", "1h ago", "1d ago" |
| 3.7 | Empty state | Launch with no iterations | Shows "No iterations yet." placeholder text |
| 3.8 | Refresh | Press `r` | Table reloads data from disk |
| 3.9 | Row navigation | Arrow keys up/down | Cursor moves between rows |
| 3.10 | Open iteration | Select row, press `Enter` | ChatScreen opens with conversation loaded in VIEWING state |

---

## 4. Home Screen — Grooming Tab

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 4.1 | Switch to tab | Click "Grooming" tab or navigate with Tab | Grooming DataTable shown |
| 4.2 | Table columns | View grooming table | Columns: Slug, Topic, Coach, Msgs, Activity |
| 4.3 | Coach indicator | View Coach column | Shows "yes" or empty |
| 4.4 | Empty state | No grooming sessions exist | Shows "No grooming sessions yet." placeholder |
| 4.5 | Open grooming | Select row, press `Enter` | ChatScreen opens with grooming conversation |

---

## 5. Home Screen — Info Tab

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 5.1 | Switch to tab | Click "Info" tab | Info content displayed |
| 5.2 | Content | View info | Shows project config: team dir, model, agents, coach, file tools, worktrees, counts |

---

## 6. Home Screen — Actions

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 6.1 | New iteration | Press `N` on Iterations tab | TextInputModal appears asking for description |
| 6.2 | New iteration — submit | Type description, press Enter | New iteration created, table updated, notification shown |
| 6.3 | New iteration — cancel | Press Escape in modal | No iteration created |
| 6.4 | New iteration — empty | Submit with empty text | Modal stays open (or dismisses with no action) |
| 6.5 | New grooming | Switch to Grooming tab, press `N` | TextInputModal for grooming topic |
| 6.6 | New grooming — submit | Type topic, press Enter | New grooming session created, table updated |
| 6.7 | Edit iteration | Select row, press `E` | EditIterationModal opens with current description, max_turns, status |
| 6.8 | Edit — save | Change fields, press Ctrl+S | Values saved, table row updated, notification |
| 6.9 | Edit — cancel | Press Escape | No changes saved |
| 6.10 | Edit — validation | Clear description, Ctrl+S | Warning: description required |
| 6.11 | Edit — max turns validation | Enter non-numeric max_turns, Ctrl+S | Warning: must be positive integer |
| 6.12 | Edit grooming | Select grooming row, press `E` | Notification: "Grooming sessions can't be edited yet." |
| 6.13 | Run from home | Select iteration, press `R` | ChatScreen opens with mode="run", session starts automatically |
| 6.14 | Run pending — no description | Select pending iteration with no description, press `R` | TextInputModal prompts for description first, then starts |
| 6.15 | Run switches current | Select non-current iteration, press `R` | Iteration becomes current, notification "Switched to {id}" |
| 6.16 | Continue from home | Select iteration, press `C` | ChatScreen opens with mode="continue", session resumes |
| 6.17 | Settings | Press `S` | SettingsScreen opens |
| 6.18 | Return from screen | Open any sub-screen, then go back | HomeScreen refreshes data (on_screen_resume) |

---

## 7. Settings Screen — Model Configuration

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 7.1 | Load config | Open settings | Provider, model, base_url, api_key populated from team.json |
| 7.2 | Provider — ollama preset | Select "ollama" from provider dropdown | base_url auto-fills to `http://localhost:11434/v1` |
| 7.3 | Provider — anthropic preset | Select "anthropic" | base_url auto-fills to `https://api.anthropic.com`, api_key to `ANTHROPIC_API_KEY` |
| 7.4 | Provider — openai preset | Select "openai" | base_url fills appropriately |
| 7.5 | Provider preset on change only | Re-select same provider | No change (guard prevents re-applying preset on mount) |
| 7.6 | Model name | Edit model name field | Free text input accepted |
| 7.7 | Base URL | Edit base_url field | Free text accepted |
| 7.8 | API key reference | Enter env var name or path | Free text accepted |

---

## 8. Settings Screen — Agents

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 8.1 | Agent table | View agent table | Shows all agents with Name and Role columns |
| 8.2 | Add agent — button | Click "Add (A)" button | AgentEditModal opens |
| 8.3 | Add agent — key | Press `A` | AgentEditModal opens |
| 8.4 | Add — fill and save | Enter name and role, Ctrl+S | Agent added to table |
| 8.5 | Add — role defaults | Enter name only, leave role blank, Ctrl+S | Role defaults to "Software Engineer" |
| 8.6 | Add — name required | Leave name blank, Ctrl+S | Warning notification, modal stays open |
| 8.7 | Add — cancel | Press Escape | No agent added |
| 8.8 | Edit agent — button | Select row, click "Edit (E)" | AgentEditModal opens pre-filled |
| 8.9 | Edit agent — key | Select row, press `E` | AgentEditModal opens pre-filled |
| 8.10 | Edit — save | Change name/role, Ctrl+S | Table row updated |
| 8.11 | Remove agent — key | Select row, press `Delete` or `Backspace` | ConfirmModal asks "Remove agent {name}?" |
| 8.12 | Remove — confirm | Press `Y` in confirm modal | Agent removed from table |
| 8.13 | Remove — cancel | Press `N` or Escape in confirm modal | Agent kept |
| 8.14 | Remove — minimum 2 | Try to remove when only 2 agents | Warning notification, removal blocked |

---

## 9. Settings Screen — Coach

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 9.1 | Coach toggle — on | Coach Switch is on (default if coach exists) | Name and Role inputs are enabled and editable |
| 9.2 | Coach toggle — off | Turn Switch off | Name and Role inputs become disabled/grayed |
| 9.3 | Save with coach off | Toggle off, Ctrl+S, check team.json | No "coach" key in team.json (or null) |
| 9.4 | Save with coach on | Toggle on, fill name/role, Ctrl+S | Coach present in team.json |

---

## 10. Settings Screen — File Access & Worktrees

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 10.1 | Writable paths | Enter comma-separated paths | Free text accepted |
| 10.2 | Protected paths | Enter comma-separated paths | Free text accepted |
| 10.3 | Max file size | Enter number | Positive integer accepted |
| 10.4 | Max file size — invalid | Enter non-numeric text, save | Validation error on save |
| 10.5 | Max files per turn | Enter number | Positive integer accepted |
| 10.6 | Max files per turn — invalid | Enter "abc", save | Validation error |
| 10.7 | Enable approvals | Toggle approvals Switch | Value saved on Ctrl+S |
| 10.8 | Worktrees toggle | Toggle worktrees Switch | Value saved on Ctrl+S |

---

## 11. Settings Screen — Save & Navigation

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 11.1 | Save — valid | Fill all required fields, Ctrl+S | "Settings saved." notification, team.json updated on disk |
| 11.2 | Save — no model | Clear model name, Ctrl+S | Warning: model name required |
| 11.3 | Save — <2 agents | (Should be blocked by remove guard, but verify) | Warning: at least 2 agents required |
| 11.4 | API key empty | Clear api_key, save | api_key omitted from team.json (not saved as empty string) |
| 11.5 | Escape without save | Make changes, press Escape | Returns to HomeScreen, changes NOT persisted |
| 11.6 | Verify on disk | After save, open team.json in editor | All values match what was entered |

---

## 12. Chat Screen — Viewing Mode

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 12.1 | Load messages | Open iteration with conversation | Messages displayed as bordered Chatbox widgets |
| 12.2 | Markdown rendering | Message with `# heading`, `**bold**`, `- list` | Rendered as formatted Markdown |
| 12.3 | Code fences | Message with ` ```python\nprint('hello')\n``` ` | Syntax-highlighted code block |
| 12.4 | Agent border colors | Multiple agents in conversation | Each gets distinct border: cyan, yellow, green, purple (by discovery order) |
| 12.5 | Agent color cycling | 5+ agents in conversation | 5th agent wraps to cyan (same as 1st) |
| 12.6 | Same agent same color | Agent appears multiple times | Always same border color |
| 12.7 | Human border | Message from "human" | Green border |
| 12.8 | System border | Message from "system" | Magenta border |
| 12.9 | Coach border | Message from coach | Orange (#ff8700) border |
| 12.10 | Border titles | View chatboxes | Each shows sender name as border_title |
| 12.11 | Phase boundary | Phase transition in history | Bold magenta separator line (not a chatbox) |
| 12.12 | Pass turn message | Message with pass_turn flag | Italic muted text (not a chatbox) |
| 12.13 | Empty conversation | Open iteration with no messages | "No messages yet." placeholder |
| 12.14 | Long content | Message with 100+ lines | Renders without crash, scrollable |
| 12.15 | Special characters | Message with `[brackets]`, `<tags>` | Escaped correctly, no Rich markup errors |
| 12.16 | Info tile — fields | View sidebar | Shows: iteration ID, description, phase, layer (if set), status, message count, max turns, last activity, agents, coach, session status |
| 12.17 | Scroll to top | Press `Home` | View jumps to first message |
| 12.18 | Scroll to bottom | Press `End` | View jumps to last message |
| 12.19 | Mouse scroll | Scroll with mouse wheel | Message list scrolls normally |
| 12.20 | Input placeholder | View input area | Shows "Press R to run, C to continue..." |
| 12.21 | Input enabled | Try typing | Input accepts text |
| 12.22 | Escape back | Press `Escape` | Returns to HomeScreen |

---

## 13. Chat Screen — Running Session

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 13.1 | Start run — R key | Press `R` in VIEWING state | State → RUNNING, input disabled, placeholder "Session running..." |
| 13.2 | Start run — auto | Open via `R` from HomeScreen | Session starts automatically on mount |
| 13.3 | Messages stream | Watch during running | New Chatbox widgets appear in real time |
| 13.4 | Turn counter | Watch info tile | Turn count increments with each engineering agent message (not coach/system/human) |
| 13.5 | Info status | During running | Info tile shows "Session: Running (turn N)" |
| 13.6 | Action bar hidden | During running | Action bar not visible |
| 13.7 | R ignored when running | Press `R` during RUNNING | Nothing happens |
| 13.8 | C ignored when running | Press `C` during RUNNING | Nothing happens |
| 13.9 | Cancel — Escape | Press `Escape` during RUNNING | Cancel requested, returns to HomeScreen |
| 13.10 | Session complete | Session reaches max turns | State → COMPLETE, action bar: "Session complete (N turns). Press C to continue with more turns." |
| 13.11 | Engine error | Trigger an error (e.g., bad API config) | Notification: "Session error: ...", state → VIEWING |

---

## 14. Chat Screen — Smart Auto-Scroll

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 14.1 | Auto-scroll at bottom | Start session, stay at bottom | New messages appear, view stays at bottom automatically |
| 14.2 | No yank when scrolled up | During running, scroll UP (mouse wheel or Page Up) to read earlier messages | New messages still arrive but view stays where you scrolled — NOT pulled to bottom |
| 14.3 | Resume auto-scroll | After scrolling up, press `End` to return to bottom, wait for messages | Auto-scroll resumes, new messages keep view at bottom |
| 14.4 | Bulk load scrolls | Open iteration with many messages | View starts at the bottom (most recent visible) |
| 14.5 | Append after empty | Open empty conversation, start run | First message appears, view shows it |

---

## 15. Chat Screen — Loading Indicator

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 15.1 | Spinner appears on run | Press `R` to start | Animated spinner (dots/bar) visible at bottom of message list |
| 15.2 | Spinner position | Watch during running | Spinner is always below the last message |
| 15.3 | Spinner between messages | Watch as messages arrive | Spinner briefly hides when message mounts, then reappears below it |
| 15.4 | Spinner gone on pause | Session pauses (phase complete / approvals / coach) | Spinner disappears |
| 15.5 | Spinner gone on complete | Session finishes (max turns) | Spinner disappears |
| 15.6 | Spinner on continue | Press `C` to resume | Spinner reappears |
| 15.7 | Spinner with human message | Type reply to coach, press Enter | Human message appears, then spinner shows while engine processes |
| 15.8 | No duplicate spinners | Rapidly trigger show_loading | Only one spinner visible at a time |

---

## 16. Chat Screen — Continue & Input

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 16.1 | Continue — C key | Press `C` in VIEWING state | Session starts (continue mode) |
| 16.2 | Continue from PAUSED | Press `C` when paused | Session resumes |
| 16.3 | Continue from COMPLETE | Press `C` when complete | New session with more turns |
| 16.4 | Continue with message — Enter | Type text in input, press Enter (while PAUSED or COMPLETE) | Human message appears in chat, session resumes |
| 16.5 | Continue with message — C key | Type text in input, press `C` | Human message sent, session starts |
| 16.6 | Empty input — Enter | Press Enter with no text | Nothing happens |
| 16.7 | Input clears after submit | Type text, press Enter | Input field is cleared |

---

## 17. Chat Screen — Phase Complete & Advance

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 17.1 | Phase complete signal | Run until coach signals phase complete | State → PAUSED, action bar: "Phase complete. Press P to advance, C to continue discussing." |
| 17.2 | Phase complete — code-review | Complete signal in code-review phase | Action bar: "Code review complete. Press D to review diffs and merge." (not P) |
| 17.3 | Advance — press P | Press `P` when paused at phase complete | State → ADVANCING, "Advancing phase..." in action bar |
| 17.4 | Advance progress | Watch during advance | Action bar updates with progress steps (extracting summary, tasks, etc.) |
| 17.5 | Advance success | Advance completes | Boundary marker + transition message appear in chat, info tile phase updates, state → VIEWING, action bar: "Advanced: X -> Y. Press R to run." |
| 17.6 | Advance error | Advance fails (e.g., already at code-review) | State returns to PAUSED, action bar: "Advance failed: ..." |
| 17.7 | Advance partial warning | Advance succeeds with warnings | Notification with warning text |
| 17.8 | P ignored — wrong state | Press `P` in VIEWING or RUNNING | Nothing happens |
| 17.9 | P ignored — wrong reason | Press `P` when paused for APPROVALS or COACH_QUESTION | Nothing happens |
| 17.10 | P ignored — grooming | Press `P` in a grooming session | Nothing happens (iterations only) |
| 17.11 | Continue instead | Press `C` at phase complete | Session continues in same phase (more discussion) |
| 17.12 | Phase display | After advance | Info tile shows new phase name |

---

## 18. Chat Screen — Coach Interaction (ask_pm)

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 18.1 | Coach question | Run until coach calls ask_pm | State → PAUSED, action bar shows coach's question text |
| 18.2 | Input focus | Paused for coach question | Input focused, placeholder: "Type reply and press Enter..." |
| 18.3 | Reply | Type answer, press Enter | Human message appears in chat, session resumes |
| 18.4 | Reply with C key | Type answer, press `C` | Human message sent, session continues |
| 18.5 | Info status | While paused for coach | Info tile shows "Session: Paused (turn N)" |

---

## 19. Chat Screen — Approvals

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 19.1 | Approval pause | Agent writes outside writable paths (with approvals enabled) | State → PAUSED, action bar: "Paused: N pending approval(s). Press A to review approvals, C to continue." |
| 19.2 | A key opens screen | Press `A` when paused for approvals | ApprovalScreen opens |
| 19.3 | A ignored — wrong state | Press `A` in VIEWING or RUNNING | Nothing happens |
| 19.4 | A ignored — wrong reason | Press `A` when paused for PHASE_COMPLETE | Nothing happens |
| 19.5 | A ignored — no file | Press `A` when approvals.json doesn't exist | Warning notification |
| 19.6 | Return from approvals | Escape from ApprovalScreen | Chat action bar refreshes with current pending count |
| 19.7 | All resolved | Approve/deny all approvals, return | Action bar: "All approvals resolved. Press C to continue." |

---

## 20. Approval Screen

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 20.1 | Table columns | Open approval screen | Columns: ID, Path, Agent, Size, Status |
| 20.2 | Subtitle | View screen title area | Shows "N pending" count |
| 20.3 | Status colors | View status column | Pending=yellow, Approved=green, Denied=red |
| 20.4 | Size formatting | View Size column | Shows human-readable: "1.2K", "3.4M" |
| 20.5 | Select approval | Move cursor to a row | Right panel (ContentViewer) shows file content with syntax highlighting |
| 20.6 | Approve — A key | Select pending row, press `A` | Status changes to "approved", notification: "Approved: {path}" |
| 20.7 | Approve all — Y key | Press `Y` | All pending requests approved, notification: "Approved N request(s)." |
| 20.8 | Approve — not pending | Select already-approved row, press `A` | Notification: "Select a pending request to approve." |
| 20.9 | Approve — no pending | All resolved, press `A` or `Y` | Notification: "No pending approvals." |
| 20.10 | Deny — D key | Select pending row, press `D` | Denial input appears at bottom |
| 20.11 | Deny — submit reason | Type reason, press Enter | Status changes to "denied", notification: "Denied: {path}", input hides |
| 20.12 | Deny — empty reason | Press Enter with no text | Denied with no reason text |
| 20.13 | Deny — cancel | Press Escape while denial input visible | Input hides, no denial |
| 20.14 | Deny blocks other actions | While denial input showing, press A or D | Blocked (focus guard active) |
| 20.15 | Action bar | View bottom of left panel | Shows "A=approve D=deny Y=approve all Esc=back" |
| 20.16 | Escape back | Press `Escape` (no denial input active) | Returns to ChatScreen |

---

## 21. Chat Screen — Code Review & Diffs

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 21.1 | D key opens review | Paused at code-review phase complete, press `D` | ReviewScreen opens |
| 21.2 | D ignored — wrong phase | Paused at refinement phase complete, press `D` | Nothing happens |
| 21.3 | D ignored — wrong state | Press `D` in VIEWING or RUNNING | Nothing happens |
| 21.4 | Return from review — no change | Escape from ReviewScreen without merging | Chat state unchanged |
| 21.5 | Return from review — next layer | Complete next-layer in ReviewScreen, return | Chat metadata updated (phase, layer), info tile refreshed, boundary + transition messages appended, state → VIEWING, action bar: "Advanced to layer N (implementation). Press R to run." |

---

## 22. Review Screen

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 22.1 | Table columns | Open review screen | Columns: Branch, Status, Files, +Lines, -Lines |
| 22.2 | Branch status colors | View Status column | Merged=green, Empty=dim, Unmerged=yellow |
| 22.3 | Select branch | Move cursor to row | Right panel (ContentViewer) shows diff with syntax highlighting |
| 22.4 | Diff display | View diff content | Uses diff lexer, no line numbers |
| 22.5 | Merge single — M key | Select unmerged branch, press `M` | Branch merged, status updates, notification |
| 22.6 | Merge all — Y key | Press `Y` | All unmerged branches merged |
| 22.7 | Merge — already merged | Select merged branch, press `M` | Notification: "Select an unmerged branch to merge." |
| 22.8 | Merge — all done | All branches merged, press `M` | Notification: "All branches already merged." |
| 22.9 | Next layer — N key | All branches merged, press `N` | Layer advances, state updates, action bar shows progress |
| 22.10 | Next layer — unmerged | Press `N` with unmerged branches | Notification: "N branch(es) still unmerged. Merge first." |
| 22.11 | Finish iteration — F key | All layers done, press `F` | Iteration marked done, notification: "Iteration {id} marked as done." |
| 22.12 | Finish — not ready | Press `F` when not all layers done | Nothing happens |
| 22.13 | Refresh — R key | Press `R` | Branch data reloaded from disk |
| 22.14 | Error on load | Open review when no worktrees exist | Error notification, screen pops automatically |
| 22.15 | Merge conflict | Merge a branch with conflicts | Conflict notification with terminal instructions |
| 22.16 | No actions during merge | Press keys during merge operation | Blocked (_merging guard active) |
| 22.17 | Escape back | Press `Escape` | Returns to ChatScreen |

---

## 23. Grooming Sessions

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 23.1 | Open grooming | Select grooming session on HomeScreen, Enter | ChatScreen opens with grooming conversation |
| 23.2 | Run grooming | Select grooming, press `R` from HomeScreen | Session starts in freeform exploration mode |
| 23.3 | Continue grooming | Select grooming, press `C` from HomeScreen | Session resumes |
| 23.4 | No phase advance | Coach signals phase complete in grooming | P key does nothing (iteration-only) |
| 23.5 | No review | Press `D` during grooming | Nothing happens (iteration-only) |
| 23.6 | Coach in grooming | Grooming with coach enabled | Coach participates, ask_pm works |
| 23.7 | Info tile | View sidebar | Shows slug (not iteration ID), topic (not description), phase shows "—" or absent |

---

## 24. Modals — General Behavior

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 24.1 | Modal overlay | Open any modal | Background screen dimmed, modal centered |
| 24.2 | Escape closes | Press Escape in any modal | Modal dismisses with None/False |
| 24.3 | Focus trap | Tab in modal | Focus stays within modal widgets |
| 24.4 | TextInputModal | Trigger (new iteration/grooming) | Single input field, Enter submits, Escape cancels |
| 24.5 | TextInputModal — empty | Press Enter with no text | Dismisses with no action (or stays open) |
| 24.6 | ConfirmModal | Trigger (remove agent) | Shows question, Y/N buttons, Y key confirms, N/Escape cancels |
| 24.7 | ConfirmModal — button click | Click "Yes" button | Dismisses with True |
| 24.8 | ConfirmModal — button click | Click "No" button | Dismisses with False |
| 24.9 | AgentEditModal — add | Trigger from settings (A key) | Empty name/role inputs, title says "Add Agent" |
| 24.10 | AgentEditModal — edit | Trigger from settings (E key) | Pre-filled inputs, title says "Edit Agent" |
| 24.11 | AgentEditModal — Ctrl+S | Fill fields, Ctrl+S | Submits with {name, role} |
| 24.12 | AgentEditModal — save button | Click "Save" button | Same as Ctrl+S |
| 24.13 | EditIterationModal | Trigger from home (E key) | Pre-filled description, max_turns, status Select |
| 24.14 | EditIterationModal — status | Change status dropdown | pending/in-progress/done options |
| 24.15 | EditIterationModal — Tab navigation | Press Tab | Moves between description, max_turns, status, buttons |

---

## 25. Keyboard Navigation & Focus

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 25.1 | Home — table focus | Launch app | DataTable has focus (arrow keys work) |
| 25.2 | Home — tab switching | Use Tab to switch between Iterations/Grooming/Info | Content switches, focus updates |
| 25.3 | Chat — input focus on coach Q | Coach asks question | Input widget receives focus automatically |
| 25.4 | Chat — input not focused normally | VIEWING state | Input exists but isn't necessarily focused |
| 25.5 | Settings — Tab navigation | Press Tab repeatedly | Moves through provider, model, base_url, api_key, agent table, buttons, coach switch/inputs, file access fields, worktree switch |
| 25.6 | Approval — table focus | Open approval screen | DataTable has focus |
| 25.7 | Review — table focus | Open review screen | DataTable has focus |

---

## 26. Visual & Layout

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 26.1 | Chat layout | Open ChatScreen | 3fr message area (left) + 1fr info sidebar (right), border between |
| 26.2 | Approval layout | Open ApprovalScreen | 2fr table (left) + 3fr content viewer (right) |
| 26.3 | Review layout | Open ReviewScreen | 2fr table (left) + 3fr diff viewer (right) |
| 26.4 | Content viewer — syntax | View file in approval/review | Syntax-highlighted with Monokai theme, line numbers |
| 26.5 | Content viewer — diff | View diff in review | Diff lexer coloring (+green, -red), no line numbers |
| 26.6 | Content viewer — empty | No selection | Placeholder text: "Select an item to view..." |
| 26.7 | Action bar — visible | Pause state | Action bar appears with border-top, text visible |
| 26.8 | Action bar — hidden | Running or viewing | Action bar not visible |
| 26.9 | Footer | Any screen | Shows visible keybindings for current screen |
| 26.10 | Header | Any screen | Shows "gotg" app title |

---

## 27. Edge Cases & Robustness

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 27.1 | Large conversation | Open iteration with 500+ messages | Loads without crash, scrolling works |
| 27.2 | 1000-line message | Open conversation with a single very long message | Renders without crash |
| 27.3 | Special chars in content | Message with `[brackets]`, `<tags>`, `&entities` | Escaped correctly, no Rich markup parse errors |
| 27.4 | Rapid R presses | Press R multiple times quickly | Only one session starts (second R ignored in RUNNING) |
| 27.5 | Rapid P presses | Press P twice at phase complete | Only one advance runs (state changes to ADVANCING) |
| 27.6 | Resize terminal | Resize window during viewing and running | Layout reflows, no crash |
| 27.7 | Narrow terminal | Run with ~40x15 terminal | Usable (may be cramped), no layout crash |
| 27.8 | Wide terminal | Run with very wide terminal | Layout stretches proportionally |
| 27.9 | No API key | Remove API key, try R to run | Graceful error notification |
| 27.10 | Corrupt team.json | Malform JSON, launch UI | Graceful error |
| 27.11 | Missing conversation.jsonl | Open iteration where file doesn't exist | Empty message list, no crash |
| 27.12 | Concurrent access | Run `gotg ui` while CLI `gotg run` active on same iteration | No file corruption (both append to JSONL) |
| 27.13 | Unicode content | Messages with emoji, CJK, RTL text | Renders correctly |
| 27.14 | Empty team.json fields | Missing optional keys (file_access, worktrees) | Settings screen handles gracefully |
| 27.15 | Cancel during advance | Press Escape while ADVANCING | Returns to home (advance may complete in background) |
