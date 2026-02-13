#!/usr/bin/env bash
# Code-KAG post-rewrite hook
# Triggers full re-index after rebase or amend.
# Arg: $1=command that triggered the rewrite (rebase or amend)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if ! source "$SCRIPT_DIR/code-kag-common.sh" 2>/dev/null; then
    echo "[code-kag] ERROR: Failed to source code-kag-common.sh" >&2
    exit 0  # Don't block git operations
fi

CODE_KAG_HOOK="post-rewrite"
rewrite_command="${1:-unknown}"

code_kag_log "INFO: Post-rewrite triggered by: $rewrite_command"
code_kag_reindex "full"
