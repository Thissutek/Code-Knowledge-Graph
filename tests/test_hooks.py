"""
Tests for the git hooks system (install / uninstall / templates).
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

from src.hooks.hook_manager import HookManager, HOOK_NAMES, CODE_KAG_MARKER


# ── HookManager.install ────────────────────────────────────────────────────

class TestHookInstall:
    def test_installs_all_hooks(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")

        hooks_dir = git_repo / ".git" / "hooks"
        for name in HOOK_NAMES:
            assert (hooks_dir / name).exists(), f"{name} not installed"

    def test_common_script_installed(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")

        common = git_repo / ".git" / "hooks" / "code-kag-common.sh"
        assert common.exists()

    def test_hooks_are_executable(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")

        hooks_dir = git_repo / ".git" / "hooks"
        for name in HOOK_NAMES:
            hook = hooks_dir / name
            assert os.access(str(hook), os.X_OK), f"{name} not executable"

    def test_common_sh_has_placeholders_filled(self, git_repo):
        hm = HookManager()
        hm.install(
            str(git_repo), repo_id="my-proj",
            mode="full", neo4j_uri="bolt://db:7687",
            neo4j_password="testpass",
        )

        common = (git_repo / ".git" / "hooks" / "code-kag-common.sh").read_text()
        assert "my-proj" in common
        assert "full" in common
        assert "bolt://db:7687" in common
        assert "{{" not in common  # No unfilled placeholders

    def test_default_repo_id_is_dirname(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), neo4j_password="testpass")

        common = (git_repo / ".git" / "hooks" / "code-kag-common.sh").read_text()
        assert git_repo.name in common

    def test_preserves_existing_hook(self, git_repo):
        hooks_dir = git_repo / ".git" / "hooks"
        existing = hooks_dir / "post-commit"
        existing.write_text("#!/bin/sh\necho original\n")
        existing.chmod(existing.stat().st_mode | stat.S_IXUSR)

        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")

        # Backup should exist
        backup = hooks_dir / "post-commit.pre-code-kag"
        assert backup.exists()
        assert "original" in backup.read_text()

        # New hook should chain the original
        new_content = existing.read_text()
        assert CODE_KAG_MARKER in new_content
        assert "pre-code-kag" in new_content

    def test_reinstall_updates_existing_code_kag_hook(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="v1", neo4j_password="testpass")

        # Install again with different repo_id
        hm.install(str(git_repo), repo_id="v2", neo4j_password="testpass")

        common = (git_repo / ".git" / "hooks" / "code-kag-common.sh").read_text()
        assert "v2" in common

    def test_raises_for_non_git_dir(self, tmp_dir):
        hm = HookManager()
        with pytest.raises(FileNotFoundError, match="Not a git repository"):
            hm.install(str(tmp_dir), repo_id="x", neo4j_password="testpass")


# ── HookManager.uninstall ──────────────────────────────────────────────────

class TestHookUninstall:
    def test_removes_all_hooks(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")
        hm.uninstall(str(git_repo))

        hooks_dir = git_repo / ".git" / "hooks"
        for name in HOOK_NAMES:
            assert not (hooks_dir / name).exists(), f"{name} still present"
        assert not (hooks_dir / "code-kag-common.sh").exists()

    def test_restores_original_hook(self, git_repo):
        hooks_dir = git_repo / ".git" / "hooks"
        existing = hooks_dir / "post-commit"
        existing.write_text("#!/bin/sh\necho original\n")
        existing.chmod(existing.stat().st_mode | stat.S_IXUSR)

        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")
        hm.uninstall(str(git_repo))

        restored = hooks_dir / "post-commit"
        assert restored.exists()
        assert "original" in restored.read_text()

        backup = hooks_dir / "post-commit.pre-code-kag"
        assert not backup.exists()

    def test_uninstall_idempotent(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")
        hm.uninstall(str(git_repo))
        hm.uninstall(str(git_repo))  # Should not raise

    def test_raises_for_non_git_dir(self, tmp_dir):
        hm = HookManager()
        with pytest.raises(FileNotFoundError, match="Not a git repository"):
            hm.uninstall(str(tmp_dir))


# ── Hook template content ──────────────────────────────────────────────────

class TestHookTemplates:
    def test_post_commit_references_common(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")

        content = (git_repo / ".git" / "hooks" / "post-commit").read_text()
        assert "code-kag-common.sh" in content

    def test_post_commit_uses_diff_tree(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")

        content = (git_repo / ".git" / "hooks" / "post-commit").read_text()
        assert "git diff-tree" in content
        assert "HEAD" in content

    def test_post_merge_uses_orig_head(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")

        content = (git_repo / ".git" / "hooks" / "post-merge").read_text()
        assert "ORIG_HEAD" in content

    def test_post_checkout_checks_flag(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")

        content = (git_repo / ".git" / "hooks" / "post-checkout").read_text()
        # Should only re-index on branch switch (flag=1)
        assert '"1"' in content or "'1'" in content or "= 1" in content

    def test_post_rewrite_uses_full_mode(self, git_repo):
        hm = HookManager()
        hm.install(str(git_repo), repo_id="test", neo4j_password="testpass")

        content = (git_repo / ".git" / "hooks" / "post-rewrite").read_text()
        assert "full" in content.lower()
