# Branch Protection Setup

This repo uses CI lanes that should be required for merges to `main`.

## Required Checks

1. `core-non-tui / tests`
2. `tui-pty / tui-tests`
3. `behavior-map-guard / guard`

For API-driven setup, configure check names without event suffix:

1. `core-non-tui / tests`
2. `tui-pty / tui-tests`
3. `behavior-map-guard / guard`

`nightly-replay` and `mutation-pilot` are scheduled/manual lanes and should not be required PR checks by default.

## One-Command Setup (gh CLI)

Prerequisites:

1. `gh` installed
2. authenticated: `gh auth login -h github.com`
3. admin access to the repository

Run:

```bash
scripts/ops/configure_branch_protection.sh
```

Dry run:

```bash
DRY_RUN=1 scripts/ops/configure_branch_protection.sh
```

Override repo/branch:

```bash
REPO=owner/repo BRANCH=main scripts/ops/configure_branch_protection.sh
```

## Notes

1. The script enforces up-to-date branches (`strict: true`).
2. It enables review requirements with `required_approving_review_count=1`.
3. It enforces admin protection.
4. The script writes required checks via `required_status_checks.checks` and clears legacy `contexts` to avoid duplicate "Expected" rows.
5. GitHub UI may display run labels with `(pull_request)`; do not include that suffix in configured required check names.
6. If pinning to a specific app, set `REQUIRED_CHECK_APP_ID=<id>`; otherwise leave it unset so any app can satisfy the check.
