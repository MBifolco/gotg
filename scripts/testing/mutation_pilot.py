#!/usr/bin/env python3
"""Lightweight mutation pilot for critical execution modules.

This avoids third-party mutation tooling by applying a small curated set of
source mutations and verifying that targeted tests fail (mutants are killed).
"""


from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys


@dataclass(frozen=True)
class MutantCase:
    name: str
    path: str
    before: str
    after: str
    test_cmd: str
    replace_count: int = 1


def _python_bin(repo_root: Path) -> str:
    venv_python = repo_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python"


def _run_command(cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    py = _python_bin(repo_root)
    floor = float(os.environ.get("GOTG_MUTATION_FLOOR", "0.80"))

    cases: list[MutantCase] = [
        MutantCase(
            name="impl_complete_tasks_empty_ids_guard",
            path="src/gotg/implementation.py",
            before='if not task_ids:\n        return "Error: task_ids is empty"',
            after='if task_ids:\n        return "Error: task_ids is empty"',
            test_cmd=f"{py} -m pytest tests/test_implementation.py -q --tb=short",
        ),
        MutantCase(
            name="impl_complete_tasks_layer_membership_guard",
            path="src/gotg/implementation.py",
            before='if tid not in lt_ids:\n            return f"Error: task \'{tid}\' is not in layer {layer}"',
            after='if tid in lt_ids:\n            return f"Error: task \'{tid}\' is not in layer {layer}"',
            test_cmd=f"{py} -m pytest tests/test_implementation.py tests/test_e2e_quality_gate.py -q --tb=short",
        ),
        MutantCase(
            name="engine_error_classification_guard",
            path="src/gotg/engine.py",
            before='if result_str.startswith("Error:"):\n        return "error"',
            after='if result_str.startswith("Error:"):\n        return "ok"',
            test_cmd=f"{py} -m pytest tests/test_engine.py tests/test_streaming.py -q --tb=short",
        ),
        MutantCase(
            name="engine_pass_turn_suppression_guard",
            path="src/gotg/engine.py",
            before='if not pass_called:\n        yield AgentTurnComplete(agent=agent["name"], turn_id=turn_id, content=final_content)',
            after='if pass_called:\n        yield AgentTurnComplete(agent=agent["name"], turn_id=turn_id, content=final_content)',
            test_cmd=f"{py} -m pytest tests/test_engine.py tests/test_behavior_contracts.py -q --tb=short",
        ),
        MutantCase(
            name="cli_agent_append_suppression_guard",
            path="src/gotg/cli.py",
            before='if _suppress_agent_append and event.msg.get("from") == _suppress_agent_append:\n                    _suppress_agent_append = None',
            after='if _suppress_agent_append and event.msg.get("from") != _suppress_agent_append:\n                    _suppress_agent_append = None',
            test_cmd=f"{py} -m pytest tests/test_cli.py tests/test_streaming.py -q --tb=short",
            replace_count=1,
        ),
    ]

    total = 0
    killed = 0
    invalid = 0

    print(f"[mutation] running {len(cases)} curated mutants (floor={floor:.0%})")

    for case in cases:
        total += 1
        target_path = repo_root / case.path
        original = target_path.read_text()

        if case.before not in original:
            invalid += 1
            print(f"[mutation] {case.name}: INVALID (pattern not found)")
            continue

        mutated = original.replace(case.before, case.after, case.replace_count)
        if mutated == original:
            invalid += 1
            print(f"[mutation] {case.name}: INVALID (replacement produced no change)")
            continue

        target_path.write_text(mutated)
        try:
            result = _run_command(case.test_cmd, repo_root)
        finally:
            target_path.write_text(original)

        if result.returncode != 0:
            killed += 1
            print(f"[mutation] {case.name}: KILLED")
        else:
            print(f"[mutation] {case.name}: SURVIVED")
            tail = "\n".join(result.stdout.splitlines()[-10:])
            if tail:
                print("[mutation] survivor output tail:")
                print(tail)

    valid = total - invalid
    if valid == 0:
        print("[mutation] no valid mutants executed")
        return 2

    kill_rate = killed / valid
    print(
        f"[mutation] summary: total={total} valid={valid} killed={killed} "
        f"survived={valid - killed} invalid={invalid} kill_rate={kill_rate:.1%}"
    )

    if invalid:
        print("[mutation] FAIL: invalid mutants detected (stale patterns).")
        return 2
    if kill_rate < floor:
        print(f"[mutation] FAIL: kill rate {kill_rate:.1%} is below floor {floor:.1%}.")
        return 1

    print("[mutation] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
