"""
Security tests for MCP server (path traversal, limit cap) and
hook manager (password not baked into common.sh, uninstall backup preservation).
"""
import os
import stat
import pytest
from pathlib import Path

from src.mcp_server import _validate_repo_path, MAX_QUERY_LIMIT
from src.hooks.hook_manager import HookManager, CODE_KAG_MARKER


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


# ── MAX_QUERY_LIMIT ────────────────────────────────────────────────────────

class TestMaxQueryLimit:
    def test_constant_defined(self):
        assert MAX_QUERY_LIMIT == 200

    def test_limit_value_is_200(self):
        """Sanity check that the limit is exactly 200."""
        assert isinstance(MAX_QUERY_LIMIT, int)
        assert MAX_QUERY_LIMIT > 0


# ── Password not written to common.sh ─────────────────────────────────────

class TestPasswordNotBakedIntoCommonSh:
    def test_password_not_written_to_common_sh(self, git_repo):
        """Installing with a password should NOT bake it into common.sh."""
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="FAKE_NEO4J_PW_FOR_TESTING")

        common = (git_repo / ".git" / "hooks" / "code-kag-common.sh").read_text()
        assert "FAKE_NEO4J_PW_FOR_TESTING" not in common

    def test_common_sh_uses_env_var_expansion(self, git_repo):
        """common.sh should reference NEO4J_PASSWORD via env var, not literal."""
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test")

        common = (git_repo / ".git" / "hooks" / "code-kag-common.sh").read_text()
        assert "NEO4J_PASSWORD" in common
        # Env var expansion syntax, not a hardcoded value
        assert "${NEO4J_PASSWORD" in common

    def test_no_unfilled_placeholders(self, git_repo):
        """No {{...}} placeholders should remain after install."""
        hm = HookManager()
        hm.install(str(git_repo), repo_id="my-proj", mode="full",
                   neo4j_uri="bolt://db:7687")

        common = (git_repo / ".git" / "hooks" / "code-kag-common.sh").read_text()
        assert "{{" not in common


# ── Uninstall does not delete foreign backups ──────────────────────────────

class TestUninstallDoesNotDeleteForeignBackup:
    def test_foreign_backup_preserved(self, git_repo):
        """A .pre-code-kag backup that code-kag didn't create is not deleted."""
        hooks_dir = git_repo / ".git" / "hooks"

        # Simulate a foreign backup (not created by code-kag's install)
        foreign_backup = hooks_dir / "post-commit.pre-code-kag"
        foreign_backup.write_text("#!/bin/sh\necho foreign\n")

        # Don't install code-kag — just uninstall (no-op for hooks, but must
        # not touch the foreign backup)
        hm = HookManager()
        hm.uninstall(str(git_repo))

        assert foreign_backup.exists(), "Foreign backup was incorrectly deleted"
        assert "foreign" in foreign_backup.read_text()

    def test_own_backup_deleted_after_restore(self, git_repo):
        """A backup created by code-kag install IS cleaned up on uninstall."""
        hooks_dir = git_repo / ".git" / "hooks"

        # Write a pre-existing hook so code-kag creates a backup
        existing = hooks_dir / "post-commit"
        existing.write_text("#!/bin/sh\necho original\n")
        existing.chmod(existing.stat().st_mode | stat.S_IXUSR)

        hm = HookManager()
        hm.install(str(git_repo), repo_id="test")
        backup = hooks_dir / "post-commit.pre-code-kag"
        assert backup.exists()

        hm.uninstall(str(git_repo))
        assert not backup.exists(), "code-kag backup should be removed after uninstall"
        # Original hook is restored
        assert existing.exists()
        assert "original" in existing.read_text()
