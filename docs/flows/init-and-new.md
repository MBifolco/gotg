# Flow: Project Init and Iteration Creation

What happens when you run `gotg init` and `gotg new`.

## `gotg init`

**Entry**: `commands/admin.py::cmd_init` → `scaffold.py::init_project`

1. **Preconditions** (`scaffold.py::init_project`)
   - Checks `.team/` doesn't already exist (raises `ConfigError` if it does)
   - Checks `.git/` exists (requires a git repo)

2. **Gitignore** (`scaffold.py::_ensure_gitignore`)
   - Adds `/.team/`, `.env`, `/.worktrees/` to `.gitignore`
   - Commits the gitignore change (tolerates "nothing to commit" and missing git identity)

3. **Directory structure** (`scaffold.py::init_project`)
   - Creates `.team/` directory
   - Writes `.team/team.json` with defaults:
     ```
     model:       anthropic / claude-sonnet-4-6 / api_key: $ANTHROPIC_API_KEY
     agents:      agent-1, agent-2 (Software Engineer)
     coach:       coach (Agile Coach)
     file_access: writable src/**, tests/**, docs/** with approvals enabled
     worktrees:   enabled
     streaming:   true
     ```
   - Writes `.team/iteration.json`: `{"iterations": [], "current": null}`
   - Creates empty `.team/iterations/` directory

4. **Output**
   ```
   Initialized .team/ in /path/to/project
     .gitignore (added .team/, .env)
     .team/team.json
     .team/iteration.json

   Next: run 'gotg explore start "topic"' or 'gotg new "description"'
   ```

### Files on disk after init

```
.team/
  team.json           ← team config (agents, model, file access, worktrees)
  iteration.json      ← iteration list + current pointer
  iterations/         ← empty, will hold per-iteration dirs
.env                  ← user adds API key here (gitignored)
```

## `gotg new "description"`

**Entry**: `commands/admin.py::cmd_new`

1. **Find team dir** — walks up from cwd looking for `.team/`
2. **Generate ID** — `iter-1`, `iter-2`, etc. (checks existing IDs to avoid collisions)
3. **Create iteration** (`iteration_store.py::create_iteration`)
   - Appends to `.team/iteration.json`:
     ```json
     {"id": "iter-1", "title": "", "description": "...", "status": "pending",
      "phase": "refinement", "max_turns": 30}
     ```
   - Sets `current` pointer to the new iteration
   - Creates `.team/iterations/iter-1/` with empty `conversation.jsonl`
4. **Output**
   ```
   Created iter-1: Build the login page
   Set as current iteration. Run 'gotg run' to start refinement.
   ```

### Files on disk after `gotg new`

```
.team/
  iteration.json      ← now has iter-1, current: "iter-1"
  iterations/
    iter-1/
      conversation.jsonl  ← empty, ready for first run
```

## What's next

The iteration is in `phase: "refinement"` and `status: "pending"`. Running `gotg run` will start the refinement discussion. See [first-turn.md](first-turn.md) for what happens during the first agent turn.

## Files touched

| Module | Responsibility |
|--------|---------------|
| `commands/admin.py` | CLI entry (`cmd_init`, `cmd_new`) |
| `scaffold.py` | `init_project` — creates directory structure + default configs |
| `iteration_store.py` | `create_iteration` — writes to iteration.json, creates iter dir |
| `config.py` | `read_dotenv`, `ensure_dotenv_key` — API key setup (called by `cmd_model`) |
