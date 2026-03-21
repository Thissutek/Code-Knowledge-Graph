"""Tests for src/pipeline.py — ProcessingPipeline."""
from unittest.mock import MagicMock, patch

from src.pipeline import PipelineResult, ProcessingMode, ProcessingPipeline

# ingest_repository and CodeKAGQuerier are imported lazily inside methods,
# so we patch them at their source module.
_INGEST = "src.neo4j_ingester.ingest_repository"
_QUERIER = "src.neo4j_ingester.CodeKAGQuerier"


# ---------------------------------------------------------------------------
# PipelineResult
# ---------------------------------------------------------------------------

class TestPipelineResult:
    def test_defaults(self):
        r = PipelineResult(
            mode_used=ProcessingMode.BATCH,
            success=True,
            files_processed=5,
            entities_processed=10,
            relationships_processed=3,
            duration=1.23,
        )
        assert r.errors == []
        assert r.stats == {}

    def test_with_errors(self):
        r = PipelineResult(
            mode_used=ProcessingMode.INCREMENTAL,
            success=False,
            files_processed=0,
            entities_processed=0,
            relationships_processed=0,
            duration=0.1,
            errors=["Something went wrong"],
        )
        assert r.success is False
        assert len(r.errors) == 1


# ---------------------------------------------------------------------------
# ProcessingMode
# ---------------------------------------------------------------------------

class TestProcessingMode:
    def test_values(self):
        assert ProcessingMode.AUTO.value == "auto"
        assert ProcessingMode.BATCH.value == "batch"
        assert ProcessingMode.INCREMENTAL.value == "incremental"


# ---------------------------------------------------------------------------
# ProcessingPipeline.process_directory
# ---------------------------------------------------------------------------

