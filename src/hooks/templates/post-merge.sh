#!/usr/bin/env bash
# Code-KAG post-merge hook
# Triggers incremental re-index for files changed during the merge.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if ! source "$SCRIPT_DIR/code-kag-common.sh" 2>/dev/null; then
    echo "[code-kag] ERROR: Failed to source code-kag-common.sh" >&2
    exit 0  # Don't block git operations
fi

CODE_KAG_HOOK="post-merge"

# Get list of changed files from the merge
changed_files=()
while IFS= read -r file; do
    [ -n "$file" ] && changed_files+=("$file")
done < <(git diff-tree --no-commit-id --name-only -r ORIG_HEAD HEAD 2>/dev/null)

if [ ${#changed_files[@]} -gt 0 ]; then
    code_kag_reindex "$MODE" "${changed_files[@]}"
else
    code_kag_log "INFO: post-merge hook fired but no changed files detected"
fi
