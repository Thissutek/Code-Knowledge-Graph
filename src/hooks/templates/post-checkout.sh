#!/usr/bin/env bash
# Code-KAG post-checkout hook
# Triggers full re-index on branch switch.
# Args: $1=prev HEAD, $2=new HEAD, $3=flag (1=branch checkout, 0=file checkout)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if ! source "$SCRIPT_DIR/code-kag-common.sh" 2>/dev/null; then
    echo "[code-kag] ERROR: Failed to source code-kag-common.sh" >&2
    exit 0  # Don't block git operations
fi

CODE_KAG_HOOK="post-checkout"

prev_head="${1:-}"
new_head="${2:-}"
checkout_flag="${3:-0}"

# Only re-index on branch switch (flag=1), not file checkout
if [ "$checkout_flag" = "1" ]; then
    code_kag_log "INFO: Branch switch detected (${prev_head:0:7} -> ${new_head:0:7})"
    code_kag_reindex "full"
else
    code_kag_log "INFO: post-checkout hook fired but was a file checkout (flag=$checkout_flag), skipping"
fi
