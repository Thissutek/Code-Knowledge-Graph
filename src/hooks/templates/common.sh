#!/usr/bin/env bash
# Code-KAG shared hook functions
# This file is sourced by all code-kag git hooks.

CODE_KAG_PATH="{{CODE_KAG_PATH}}"
REPO_ID="{{REPO_ID}}"
MODE="{{MODE}}"
NEO4J_URI="{{NEO4J_URI}}"
NEO4J_USER="{{NEO4J_USER}}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:?Error: NEO4J_PASSWORD must be set in environment before running code-kag hooks}"

LOCKFILE="/tmp/code-kag-reindex-${REPO_ID}.lock"
LOGFILE="/tmp/code-kag-reindex-${REPO_ID}.log"

code_kag_log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOGFILE"
}

# Find the right Python: prefer the project venv, then python3, then python
if [ -x "$CODE_KAG_PATH/.venv/bin/python" ]; then
    PYTHON="$CODE_KAG_PATH/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "[code-kag] ERROR: No python or python3 found in PATH" >&2
    code_kag_log "ERROR: No python or python3 found in PATH"
    return 1 2>/dev/null || exit 1
fi

code_kag_reindex() {
    local mode="$1"
    shift
    local files=("$@")

    code_kag_log "TRIGGER: mode=$mode, files=${#files[@]}, hook=$CODE_KAG_HOOK"

    # Check if Neo4j is reachable before attempting re-index
    local neo4j_host neo4j_port
    neo4j_host=$(echo "$NEO4J_URI" | sed -E 's|^bolt://||;s|:([0-9]+)$||')
    neo4j_port=$(echo "$NEO4J_URI" | grep -oE '[0-9]+$')
    neo4j_port="${neo4j_port:-7687}"

    if ! nc -z "$neo4j_host" "$neo4j_port" 2>/dev/null; then
        echo "[code-kag] WARNING: Neo4j is not reachable at $NEO4J_URI" >&2
        echo "[code-kag] Skipping re-index. Start Neo4j and re-run: $PYTHON \"$CODE_KAG_PATH/cli.py\" index \"$(pwd)\" --id \"$REPO_ID\"" >&2
        code_kag_log "SKIPPED: Neo4j not reachable at $NEO4J_URI"
        return 1
    fi

    # Debounce: skip if another re-index is running
    if [ -f "$LOCKFILE" ]; then
        pid=$(cat "$LOCKFILE" 2>/dev/null)
        if kill -0 "$pid" 2>/dev/null; then
            echo "[code-kag] Re-index already in progress (pid $pid), skipping." >&2
            code_kag_log "SKIPPED: Re-index already in progress (pid $pid)"
            return 0
        fi
        code_kag_log "INFO: Cleaned up stale lockfile (pid $pid no longer running)"
        rm -f "$LOCKFILE"
    fi

    # Run re-index in the background
    (
        echo ${BASHPID:-$$} > "$LOCKFILE"
        trap 'rm -f "$LOCKFILE"' EXIT

        local exit_code=0

        if [ "$mode" = "incremental" ] && [ ${#files[@]} -gt 0 ]; then
            code_kag_log "START: Incremental re-index of ${#files[@]} file(s): ${files[*]}"
            "$PYTHON" "$CODE_KAG_PATH/cli.py" \
                --neo4j-uri "$NEO4J_URI" \
                --neo4j-user "$NEO4J_USER" \
                --neo4j-password "$NEO4J_PASSWORD" \
                index "$(pwd)" \
                --id "$REPO_ID" \
                --incremental \
                --changed-files "${files[@]}" \
                >> "$LOGFILE" 2>&1
            exit_code=$?
        else
            code_kag_log "START: Full re-index"
            "$PYTHON" "$CODE_KAG_PATH/cli.py" \
                --neo4j-uri "$NEO4J_URI" \
                --neo4j-user "$NEO4J_USER" \
                --neo4j-password "$NEO4J_PASSWORD" \
                index "$(pwd)" \
                --id "$REPO_ID" \
                >> "$LOGFILE" 2>&1
            exit_code=$?
        fi

        if [ $exit_code -ne 0 ]; then
            code_kag_log "FAILED: Re-index exited with code $exit_code (mode=$mode)"
            echo "[code-kag] ERROR: Re-index failed. Check log: $LOGFILE" >&2
        else
            code_kag_log "SUCCESS: Re-index completed (mode=$mode)"
        fi
    ) &
    disown
}
