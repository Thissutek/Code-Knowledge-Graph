"""
Security tests for MCP server path traversal prevention.
"""
import pytest
from pathlib import Path

from src.mcp_server import _validate_repo_path


# ── _validate_repo_path ────────────────────────────────────────────────────

class TestValidateRepoPath:
    def test_no_restriction_any_path_accepted(self, tmp_path, monkeypatch):
        """When ALLOWED_INDEX_ROOT is not set, any path is accepted."""
        monkeypatch.delenv("ALLOWED_INDEX_ROOT", raising=False)
        resolved = _validate_repo_path(str(tmp_path))
        assert resolved == str(tmp_path.resolve())

    def test_path_under_allowed_root_accepted(self, tmp_path, monkeypatch):
        """Path inside an allowed root is accepted."""
        sub = tmp_path / "project"
        sub.mkdir()
        monkeypatch.setenv("ALLOWED_INDEX_ROOT", str(tmp_path))
        resolved = _validate_repo_path(str(sub))
        assert resolved == str(sub.resolve())

    def test_path_outside_allowed_root_rejected(self, tmp_path, monkeypatch, tmp_path_factory):
        """Path outside every allowed root raises ValueError."""
        other = tmp_path_factory.mktemp("other")
        monkeypatch.setenv("ALLOWED_INDEX_ROOT", str(tmp_path))
        with pytest.raises(ValueError, match="not under any allowed"):
            _validate_repo_path(str(other))

    def test_traversal_attempt_rejected(self, tmp_path, monkeypatch):
        """Path traversal via '..' is caught after resolution."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        monkeypatch.setenv("ALLOWED_INDEX_ROOT", str(allowed))
        # Construct a path that tries to escape via ..
        traversal = str(allowed / ".." / "escape")
        with pytest.raises(ValueError, match="not under any allowed"):
            _validate_repo_path(traversal)

    def test_exact_root_match_accepted(self, tmp_path, monkeypatch):
        """The exact root itself is accepted."""
        monkeypatch.setenv("ALLOWED_INDEX_ROOT", str(tmp_path))
        resolved = _validate_repo_path(str(tmp_path))
        assert resolved == str(tmp_path.resolve())
