#!/usr/bin/env bash
# PostToolUse hook for Edit|Write: format and lint the edited Python file.
# Exit 2 sends ruff's output back to Claude when an error can't be auto-fixed.
set -uo pipefail

file=$(jq -r '.tool_input.file_path // .tool_response.filePath // empty')
[[ "$file" == *.py && -f "$file" ]] || exit 0

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" || exit 0
out=$(uv run --quiet ruff check --force-exclude --fix --quiet "$file" 2>&1)
status=$?
uv run --quiet ruff format --force-exclude --quiet "$file"
if [[ $status -ne 0 ]]; then
  echo "ruff check failed on $file:" >&2
  echo "$out" >&2
  exit 2
fi
