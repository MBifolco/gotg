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
- `tests/test_e2e_quality_gate.py::test_replay_test16_next_layer_boundary_uses_code_review_phase`

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

Behavior: Implementation artifacts stay consistent across debug tool ops, conversation tool messages, and task state.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_artifact_consistency_tool_ops_and_task_state`
- `tests/test_e2e_quality_gate.py::test_replay_test8_implementation_tool_activity_persisted_to_conversation_and_debug`

Behavior: Non-streaming implementation persists both assistant text and tool operation messages.
Tests:
- `tests/test_behavior_contracts.py::test_contract_implementation_non_streaming_logs_text_and_tool_ops`

Behavior: Streaming pass-turn does not suppress the next agent’s substantive message.
Tests:
- `tests/test_behavior_contracts.py::test_contract_pass_turn_does_not_suppress_next_agent_message`
- `tests/test_engine.py::test_streaming_agent_turn_with_tools`

Behavior: Streaming coach turns persist correctly for tool-only and mixed text+tool responses.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_coach_streaming_tool_only_phase_complete`
- `tests/test_e2e_quality_gate.py::test_e2e_coach_streaming_mixed_text_and_tool_single_persisted_message`

## TUI Settings Contracts

Behavior: Model select supports explicit blank selection for validation paths.
Tests:
- `tests/test_tui_settings.py::test_settings_validation_empty_model`

Behavior: Blank model selection remains legal after provider-triggered option refresh.
Tests:
- `tests/test_tui_settings.py::test_settings_blank_model_remains_valid_after_provider_change`

## Task State and Constraints

Behavior: `complete_tasks` can only close tasks assigned to the acting agent in the current layer.
Tests:
- `tests/test_implementation.py::test_handle_complete_tasks_wrong_agent`
- `tests/test_implementation.py::test_handle_complete_tasks_wrong_layer`
- `tests/test_implementation.py::test_complete_tasks_validation_rejects_wrong_agent`
- `tests/test_e2e_quality_gate.py::test_e2e_drift_check_reverts_completion_on_must_not_violation`
- `tests/test_e2e_quality_gate.py::test_e2e_complete_tasks_atomic_rejection_on_invalid_id`

Behavior: `report_blocked` validates ownership and persists blocked state.
Tests:
- `tests/test_implementation.py::test_handle_report_blocked_success`
- `tests/test_implementation.py::test_handle_report_blocked_wrong_agent`
- `tests/test_implementation.py::test_handle_report_blocked_empty_ids`
- `tests/test_implementation.py::test_handle_report_blocked_reason_required`
- `tests/test_implementation.py::test_handle_report_blocked_wrong_layer`
- `tests/test_implementation.py::test_handle_report_blocked_rejects_done_task`
- `tests/test_implementation.py::test_handle_report_blocked_atomic_on_mixed_valid_and_invalid_ids`
- `tests/test_implementation.py::test_handle_report_blocked_atomic_on_mixed_own_and_foreign_ids`
- `tests/test_implementation.py::test_handle_report_blocked_atomic_on_mixed_done_and_pending_ids`

Behavior: Invalid `report_blocked` payload does not deadlock implementation progress.
Tests:
- `tests/test_e2e_quality_gate.py::test_replay_test14_invalid_report_blocked_payload_does_not_deadlock_completion`

Behavior: Attestation payload mismatch does not deadlock implementation completion.
Tests:
- `tests/test_e2e_quality_gate.py::test_replay_test9_attestation_payload_mismatch_does_not_block_completion`

Behavior: File writes do not complete a task unless `complete_tasks` is explicitly called.
Tests:
- `tests/test_e2e_quality_gate.py::test_replay_test10_file_writes_do_not_complete_task_until_complete_tasks`

Behavior: Drift-check reverts MUST NOT violations but still allows later successful completion.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_drift_check_recovery_allows_subsequent_completion`
- `tests/test_e2e_quality_gate.py::test_replay_test11_must_not_reverts_but_warning_only_allows_completion`

## Approval and Resume

Behavior: Pending approvals pause execution and resume after apply/inject.
Tests:
- `tests/test_session.py::test_apply_and_inject_applies_approved`
- `tests/test_session.py::test_apply_and_inject_injects_denials`
- `tests/test_implementation.py::test_pause_for_approvals`
- `tests/test_e2e_quality_gate.py::test_e2e_approval_pause_resume_implementation`
- `tests/test_e2e_quality_gate.py::test_e2e_implementation_state_resume_contract`
- `tests/test_e2e_quality_gate.py::test_e2e_mixed_approval_resume_contract`

Behavior: Restore checkpoint rewinds iteration phase and iteration artifacts to snapshot.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_checkpoint_restore_contract`

