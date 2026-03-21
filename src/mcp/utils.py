"""Shared utilities for Code-KAG MCP tool handlers."""
import logging
import os
import time
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

MAX_QUERY_LIMIT = 200
SERVER_START_TIME = time.time()

# Module-level querier cache
_querier = None


def get_querier():
    """Get or create the Neo4j querier with connection validation and retry."""
    import time as _time
    from src.neo4j_ingester import CodeKAGQuerier

    global _querier

    if _querier is not None:
        try:
            _querier.driver.verify_connectivity()
            return _querier
        except Exception:
            try:
                _querier.close()
            except Exception:
                pass
            _querier = None

    last_error = None
    for attempt in range(3):
        try:
            q = CodeKAGQuerier()
            q.connect()
            q.driver.verify_connectivity()
            _querier = q
            return _querier
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                _time.sleep(1 * (attempt + 1))

    raise ConnectionError(
        f"Failed to connect to Neo4j after 3 attempts: {last_error}. "
        "Check that Neo4j is running and NEO4J_URI/NEO4J_USERNAME/NEO4J_PASSWORD are correct."
    )


def _parse_limit(value: Any, default: int) -> int:
    """Parse a limit argument safely, clamping to [1, MAX_QUERY_LIMIT]."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, MAX_QUERY_LIMIT))


def _validate_repo_path(repo_path: str) -> str:
    """Validate repo_path against ALLOWED_INDEX_ROOT to prevent path traversal."""
    resolved = str(Path(repo_path).resolve())
    raw = os.environ.get("ALLOWED_INDEX_ROOT", "").strip()
    if not raw:
        _logger.warning("ALLOWED_INDEX_ROOT not set; any path may be indexed via MCP.")
        return resolved
    roots = [r.strip() for r in raw.split(os.pathsep) if r.strip()]
    for root in roots:
        allowed = str(Path(root).resolve())
        if resolved == allowed or resolved.startswith(allowed + os.sep):
            return resolved
    raise ValueError(f"repo_path '{resolved}' is not under any allowed ALLOWED_INDEX_ROOT.")
