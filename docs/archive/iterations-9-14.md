# Iterations 9–14: File Access, Worktrees, and Code Review

**Context:** Iterations 1–8 established conversation protocol, grooming, planning, coach facilitation, tool infrastructure, and task generation. Agents can converse and produce artifacts. Now they need hands.

---

## Iteration 9: File Tools + FileGuard

**Goal:** Engineering agents can read and write files within the project, constrained by safety boundaries.

**What to build:**
- Three new tools in the agent tool schema: `file_read`, `file_write`, `file_list`
- `FileGuard` class that validates all paths before execution
  - Relative paths only (reject absolute, reject `..`)
  - Resolve and verify containment within project root
  - `.team/**` and `.git/**` hard-denied for writes (non-configurable)
  - `.env` / `.env.*` hard-denied for writes
  - Configurable `writable_paths` and `protected_paths` in `team.json`
- `file_access` section added to `team.json` schema
- Tool calls flow through `chat_completion()` — same pattern as coach tool, but now engineering agents get tools too
- All file operations logged as messages in conversation

**What NOT to build:**
- No bash tool
- No delete tool
- No approval gate (everything within writable paths auto-allows)
- No worktrees (agents write directly to the project for now)
- No git integration

**Test:** Run a task where agents implement a small feature using file tools. Verify: files land in the right place, `.team/` writes are blocked, path traversal attempts fail, conversation log captures all file operations.

**Hypothesis:** Agents with file tools and clear path constraints can produce working code files without escaping project boundaries.

**Success criteria:**
- FileGuard blocks all out-of-scope writes
- Agents successfully create/modify files within writable paths
- Conversation log shows complete audit trail of file operations
- No manual intervention needed for normal file operations

---

## Iteration 10: Structured Approval System

**Goal:** PM can approve or deny file operations that fall outside auto-allow boundaries.

**What to build:**
- `.team/iterations/<id>/approvals.json` file for pending requests
- When FileGuard encounters a write that requires approval (outside `writable_paths` but inside project), system writes a pending request and pauses the run
- Three new CLI commands:
  - `gotg approvals` — show pending requests with content preview
  - `gotg approve <id>` — approve a pending request
  - `gotg deny <id> -m "reason"` — deny with reason
- On `gotg continue` after approval: write executes, agent sees confirmation
- On `gotg continue` after denial: agent sees denial reason as system message and adapts
- Batch support: `gotg approve all`

**What NOT to build:**
- No per-agent scoping (global writable paths still)
- No worktrees yet

**Test:** Configure `writable_paths` to exclude root-level files. Have an agent try to create `Dockerfile` or `package.json` at project root. Verify: run pauses, `gotg approvals` shows the request, approve/deny works, agent resumes correctly.

**Hypothesis:** Structured approvals using the `gotg advance` pattern provide clean PM control without message parsing.

**Success criteria:**
- Run pauses cleanly when approval required
- `gotg approvals` shows useful preview of what the agent wants to write
- Approve resumes execution with the write applied
- Deny injects reason into conversation, agent course-corrects
- Approvals file is a clean audit artifact

---

## Iteration 11: Git Worktree Infrastructure

**Goal:** System manages git branches and worktrees transparently. Agents don't know they exist.

**What to build:**
- Worktree lifecycle manager (create, commit, remove)
- On task assignment: system creates branch `agent-<n>/<task-id>` and worktree at `.worktrees/agent-<n>-<task-id>/`
- `FileGuard` updated: resolves agent file operations relative to agent's worktree root, not project root
- Agent's `file_read` sees files from their branch's perspective
- Agent's `file_write` writes to their worktree directory
- On task completion: system auto-commits all changes in worktree
- `.worktrees/` added to `.gitignore`
- `.team/` excluded from worktrees (sparse checkout or FileGuard deny — whichever is simpler)
- Worktree cleanup on layer completion

**What NOT to build:**
- No merge workflow yet (PM merges manually or we build that next)
- No cross-agent visibility during implementation
- No diff generation

**Test:** Assign two agents parallel tasks in the same layer. Both write files. Verify: each agent's work lands on its own branch, no interference, commits are clean, worktrees are created and cleaned up correctly.

**Hypothesis:** Git worktrees provide transparent filesystem isolation for parallel agent execution without constraining task decomposition.

**Success criteria:**
- Two agents work in parallel without file conflicts
- Each agent's changes are on a separate branch
- `git log` shows clean per-agent commits
- Worktree creation/teardown is automatic and reliable
- Agents are completely unaware of the branching — their tool calls look identical to Iteration 9

---

## Iteration 12: Merge Workflow + PM Review

**Goal:** PM can review agent work as git diffs and merge into main.

**What to build:**
- `gotg review` command — shows diffs for all branches in the current layer
  - Output: per-agent diff against main, summary stats (files changed, lines added/removed)
