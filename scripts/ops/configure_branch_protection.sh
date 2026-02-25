#!/usr/bin/env bash
set -euo pipefail

# Configure branch protection required checks for the default/main branch.
#
# Usage:
#   scripts/ops/configure_branch_protection.sh
#
# Optional env vars:
#   REPO=owner/name
#   BRANCH=main
#   REQUIRED_CHECKS_CSV="core-non-tui / tests (pull_request),tui-pty / tui-tests (pull_request),behavior-map-guard / guard (pull_request)"
#   DRY_RUN=1

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: gh CLI is required." >&2
  exit 2
fi

DRY_RUN="${DRY_RUN:-0}"
BRANCH="${BRANCH:-main}"
REQUIRED_CHECKS_CSV="${REQUIRED_CHECKS_CSV:-core-non-tui / tests (pull_request),tui-pty / tui-tests (pull_request),behavior-map-guard / guard (pull_request)}"
REPO="${REPO:-}"

if [[ -z "${REPO}" ]]; then
  remote_url="$(git config --get remote.origin.url || true)"
  if [[ -n "${remote_url}" ]]; then
    if [[ "${remote_url}" =~ github\.com[:/]([^/]+)/([^.]+)(\.git)?$ ]]; then
      REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    fi
  fi
fi

IFS=',' read -r -a required_checks <<< "${REQUIRED_CHECKS_CSV}"

checks_json="["
for check in "${required_checks[@]}"; do
  trimmed="$(echo "${check}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  checks_json="${checks_json}\"${trimmed}\","
done
checks_json="${checks_json%,}]"

payload="$(cat <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": ${checks_json}
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1
  },
  "restrictions": null
}
JSON
)"

if [[ "${DRY_RUN}" == "1" ]]; then
  if [[ -z "${REPO}" ]]; then
    REPO="<owner>/<repo>"
  fi
  echo "Repo: ${REPO}"
  echo "Branch: ${BRANCH}"
  echo "Payload:"
  echo "${payload}"
  exit 0
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "Error: gh auth is not valid. Run: gh auth login -h github.com" >&2
  exit 2
fi

if [[ -z "${REPO}" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
fi

echo "Applying branch protection to ${REPO}:${BRANCH}"
echo "${payload}" | gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "repos/${REPO}/branches/${BRANCH}/protection" \
  --input -

echo "Branch protection updated."