class TestProcessDirectory:
    def _make_pipeline(self, tmp_path):
        return ProcessingPipeline(
            repo_path=str(tmp_path),
            repo_id="test-repo",
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
        )

    def _fake_stats(self, files=3, classes=2, funcs=5, ifaces=0, rels=4):
        return {
            "files_ingested": files,
            "classes_ingested": classes,
            "functions_ingested": funcs,
            "interfaces_ingested": ifaces,
            "relationships_ingested": rels,
        }

    def test_auto_mode_runs_batch(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        fake_stats = self._fake_stats()
        with patch(_INGEST, return_value=fake_stats) as mock_ingest:
            result = pipeline.process_directory()

        assert result.mode_used == ProcessingMode.BATCH
        assert result.success is True
        assert result.files_processed == 3
        assert result.entities_processed == 7  # 2 + 5 + 0
        assert result.relationships_processed == 4
        mock_ingest.assert_called_once()
        call_kwargs = mock_ingest.call_args[1]
        assert call_kwargs["incremental"] is False

    def test_batch_mode_explicit(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        with patch(_INGEST, return_value=self._fake_stats(files=1, classes=0, funcs=1, rels=0)):
            result = pipeline.process_directory(mode=ProcessingMode.BATCH)

        assert result.mode_used == ProcessingMode.BATCH

    def test_incremental_mode(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        with patch(_INGEST, return_value=self._fake_stats(files=1, classes=0, funcs=1, rels=0)):
            result = pipeline.process_directory(mode=ProcessingMode.INCREMENTAL)

        assert result.mode_used == ProcessingMode.INCREMENTAL

    def test_ingest_failure_returns_error_result(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        with patch(_INGEST, side_effect=RuntimeError("DB down")):
            result = pipeline.process_directory()

        assert result.success is False
        assert "DB down" in result.errors[0]
        assert result.files_processed == 0

    def test_duration_is_non_negative(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        with patch(_INGEST, return_value=self._fake_stats(files=0, classes=0, funcs=0, rels=0)):
            result = pipeline.process_directory()

        assert result.duration >= 0.0

    def test_skip_embeddings_passed_through(self, tmp_path):
        pipeline = ProcessingPipeline(
            repo_path=str(tmp_path),
            repo_id="test-repo",
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
            skip_embeddings=True,
        )
        with patch(_INGEST, return_value=self._fake_stats(files=0, classes=0, funcs=0, rels=0)) as mock_ingest:
            pipeline.process_directory()

        call_kwargs = mock_ingest.call_args[1]
        assert call_kwargs["skip_embeddings"] is True


# ---------------------------------------------------------------------------
# ProcessingPipeline.process_git_changes
# ---------------------------------------------------------------------------

class TestProcessGitChanges:
    def _make_pipeline(self, tmp_path):
        return ProcessingPipeline(
            repo_path=str(tmp_path),
            repo_id="test-repo",
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
        )

    def test_no_changed_files_returns_early(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        with patch.object(pipeline, "_get_git_changed_files", return_value=[]):
            result = pipeline.process_git_changes(since_commit="HEAD~1")

        assert result.success is True
        assert result.files_processed == 0
        assert result.mode_used == ProcessingMode.INCREMENTAL
        assert result.stats["since_commit"] == "HEAD~1"

    def test_changed_files_triggers_incremental(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)
        changed = ["src/foo.py", "src/bar.py"]
        fake_stats = {"files_ingested": 2, "classes_ingested": 1, "functions_ingested": 3,
                      "interfaces_ingested": 0, "relationships_ingested": 2}

        with patch.object(pipeline, "_get_git_changed_files", return_value=changed), \
             patch(_INGEST, return_value=fake_stats) as mock_ingest:
            result = pipeline.process_git_changes(since_commit="abc123")

        assert result.mode_used == ProcessingMode.INCREMENTAL
        assert result.success is True
        assert result.stats["since_commit"] == "abc123"
        assert result.stats["changed_files"] == changed
        call_kwargs = mock_ingest.call_args[1]
        assert call_kwargs["incremental"] is True
        assert call_kwargs["changed_files"] == changed


# ---------------------------------------------------------------------------
# ProcessingPipeline._get_git_changed_files
# ---------------------------------------------------------------------------

class TestGetGitChangedFiles:
    def _make_pipeline(self, tmp_path):
        return ProcessingPipeline(
            repo_path=str(tmp_path),
            repo_id="test-repo",
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
        )

    def test_returns_files_from_git_diff(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)

        mock_proc1 = MagicMock()
        mock_proc1.returncode = 0
        mock_proc1.stdout = "src/foo.py\nsrc/bar.py\n"

        mock_proc2 = MagicMock()
        mock_proc2.returncode = 0
        mock_proc2.stdout = ""

        with patch("src.pipeline.subprocess.run", side_effect=[mock_proc1, mock_proc2]):
            files = pipeline._get_git_changed_files("HEAD~1")

        assert files == ["src/foo.py", "src/bar.py"]

    def test_deduplicates_staged_and_unstaged(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)

        mock_proc1 = MagicMock()
        mock_proc1.returncode = 0
        mock_proc1.stdout = "src/foo.py\n"

        mock_proc2 = MagicMock()
        mock_proc2.returncode = 0
        mock_proc2.stdout = "src/foo.py\nsrc/bar.py\n"  # foo appears in both

        with patch("src.pipeline.subprocess.run", side_effect=[mock_proc1, mock_proc2]):
            files = pipeline._get_git_changed_files("HEAD~1")

        assert files == ["src/foo.py", "src/bar.py"]
        assert len(files) == 2  # no duplicate

    def test_git_diff_failure_returns_empty(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)

        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.stderr = "fatal: bad revision"

        with patch("src.pipeline.subprocess.run", return_value=mock_proc):
            files = pipeline._get_git_changed_files("BAD_COMMIT")

        assert files == []

    def test_file_not_found_returns_empty(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)

        with patch("src.pipeline.subprocess.run", side_effect=FileNotFoundError("git not found")):
            files = pipeline._get_git_changed_files("HEAD~1")

        assert files == []

    def test_timeout_returns_empty(self, tmp_path):
        import subprocess
        pipeline = self._make_pipeline(tmp_path)

        with patch("src.pipeline.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            files = pipeline._get_git_changed_files("HEAD~1")

        assert files == []


# ---------------------------------------------------------------------------
# ProcessingPipeline.health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def _make_pipeline(self, tmp_path):
        return ProcessingPipeline(
            repo_path=str(tmp_path),
            repo_id="test-repo",
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
        )

    def test_healthy_indexed_repo(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)

        mock_querier = MagicMock()
        mock_querier.list_repositories.return_value = [
            {"id": "test-repo", "fileCount": 10, "functionCount": 25}
        ]

        with patch(_QUERIER, return_value=mock_querier):
            status = pipeline.health_check()

        assert status["neo4j"]["status"] == "healthy"
        assert status["repository"]["indexed"] is True
        assert status["repository"]["file_count"] == 10

    def test_unhealthy_neo4j(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)

        with patch(_QUERIER, side_effect=Exception("Connection refused")):
            status = pipeline.health_check()

        assert status["neo4j"]["status"] == "unhealthy"
        assert "error" in status["neo4j"]

    def test_repo_not_indexed(self, tmp_path):
        pipeline = self._make_pipeline(tmp_path)

        mock_querier = MagicMock()
        mock_querier.list_repositories.return_value = []

        with patch(_QUERIER, return_value=mock_querier):
            status = pipeline.health_check()

        assert status["neo4j"]["status"] == "healthy"
        assert status["repository"]["indexed"] is False
