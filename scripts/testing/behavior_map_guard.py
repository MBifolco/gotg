#!/usr/bin/env python3
"""Fail when critical execution changes lack behavior-map and test updates."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


CRITICAL_FILES = {
    "src/gotg/engine.py",
    "src/gotg/implementation.py",
    "src/gotg/cli.py",
    "src/gotg/session.py",
    "src/gotg/session_advance.py",
    "src/gotg/session_review.py",
    "src/gotg/console_events.py",
}
BEHAVIOR_MAP = "docs/testing-behavior-map.md"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _resolve_diff_range(repo_root: Path) -> str | None:
    base_ref = os.environ.get("BASE_REF") or os.environ.get("GITHUB_BASE_REF", "")
    if base_ref:
        _run(["git", "fetch", "--no-tags", "--depth=1", "origin", base_ref], repo_root)
        probe = _run(["git", "rev-parse", "--verify", f"origin/{base_ref}"], repo_root)
        if probe.returncode == 0:
            return f"origin/{base_ref}...HEAD"

    probe = _run(["git", "rev-parse", "--verify", "HEAD~1"], repo_root)
    if probe.returncode == 0:
        return "HEAD~1..HEAD"
    return None


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    diff_range = _resolve_diff_range(repo_root)
    if not diff_range:
        print("[behavior-map-guard] no diff base found, skipping")
        return 0

    diff = _run(["git", "diff", "--name-only", diff_range], repo_root)
    if diff.returncode != 0:
        print("[behavior-map-guard] failed to compute diff", file=sys.stderr)
        print(diff.stderr, file=sys.stderr)
        return 2

    changed = {line.strip() for line in diff.stdout.splitlines() if line.strip()}
    if not changed:
        print("[behavior-map-guard] no changed files")
        return 0

    critical_changed = sorted(path for path in changed if path in CRITICAL_FILES)
    if not critical_changed:
        print("[behavior-map-guard] no critical execution changes detected")
        return 0

    behavior_map_changed = BEHAVIOR_MAP in changed
    tests_changed = any(path.startswith("tests/") for path in changed)

    print("[behavior-map-guard] critical execution changes detected:")
    for path in critical_changed:
        print(f"  - {path}")

    errors: list[str] = []
    if not behavior_map_changed:
        errors.append(f"Missing update to {BEHAVIOR_MAP}")
    if not tests_changed:
        errors.append("Missing test updates under tests/")

    if errors:
        print("[behavior-map-guard] FAIL:")
        for err in errors:
            print(f"  - {err}")
        print("[behavior-map-guard] Required for critical-flow changes:")
        print("  1) Update docs/testing-behavior-map.md")
        print("  2) Add/adjust at least one behavior-level test")
        return 1

    print("[behavior-map-guard] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
