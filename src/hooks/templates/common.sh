#!/usr/bin/env bash
# Code-KAG shared hook functions
# This file is sourced by all code-kag git hooks.

CODE_KAG_PATH="{{CODE_KAG_PATH}}"
REPO_ID="{{REPO_ID}}"
MODE="{{MODE}}"
NEO4J_URI="{{NEO4J_URI}}"

LOCKFILE="/tmp/code-kag-reindex-${REPO_ID}.lock"
LOGFILE="/tmp/code-kag-reindex-${REPO_ID}.log"

code_kag_reindex() {
    local mode="$1"
    shift
    local files=("$@")

    # Check if Neo4j is reachable before attempting re-index
    local neo4j_host neo4j_port
    neo4j_host=$(echo "$NEO4J_URI" | sed -E 's|^bolt://||;s|:([0-9]+)$||')
    neo4j_port=$(echo "$NEO4J_URI" | grep -oE '[0-9]+$')
    neo4j_port="${neo4j_port:-7687}"

    if ! nc -z "$neo4j_host" "$neo4j_port" 2>/dev/null; then
        echo "[code-kag] WARNING: Neo4j is not reachable at $NEO4J_URI" >&2
        echo "[code-kag] Skipping re-index. Start Neo4j and re-run: python \"$CODE_KAG_PATH/cli.py\" index \"$(pwd)\" --id \"$REPO_ID\"" >&2
        echo "$(date '+%Y-%m-%d %H:%M:%S') SKIPPED: Neo4j not reachable at $NEO4J_URI" >> "$LOGFILE"
        return 1
    fi

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
        echo ${BASHPID:-$$} > "$LOCKFILE"
        trap 'rm -f "$LOCKFILE"' EXIT

        local exit_code=0

        if [ "$mode" = "incremental" ] && [ ${#files[@]} -gt 0 ]; then
            echo "[code-kag] Incremental re-index: ${#files[@]} file(s)"
            python "$CODE_KAG_PATH/cli.py" index "$(pwd)" \
                --id "$REPO_ID" \
                --neo4j-uri "$NEO4J_URI" \
                --incremental \
                --changed-files "${files[@]}" \
                >> "$LOGFILE" 2>&1
            exit_code=$?
        else
            echo "[code-kag] Full re-index"
            python "$CODE_KAG_PATH/cli.py" index "$(pwd)" \
                --id "$REPO_ID" \
                --neo4j-uri "$NEO4J_URI" \
                >> "$LOGFILE" 2>&1
            exit_code=$?
        fi

        if [ $exit_code -ne 0 ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') FAILED: Re-index exited with code $exit_code (mode=$mode)" >> "$LOGFILE"
            echo "[code-kag] ERROR: Re-index failed. Check log: $LOGFILE" >&2
        else
            echo "$(date '+%Y-%m-%d %H:%M:%S') SUCCESS: Re-index completed (mode=$mode)" >> "$LOGFILE"
        fi
    ) &
    disown
}
