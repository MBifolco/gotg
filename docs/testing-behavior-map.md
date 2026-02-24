# Testing Behavior Map

This maps critical product behaviors to tests that verify them.
Use this as the primary signal for coverage quality, not raw test counts.

## Core Lifecycle

Behavior: Refinement -> planning -> pre-code-review -> implementation -> code-review progression works with persisted artifacts.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_iteration_lifecycle_refinement_to_code_review`
- `tests/test_session.py::test_advance_refinement_to_planning`
- `tests/test_session.py::test_advance_planning_bad_json`

Behavior: Phase boundaries are written to conversation history.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_iteration_lifecycle_refinement_to_code_review`
- `tests/test_session.py::test_advance_refinement_to_planning`

Behavior: Phase skeleton accumulation persists per phase.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_iteration_lifecycle_refinement_to_code_review`

## Implementation Layering

Behavior: Implementation dispatch is constrained to the current layer.
Tests:
- `tests/test_behavior_contracts.py::test_contract_layer_dispatch_only_affects_current_layer`
- `tests/test_implementation.py::test_dispatch_only_current_layer_agents`

Behavior: Layer completion then next-layer transition updates state and logs.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_layer_progression_next_layer_contract`
- `tests/test_session_review.py::test_advance_next_layer_success`
- `tests/test_e2e_quality_gate.py::test_replay_test16_next_layer_boundary_uses_implementation_phase`

Behavior: Final next-layer call returns all-done when no more layers exist.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_layer_progression_next_layer_contract`
- `tests/test_session_review.py::test_advance_next_layer_all_done`

## Streaming and Logging Parity

Behavior: Streaming discussion output persists final assistant content in conversation log.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_streaming_parity_discussion_and_implementation`
- `tests/test_behavior_contracts.py::test_contract_discussion_streaming_logs_text_and_tool_ops`

Behavior: Streaming implementation output persists both assistant text and tool operation messages.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_streaming_parity_discussion_and_implementation`
- `tests/test_behavior_contracts.py::test_contract_implementation_streaming_logs_text_and_tool_ops`
- `tests/test_e2e_quality_gate.py::test_replay_streamed_text_only_round_is_persisted_for_traceability`

Behavior: Non-streaming implementation persists both assistant text and tool operation messages.
Tests:
- `tests/test_behavior_contracts.py::test_contract_implementation_non_streaming_logs_text_and_tool_ops`

Behavior: Streaming pass-turn does not suppress the next agent’s substantive message.
Tests:
- `tests/test_behavior_contracts.py::test_contract_pass_turn_does_not_suppress_next_agent_message`
- `tests/test_engine.py::test_streaming_agent_turn_with_tools`

## Task State and Constraints

Behavior: `complete_tasks` can only close tasks assigned to the acting agent in the current layer.
Tests:
- `tests/test_implementation.py::test_handle_complete_tasks_wrong_agent`
- `tests/test_implementation.py::test_handle_complete_tasks_wrong_layer`
- `tests/test_implementation.py::test_complete_tasks_validation_rejects_wrong_agent`
- `tests/test_e2e_quality_gate.py::test_e2e_drift_check_reverts_completion_on_must_not_violation`

Behavior: `report_blocked` validates ownership and persists blocked state.
Tests:
- `tests/test_implementation.py::test_handle_report_blocked_success`
- `tests/test_implementation.py::test_handle_report_blocked_wrong_agent`

Behavior: Attestation payload mismatch does not deadlock implementation completion.
Tests:
- `tests/test_e2e_quality_gate.py::test_replay_test9_attestation_payload_mismatch_does_not_block_completion`

Behavior: File writes do not complete a task unless `complete_tasks` is explicitly called.
Tests:
- `tests/test_e2e_quality_gate.py::test_replay_test10_file_writes_do_not_complete_task_until_complete_tasks`

## Approval and Resume

Behavior: Pending approvals pause execution and resume after apply/inject.
Tests:
- `tests/test_session.py::test_apply_and_inject_applies_approved`
- `tests/test_session.py::test_apply_and_inject_injects_denials`
- `tests/test_implementation.py::test_pause_for_approvals`
- `tests/test_e2e_quality_gate.py::test_e2e_approval_pause_resume_implementation`
- `tests/test_e2e_quality_gate.py::test_e2e_implementation_state_resume_contract`

## Review and Merge Safety

Behavior: Merge and next-layer safety checks prevent unsafe transitions.
Tests:
- `tests/test_session_review.py::test_validate_next_layer_wrong_phase`
- `tests/test_session_review.py::test_validate_next_layer_unmerged_branches`
- `tests/test_session_review.py::test_validate_next_layer_dirty_worktree`

## Known Gaps (Next Additions)

1. Replay tests from additional historical `gotg-tests/test*` incidents (escape-based regression lane).
2. PTY-enabled TUI parity tests in CI (autoscroll and streaming widget lifecycle).
