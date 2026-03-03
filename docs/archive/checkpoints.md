Plan: Iteration 8 — Checkpoint/Restore

     Summary

     Add checkpoint and restore commands so iteration state can be saved and rolled back. Checkpoints are created
      automatically after every run, continue, and advance, and manually via gotg checkpoint. Restore prompts
     user to snapshot current state first. Per-iteration scoping for future multi-iteration support.

     Design Decisions

     - Storage: .team/iterations/<iter-id>/checkpoints/<number>/ — each checkpoint is a directory containing
     copied files + state.json metadata
     - Numbering: Shared auto-incrementing sequence (auto and manual checkpoints use same counter)
     - Files captured: Discovery-based — backs up all files in the iteration directory, excluding debug.jsonl and
      the checkpoints/ subdirectory. This means new artifacts are automatically included without updating a list.
      The exclude list (CHECKPOINT_EXCLUDE) is small, stable, and contains only things intentionally excluded.
     - state.json: Records number, phase, status, max_turns, turn_count, timestamp, description (user-provided or
      auto-generated), trigger ("auto"/"manual")
     - Restore: Copies checkpoint files back into iteration dir, updates iteration.json fields (phase,
     max_turns), prompts user to create safety checkpoint first
     - No debug.jsonl restore: debug logs are append-only diagnostics, not conversation state

     New File: src/gotg/checkpoint.py

     Constants

     CHECKPOINT_EXCLUDE = {"debug.jsonl", "checkpoints"}

     _iter_files(iter_dir) -> list[str]

     - Lists all files in iter_dir (non-recursive, files only)
     - Excludes anything in CHECKPOINT_EXCLUDE
     - Returns sorted list of filenames

     create_checkpoint(iter_dir, iteration, description=None, trigger="auto") -> int

     - Calls _next_checkpoint_number(iter_dir) to get next number
     - Creates iter_dir/checkpoints/<number>/
     - Discovers files via _iter_files(iter_dir) and copies each one
     - Writes state.json with: number, phase (from iteration), status, max_turns, turn_count (from
     _count_agent_turns()), timestamp (ISO), description, trigger
     - Returns the checkpoint number
     - Description defaults to auto-generated: "Auto after {trigger}" or user-provided string

     _next_checkpoint_number(iter_dir) -> int

     - Reads iter_dir/checkpoints/ subdirectories
     - Returns max(existing numbers) + 1, or 1 if none exist

     _count_agent_turns(iter_dir) -> int

     - Reads conversation.jsonl, counts messages where from not in ("human", "coach", "system")
     - Uses read_log() from gotg.conversation

     list_checkpoints(iter_dir) -> list[dict]

     - Reads all state.json files from iter_dir/checkpoints/*/
     - Returns list sorted by number ascending
     - Each dict has all state.json fields

     restore_checkpoint(iter_dir, number) -> dict

     - Validates checkpoint number exists
     - Removes all current non-excluded files from iter_dir via _iter_files() (clean slate)
     - Copies checkpoint files back into iter_dir
     - Returns the state.json dict (caller uses it to update iteration.json)
     - Raises ValueError if checkpoint number doesn't exist

     Modified: src/gotg/cli.py

     _auto_checkpoint(iter_dir, iteration) helper (private)

     - Called after run_conversation() returns in cmd_run and cmd_continue
     - Called at end of cmd_advance (after phase transition)
     - Wraps create_checkpoint() with print output: "Checkpoint 3 created (auto)"
     - Catches and prints errors (shouldn't block the command)

     Hook points

     1. cmd_run (line 187): After run_conversation() returns → _auto_checkpoint(iter_dir, iteration)
     2. cmd_continue (line 313): After run_conversation() returns → _auto_checkpoint(iter_dir, iteration). Need
     to re-read iteration since phase/max_turns may have changed? No — iteration dict is already loaded and phase
      doesn't change during run. Just use it.
     3. cmd_advance (line 454): After the phase transition print → _auto_checkpoint(iter_dir, iteration_after).
     Need to re-read iteration since phase changed. Re-read via get_current_iteration() or just update the dict's
      phase to next_phase.

     New command: cmd_checkpoint(args)

     - Manual checkpoint creation
     - args.description — optional string
     - Calls create_checkpoint(iter_dir, iteration, description=args.description, trigger="manual")
     - Prints: "Checkpoint 5 created"

     New command: cmd_checkpoints(args)

     - Lists all checkpoints for current iteration
     - Calls list_checkpoints(iter_dir)
     - Formats table: #  | Phase | Turns | Trigger | Description | Timestamp
     - Empty list: "No checkpoints yet."

     New command: cmd_restore(args)

     - args.number — required int (checkpoint number to restore)
     - Pre-restore safety prompt: input("Create checkpoint of current state before restoring? [Y/n] ")
       - If yes/empty: create_checkpoint(iter_dir, iteration, description=f"Safety before restore to #{number}",
     trigger="manual")
     - Calls restore_checkpoint(iter_dir, number) → gets state dict
     - Updates iteration.json: phase from state, max_turns from state (use existing save_iteration_phase pattern
     — may need a new helper or expand existing one)
     - Prints: "Restored to checkpoint 3 (phase: planning, turns: 14)"

     save_iteration_fields(team_dir, iteration_id, fields: dict) — new helper in config.py

     - Generalizes save_iteration_phase — updates arbitrary fields on iteration dict
     - Used by restore to set both phase and max_turns atomically
     - save_iteration_phase can delegate to this internally (optional cleanup)

     Subparser registration in main()

     cp_parser = subparsers.add_parser("checkpoint", help="Create a manual checkpoint")
     cp_parser.add_argument("description", nargs="?", default=None, help="Checkpoint description")

     subparsers.add_parser("checkpoints", help="List checkpoints for current iteration")

     restore_parser = subparsers.add_parser("restore", help="Restore iteration to a checkpoint")
     restore_parser.add_argument("number", type=int, help="Checkpoint number to restore")

     Add to if-elif dispatch chain:
     elif args.command == "checkpoint":
         cmd_checkpoint(args)
     elif args.command == "checkpoints":
         cmd_checkpoints(args)
     elif args.command == "restore":
         cmd_restore(args)

     Modified: src/gotg/config.py

     save_iteration_fields(team_dir, iteration_id, **fields)

     - Same pattern as save_iteration_phase: read iteration.json, find iteration by ID, update fields, write back
     - save_iteration_phase becomes a thin wrapper: save_iteration_fields(team_dir, iteration_id,
     phase=new_phase)

     Tests

     tests/test_checkpoint.py (~20 tests)

     _iter_files:
     - Returns all files in iter_dir except excluded ones
     - Excludes debug.jsonl and checkpoints directory
     - Returns empty list for empty dir
     - Does not recurse into subdirectories

     create_checkpoint:
     - Creates checkpoint dir with correct number
     - Copies all discovered files (not just a hardcoded list)
     - New artifact files are automatically included (safety net test — see below)
     - state.json has all required fields
     - Auto-increments number correctly
     - trigger field matches argument
     - description defaults for auto, uses provided string for manual

     _next_checkpoint_number:
     - Returns 1 when no checkpoints exist
     - Returns max+1 with existing checkpoints
     - Handles non-sequential numbers (gaps from deleted checkpoints)

     _count_agent_turns:
     - Counts only agent messages (excludes human, coach, system)
     - Returns 0 for empty conversation

     list_checkpoints:
     - Returns empty list when no checkpoints
     - Returns sorted list with all metadata
     - Handles missing state.json gracefully (skip that checkpoint)

     restore_checkpoint:
     - Copies files back to iter_dir
     - Removes files not in checkpoint (e.g., tasks.json existed before but not in checkpoint)
     - Raises ValueError for nonexistent checkpoint number
     - Returns state dict

     Safety net — discovery covers new artifacts:
     - Create an iter_dir with conversation.jsonl, groomed.md, tasks.json, AND an unexpected file
     new_artifact.txt
     - Create checkpoint → assert new_artifact.txt is in the checkpoint dir
     - This test proves the discovery approach works: future artifacts get backed up without code changes
     - Also assert debug.jsonl is NOT in the checkpoint (excluded)

     tests/test_cli.py (~10 tests)

     - cmd_run creates auto-checkpoint after conversation
     - cmd_continue creates auto-checkpoint after conversation
     - cmd_advance creates auto-checkpoint after phase transition
     - cmd_checkpoint creates manual checkpoint with description
     - cmd_checkpoints lists checkpoints (empty and populated)
     - cmd_restore restores and updates iteration.json fields
     - cmd_restore safety prompt creates checkpoint when user says yes
     - cmd_restore skips safety checkpoint when user says no
     - cmd_restore with invalid number shows error

     tests/test_config.py (if exists, or in test_cli.py)

     - save_iteration_fields updates multiple fields atomically

     Expected total: ~265 tests (235 + ~30 new)

     Files Modified




     ┌──────────────────────────┬───────────────────────────────────────────────────────────────┐
     │           File           │                            Changes                            │
     ├──────────────────────────┼───────────────────────────────────────────────────────────────┤
     │ src/gotg/checkpoint.py   │ New — create, list, restore, helpers                          │
     ├──────────────────────────┼───────────────────────────────────────────────────────────────┤
     │ src/gotg/cli.py          │ Auto-checkpoint hooks, 3 new commands, subparser registration │
     ├──────────────────────────┼───────────────────────────────────────────────────────────────┤
     │ src/gotg/config.py       │ save_iteration_fields() generalized helper                    │
     ├──────────────────────────┼───────────────────────────────────────────────────────────────┤
     │ tests/test_checkpoint.py │ New — ~20 tests                                               │
     ├──────────────────────────┼───────────────────────────────────────────────────────────────┤
     │ tests/test_cli.py        │ ~10 new tests                                                 │
     └──────────────────────────┴───────────────────────────────────────────────────────────────┘
     Implementation Order

     1. config.py — save_iteration_fields (small, enables restore)
     2. checkpoint.py — all functions (core logic, independent)
     3. cli.py — auto-checkpoint hooks + 3 new commands
     4. Tests — test_checkpoint.py, then test_cli.py additions
     5. Manual verification in /tmp/gotg-test/

     Verification

     1. Run existing tests: .venv/bin/python -m pytest tests/ -q — all 235 pass
     2. In test project:
       - gotg run → verify checkpoint dir created under .team/iterations/iter-1/checkpoints/1/
       - gotg checkpoints → shows checkpoint #1
       - gotg checkpoint "manual save" → creates #2
       - gotg checkpoints → shows both
       - gotg continue --max-turns 2 → creates #3 auto
       - gotg restore 1 → prompts for safety checkpoint (creates #4), restores conversation.jsonl to #1 state
       - Verify iteration.json phase matches checkpoint #1's phase
       - gotg show → conversation matches checkpoint #1