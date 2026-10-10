#!/usr/bin/env bash
# Stop hook: run the fast test suite when Python code or dependencies changed.
# Exit 2 keeps Claude working on failures, but only once per stop to avoid a loop.
set -uo pipefail

stop_hook_active=$(jq -r '.stop_hook_active // false')
cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" || exit 0

git status --porcelain | grep -qE '(\.py|pyproject\.toml|uv\.lock)$' || exit 0

if ! out=$(make test 2>&1); then
  if [[ "$stop_hook_active" == "true" ]]; then
    echo "make test is still failing; stopping anyway." >&2
    exit 0
  fi
  echo "make test failed:" >&2
  echo "$out" | tail -40 >&2
  exit 2
fi
