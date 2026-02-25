#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="python"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

"${PYTHON_BIN}" -m pytest tests/ -q --tb=short --ignore-glob='tests/test_tui*.py'
