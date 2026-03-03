# High-Confidence Testing Plan

## Target State

The project is considered "sufficient for high confidence" when all of the following are true:

1. `core-non-tui` is green with zero known red regressions.
2. Replay suite includes all recent escaped incidents and is green.
3. TUI suite runs in PTY-capable CI and catches streaming/autoscroll regressions.
4. Critical behavior map in `docs/testing-behavior-map.md` is fully covered.
5. Mutation score floor is enforced for:
   - `src/gotg/engine.py`
   - `src/gotg/implementation.py`
   - `src/gotg/cli.py`

## Execution Plan

### 1. Close Current Known Red First (1-2 days)

Fix and validate:

- `tests/test_e2e_quality_gate.py::test_replay_streamed_text_only_round_is_persisted_for_traceability`

Goal:

- No known red replay tests.
- Streaming UI/log parity restored for this incident class.

### 2. Expand Deterministic E2E Coverage (3-4 days)

Add next high-value tests:

1. Coach streaming (tool-only and mixed text+tool cases).
2. Implementation resume state contract.
3. Drift-check contract behavior.
4. Checkpoint/restore contract.
5. Worktree isolation contract.

Goal:

- Critical path behavior coverage is mostly e2e and deterministic.

### 3. Build Escape Replay Lane (2-3 days)

Encode escaped incidents as deterministic tests:

- `gotg-tests/test8`
- `gotg-tests/test9`
- `gotg-tests/test10`
- `gotg-tests/test11`
- `gotg-tests/test14`
- `gotg-tests/test16`

Policy:

- Every future escape gets a replay regression test within 24 hours.

Implementation status:

- Replay contracts currently encoded in `tests/test_e2e_quality_gate.py`:
  - `test_replay_test8_implementation_tool_activity_persisted_to_conversation_and_debug`
  - `test_replay_test9_attestation_payload_mismatch_does_not_block_completion`
  - `test_replay_test10_file_writes_do_not_complete_task_until_complete_tasks`
  - `test_replay_test11_must_not_reverts_but_warning_only_allows_completion`
  - `test_replay_test14_invalid_report_blocked_payload_does_not_deadlock_completion`
  - `test_replay_test16_next_layer_boundary_uses_implementation_phase`

### 4. Add CI Lane Split (1-2 days)

Create CI lanes:

1. `core-non-tui`
2. `tui-pty`
3. `nightly-replay`

Merge gating:

- Block merges on `core-non-tui` and `tui-pty`.
- Run replay lane nightly.

Implementation status:

- `core-non-tui`: `.github/workflows/core-non-tui.yml`
- `tui-pty`: `.github/workflows/tui-pty.yml`
- `nightly-replay`: `.github/workflows/nightly-replay.yml`
- CI ops checklist and triage: `docs/ci-lane-checklist-and-triage.md`
- Branch protection setup script: `scripts/ops/configure_branch_protection.sh`

### 5. Add Mutation Testing Pilot (2 days)

Run mutation testing on critical modules and enforce an initial floor (for example 45%), then ratchet upward over time.

Implementation status:

- Mutation pilot runner: `scripts/testing/mutation_pilot.py`
- CI lane: `.github/workflows/mutation-pilot.yml`
- Current floor (env-configurable): `GOTG_MUTATION_FLOOR=0.80`

### 6. Enforce Behavior-Map Governance (1 day)

Require each PR touching critical flows to:

1. Update `docs/testing-behavior-map.md`.
2. Add at least one behavior-level test.

Implementation status:

- Governance guard runner: `scripts/testing/behavior_map_guard.py`
- CI lane: `.github/workflows/behavior-map-guard.yml`

## Definition of Done (High Confidence)

1. No known red replay tests.
2. At least 10 deterministic critical-path e2e tests passing.
3. Replay lane includes all historical escapes from current cycle.
4. PTY TUI lane is stable across repeated runs.
5. Mutation floor is met on critical modules.
