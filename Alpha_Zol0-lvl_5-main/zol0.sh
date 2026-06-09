#!/usr/bin/env sh
set -eu
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python
fi
"$PYTHON_BIN" -m tools.zol0ctl "$@"
status=$?
exit "$status"
