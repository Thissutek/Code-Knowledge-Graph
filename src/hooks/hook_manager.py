"""
Hook Manager
Installs and uninstalls code-kag git hooks into target repositories.
"""
import os
import re
import stat
import shutil
from pathlib import Path
from typing import Optional


HOOK_NAMES = ['post-commit', 'post-merge', 'post-checkout', 'post-rewrite']
# Pattern for safe shell variable values (alphanumeric, dash, underscore, dot, colon, slash)
_SAFE_SHELL_VALUE = re.compile(r'^[a-zA-Z0-9._/:@\-]+$')
TEMPLATES_DIR = Path(__file__).parent / 'templates'
CODE_KAG_MARKER = '# code-kag-hook'


class HookManager:
    """Manages installation and removal of code-kag git hooks."""

    def __init__(self, code_kag_path: Optional[str] = None):
        self.code_kag_path = code_kag_path or str(
            Path(__file__).parent.parent.parent.resolve())

    def install(self, repo_path: str, repo_id: Optional[str] = None,
                mode: str = 'incremental',
                neo4j_uri: str = 'bolt://localhost:7687',
                neo4j_user: str = 'neo4j',
                neo4j_password: str = 'password'):
        """Install code-kag hooks into a git repository.

        Args:
            repo_path: Path to the git repository.
            repo_id: Repository identifier (defaults to directory name).
            mode: 'incremental' or 'full' re-indexing mode.
            neo4j_uri: Neo4j connection URI.
            neo4j_user: Neo4j username.
            neo4j_password: Neo4j password.
        """
        repo = Path(repo_path).resolve()
        hooks_dir = repo / '.git' / 'hooks'

        if not hooks_dir.exists():
            raise FileNotFoundError(
                f"Not a git repository (no .git/hooks): {repo}")

        if repo_id is None:
            repo_id = repo.name

        # Validate values against shell injection
        for name, value in [('repo_id', repo_id), ('mode', mode),
                            ('neo4j_uri', neo4j_uri),
                            ('neo4j_user', neo4j_user),
                            ('neo4j_password', neo4j_password),
                            ('code_kag_path', self.code_kag_path)]:
            if not _SAFE_SHELL_VALUE.match(value):
                raise ValueError(
                    f"Unsafe characters in {name}: {value!r}. "
                    f"Only alphanumeric, dash, underscore, dot, colon, "
                    f"slash, and @ are allowed.")

        # Install common.sh with placeholders filled in
        common_template = (TEMPLATES_DIR / 'common.sh').read_text()
        common_content = (
            common_template
            .replace('{{CODE_KAG_PATH}}', self.code_kag_path)
            .replace('{{REPO_ID}}', repo_id)
            .replace('{{MODE}}', mode)
            .replace('{{NEO4J_URI}}', neo4j_uri)
            .replace('{{NEO4J_USER}}', neo4j_user)
            .replace('{{NEO4J_PASSWORD}}', neo4j_password)
        )
        common_dest = hooks_dir / 'code-kag-common.sh'
        common_dest.write_text(common_content)
        self._make_executable(common_dest)

        # Install each hook
        for hook_name in HOOK_NAMES:
            template_path = TEMPLATES_DIR / f'{hook_name}.sh'
            if not template_path.exists():
                continue

            hook_content = template_path.read_text()
            hook_dest = hooks_dir / hook_name

            if hook_dest.exists():
                existing = hook_dest.read_text()
                if CODE_KAG_MARKER in existing:
                    # Already installed, update in place
                    backup = hooks_dir / f'{hook_name}.pre-code-kag'
                    if backup.exists():
                        # Preserve the chaining wrapper
                        wrapper = f"""#!/usr/bin/env bash
{CODE_KAG_MARKER}
# This hook chains the original hook with code-kag.

# Run original hook first
if [ -f "$(dirname "$0")/{hook_name}.pre-code-kag" ]; then
    "$(dirname "$0")/{hook_name}.pre-code-kag" "$@"
fi

# Run code-kag hook
{hook_content}
"""
                        hook_dest.write_text(wrapper)
                    else:
                        hook_dest.write_text(
                            f'#!/usr/bin/env bash\n{CODE_KAG_MARKER}\n{hook_content}')
                    self._make_executable(hook_dest)
                    continue

                # Preserve existing hook by renaming
                backup = hooks_dir / f'{hook_name}.pre-code-kag'
                shutil.copy2(str(hook_dest), str(backup))
                print(f"  Backed up existing {hook_name} -> {hook_name}.pre-code-kag")

                # Write wrapper that calls both
                wrapper = f"""#!/usr/bin/env bash
{CODE_KAG_MARKER}
# This hook chains the original hook with code-kag.

# Run original hook first
if [ -f "$(dirname "$0")/{hook_name}.pre-code-kag" ]; then
    "$(dirname "$0")/{hook_name}.pre-code-kag" "$@"
fi

# Run code-kag hook
{hook_content}
"""
                hook_dest.write_text(wrapper)
            else:
                hook_dest.write_text(
                    f'#!/usr/bin/env bash\n{CODE_KAG_MARKER}\n{hook_content}')

            self._make_executable(hook_dest)
            print(f"  Installed {hook_name} hook")

        print(f"Code-KAG hooks installed in {repo}")
        print(f"  Mode: {mode}, Repo ID: {repo_id}")

    def uninstall(self, repo_path: str):
        """Remove code-kag hooks from a git repository.

        Restores any previously backed-up hooks.
        """
        repo = Path(repo_path).resolve()
        hooks_dir = repo / '.git' / 'hooks'

        if not hooks_dir.exists():
            raise FileNotFoundError(
                f"Not a git repository (no .git/hooks): {repo}")

        # Remove common.sh
        common_file = hooks_dir / 'code-kag-common.sh'
        if common_file.exists():
            common_file.unlink()
            print("  Removed code-kag-common.sh")

        # Remove or restore each hook
        for hook_name in HOOK_NAMES:
            hook_path = hooks_dir / hook_name
            backup_path = hooks_dir / f'{hook_name}.pre-code-kag'

            if hook_path.exists():
                content = hook_path.read_text()
                if CODE_KAG_MARKER in content:
                    hook_path.unlink()
                    print(f"  Removed {hook_name} hook")

                    # Restore backup if it exists
                    if backup_path.exists():
                        shutil.move(str(backup_path), str(hook_path))
                        print(f"  Restored {hook_name} from backup")

            # Clean up any leftover backups
            if backup_path.exists():
                backup_path.unlink()

        print(f"Code-KAG hooks uninstalled from {repo}")

    @staticmethod
    def _make_executable(path: Path):
        """Make a file executable."""
        current = path.stat().st_mode
        path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
