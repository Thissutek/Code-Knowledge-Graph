"""
Security tests for hook manager: password not baked into common.sh.
"""
import pytest
from pathlib import Path

from src.hooks.hook_manager import HookManager, CODE_KAG_MARKER


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
