# Token Efficiency Analysis

Based on test19 (`~/eng/gotg-tests/test19`, iter-1): "Create a CLI calculator" through all 5 phases, 3 layers.

## Baseline Numbers (test19)

| Phase | API Calls | Est. Input Tokens | Est. Cost |
|---|---|---|---|
| refinement | 15 | ~48K | $0.16 |
| planning (2 runs) | 40 | ~278K | $0.87 |
| pre-code-review | 18 | ~149K | $0.45 |
| implementation (L0-L2) | 3 | ~1.8K | $0.00 |
| code-review (L0-L2) | 21 | ~326K | $0.99 |
| **Total** | **97** | **~802K** | **~$2.48** |

172:1 input/output ratio. 97% of cost is re-reading context.

## Problem 1: Prior-Phase Transcripts (42% of prompt, ~$0.66 wasted)

**Reference:** test19 code-review L1, agent-1 prompt: 80,345 chars.
- 15% essential (system prompt, tasks, instructions)
- 42% raw transcripts from refinement + planning + pre-code-review
- 42% implementation diffs

The raw transcripts are carried forward verbatim even though structured artifacts already exist:
- refinement → `refinement_summary.md` captures all agreed requirements
- planning → `tasks.json` captures all tasks, dependencies, approach, done criteria
- pre-code-review → task `notes` field captures interface agreements

**Fix:** Stop injecting prior-phase transcripts into later phases. The artifacts are the source of truth. Agents in code-review don't need to re-read the raw refinement debate — they need the summary + tasks + diffs.

**Where:** `agent.py:build_prompt()` assembles the system prompt. The `groomed_summary` and `tasks_summary` parameters are already the artifact content. The transcript injection comes from `history` which includes all prior-phase messages (phase-scoped history only helps with turn counting, the full history is still in the system prompt via `build_prompt`). Need to verify: is the transcript injection happening through history or through explicit parameters?

**Impact:** ~27% total cost reduction. Code-review prompts drop from ~80K to ~46K chars.

## Problem 2: Pass-Turn Death Spiral (33% of input tokens, ~$0.23 wasted)

**Reference:** test19 planning run 1 — 6 productive turns, then 12 wasted pass turns where both agents passed and coach kept issuing guide_discussion. Each wasted round re-reads ~30K chars of prompt.

Across all phases: 25 pass_turns consuming ~266K tokens.

**Root cause:** No circuit breaker. When all agents pass consecutively, the coach should recognize convergence and either signal completion or ask_pm. Instead it keeps trying guide_discussion ("Let me verify the task breakdown..." repeated 4+ times).

**Fix options (not mutually exclusive):**
1. **Engine-level circuit breaker:** If all agents in a full rotation pass, inject a system message telling the coach "All agents passed. Either signal_phase_complete or ask_pm." This is mechanical and doesn't require prompt changes.
2. **Coach prompt guidance:** Add to TOOLS block: "If all agents passed in the previous rotation, the discussion has converged. Either signal completion or use ask_pm to confirm with the PM."
3. **Hard limit:** After 2 consecutive all-pass rotations, auto-yield a `SessionComplete` or `PauseForApprovals` event. Nuclear option — prevents runaway costs.

**Where:** Engine circuit breaker would go in `engine.py:run_session()` after the coach turn. Track consecutive all-pass rotations. Coach prompt change goes in `default_prompts.toml` TOOLS blocks.

**Impact:** ~9% total cost reduction, eliminates death spirals.

## Problem 3: Current-Layer Diffs Only (minor savings)

**Reference:** test19 code-review L1 prompt had diffs from both L0 and L1. Only L1 is being reviewed.

**Fix:** `policy.py:iteration_policy()` builds `diffs_summary` — scope it to current layer only.

**Where:** `session.py:load_diffs_for_review()` or `policy.py` where diffs are assembled.

**Impact:** Small per-turn savings, but cleaner context. L0 diffs were ~15K chars in the L1 review prompt.

## Problem 4: Cache Hit Rates Vary (optimization opportunity)

Cache hit rates by phase:
- refinement: 60%
- planning: 64-76%
- pre-code-review: 77%
- code-review: 33-55% (worst)

Code-review has poor cache rates because of 3-participant rotation (agent-1, agent-2, coach) with different system prompts. Each prompt variation invalidates the cache.

**Fix:** Align system prompt structure so the shared prefix (task description, diffs) is identical across agents and coach, with agent-specific content at the end. This maximizes the cacheable prefix.

**Where:** `agent.py:build_prompt()` and `agent.py:build_coach_prompt()` — restructure message ordering.

**Impact:** Could improve code-review cache rate from ~40% to ~70%, saving ~$0.15-0.20 per iteration.

## Implementation Executor: Already Efficient

The implementation executor (`implementation.py`) is the gold standard:
- 1 API call per agent per layer
- Compact system prompt (~2K chars): just task spec + tool schemas
- Multi-round tool loop within a single API call
- No transcript bloat, no prior-phase history

test19 implementation: 3 API calls total across 3 layers, ~1.8K tokens. Negligible cost.

## Priority Order

1. **Drop prior-phase transcripts** — biggest savings, cleanest fix
2. **Pass-turn circuit breaker** — prevents death spirals, improves UX
3. **Coach prompt convergence guidance** — cheap to add, complements #2
4. **Current-layer diffs only** — small savings, quick fix
5. **Cache alignment** — moderate savings, more complex refactor
