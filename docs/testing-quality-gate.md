# Testing Quality Gate (v1)

Use this as release criteria, not just "pytest is green."

1. Behavior map exists and is current.
2. Golden-path lifecycle tests pass.
3. Invariant suite passes.
4. Escape-to-regression SLA is met.
5. Critical-path low-mock rule is enforced.
6. Replay coverage is in place.
7. TUI parity runs in CI.
8. Mutation score floor is enforced.
9. Artifact consistency checks pass.
10. Failure-quality checks pass.

## Gate Details

1. Behavior map exists and is current.
Behavior: Every critical behavior has at least one direct test in `docs/testing-behavior-map.md`.

2. Golden-path lifecycle tests pass.
Behavior: At least one deterministic full-iteration test (all phases) passes.

3. Invariant suite passes.
Behavior: Layer isolation, approval semantics, logging parity, and turn suppression invariants all pass.

4. Escape-to-regression SLA is met.
Behavior: Any prod/manual escape gets a regression test within one day.

5. Critical-path low-mock rule is enforced.
Behavior: Engine, implementation, and CLI integration tests for critical flows do not patch `run_session` or `run_implementation`.

6. Replay coverage is in place.
Behavior: At least five historical `gotg-tests/test*` failures are encoded as deterministic regression tests.

7. TUI parity runs in CI.
Behavior: TUI tests run in a PTY-capable CI job (separate lane if needed).

8. Mutation score floor is enforced.
Behavior: Start with a floor (for example 45%) on `engine.py`, `implementation.py`, and `cli.py`, then ratchet up.

9. Artifact consistency checks pass.
Behavior: Tests assert consistency across `conversation.jsonl`, `debug.jsonl`, `tasks.json`, and `iteration.json`.

10. Failure-quality checks pass.
Behavior: Negative tests assert clear failure modes, not just absence of crash.

Governance enforcement:
- `.github/workflows/behavior-map-guard.yml` ensures critical execution changes include behavior-map and test updates.

## Prioritized Next 10 High-Value Tests

1. Full deterministic end-to-end iteration lifecycle.
Target file: `tests/test_e2e_iteration_lifecycle.py`

2. Multi-layer implementation boundary with merge and next-layer sequencing.
Target file: `tests/test_e2e_layer_progression.py`

3. Streaming parity for display and persistence across discussion and implementation.
Target file: `tests/test_e2e_streaming_parity.py`

4. Approval pause and resume with approve and deny branches.
Target file: `tests/test_e2e_approval_resume.py`

5. Cross-turn suppression guard for pass-turn followed by substantive next-agent response.
Target file: `tests/test_e2e_turn_suppression.py`

6. Coach streaming behavior for tool-only and mixed text+tool turns.
Target file: `tests/test_e2e_coach_streaming.py`

7. Resume from `implementation_state.json` mid-layer after interruption.
Target file: `tests/test_e2e_impl_resume_state.py`

8. Drift-check contract behavior.
Target file: `tests/test_e2e_drift_contract.py`

9. Worktree isolation contract.
Target file: `tests/test_e2e_worktree_isolation.py`

10. Checkpoint and restore correctness for phase and artifacts.
Target file: `tests/test_e2e_checkpoint_restore_contract.py`

## Other Assessment Lenses (Beyond Coverage Percent)

1. Mutation testing.
Purpose: Detect weak assertions where tests pass even when logic is wrong.

2. Scenario replay harness.
Purpose: Run scripted replays from `gotg-tests/test*` as a nightly suite.

3. Property-based testing.
Purpose: Validate invariants under randomized event and tool sequences.

4. Observability QA.
Purpose: Assert runtime telemetry counters and events for streaming and tool loops match expectations.

## Suggested CI Split

1. `core-non-tui`
Purpose: Fast deterministic unit/integration checks.

2. `tui-pty`
Purpose: Textual tests in PTY-capable runtime.

3. `nightly-replay`
Purpose: Historical scenario replays and longer-running regression suites.

4. `mutation-pilot`
Purpose: Curated mutation checks over critical execution modules with a kill-rate floor.

5. `behavior-map-guard`
Purpose: Enforce behavior-map + test updates when critical execution files change.

Operational checklist and triage playbook:
- `docs/ci-lane-checklist-and-triage.md`

Branch-protection setup reference:
- `docs/branch-protection-setup.md`
