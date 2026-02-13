#!/usr/bin/env bash
# Code-KAG shared hook functions
# This file is sourced by all code-kag git hooks.

CODE_KAG_PATH="{{CODE_KAG_PATH}}"
REPO_ID="{{REPO_ID}}"
MODE="{{MODE}}"
NEO4J_URI="{{NEO4J_URI}}"

LOCKFILE="/tmp/code-kag-reindex-${REPO_ID}.lock"

code_kag_reindex() {
    local mode="$1"
    shift
    local files=("$@")

    # Debounce: skip if another re-index is running
    if [ -f "$LOCKFILE" ]; then
        pid=$(cat "$LOCKFILE" 2>/dev/null)
        if kill -0 "$pid" 2>/dev/null; then
            echo "[code-kag] Re-index already in progress (pid $pid), skipping."
            return 0
        fi
        rm -f "$LOCKFILE"
    fi

    # Run re-index in the background
    (
        echo $$ > "$LOCKFILE"
        trap 'rm -f "$LOCKFILE"' EXIT

        if [ "$mode" = "incremental" ] && [ ${#files[@]} -gt 0 ]; then
            echo "[code-kag] Incremental re-index: ${#files[@]} file(s)"
            python "$CODE_KAG_PATH/cli.py" index "$(pwd)" \
                --id "$REPO_ID" \
                --neo4j-uri "$NEO4J_URI" \
                --incremental \
                --changed-files "${files[@]}" \
                2>&1 | while IFS= read -r line; do echo "[code-kag] $line"; done
        else
            echo "[code-kag] Full re-index"
            python "$CODE_KAG_PATH/cli.py" index "$(pwd)" \
                --id "$REPO_ID" \
                --neo4j-uri "$NEO4J_URI" \
                2>&1 | while IFS= read -r line; do echo "[code-kag] $line"; done
        fi
    ) &
    disown
}
