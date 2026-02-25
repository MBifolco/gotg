# Branch Protection Setup

This repo uses CI lanes that should be required for merges to `main`.

## Required Checks

1. `core-non-tui / tests`
2. `tui-pty / tui-tests`
3. `behavior-map-guard / guard`

For this repository, required checks must match the **check run names** exactly:

1. `tests`
2. `tui-tests`
3. `guard`

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

Require one approving review (team mode):

```bash
REQUIRED_APPROVING_REVIEW_COUNT=1 scripts/ops/configure_branch_protection.sh
```

## Notes

1. The script enforces up-to-date branches (`strict: true`).
2. It enables review requirements with `required_approving_review_count=0` by default (solo-friendly).
3. For team mode, set `REQUIRED_APPROVING_REVIEW_COUNT=1` (or higher) when running the script.
4. It enforces admin protection.
5. The script writes required checks via `required_status_checks.checks` (no legacy `contexts`).
6. Required checks are exact string matches against `check_runs[].name` (from the GitHub API), not the decorated label shown in the PR UI.
7. If results still look duplicated/mismatched after applying branch protection, check repository Rulesets for additional required checks configured there.
8. If pinning to a specific app, set `REQUIRED_CHECK_APP_ID=<id>`; otherwise leave it unset so any app can satisfy the check.
