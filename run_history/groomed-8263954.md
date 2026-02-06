# Grooming Session Summary: Command-Line Todo List Application

## Summary
The team is building a command-line todo list application that allows users to manage tasks with priorities and due dates. Tasks persist across application restarts, and the system provides an intelligent default view that surfaces urgent and important work while keeping completed tasks visible for reference.

## Agreed Requirements

### Core Operations
- **add**: Create tasks with title, optional priority (High/Medium/Low), and optional due date
- **list**: Display all tasks in a single default view with defined sorting
- **complete**: Mark tasks as done by ID
- **un-complete**: Revert completed tasks back to incomplete status
- **delete**: Remove tasks entirely by ID

### Task Properties
- Persistent unique ID (assigned at creation, never reused)
- Title (required, cannot be empty/whitespace-only)
- Priority: High, Medium, or Low (defaults to Medium if not specified)
- Due date: optional, in ISO format (YYYY-MM-DD)
- Status: complete or incomplete

### Display and Sorting Behavior
- Single default list view (no user-controllable filtering/sorting in v1)
- Sort order within each priority tier (High → Medium → Low):
  1. Overdue tasks (most overdue first - oldest due date first)
  2. Tasks with future due dates (soonest due date first)
  3. Tasks with no due date (by creation order)
- Completed tasks follow the same sort rules, remain visible, and are visually marked as done
- Overdue tasks receive visual warning indicators (e.g., ⚠ OVERDUE)

### Persistence
- Tasks must survive application restarts
- Data persisted to disk (exact file location is implementation detail)
- User should not need to manually manage the data file

### First-Run Experience
- Empty list on first run with helpful message (e.g., "No tasks yet. Use 'add' to create your first task")
- Not an error or crash

### Data Validation
- Invalid dates (e.g., 2024-02-31) must be rejected immediately with clear error message
- Task titles cannot be empty or whitespace-only
- Operations on non-existent task IDs should show clear error messages

### Quality Expectations
- Clear, user-friendly error messages for invalid input
- Graceful handling of edge cases (non-existent IDs, corrupted data files, etc.)
- No crashes or data corruption

## Open Questions
None remaining - all critical questions were resolved during the grooming session.

## Assumptions

### User Mental Model
- Users understand persistent IDs (task [1], [3], [7] after deletions create gaps)
- Due dates represent time-based commitments that should surface when overdue, even if priority is lower
- Completed tasks provide value as accomplishment history and reference
- Delete + re-add is an acceptable workaround for editing in v1

### Technical Assumptions
- Command-line interface is the target platform
- Users can specify dates in ISO format (YYYY-MM-DD)
- Two tasks can have identical titles (IDs distinguish them)
- No enforced maximum task title length (may wrap in display)

### Scope Philosophy
- v1 should be minimal but useful
- Tight scope that allows learning from actual usage before adding complexity
- Features can be added in v2 based on user feedback

## Out of Scope

### Explicitly Deferred to Post-v1
- **Edit command**: Modifying task priority, due date, or title after creation
- **Clear completed**: Bulk operation to remove all completed tasks
- **Filtering/sorting options**: User-controllable views (e.g., `--sort-by`, `--filter`)
- **Description field**: Tasks are title-only in v1
- **Natural language date parsing**: Only ISO format (YYYY-MM-DD) supported in v1
- **Task relationships**: No blocking/dependency tracking between tasks
- **History/audit log**: No tracking of task changes over time
- **External integrations**: No API or third-party service connections

### Edge Case Behaviors (Implementation Details)
- Specific error message text
- Behavior when completing an already-completed task (likely no-op with message)
- Behavior when un-completing an incomplete task (likely no-op with message)
- Handling of corrupted or missing data file (likely start fresh with warning)
- Exact file path for persistence
- Maximum title length handling
- Visual formatting details (strikethrough, colors, indicators)