## Review and Merge Safety

Behavior: Merge and next-layer safety checks prevent unsafe transitions.
Tests:
- `tests/test_session_review.py::test_validate_next_layer_wrong_phase`
- `tests/test_session_review.py::test_validate_next_layer_unmerged_branches`
- `tests/test_session_review.py::test_validate_next_layer_dirty_worktree`

Behavior: Merge requires approved code review (phase gate).
Tests:
- `tests/test_rework.py::test_merge_blocked_when_changes_requested`
- `tests/test_rework.py::test_merge_blocked_when_no_outcome`
- `tests/test_rework.py::test_merge_blocked_when_not_code_review`

Behavior: Next-layer requires approved code review outcome.
Tests:
- `tests/test_rework.py::test_next_layer_blocked_when_changes_requested`
- `tests/test_rework.py::test_next_layer_blocked_when_no_outcome`

Behavior: File writes during implementation are isolated per agent worktree root.
Tests:
- `tests/test_e2e_quality_gate.py::test_e2e_worktree_isolation_contract`

## Code-Review Outcome and Rework Loop

Behavior: Coach `signal_phase_complete` carries outcome (approved/changes_requested) and persists structured data on coach message.
Tests:
- `tests/test_rework.py::test_phase_complete_signaled_default_outcome`
- `tests/test_rework.py::test_phase_complete_signaled_changes_requested`
- `tests/test_engine.py::test_signal_phase_complete_extracts_outcome`
- `tests/test_engine.py::test_signal_phase_complete_default_outcome`
- `tests/test_engine.py::test_signal_phase_complete_persists_on_message`
- `tests/test_engine.py::test_signal_phase_complete_fallback_includes_summary`

Behavior: `reconstruct_resume_state` reads review outcome from structured data, legacy fallback, or new fallback text.
Tests:
- `tests/test_rework.py::test_reconstruct_resume_state_phase_complete_approved`
- `tests/test_rework.py::test_reconstruct_resume_state_phase_complete_changes_requested`
- `tests/test_rework.py::test_reconstruct_resume_state_legacy_fallback_text`
- `tests/test_rework.py::test_reconstruct_resume_state_new_fallback_text`

Behavior: Review feedback extraction via one-shot LLM call returns structured feedback map (includes coach messages, excludes system).
Tests:
- `tests/test_rework.py::test_extract_review_feedback_success`
- `tests/test_rework.py::test_extract_review_feedback_all_approved`
- `tests/test_rework.py::test_extract_review_feedback_bad_json`
- `tests/test_rework.py::test_extract_review_feedback_filters_unknown_ids`
- `tests/test_rework.py::test_extract_review_feedback_non_string_feedback`
- `tests/test_rework.py::test_extract_review_feedback_includes_coach_messages`

Behavior: `gotg rework` extracts feedback, applies to tasks, transitions code-review to implementation on same layer.
Tests:
- `tests/test_rework.py::test_advance_rework_applies_feedback`
- `tests/test_rework.py::test_advance_rework_preserves_done_tasks`
- `tests/test_rework.py::test_advance_rework_saves_phase`
- `tests/test_rework.py::test_advance_rework_keeps_layer`
- `tests/test_rework.py::test_advance_rework_empty_feedback_raises`
- `tests/test_rework.py::test_advance_rework_clears_completion_metadata`
- `tests/test_rework.py::test_advance_rework_clears_review_outcome`
- `tests/test_rework.py::test_advance_rework_scoped_to_layer`
- `tests/test_rework.py::test_cmd_rework_success`
- `tests/test_rework.py::test_cmd_rework_wrong_phase`

Behavior: Implementation prompts display review feedback and separate done from actionable tasks.
Tests:
- `tests/test_rework.py::test_format_agent_tasks_includes_review_feedback`
- `tests/test_rework.py::test_format_agent_tasks_no_feedback`
- `tests/test_rework.py::test_format_agent_tasks_separates_done_from_actionable`
- `tests/test_rework.py::test_format_agent_tasks_all_actionable_no_done_section`
- `tests/test_rework.py::test_handle_complete_tasks_clears_review_feedback`

## Implementation Phase Gate

Behavior: Implementation phase does not support merge/next-layer shortcuts (must advance through code-review first).
Tests:
- `tests/test_phases.py::test_implementation_caps`
- `tests/test_rework.py::test_merge_blocked_when_not_code_review`
- `tests/test_session_review.py::test_validate_next_layer_implementation_phase`

