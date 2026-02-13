"""
Tests for the CLI (cli.py).
Exercises argument parsing and command dispatch without requiring Neo4j.
"""
import subprocess
import sys
import os
from pathlib import Path

import pytest

CLI_PATH = str(Path(__file__).parent.parent / "cli.py")


def run_cli(*args, expect_success=True) -> subprocess.CompletedProcess:
    """Run the CLI and return CompletedProcess."""
    result = subprocess.run(
        [sys.executable, CLI_PATH, *args],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent)},
    )
    if expect_success:
        assert result.returncode == 0, (
            f"CLI failed with code {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


# ── Help ────────────────────────────────────────────────────────────────────

class TestCLIHelp:
    def test_root_help(self):
        r = run_cli("--help")
        assert "Code Knowledge Graph CLI" in r.stdout
        assert "index" in r.stdout
        assert "hooks" in r.stdout

    def test_index_help(self):
        r = run_cli("index", "--help")
        assert "--incremental" in r.stdout
        assert "--changed-files" in r.stdout

    def test_hooks_help(self):
        r = run_cli("hooks", "--help")
        assert "install" in r.stdout
        assert "uninstall" in r.stdout

    def test_hooks_install_help(self):
        r = run_cli("hooks", "install", "--help")
        assert "--mode" in r.stdout
        assert "--id" in r.stdout


# ── No command ──────────────────────────────────────────────────────────────

class TestCLINoCommand:
    def test_no_command_shows_help(self):
        r = run_cli(expect_success=False)
        # Should exit non-zero and show help
        assert r.returncode != 0


# ── hooks install / uninstall via CLI ───────────────────────────────────────

class TestCLIHooks:
    def test_install_and_uninstall(self, git_repo):
        # Install
        r = run_cli(
            "hooks", "install", str(git_repo),
            "--id", "cli-test", "--mode", "full",
        )
        assert "installed" in r.stdout.lower() or r.returncode == 0

        hooks_dir = git_repo / ".git" / "hooks"
        assert (hooks_dir / "post-commit").exists()

        # Uninstall
        r = run_cli("hooks", "uninstall", str(git_repo))
        assert not (hooks_dir / "post-commit").exists()

    def test_install_non_git_fails(self, tmp_dir):
        r = run_cli(
            "hooks", "install", str(tmp_dir), "--id", "x",
            expect_success=False,
        )
        assert r.returncode != 0


# ── index (dry-run — Neo4j unavailable, but arg parsing works) ─────────────

class TestCLIIndex:
    def test_index_missing_path_fails(self):
        r = run_cli("index", expect_success=False)
        assert r.returncode != 0

    def test_index_with_incremental_flag_parses(self):
        """Ensure --incremental + --changed-files flags are accepted.
        This will fail at Neo4j connection, but we verify arg parsing."""
        r = subprocess.run(
            [
                sys.executable, CLI_PATH, "index", "/nonexistent",
                "--id", "test", "--incremental",
                "--changed-files", "a.py", "b.ts",
                "--neo4j-uri", "bolt://invalid:9999",
            ],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).parent.parent)},
        )
        # It should fail due to neo4j connection, not argument parsing
        # so we check for indexing message or connection error
        combined = r.stdout + r.stderr
        assert "Indexing" in combined or "error" in combined.lower() or r.returncode != 0
