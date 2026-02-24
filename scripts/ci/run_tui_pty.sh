#!/usr/bin/env bash
set -euo pipefail

export TERM="${TERM:-xterm-256color}"

PYTHON_BIN="python"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

timeout 420 "${PYTHON_BIN}" -m pytest tests/test_tui*.py -q --tb=short
