"""
Tests for Neo4j ingester — unit-level tests that don't require a running Neo4j.
Integration tests with a real Neo4j are in test_integration.py.
"""
from unittest.mock import MagicMock, patch, call
from typing import List

from src.models import (
    ParsedCodebase, Repository, File, Module, Class, Function,
    Variable, Import, Relationship,
)
from src.neo4j_ingester import Neo4jIngester


def _make_codebase(repo_id: str = "test-repo") -> ParsedCodebase:
    """Build a minimal ParsedCodebase for testing."""
    repo = Repository(id=repo_id, name="test", path="/tmp/test")
    cb = ParsedCodebase(repository=repo)
    cb.files.append(File(id="src/main.py", name="main.py", path="src/main.py",
                         extension=".py", language="Python",
                         lines_of_code=10, content_hash="abc"))
    cb.classes.append(Class(id="src/main.py:Foo", name="Foo",
                            docstring="A class", start_line=1, end_line=10,
                            language_type="class"))
    cb.functions.append(Function(id="src/main.py:bar", name="bar",
                                 signature="(x: int)", start_line=12,
                                 end_line=14, complexity=1))
    cb.variables.append(Variable(id="src/main.py:MAX", name="MAX",
                                 is_constant=True, scope="global"))
    cb.imports.append(Import(id="src/main.py:import:os", name="os",
                             source="os", is_external=True))
    cb.modules.append(Module(id="src", name="src", path="src",
                             module_type="package"))
    cb.add_relationship("CONTAINS_FILE", repo_id, "src/main.py")
    cb.add_relationship("DEFINES_CLASS", "src/main.py", "src/main.py:Foo")
    return cb


# ── Neo4jIngester.ingest ────────────────────────────────────────────────────

class TestIngest:
    def test_calls_all_ingestion_steps(self):
        ingester = Neo4jIngester.__new__(Neo4jIngester)
        mock_session = MagicMock()
        ingester.driver = MagicMock()
        ingester.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        ingester.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        ingester.clear_repository = MagicMock()

        cb = _make_codebase()
        ingester.ingest(cb, clear_existing=True)

        ingester.clear_repository.assert_called_once_with("test-repo")
        # session.run should be called multiple times for batched ingestion
        assert mock_session.run.call_count >= 5  # repo, files, modules, classes, functions, ...

    def test_ingest_without_clearing(self):
        ingester = Neo4jIngester.__new__(Neo4jIngester)
        mock_session = MagicMock()
        ingester.driver = MagicMock()
        ingester.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        ingester.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        ingester.clear_repository = MagicMock()

        cb = _make_codebase()
        ingester.ingest(cb, clear_existing=False)

        ingester.clear_repository.assert_not_called()


# ── Neo4jIngester.ingest_incremental ────────────────────────────────────────

class TestIngestIncremental:
    def test_clears_specified_files_then_ingests(self):
        ingester = Neo4jIngester.__new__(Neo4jIngester)
        mock_session = MagicMock()
        ingester.driver = MagicMock()
        ingester.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        ingester.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        cb = _make_codebase()
        changed = ["src/main.py"]
        ingester.ingest_incremental(cb, changed)

        # Should have called session.run for _clear_file_entities query
        calls = mock_session.run.call_args_list
        clear_calls = [c for c in calls if "DETACH DELETE" in str(c)]
        assert len(clear_calls) >= 1

        # Should also have normal ingestion calls
        merge_calls = [c for c in calls if "MERGE" in str(c)]
        assert len(merge_calls) >= 3  # repo, files, classes etc.

    def test_clears_multiple_files(self):
        ingester = Neo4jIngester.__new__(Neo4jIngester)
        mock_session = MagicMock()
        ingester.driver = MagicMock()
        ingester.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        ingester.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        cb = _make_codebase()
        changed = ["src/main.py", "src/util.py"]
        ingester.ingest_incremental(cb, changed)

        calls = mock_session.run.call_args_list
        clear_calls = [c for c in calls if "DETACH DELETE" in str(c)]
        assert len(clear_calls) >= 2


# ── _ingest_classes includes languageType ───────────────────────────────────

class TestIngestClasses:
    def test_language_type_in_cypher(self):
        ingester = Neo4jIngester.__new__(Neo4jIngester)
        mock_session = MagicMock()

        cb = _make_codebase()
        ingester._ingest_classes(mock_session, cb)

        # The UNWIND query should reference languageType
        call_args = mock_session.run.call_args
        query = call_args[0][0]
        assert "languageType" in query


# ── ingest_repository convenience function ──────────────────────────────────

class TestIngestRepositoryFunction:
    @patch("src.neo4j_ingester.Neo4jIngester")
    @patch("src.parser.CodebaseParser")
    def test_full_mode(self, MockParser, MockIngester):
        from src.neo4j_ingester import ingest_repository

        mock_parser_inst = MagicMock()
        mock_parser_inst.parse.return_value = _make_codebase()
        MockParser.return_value = mock_parser_inst

        mock_ingester_inst = MagicMock()
        MockIngester.return_value = mock_ingester_inst

        stats = ingest_repository("/tmp/repo", repo_id="r1",
                                  neo4j_uri="bolt://x", neo4j_user="u",
                                  neo4j_password="p")

        mock_parser_inst.parse.assert_called_once()
        mock_ingester_inst.ingest.assert_called_once()
        assert "files" in stats

    @patch("src.neo4j_ingester.Neo4jIngester")
    @patch("src.parser.CodebaseParser")
    def test_incremental_mode(self, MockParser, MockIngester):
        from src.neo4j_ingester import ingest_repository

        mock_parser_inst = MagicMock()
        mock_parser_inst.parse_incremental.return_value = _make_codebase()
        MockParser.return_value = mock_parser_inst

        mock_ingester_inst = MagicMock()
        MockIngester.return_value = mock_ingester_inst

        stats = ingest_repository("/tmp/repo", repo_id="r1",
                                  incremental=True,
                                  changed_files=["a.py"])

        mock_parser_inst.parse_incremental.assert_called_once_with(["a.py"])
        mock_ingester_inst.ingest_incremental.assert_called_once()
        assert "files" in stats
