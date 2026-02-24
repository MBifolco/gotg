# CI Lane Checklist And Triage

Use this during PR review and when CI fails.

## Merge Checklist

1. `core-non-tui` is green.
2. `tui-pty` is green for UI/streaming/autoscroll changes.
3. `nightly-replay` is green (or no new failures introduced by the PR).
4. `mutation-pilot` is green (kill-rate floor met).
5. `behavior-map-guard` is green.
6. `docs/testing-behavior-map.md` is updated for any critical-flow change.
7. New escaped bug has a deterministic replay/contract test within 24h.

Branch protection setup reference:
- `docs/branch-protection-setup.md`

## Lanes

### `core-non-tui`
- Workflow: `.github/workflows/core-non-tui.yml`
- Script: `scripts/ci/run_core_non_tui.sh`
- Purpose: fast deterministic baseline for non-TUI logic.
- Local repro:
  - `bash scripts/ci/run_core_non_tui.sh`

### `tui-pty`
- Workflow: `.github/workflows/tui-pty.yml`
- Script: `scripts/ci/run_tui_pty.sh`
- Purpose: Textual/PTY behavior (streaming widget lifecycle, autoscroll, UI wiring).
- Local repro (PTY-capable shell):
  - `bash scripts/ci/run_tui_pty.sh`

### `nightly-replay`
- Workflow: `.github/workflows/nightly-replay.yml`
- Script: `scripts/ci/run_nightly_replay.sh`
- Purpose: escaped-incident regression contracts and quality-gate replay coverage.
- Local repro:
  - `bash scripts/ci/run_nightly_replay.sh`

### `mutation-pilot`
- Workflow: `.github/workflows/mutation-pilot.yml`
- Script: `scripts/ci/run_mutation_pilot.sh`
- Purpose: assertion-strength check for critical execution modules.
- Local repro:
  - `bash scripts/ci/run_mutation_pilot.sh`
- Floor override:
  - `GOTG_MUTATION_FLOOR=0.85 bash scripts/ci/run_mutation_pilot.sh`

### `behavior-map-guard`
- Workflow: `.github/workflows/behavior-map-guard.yml`
- Script: `scripts/ci/run_behavior_map_guard.sh`
- Purpose: enforce behavior-map + tests updates for critical execution changes.
- Local repro:
  - `BASE_REF=main bash scripts/ci/run_behavior_map_guard.sh`

## Failure Triage

### 1) `core-non-tui` failed

1. Run `bash scripts/ci/run_core_non_tui.sh`.
2. Isolate first failing test (`pytest path::test_name -q --tb=short`).
3. Classify:
   - contract mismatch (expected behavior changed): update tests + behavior map.
   - regression: fix code or revert.
   - flaky assumption: remove nondeterminism from test.
4. Re-run targeted test, then full `core-non-tui`.

### 2) `nightly-replay` failed

1. Run `bash scripts/ci/run_nightly_replay.sh`.
2. Map failing test to source incident in `tests/test_e2e_quality_gate.py`.
3. Decide:
   - intended product behavior changed -> update replay test and behavior map.
   - unintended drift -> treat as blocker, fix code path.
4. Add new replay test if this is a new escape pattern.

### 3) `mutation-pilot` failed

1. Run `bash scripts/ci/run_mutation_pilot.sh`.
2. For each survivor, read printed mutant name and target file.
3. Add/strengthen tests that should kill that mutation (behavior-level first).
4. Re-run mutation pilot and verify kill-rate floor.

### 4) `behavior-map-guard` failed

1. Run `BASE_REF=main bash scripts/ci/run_behavior_map_guard.sh`.
2. If critical files changed, add:
   - an update to `docs/testing-behavior-map.md`
   - at least one relevant test update under `tests/`
3. Re-run guard; then run `core-non-tui`.

### 5) `tui-pty` failed

1. Check if failure is PTY/env-specific vs app logic.
2. Re-run `bash scripts/ci/run_tui_pty.sh` in a PTY-capable local shell.
3. For streaming/autoscroll issues:
   - verify message finalization transitions
   - verify suppression logic does not hide next message
   - verify scroll anchor updates after widget swap
4. Add/adjust TUI regression test tied to the incident.

## Escalation Rules

1. Two consecutive failures on same lane with no clear root cause: open an investigation issue.
2. Replay or mutation failures on main: prioritize before feature work.
3. Do not waive `nightly-replay` or `mutation-pilot` without documented risk and owner.

## Artifacts To Check

1. `.team/iterations/<id>/conversation.jsonl`
2. `.team/iterations/<id>/debug.jsonl`
3. `.team/iterations/<id>/tasks.json`
4. `.team/iteration.json`
5. `.team/iterations/<id>/implementation_state.json` (when pause/resume involved)