## Persistence Store Consolidation

Behavior: `persist_event` supports both legacy `(event, log_path, debug_path)` and store-based `(event, store=store)` signatures with strict mutual exclusion.
Tests:
- `tests/test_session.py::test_persist_event_append_message`
- `tests/test_session.py::test_persist_event_append_debug`
- `tests/test_session.py::test_persist_event_with_store`
- `tests/test_session.py::test_persist_event_store_debug`
- `tests/test_session.py::test_persist_event_store_debug_noop_when_no_debug_path`
- `tests/test_session.py::test_persist_event_rejects_mixed_args`
- `tests/test_session.py::test_persist_event_rejects_no_args`
- `tests/test_session.py::test_persist_event_rejects_partial_legacy`
- `tests/test_session.py::test_persist_event_store_noop_for_other_events`

Behavior: `run_and_persist` routes persistence through `SessionSetup.conv_store` when present.
Tests:
- `tests/test_session.py::test_run_and_persist_discussion`
- `tests/test_session.py::test_run_and_persist_implementation`
- `tests/test_session.py::test_run_and_persist_only_persists_append_events`
- `tests/test_session.py::test_run_and_persist_debug_events`

Behavior: TaskRepo wraps tasks.json persistence (load, save, exists) and delegates to free functions.
Tests:
- `tests/test_tasks.py::test_task_repo_save_and_load`
- `tests/test_tasks.py::test_task_repo_round_trip`
- `tests/test_tasks.py::test_task_repo_exists_false_initially`
- `tests/test_tasks.py::test_task_repo_overwrite`

Behavior: ConversationStore wraps conversation log I/O (read_full, read_phase_history, append, append_debug).
Tests:
- `tests/test_context.py::test_conversation_store_read_full`
- `tests/test_context.py::test_conversation_store_append`
- `tests/test_context.py::test_conversation_store_read_phase_history`
- `tests/test_context.py::test_conversation_store_append_debug`
- `tests/test_context.py::test_conversation_store_append_debug_noop_without_path`

Behavior: IterationStore wraps iteration config operations (get_current, save_fields, save_phase, create, set_current).
Tests:
- `tests/test_context.py::test_iteration_store_get_current`
- `tests/test_context.py::test_iteration_store_load`
- `tests/test_context.py::test_iteration_store_save_fields`
- `tests/test_context.py::test_iteration_store_save_phase`

## Session Module Structure

Behavior: Session preparation validates iteration state and builds file infrastructure before engine dispatch.
Tests:
- `tests/test_session.py::test_validate_iteration_for_run_requires_tasks`
- `tests/test_session.py::test_validate_advance_wrong_phase`
- `tests/test_session.py::test_validate_advance_no_tasks`
- `tests/test_session.py::test_run_and_persist_translates_validate_error`

Behavior: Phase advance extracts artifacts and writes boundary markers atomically.
Tests:
- `tests/test_session.py::test_advance_refinement_to_planning`
- `tests/test_session.py::test_advance_planning_bad_json`
- `tests/test_session.py::test_advance_planning_to_pre_code_review`
- `tests/test_session.py::test_advance_pre_code_review_to_implementation`

## Grooming Outcomes

Behavior: Coach `propose_iterations` tool yields `IterationsProposed` event, pauses session, and takes priority over `ask_pm`.
Tests:
- `tests/test_grooming_outcomes.py::test_coach_propose_iterations_yields_event`
- `tests/test_grooming_outcomes.py::test_coach_propose_iterations_stored_in_message`
- `tests/test_grooming_outcomes.py::test_coach_propose_iterations_fallback_text`
- `tests/test_grooming_outcomes.py::test_coach_propose_iterations_priority_over_ask_pm`
- `tests/test_grooming_outcomes.py::test_coach_propose_iterations_batch_id_increments`

Behavior: `apply_iteration_proposals` validates, creates/updates iterations with batch-safe IDs, and persists idempotent approval markers.
Tests:
- `tests/test_grooming_outcomes.py::test_apply_iteration_proposals_create`
- `tests/test_grooming_outcomes.py::test_apply_iteration_proposals_create_batch_ids`
- `tests/test_grooming_outcomes.py::test_apply_iteration_proposals_update`
- `tests/test_grooming_outcomes.py::test_apply_iteration_proposals_update_not_found`
- `tests/test_grooming_outcomes.py::test_apply_iteration_proposals_mixed`
- `tests/test_grooming_outcomes.py::test_apply_iteration_proposals_injects_messages`
- `tests/test_grooming_outcomes.py::test_apply_iteration_proposals_idempotent`
- `tests/test_grooming_outcomes.py::test_apply_iteration_proposals_validation_bad_action`
- `tests/test_grooming_outcomes.py::test_apply_iteration_proposals_validation_missing_fields`
- `tests/test_grooming_outcomes.py::test_apply_iteration_proposals_validation_update_no_id`

