# Grooming Improvements Roadmap

Deferred improvements for the grooming context injection feature, with rationale and trigger conditions for when to implement each.

## 1. Iteration-to-iteration context (NEXT)

**What**: Apply `load_iteration_context()` to iteration-2's refinement phase — inject iter-1 context into new iteration system prompts.

**Why wait**: Grooming context gap is the immediate pain. The function and `SessionPolicy.project_context` field are designed phase-agnostic to support this without redesign.

**Implement when**: Next iteration after this feature ships. Low effort — wire `load_iteration_context` into `iteration_policy()`.

## 2. Project narrative doc

**What**: `.team/project_narrative.md` — rolling document appended each iteration with "what changed and why."

**Why wait**: Only add this when you have 3+ iterations on the same project and the iteration summary alone isn't capturing cross-iteration decisions. Single-iteration projects don't need it.

**Implement when**: A grooming session makes a proposal contradicting a decision from 2+ iterations ago that isn't in the most recent refinement summary.

## 3. Iteration summary generation

**What**: Auto-generate `iteration_summary.md` at iteration completion from `tasks.json` outcomes + `refinement_summary.md` + changed files. Pure function, no LLM call.

**Why wait**: `refinement_summary.md` + `tasks.json` are sufficient for context injection now. A dedicated summary becomes valuable when task completion outcomes (what was built, what was deferred) need to carry forward.

**Implement when**: The `tasks.json` format gains completion status fields, or users report that refinement summary + tasks aren't enough context for grooming.

## 4. Context budgeting

**What**: Inject only compact summaries into system prompt; use file tools for deep dives to avoid prompt bloat.

**Why wait**: Not hitting context limits yet. The iteration summary for a small project is ~80 lines.

**Implement when**: A project reaches the point where iteration context + file tool results regularly exceed 50% of the model's context window. Likely requires 5+ iterations worth of artifacts.

## 5. Unresolved decisions / backlog artifact

**What**: Track open questions and deferred decisions across iterations so they don't get lost.

**Why wait**: Single-iteration projects don't accumulate enough decisions to warrant a dedicated artifact.

**Implement when**: Multi-iteration projects consistently lose track of open questions between iterations.

## 6. Code map artifact

**What**: `module_map.md` listing key files, responsibilities, and integration points.

**Why wait**: Read-only file tools (`file_list` + `file_read`) let agents discover this themselves. A static map risks staleness.

**Implement when**: Projects grow large enough that file tool exploration becomes inefficient (50+ files), or agents consistently miss important modules.

## 7. Grooming bootstrap step improvements

**What**: Make the bootstrap step adaptive — coach adjusts orientation depth based on project size and available context.

**Why wait**: The fixed 3-variant kickoff template works for current project sizes.

**Implement when**: User feedback indicates the bootstrap step is too heavy for small projects or too light for large ones.
