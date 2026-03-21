"""Tests for src/repair.py — GraphRepairTool."""
from unittest.mock import MagicMock, patch, call

import pytest

from src.repair import GraphRepairTool


def _make_tool():
    """Create a GraphRepairTool with a mocked CodeKAGQuerier."""
    with patch("src.repair.GraphRepairTool.__init__", return_value=None):
        tool = GraphRepairTool.__new__(GraphRepairTool)

    mock_driver = MagicMock()
    mock_querier = MagicMock()
    mock_querier.driver = mock_driver
    tool._querier = mock_querier
    tool._uri = "bolt://localhost:7687"
    tool._user = "neo4j"
    tool._password = "test"
    return tool, mock_driver


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_healthy_empty_graph(self):
        tool, mock_driver = _make_tool()

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        # All node count queries return 0, repo list returns []
        def run_side_effect(query, **kwargs):
            result = MagicMock()
            if "count" in query:
                result.single.return_value = {"cnt": 0}
            else:
                result.__iter__ = MagicMock(return_value=iter([]))
            return result

        mock_session.run.side_effect = run_side_effect

        report = tool.health_check()

        assert report["connectivity"]["status"] == "healthy"
        assert report["overall_status"] == "warning"  # no repos
        assert "No repositories indexed yet." in report["warnings"]

    def test_connectivity_failure(self):
        tool, mock_driver = _make_tool()
        mock_driver.verify_connectivity.side_effect = Exception("Connection refused")

        report = tool.health_check()

        assert report["connectivity"]["status"] == "unhealthy"
        assert report["overall_status"] == "unhealthy"
        assert "error" in report["connectivity"]

    def test_with_repositories(self):
        tool, mock_driver = _make_tool()

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        call_count = [0]

        def run_side_effect(query, **kwargs):
            result = MagicMock()
            if "count" in query:
                result.single.return_value = {"cnt": 5}
            elif "Repository" in query and "RETURN" in query and "count" not in query:
                # list repos query
                mock_rec = {"id": "my-repo", "path": "/tmp/repo", "lastIndexed": None}
                result.__iter__ = MagicMock(return_value=iter([mock_rec]))
            else:
                result.__iter__ = MagicMock(return_value=iter([]))
            return result

        mock_session.run.side_effect = run_side_effect

        report = tool.health_check()

        assert report["connectivity"]["status"] == "healthy"
        assert report["overall_status"] == "healthy"

    def test_stats_include_node_labels(self):
        tool, mock_driver = _make_tool()

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        def run_side_effect(query, **kwargs):
            result = MagicMock()
            if "count" in query:
                result.single.return_value = {"cnt": 3}
            else:
                result.__iter__ = MagicMock(return_value=iter([
                    {"id": "r1", "path": "/tmp", "lastIndexed": None}
                ]))
            return result

        mock_session.run.side_effect = run_side_effect

        report = tool.health_check()

        for label in ("Repository", "File", "Class", "Function"):
            assert label in report["stats"]
        assert "total_relationships" in report["stats"]


# ---------------------------------------------------------------------------
# find_orphaned_nodes
# ---------------------------------------------------------------------------

class TestFindOrphanedNodes:
    def test_no_orphans(self):
        tool, mock_driver = _make_tool()

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = result_mock

        orphans = tool.find_orphaned_nodes()

        assert orphans["Function"] == []
        assert orphans["Class"] == []

    def test_orphaned_functions(self):
        tool, mock_driver = _make_tool()

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        call_count = [0]

        def run_side_effect(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # Function query
                result.__iter__ = MagicMock(return_value=iter([
                    {"id": "repo/src/a.py::orphan_func"},
                ]))
            else:  # Class query
                result.__iter__ = MagicMock(return_value=iter([]))
            return result

        mock_session.run.side_effect = run_side_effect

        orphans = tool.find_orphaned_nodes()

        assert "repo/src/a.py::orphan_func" in orphans["Function"]
        assert orphans["Class"] == []

    def test_orphaned_classes(self):
        tool, mock_driver = _make_tool()

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        call_count = [0]

        def run_side_effect(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # Function query
                result.__iter__ = MagicMock(return_value=iter([]))
            else:  # Class query
                result.__iter__ = MagicMock(return_value=iter([
                    {"id": "repo/src/b.py::OrphanClass"},
                ]))
            return result

        mock_session.run.side_effect = run_side_effect

        orphans = tool.find_orphaned_nodes()

        assert orphans["Function"] == []
        assert "repo/src/b.py::OrphanClass" in orphans["Class"]


# ---------------------------------------------------------------------------
# fix_orphaned_nodes
# ---------------------------------------------------------------------------

class TestFixOrphanedNodes:
    def test_dry_run_returns_counts_without_deleting(self):
        tool, mock_driver = _make_tool()
        orphans = {"Function": ["id1", "id2"], "Class": ["id3"]}

        with patch.object(tool, "find_orphaned_nodes", return_value=orphans):
            counts = tool.fix_orphaned_nodes(dry_run=True)

        assert counts == {"Function": 2, "Class": 1}
        mock_driver.session.assert_not_called()

    def test_live_run_deletes_orphans(self):
        tool, mock_driver = _make_tool()
        orphans = {"Function": ["id1"], "Class": ["id2"]}

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(tool, "find_orphaned_nodes", return_value=orphans):
            counts = tool.fix_orphaned_nodes(dry_run=False)

        assert counts == {"Function": 1, "Class": 1}
        assert mock_session.run.call_count == 2

    def test_no_orphans_no_queries(self):
        tool, mock_driver = _make_tool()
        orphans = {"Function": [], "Class": []}

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(tool, "find_orphaned_nodes", return_value=orphans):
            counts = tool.fix_orphaned_nodes(dry_run=False)

        assert counts == {"Function": 0, "Class": 0}
        mock_session.run.assert_not_called()


# ---------------------------------------------------------------------------
# validate_integrity
# ---------------------------------------------------------------------------

class TestValidateIntegrity:
    def test_no_issues(self):
        tool, mock_driver = _make_tool()

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = result_mock

        issues = tool.validate_integrity()

        assert issues["overall"] == "ok"
        assert issues["broken_calls"] == []
        assert issues["broken_extends"] == []

    def test_broken_calls_detected(self):
        tool, mock_driver = _make_tool()

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        call_count = [0]

        def run_side_effect(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # CALLS query
                row = {"source": "func_a", "rel": "CALLS", "target_node_id": 99}
                result.__iter__ = MagicMock(return_value=iter([row]))
            else:  # EXTENDS query
                result.__iter__ = MagicMock(return_value=iter([]))
            return result

        mock_session.run.side_effect = run_side_effect

        issues = tool.validate_integrity()

        assert issues["overall"] == "issues_found"
        assert len(issues["broken_calls"]) == 1
        assert issues["broken_calls"][0]["source"] == "func_a"

    def test_broken_extends_detected(self):
        tool, mock_driver = _make_tool()

        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        call_count = [0]

        def run_side_effect(query):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # CALLS query
                result.__iter__ = MagicMock(return_value=iter([]))
            else:  # EXTENDS query
                row = {"source": "class_a", "rel": "EXTENDS", "target_node_id": 42}
                result.__iter__ = MagicMock(return_value=iter([row]))
            return result

        mock_session.run.side_effect = run_side_effect

        issues = tool.validate_integrity()

        assert issues["overall"] == "issues_found"
        assert len(issues["broken_extends"]) == 1


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

class TestClose:
    def test_close_delegates_to_querier(self):
        tool, mock_driver = _make_tool()
        tool.close()
        tool._querier.close.assert_called_once()
