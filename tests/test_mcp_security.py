"""
Security tests for hook manager: uninstall does not delete foreign backups.
"""
import os
import stat
import pytest
from pathlib import Path

from src.hooks.hook_manager import HookManager, CODE_KAG_MARKER


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
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")
        backup = hooks_dir / "post-commit.pre-code-kag"
        assert backup.exists()

        hm.uninstall(str(git_repo))
        assert not backup.exists(), "code-kag backup should be removed after uninstall"
        # Original hook is restored
        assert existing.exists()
        assert "original" in existing.read_text()
