#!/usr/bin/env bash
# Code-KAG post-merge hook
# Triggers incremental re-index for files changed during the merge.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/code-kag-common.sh"

# Get list of changed files from the merge
changed_files=($(git diff-tree --no-commit-id --name-only -r ORIG_HEAD HEAD 2>/dev/null))

if [ ${#changed_files[@]} -gt 0 ]; then
    code_kag_reindex "$MODE" "${changed_files[@]}"
fi
