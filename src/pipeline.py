"""
ProcessingPipeline — high-level interface for indexing code repositories.

Wraps Neo4jIngester and CodebaseParser with a unified API that supports
three processing modes (AUTO, BATCH, INCREMENTAL) and git-native change
detection via --git-since.
"""
import logging
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional

_logger = logging.getLogger(__name__)


class ProcessingMode(Enum):
    AUTO = "auto"
    BATCH = "batch"
    INCREMENTAL = "incremental"


@dataclass
class PipelineResult:
    """Result returned by all ProcessingPipeline processing methods."""
    mode_used: ProcessingMode
    success: bool
    files_processed: int
    entities_processed: int
    relationships_processed: int
    duration: float
    errors: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


class ProcessingPipeline:
    """
    Unified pipeline for indexing code repositories into the knowledge graph.

    Supports three modes:
    - BATCH: full re-index (default for new repos or --force)
    - INCREMENTAL: re-index only changed files (requires changed_files list)
    - AUTO: batch if the repo isn't indexed yet, otherwise incremental

    Example usage::

        pipeline = ProcessingPipeline(
            repo_path="/path/to/repo",
            repo_id="my-project",
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="secret",
        )
        result = pipeline.process_directory()
        result = pipeline.process_git_changes(since_commit="HEAD~5")
    """

    def __init__(
        self,
        repo_path: str,
        repo_id: str,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        skip_embeddings: bool = False,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.repo_id = repo_id
        self._neo4j_uri = neo4j_uri
        self._neo4j_user = neo4j_user
        self._neo4j_password = neo4j_password
        self._skip_embeddings = skip_embeddings

    # ── Public API ─────────────────────────────────────────────────────────

    def process_directory(
        self, mode: ProcessingMode = ProcessingMode.AUTO
    ) -> PipelineResult:
        """Index all supported source files in *repo_path*.

        In AUTO mode, a full BATCH index is always performed (consistent with
        the existing ingest_repository behaviour which clears and re-indexes).
        """
        effective_mode = mode if mode != ProcessingMode.AUTO else ProcessingMode.BATCH
        return self._run_ingest(changed_files=None, mode=effective_mode)

    def process_git_changes(
        self, since_commit: str = "HEAD~1"
    ) -> PipelineResult:
        """Index only files changed in git since *since_commit*.

        Uses ``git diff --name-only <since_commit> HEAD`` to determine the
        changed file list, then runs an incremental index.
        """
        changed = self._get_git_changed_files(since_commit)
        if not changed:
            _logger.info("No changed files since %s", since_commit)
            return PipelineResult(
                mode_used=ProcessingMode.INCREMENTAL,
                success=True,
                files_processed=0,
                entities_processed=0,
                relationships_processed=0,
                duration=0.0,
                stats={"since_commit": since_commit},
            )
        _logger.info("Processing %d git-changed files since %s", len(changed), since_commit)
        result = self._run_ingest(changed_files=changed, mode=ProcessingMode.INCREMENTAL)
        result.stats["since_commit"] = since_commit
        result.stats["changed_files"] = changed
        return result

    def health_check(self) -> Dict[str, Any]:
        """Check Neo4j connectivity and whether the repo is indexed."""
        from .neo4j_ingester import CodeKAGQuerier
        status: Dict[str, Any] = {
            "neo4j": {"status": "unknown"},
            "repository": {"indexed": False},
        }
        try:
            q = CodeKAGQuerier(self._neo4j_uri, self._neo4j_user, self._neo4j_password)
            q.connect()
            q.driver.verify_connectivity()
            status["neo4j"]["status"] = "healthy"
            repos = q.list_repositories()
            for r in repos:
                if r.get("id") == self.repo_id:
                    status["repository"]["indexed"] = True
                    status["repository"]["file_count"] = r.get("fileCount", 0)
                    status["repository"]["function_count"] = r.get("functionCount", 0)
                    break
            q.close()
        except Exception as exc:
            status["neo4j"]["status"] = "unhealthy"
            status["neo4j"]["error"] = str(exc)
        return status

    # ── Internals ──────────────────────────────────────────────────────────

    def _run_ingest(
        self, changed_files: Optional[List[str]], mode: ProcessingMode
    ) -> PipelineResult:
        from .neo4j_ingester import ingest_repository

        start = time.time()
        try:
            stats = ingest_repository(
                repo_path=str(self.repo_path),
                repo_id=self.repo_id,
                neo4j_uri=self._neo4j_uri,
                neo4j_user=self._neo4j_user,
                neo4j_password=self._neo4j_password,
                incremental=(mode == ProcessingMode.INCREMENTAL),
                changed_files=changed_files,
                skip_embeddings=self._skip_embeddings,
            )
            duration = time.time() - start
            entities = (
                stats.get("classes_ingested", 0)
                + stats.get("functions_ingested", 0)
                + stats.get("interfaces_ingested", 0)
            )
            return PipelineResult(
                mode_used=mode,
                success=True,
                files_processed=stats.get("files_ingested", 0),
                entities_processed=entities,
                relationships_processed=stats.get("relationships_ingested", 0),
                duration=duration,
                stats=stats,
            )
        except Exception as exc:
            _logger.error("Ingestion failed: %s", exc)
            return PipelineResult(
                mode_used=mode,
                success=False,
                files_processed=0,
                entities_processed=0,
                relationships_processed=0,
                duration=time.time() - start,
                errors=[str(exc)],
            )

    def _get_git_changed_files(self, since_commit: str) -> List[str]:
        """Run git diff --name-only and return a list of changed file paths."""
        try:
            proc = subprocess.run(
                ["git", "diff", "--name-only", since_commit, "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(self.repo_path),
                timeout=30,
            )
            if proc.returncode != 0:
                _logger.warning("git diff failed: %s", proc.stderr.strip())
                return []
            files = [f.strip() for f in proc.stdout.splitlines() if f.strip()]
            # Also include untracked staged files (git diff --cached)
            proc2 = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                capture_output=True,
                text=True,
                cwd=str(self.repo_path),
                timeout=30,
            )
            if proc2.returncode == 0:
                staged = [f.strip() for f in proc2.stdout.splitlines() if f.strip()]
                files = list(dict.fromkeys(files + staged))  # deduplicate, preserve order
            return files
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            _logger.warning("Could not run git diff: %s", exc)
            return []
