#!/bin/sh
# Code-KAG MCP Server entrypoint
#
# On startup, checks whether the repo index is stale. If it is (or has never
# been indexed), runs a full index before starting the MCP server.
#
# Environment variables:
#   CODE_PATH        Path to the repository to index (default: /repos)
#   REPO_ID          Repository identifier used in the graph (default: my-project)
#   MAX_INDEX_AGE_HOURS  How many hours before the index is considered stale (default: 24)
#   NEO4J_URI        Bolt URI for Neo4j (default: bolt://localhost:7687)
#   NEO4J_USERNAME   Neo4j username (default: neo4j)
#   NEO4J_PASSWORD   Neo4j password (required)

CODE_PATH="${CODE_PATH:-/repos}"
REPO_ID="${REPO_ID:-my-project}"
MAX_INDEX_AGE_HOURS="${MAX_INDEX_AGE_HOURS:-24}"

echo "[code-kag] Checking index freshness for repo '${REPO_ID}'..." >&2

python cli.py check-staleness \
    --repo-id "${REPO_ID}" \
    --max-age-hours "${MAX_INDEX_AGE_HOURS}"

if [ $? -ne 0 ]; then
    echo "[code-kag] Re-indexing '${CODE_PATH}' as '${REPO_ID}'..." >&2
    python cli.py index "${CODE_PATH}" --id "${REPO_ID}"
    if [ $? -ne 0 ]; then
        echo "[code-kag] WARNING: Indexing failed. Starting MCP server anyway." >&2
    else
        echo "[code-kag] Indexing complete." >&2
    fi
fi

echo "[code-kag] Starting MCP server..." >&2
exec python src/mcp_server.py
