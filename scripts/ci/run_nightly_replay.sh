#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="python"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

"${PYTHON_BIN}" -m pytest tests/test_e2e_quality_gate.py -q --tb=short