Behavior: Coach `end_grooming` tool yields `SessionComplete`, suppresses `ask_pm`, and is lower priority than `propose_iterations`.
Tests:
- `tests/test_grooming_outcomes.py::test_coach_end_grooming_yields_session_complete`
- `tests/test_grooming_outcomes.py::test_coach_end_grooming_fallback_text`
- `tests/test_grooming_outcomes.py::test_coach_end_grooming_priority_over_ask_pm`
- `tests/test_grooming_outcomes.py::test_propose_iterations_priority_over_end_grooming`
- `tests/test_grooming_outcomes.py::test_end_grooming_tool_in_grooming_coach_tools`
- `tests/test_grooming_outcomes.py::test_end_grooming_tool_not_in_iteration_coach_tools`

Behavior: Grooming session resume detects pending iteration proposals and distinguishes from already-approved batches.
Tests:
- `tests/test_grooming_outcomes.py::test_reconstruct_resume_state_iterations_proposed`
- `tests/test_grooming_outcomes.py::test_reconstruct_resume_state_proposals_already_approved`
- `tests/test_grooming_outcomes.py::test_pause_reason_iterations_proposed`

Behavior: `gotg groom summarize` extracts a summary document from the grooming conversation via one-shot LLM call.
Tests:
- `tests/test_grooming_outcomes.py::test_extract_grooming_summary_doc`
- `tests/test_grooming_outcomes.py::test_extract_grooming_summary_doc_strips_fences`
- `tests/test_grooming_outcomes.py::test_extract_grooming_summary_doc_includes_coach`
- `tests/test_grooming_outcomes.py::test_grooming_summary_extraction_prompt_loaded`
- `tests/test_grooming_outcomes.py::test_cmd_groom_summarize`
- `tests/test_grooming_outcomes.py::test_cmd_groom_summarize_empty`

## Grooming Context Injection

Behavior: Grooming sessions auto-detect or explicitly load iteration context (refinement_summary.md, tasks.json) into agent prompts.
Tests:
- `tests/test_grooming_context.py::test_load_iteration_context_explicit`
- `tests/test_grooming_context.py::test_load_iteration_context_auto_detect`
- `tests/test_grooming_context.py::test_load_iteration_context_skips_pending`
- `tests/test_grooming_context.py::test_load_iteration_context_no_iterations`
- `tests/test_grooming_context.py::test_load_iteration_context_no_artifacts`
- `tests/test_grooming_context.py::test_load_iteration_context_tasks_only`
- `tests/test_grooming_context.py::test_load_iteration_context_explicit_not_found`
- `tests/test_grooming_context.py::test_load_iteration_context_explicit_no_artifacts`
- `tests/test_grooming_context.py::test_no_context_flag_suppresses_injection`

Behavior: Project context flows through SessionPolicy into agent and coach prompts.
Tests:
- `tests/test_grooming_context.py::test_grooming_policy_with_project_context`
- `tests/test_grooming_context.py::test_grooming_policy_without_project_context`
- `tests/test_grooming_context.py::test_build_prompt_project_context`
- `tests/test_grooming_context.py::test_build_prompt_no_project_context`
- `tests/test_grooming_context.py::test_build_coach_prompt_project_context`

Behavior: Grooming sessions get read-only file tools (file_read + file_list, no file_write).
Tests:
- `tests/test_grooming_context.py::test_read_only_file_tools_excludes_write`

## CLI Iteration Switching

Behavior: `gotg run -i` and `gotg continue -i` switch current iteration before loading session state.
Tests:
- `tests/test_cli.py::test_cmd_run_basic`
- `tests/test_cli.py::test_cmd_continue_injects_message`

Behavior: Merge dirty-main check ignores untracked files (only tracked modifications block merge).
Tests:
- `tests/test_cli.py::test_cmd_merge_dirty_main_blocks`

## Known Gaps (Next Additions)

1. Replay tests from additional historical `gotg-tests/test*` incidents (escape-based regression lane).
2. Automated repeated-run flake detection for the PTY lane (stability burn-in in CI).
