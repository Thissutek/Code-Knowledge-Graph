#!/usr/bin/env bash
# Code-KAG post-commit hook
# Triggers incremental re-index for files changed in the latest commit.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/code-kag-common.sh"

# Get list of changed files from the latest commit
changed_files=()
while IFS= read -r file; do
    [ -n "$file" ] && changed_files+=("$file")
done < <(git diff-tree --no-commit-id --name-only -r HEAD 2>/dev/null)

if [ ${#changed_files[@]} -gt 0 ]; then
    code_kag_reindex "$MODE" "${changed_files[@]}"
fi