- `gotg merge <branch>` — merges an agent's branch into main
- `gotg merge all` — merges all branches from current layer (stops on conflict)
- Conflict handling: if merge conflicts, system reports which files conflict and between which agents
- After merge, next layer's worktrees branch from updated main
- Layer progression: all branches merged → `gotg advance` to next layer or phase

**What NOT to build:**
- No AI-assisted review yet (that's next iteration)
- No automated conflict resolution
- PM does the review manually using diffs, same as reviewing a human engineer's PR

**Test:** Complete a full layer with two agents. Run `gotg review` to see diffs. Merge both. Verify: main has both agents' work integrated, next layer starts from correct state.

**Hypothesis:** Git diffs provide a natural, familiar review interface for the PM that requires no new tooling concepts.

**Success criteria:**
- `gotg review` output is readable and useful
- Clean merges work end-to-end
- Conflicting merges report clearly what conflicts and why
- Layer-to-layer progression maintains correct git state

---

## Iteration 13: Pre-Code Review Phase (Agent-to-Agent)

**Goal:** Agents review each other's implementation through conversation, with diffs as context.

**What to build:**
- New phase: `pre-code-review` (between implementation and merge)
- System generates diffs for all branches in the layer
- Diffs injected into review conversation as system context (same pattern as groomed scope → planning, planning artifacts → implementation)
- All implementation agents participate in review — reviewing each other's work
- Coach facilitates review convergence: are concerns addressed, is code ready?
- Coach signals review completion via tool call (existing pattern)
- Review outcome: `approved` or `changes-requested` with specific feedback
- If changes requested: agents return to their worktrees to make fixes, new commits, new diffs for re-review

**What NOT to build:**
- No automated merge after approval (PM still merges)
- No review-specific agent differentiation

**Prompt design:**
- Review system prompt: "You are reviewing your teammates' implementations. You can see all diffs from this layer. Focus on: correctness, consistency between components, adherence to groomed requirements, test coverage. Defend your own implementation when questioned. Suggest specific changes when you see issues."
- Coach review prompt: "Track open review concerns. A concern is resolved when the author acknowledges it and either agrees to change or explains why it should stay. Signal completion when all concerns are resolved."

**Test:** Run a full layer through implementation → review. Verify: agents find real issues in each other's code, agents defend their choices, coach tracks convergence, review produces actionable feedback.

**Hypothesis:** Agents reviewing each other's diffs through facilitated conversation produces integration-quality code review — catching interface mismatches and design inconsistencies, not just syntax.

**Success criteria:**
- Agents reference specific lines/sections from diffs in their review comments
- At least one substantive concern is raised and resolved per review
- Coach accurately tracks open vs. resolved concerns
- Review conversation stays focused on the changes (diffs constrain scope)
- Review completion signal fires at the right time

---

## Iteration 14: End-to-End Layer Execution

**Goal:** A full layer flows from task assignment through implementation, review, and merge without manual system orchestration.

**What to build:**
- Layer execution orchestrator: given a set of tasks and agent assignments, runs the full cycle:
  1. Create worktrees per agent
  2. Run implementation phase (agents write code using file tools)
  3. Coach signals implementation complete
  4. Generate diffs, transition to pre-code-review phase
  5. Run review phase (agents review each other's diffs)
  6. Coach signals review complete
  7. PM reviews diffs (`gotg review`), merges (`gotg merge`)
  8. Clean up worktrees, advance to next layer
- `gotg execute-layer` command (or integrate into existing `gotg advance` flow)
- Layer-to-layer chaining: after merge, next layer auto-sets up

**What NOT to build:**
- No multi-layer auto-execution (PM advances between layers)
- No automated conflict resolution
- No agent self-assignment

**Test:** Full end-to-end: groomed scope → planned tasks → layer 0 implementation → layer 0 review → merge → layer 1 implementation → layer 1 review → merge → done.

**Hypothesis:** The full pipeline from conversation to code to review to merge works as a coherent workflow, with the PM operating at the strategic level (scope, review, merge decisions) rather than the operational level (file management, branch management, phase transitions).

**Success criteria:**
- A multi-layer feature is implemented end-to-end
- PM interacts only at decision points (approvals, merge, advance)
- Conversation log + git history together tell the complete story
- The URL shortener (or equivalent test project) gains working functionality through this process

---

## Sequencing Rationale

Each iteration adds one capability and validates it before the next builds on top:

```
9:  file tools + safety       → can agents write code safely?
10: approval system           → can PM control edge cases?
11: worktrees                 → can agents work in parallel?
12: merge workflow            → can PM review and integrate?
13: agent review with diffs   → can agents review each other?
14: end-to-end orchestration  → does the full pipeline work?
```

Iterations 9–10 work without git at all — agents write directly to the project. This validates file tools and safety in isolation. Iteration 11 adds worktrees underneath without changing the agent experience. 12 adds the PM merge interface. 13 adds the review conversation. 14 connects everything.

If something fails at any step, you learn why without the complexity of everything above it. Consistent with "fail simple, learn why."
