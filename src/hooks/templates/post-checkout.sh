#!/usr/bin/env bash
# Code-KAG post-checkout hook
# Triggers full re-index on branch switch.
# Args: $1=prev HEAD, $2=new HEAD, $3=flag (1=branch checkout, 0=file checkout)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/code-kag-common.sh"

checkout_flag="${3:-0}"

# Only re-index on branch switch (flag=1), not file checkout
if [ "$checkout_flag" = "1" ]; then
    code_kag_reindex "full"
fi
