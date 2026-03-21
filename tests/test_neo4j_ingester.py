"""
Tests for Neo4j ingester — unit-level tests that don't require a running Neo4j.
Integration tests with a real Neo4j are in test_integration.py.
"""
from unittest.mock import MagicMock, patch, call
from typing import List

import pytest

from src.models import (
    ParsedCodebase, Repository, File, Module, Class, Function,
    Variable, Import, Relationship,
)
from src.neo4j_ingester import Neo4jIngester, CodeKAGQuerier


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


# ═══════════════════════════════════════════════════════════════════════════
# CodeKAGQuerier tests
# ═══════════════════════════════════════════════════════════════════════════

def _make_querier(password="secret"):
    """Create a CodeKAGQuerier with a mocked driver."""
    q = CodeKAGQuerier(uri="bolt://fake:7687", username="neo4j", password=password)
    q.driver = MagicMock()
    return q


def _mock_session(querier, records):
    """Configure the querier's mock driver to return *records* from session.run()."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(records))
    mock_result.single.return_value = records[0] if records else None
    mock_session.run.return_value = mock_result
    querier.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    querier.driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return mock_session


# ── connect / close ────────────────────────────────────────────────────────

class TestQuerierConnect:
    def test_connect_requires_password(self):
        q = CodeKAGQuerier(password=None)
        # Clear env var influence
        q.password = None
        with pytest.raises(ValueError, match="password"):
            q.connect()

    @patch("src.neo4j_ingester.GraphDatabase")
    def test_connect_creates_driver(self, MockGD):
        mock_driver = MagicMock()
        MockGD.driver.return_value = mock_driver
        q = CodeKAGQuerier(password="pw")
        q.connect()
        MockGD.driver.assert_called_once()
        assert q.driver is mock_driver

    def test_close_calls_driver_close(self):
        q = _make_querier()
        q.close()
        q.driver.close.assert_called_once()

    def test_close_without_driver_is_safe(self):
        q = CodeKAGQuerier(password="pw")
        q.driver = None
        q.close()  # should not raise


# ── search_functions ───────────────────────────────────────────────────────

class TestQuerierSearchFunctions:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"id": "f1", "name": "foo", "signature": "()", "docstring": "d", "score": 1.0}
        sess = _mock_session(q, [rec])
        result = q.search_functions("foo")
        query = sess.run.call_args[0][0]
        assert "function_docstring" in query
        assert "$searchTerm" in query
        assert len(result) == 1
        assert result[0]["name"] == "foo"

    def test_with_repo_id(self):
        q = _make_querier()
        rec = {"id": "f1", "name": "foo", "signature": "()", "docstring": "d", "score": 1.0}
        sess = _mock_session(q, [rec])
        result = q.search_functions("foo", repo_id="r1")
        query = sess.run.call_args[0][0]
        assert "$repo_id" in query
        assert len(result) == 1


# ── search_classes ─────────────────────────────────────────────────────────

class TestQuerierSearchClasses:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"id": "c1", "name": "Foo", "docstring": "d", "score": 1.0}
        sess = _mock_session(q, [rec])
        result = q.search_classes("Foo")
        query = sess.run.call_args[0][0]
        assert "class_docstring" in query
        assert len(result) == 1

    def test_with_repo_id(self):
        q = _make_querier()
        sess = _mock_session(q, [{"id": "c1", "name": "Foo", "docstring": "", "score": 0.5}])
        q.search_classes("Foo", repo_id="r1")
        query = sess.run.call_args[0][0]
        assert "$repo_id" in query


# ── find_function_by_name ──────────────────────────────────────────────────

class TestQuerierFindFunction:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"id": "f1", "name": "bar", "signature": "()", "docstring": "",
               "startLine": 1, "filePath": "a.py", "className": None}
        sess = _mock_session(q, [rec])
        result = q.find_function_by_name("bar")
        query = sess.run.call_args[0][0]
        assert "Function" in query
        assert "$name" in query
        assert result[0]["name"] == "bar"

    def test_with_repo_id(self):
        q = _make_querier()
        sess = _mock_session(q, [{"id": "f1", "name": "bar", "signature": "()",
                                   "docstring": "", "startLine": 1,
                                   "filePath": "a.py", "className": None}])
        q.find_function_by_name("bar", repo_id="r1")
        query = sess.run.call_args[0][0]
        assert "$repo_id" in query


# ── find_class_by_name ─────────────────────────────────────────────────────

class TestQuerierFindClass:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"id": "c1", "name": "Foo", "docstring": "", "startLine": 1,
               "filePath": "a.py", "parentClasses": [], "methods": []}
        sess = _mock_session(q, [rec])
        result = q.find_class_by_name("Foo")
        query = sess.run.call_args[0][0]
        assert "Class" in query
        assert "$name" in query
        assert result[0]["name"] == "Foo"

    def test_with_repo_id(self):
        q = _make_querier()
        sess = _mock_session(q, [{"id": "c1", "name": "Foo", "docstring": "",
                                   "startLine": 1, "filePath": "a.py",
                                   "parentClasses": [], "methods": []}])
        q.find_class_by_name("Foo", repo_id="r1")
        query = sess.run.call_args[0][0]
        assert "$repo_id" in query


# ── get_function_callgraph ─────────────────────────────────────────────────

class TestQuerierCallGraph:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"sourceId": "f1", "sourceName": "foo", "calls": []}
        sess = _mock_session(q, [rec])
        result = q.get_function_callgraph("f1", depth=3)
        query = sess.run.call_args[0][0]
        assert "CALLS" in query
        assert "*1..3" in query  # depth interpolated
        assert result["sourceId"] == "f1"

    def test_with_repo_id(self):
        q = _make_querier()
        rec = {"sourceId": "f1", "sourceName": "foo", "calls": []}
        sess = _mock_session(q, [rec])
        q.get_function_callgraph("f1", repo_id="r1")
        query = sess.run.call_args[0][0]
        assert "$repo_id" in query

    def test_empty_result(self):
        q = _make_querier()
        sess = _mock_session(q, [])
        result = q.get_function_callgraph("nonexistent")
        assert result == {}


# ── get_callers ────────────────────────────────────────────────────────────

class TestQuerierGetCallers:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"id": "f2", "name": "bar", "signature": "()", "filePath": "src/bar.py", "startLine": 10}
        sess = _mock_session(q, [rec])
        result = q.get_callers("f1")
        query = sess.run.call_args[0][0]
        assert "CALLS" in query
        assert "$function_id" in query
        assert "$limit" in query
        assert result == [rec]

    def test_with_repo_id(self):
        q = _make_querier()
        rec = {"id": "f2", "name": "bar", "signature": "()", "filePath": "src/bar.py", "startLine": 10}
        sess = _mock_session(q, [rec])
        q.get_callers("f1", repo_id="r1")
        query = sess.run.call_args[0][0]
        assert "$repo_id" in query
        assert "Repository" in query

    def test_empty_result(self):
        q = _make_querier()
        _mock_session(q, [])
        result = q.get_callers("nonexistent")
        assert result == []

    def test_custom_limit(self):
        q = _make_querier()
        rec = {"id": "f2", "name": "bar", "signature": "()", "filePath": "src/bar.py", "startLine": 10}
        sess = _mock_session(q, [rec])
        q.get_callers("f1", limit=5)
        kwargs = sess.run.call_args[1]
        assert kwargs.get("limit") == 5


# ── get_class_hierarchy ────────────────────────────────────────────────────

class TestQuerierClassHierarchy:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"id": "c1", "name": "Foo", "ancestors": [], "descendants": []}
        sess = _mock_session(q, [rec])
        result = q.get_class_hierarchy("Foo")
        query = sess.run.call_args[0][0]
        assert "EXTENDS" in query
        assert "$class_name" in query
        assert result["name"] == "Foo"

    def test_with_repo_id(self):
        q = _make_querier()
        sess = _mock_session(q, [{"id": "c1", "name": "Foo",
                                   "ancestors": [], "descendants": []}])
        q.get_class_hierarchy("Foo", repo_id="r1")
        query = sess.run.call_args[0][0]
        assert "$repo_id" in query


# ── get_file_dependencies ──────────────────────────────────────────────────

class TestQuerierFileDeps:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"filePath": "a.py", "dependsOn": ["b.py"], "dependedBy": []}
        sess = _mock_session(q, [rec])
        result = q.get_file_dependencies("a.py")
        query = sess.run.call_args[0][0]
        assert "DEPENDS_ON" in query
        assert "$file_path" in query
        assert result["filePath"] == "a.py"

    def test_with_repo_id(self):
        q = _make_querier()
        sess = _mock_session(q, [{"filePath": "a.py", "dependsOn": [],
                                   "dependedBy": []}])
        q.get_file_dependencies("a.py", repo_id="r1")
        query = sess.run.call_args[0][0]
        assert "$repo_id" in query


# ── find_similar_functions ─────────────────────────────────────────────────

class TestQuerierSimilar:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"id": "f2", "name": "bar", "signature": "()", "commonCalls": 2,
               "similarity": 0.5}
        sess = _mock_session(q, [rec])
        result = q.find_similar_functions("f1")
        query = sess.run.call_args[0][0]
        assert "CALLS" in query
        assert "similarity" in query
        assert len(result) == 1

    def test_with_repo_id(self):
        q = _make_querier()
        sess = _mock_session(q, [{"id": "f2", "name": "bar", "signature": "()",
                                   "commonCalls": 1, "similarity": 0.3}])
        q.find_similar_functions("f1", repo_id="r1")
        query = sess.run.call_args[0][0]
        assert "$repo_id" in query


# ── get_code_context ───────────────────────────────────────────────────────

class TestQuerierContext:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"type": "function", "id": "f1", "name": "foo", "signature": "()",
               "docstring": "", "startLine": 1, "endLine": 5, "filePath": "a.py",
               "className": None, "calls": [], "calledBy": [], "usesClasses": []}
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([rec]))
        # list() is called on result
        mock_session.run.return_value = mock_result
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = q.get_code_context("f1")
        query = mock_session.run.call_args[0][0]
        assert "Function" in query
        assert "UNION" in query
        assert result["name"] == "foo"

    def test_with_repo_id(self):
        q = _make_querier()
        rec = {"type": "function", "id": "f1", "name": "foo", "signature": "()",
               "docstring": "", "startLine": 1, "endLine": 5, "filePath": "a.py",
               "className": None, "calls": [], "calledBy": [], "usesClasses": []}
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([rec]))
        mock_session.run.return_value = mock_result
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        q.get_code_context("f1", repo_id="r1")
        query = mock_session.run.call_args[0][0]
        assert "$repo_id" in query

    def test_empty_result(self):
        q = _make_querier()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = q.get_code_context("nonexistent")
        assert result == {}


# ── semantic_code_search ───────────────────────────────────────────────────

class TestQuerierSemanticSearch:
    def test_without_repo_id(self):
        q = _make_querier()
        mock_session = MagicMock()
        # Each call returns different records for functions, classes, files
        func_rec = {"type": "function", "id": "f1", "name": "foo",
                     "description": "", "location": "a.py", "startLine": 1}
        class_rec = {"type": "class", "id": "c1", "name": "Bar",
                      "description": "", "location": "a.py", "startLine": 10}
        file_rec = {"type": "file", "id": "a.py", "name": "a.py",
                     "description": "a.py", "location": "a.py", "startLine": 0}

        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                mock_result.__iter__ = MagicMock(return_value=iter([func_rec]))
            elif call_count[0] == 2:
                mock_result.__iter__ = MagicMock(return_value=iter([class_rec]))
            else:
                mock_result.__iter__ = MagicMock(return_value=iter([file_rec]))
            return mock_result

        mock_session.run.side_effect = side_effect
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = q.semantic_code_search("foo")
        assert mock_session.run.call_count == 3  # functions, classes, files
        assert len(result) == 3

    def test_with_repo_id(self):
        q = _make_querier()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        q.semantic_code_search("foo", repo_id="r1")
        # All three queries should contain repo_id
        for c in mock_session.run.call_args_list:
            query = c[0][0]
            assert "$repo_id" in query

    def test_limit_respected(self):
        q = _make_querier()
        mock_session = MagicMock()
        records = [{"type": "function", "id": f"f{i}", "name": f"fn{i}",
                     "description": "", "location": "a.py", "startLine": i}
                    for i in range(30)]

        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                mock_result.__iter__ = MagicMock(return_value=iter(records))
            else:
                mock_result.__iter__ = MagicMock(return_value=iter([]))
            return mock_result

        mock_session.run.side_effect = side_effect
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = q.semantic_code_search("foo", limit=5)
        assert len(result) <= 5


# ── handle_find_entry_points (filter logic) ────────────────────────────────

class TestFindEntryPointsFilters:
    """Test that handle_find_entry_points applies the correct Cypher filters."""

    def _run_handler(self, arguments):
        import asyncio
        from unittest.mock import patch, MagicMock
        from src.mcp_server import handle_find_entry_points

        q = _make_querier()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.mcp_server.get_querier", return_value=q):
            asyncio.run(handle_find_entry_points(arguments))
        return mock_session.run.call_args[0][0]  # the Cypher query string

    def test_default_excludes_test_files(self):
        query = self._run_handler({})
        assert "test" in query.lower()

    def test_exclude_test_files_false_omits_filter(self):
        query = self._run_handler({"exclude_test_files": False})
        # The test-exclusion clause should be absent
        assert "CONTAINS '/test'" not in query

    def test_path_prefix_added_when_provided(self):
        query = self._run_handler({"path_prefix": "cli"})
        assert "$path_prefix" in query

    def test_path_prefix_absent_when_empty(self):
        query = self._run_handler({"path_prefix": ""})
        assert "$path_prefix" not in query


# ── list_repositories ──────────────────────────────────────────────────────

class TestQuerierListRepositories:
    def test_returns_repo_list(self):
        q = _make_querier()
        rec = {"id": "repo1", "path": "/src", "fileCount": 10, "functionCount": 50, "classCount": 5}
        sess = _mock_session(q, [rec])
        result = q.list_repositories()
        query = sess.run.call_args[0][0]
        assert "Repository" in query
        assert result == [rec]

    def test_empty_graph(self):
        q = _make_querier()
        _mock_session(q, [])
        result = q.list_repositories()
        assert result == []


# ── remove_repository ──────────────────────────────────────────────────────

class TestQuerierRemoveRepository:
    def test_returns_false_when_not_found(self):
        q = _make_querier()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"n": 0}
        mock_session.run.return_value = mock_result
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)
        assert q.remove_repository("nonexistent") is False

    def test_returns_true_and_clears_when_found(self):
        q = _make_querier()
        mock_session = MagicMock()

        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_result = MagicMock()
            # First call: existence check — repo found
            mock_result.single.return_value = {"n": 1}
            mock_result.__iter__ = MagicMock(return_value=iter([]))
            return mock_result

        mock_session.run.side_effect = side_effect
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = q.remove_repository("repo1")
        assert result is True
        # clear_repository runs multiple DELETE statements
        assert mock_session.run.call_count > 1


# ── _link_tests_to_implementations ────────────────────────────────────────

class TestLinkTestsToImplementations:
    def test_cypher_uses_tests_relationship(self):
        ingester = Neo4jIngester.__new__(Neo4jIngester)
        mock_session = MagicMock()
        ingester._link_tests_to_implementations(mock_session, "repo1")
        query = mock_session.run.call_args[0][0]
        assert "TESTS" in query
        assert "$repo_id" in query
        assert "MERGE" in query

    def test_called_during_ingest(self):
        ingester = Neo4jIngester.__new__(Neo4jIngester)
        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock()
        ingester.driver = MagicMock()
        ingester.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        ingester.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        cb = _make_codebase("r1")

        with patch.object(ingester, "clear_repository"), \
             patch.object(ingester, "_ingest_repository"), \
             patch.object(ingester, "_ingest_files"), \
             patch.object(ingester, "_ingest_modules"), \
             patch.object(ingester, "_ingest_classes"), \
             patch.object(ingester, "_ingest_functions"), \
             patch.object(ingester, "_ingest_variables"), \
             patch.object(ingester, "_ingest_imports"), \
             patch.object(ingester, "_ingest_interfaces"), \
             patch.object(ingester, "_ingest_relationships"), \
             patch.object(ingester, "_link_tests_to_implementations") as mock_link:
            ingester.ingest(cb)
            mock_link.assert_called_once_with(mock_session, "r1")


# ── get_tests_for_function ─────────────────────────────────────────────────

class TestQuerierGetTestsForFunction:
    def test_without_repo_id(self):
        q = _make_querier()
        rec = {"id": "t1", "name": "test_parse", "signature": "()", "filePath": "tests/test_p.py", "startLine": 5}
        sess = _mock_session(q, [rec])
        result = q.get_tests_for_function("src/p.py:parse")
        query = sess.run.call_args[0][0]
        assert "TESTS" in query
        assert "$function_id" in query
        assert result == [rec]

    def test_with_repo_id(self):
        q = _make_querier()
        _mock_session(q, [])
        q.get_tests_for_function("src/p.py:parse", repo_id="r1")
        query = q.driver.session.return_value.__enter__.return_value.run.call_args[0][0]
        assert "$repo_id" in query

    def test_empty_result(self):
        q = _make_querier()
        _mock_session(q, [])
        result = q.get_tests_for_function("nonexistent")
        assert result == []


# ── semantic search (vector path) ─────────────────────────────────────────

class TestSemanticSearchVectorFallback:
    """Test that semantic_code_search falls back to substring when embeddings unavailable."""

    def test_fallback_to_substring_when_model_unavailable(self):
        """When _embed_texts returns [] (model absent), substring path is used."""
        q = _make_querier()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.neo4j_ingester._embed_texts", return_value=[]):
            q.semantic_code_search("authentication")
        query = mock_session.run.call_args[0][0]
        assert "CONTAINS" in query  # substring path used

    def test_vector_path_used_when_embedding_available(self):
        """When _embed_texts returns a vector, the vector index query is used."""
        q = _make_querier()
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result
        q.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        q.driver.session.return_value.__exit__ = MagicMock(return_value=False)

        fake_vector = [0.1] * 384
        with patch("src.neo4j_ingester._embed_texts", return_value=[fake_vector]):
            q.semantic_code_search("authentication")
        query = mock_session.run.call_args[0][0]
        assert "vector" in query.lower() or "queryNodes" in query


# ── skip_embeddings in ingest ──────────────────────────────────────────────

class TestSkipEmbeddings:
    def test_skip_embeddings_does_not_call_embed(self):
        ingester = Neo4jIngester.__new__(Neo4jIngester)
        ingester._skip_embeddings = True
        mock_session = MagicMock()
        mock_session.run.return_value = MagicMock()

        from src.models import Function
        fn = Function(id="f1", name="foo")
        cb = _make_codebase()
        cb.functions = [fn]

        with patch("src.neo4j_ingester._embed_texts") as mock_embed:
            ingester._ingest_functions(mock_session, cb)
            mock_embed.assert_not_called()


# ── find_dead_code ──────────────────────────────────────────────────────────

class TestFindDeadCode:
    def test_query_excludes_test_functions(self):
        q = _make_querier()
        _mock_session(q, [])
        q.find_dead_code()
        query = q.driver.session.return_value.__enter__.return_value.run.call_args[0][0]
        assert "CALLS" in query
        assert "test" in query.lower()

    def test_returns_results(self):
        q = _make_querier()
        rec = {"id": "src/a.py:foo", "name": "foo", "filePath": "src/a.py", "startLine": 1, "complexity": 2}
        sess = _mock_session(q, [rec])
        result = q.find_dead_code()
        assert result == [rec]

    def test_with_repo_id(self):
        q = _make_querier()
        _mock_session(q, [])
        q.find_dead_code(repo_id="r1")
        query = q.driver.session.return_value.__enter__.return_value.run.call_args[0][0]
        assert "$repo_id" in query


# ── analyze_change_impact ───────────────────────────────────────────────────

class TestAnalyzeChangeImpact:
    def test_query_uses_calls_traversal(self):
        q = _make_querier()
        _mock_session(q, [])
        q.analyze_change_impact("src/a.py:foo")
        query = q.driver.session.return_value.__enter__.return_value.run.call_args[0][0]
        assert "CALLS" in query
        assert "$function_id" in query

    def test_returns_affected_functions(self):
        q = _make_querier()
        rec = {"id": "src/b.py:bar", "name": "bar", "filePath": "src/b.py", "startLine": 5, "distance": 1}
        _mock_session(q, [rec])
        result = q.analyze_change_impact("src/a.py:foo")
        assert result == [rec]


# ── find_circular_dependencies ─────────────────────────────────────────────

class TestFindCircularDependencies:
    def test_query_structure(self):
        q = _make_querier()
        _mock_session(q, [])
        q.find_circular_dependencies()
        query = q.driver.session.return_value.__enter__.return_value.run.call_args[0][0]
        assert "CALLS" in query
        assert "cycle" in query.lower()

    def test_returns_cycles(self):
        q = _make_querier()
        rec = {"cycle": ["src/a.py:f", "src/b.py:g", "src/a.py:f"], "cycle_length": 2}
        _mock_session(q, [rec])
        result = q.find_circular_dependencies()
        assert result == [rec]


# ── get_complexity_hotspots ─────────────────────────────────────────────────

class TestGetComplexityHotspots:
    def test_query_counts_calls(self):
        q = _make_querier()
        _mock_session(q, [])
        q.get_complexity_hotspots()
        query = q.driver.session.return_value.__enter__.return_value.run.call_args[0][0]
        assert "CALLS" in query
        assert "totalCoupling" in query or "total_coupling" in query.lower() or "out_calls + in_calls" in query

    def test_returns_hotspots(self):
        q = _make_querier()
        rec = {"id": "src/a.py:foo", "name": "foo", "filePath": "src/a.py",
               "complexity": 5, "outgoingCalls": 3, "incomingCalls": 4, "totalCoupling": 7}
        _mock_session(q, [rec])
        result = q.get_complexity_hotspots()
        assert result == [rec]

    def test_with_repo_id(self):
        q = _make_querier()
        _mock_session(q, [])
        q.get_complexity_hotspots(repo_id="r1")
        query = q.driver.session.return_value.__enter__.return_value.run.call_args[0][0]
        assert "$repo_id" in query
