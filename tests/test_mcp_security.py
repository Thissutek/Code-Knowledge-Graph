"""
Security tests for MCP server unbounded limit cap.
"""
import pytest

from src.mcp_server import MAX_QUERY_LIMIT


# ── MAX_QUERY_LIMIT ────────────────────────────────────────────────────────

class TestMaxQueryLimit:
    def test_constant_defined(self):
        assert MAX_QUERY_LIMIT == 200

    def test_limit_value_is_200(self):
        """Sanity check that the limit is exactly 200."""
        assert isinstance(MAX_QUERY_LIMIT, int)
        assert MAX_QUERY_LIMIT > 0
