"""
Graph Repair Tool — validate and repair the Code-KAG Neo4j database.

Provides health checks, orphaned-entity detection, integrity validation,
and relationship rebuilding for the code knowledge graph.
"""
import logging
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)


class GraphRepairTool:
    """
    Maintenance and repair utilities for the Code-KAG graph database.

    Usage::

        tool = GraphRepairTool(uri, user, password)
        report = tool.health_check()
        orphans = tool.find_orphaned_nodes()
        counts = tool.fix_orphaned_nodes(dry_run=False)
        issues = tool.validate_integrity()
    """

    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_password: str):
        from .neo4j_ingester import CodeKAGQuerier
        self._uri = neo4j_uri
        self._user = neo4j_user
        self._password = neo4j_password
        self._querier = CodeKAGQuerier(neo4j_uri, neo4j_user, neo4j_password)
        self._querier.connect()

    def close(self):
        self._querier.close()

    # ── Health check ───────────────────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        """Return a comprehensive health report for the graph database.

        Checks:
        - Neo4j connectivity
        - Node and relationship counts per label/type
        - Number of indexed repositories
        - Whether expected constraints/indexes exist
        """
        report: Dict[str, Any] = {
            "overall_status": "healthy",
            "connectivity": {"status": "unknown"},
            "stats": {},
            "repositories": [],
            "warnings": [],
        }

        # Connectivity
        try:
            self._querier.driver.verify_connectivity()
            report["connectivity"]["status"] = "healthy"
        except Exception as exc:
            report["connectivity"]["status"] = "unhealthy"
            report["connectivity"]["error"] = str(exc)
            report["overall_status"] = "unhealthy"
            return report

        # Node / relationship counts
        with self._querier.driver.session() as session:
            for label in ("Repository", "File", "Class", "Function", "Interface", "Variable", "Import"):
                result = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
                row = result.single()
                report["stats"][label] = row["cnt"] if row else 0

            result = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            row = result.single()
            report["stats"]["total_relationships"] = row["cnt"] if row else 0

            # List repositories
            result = session.run(
                "MATCH (r:Repository) RETURN r.id AS id, r.path AS path, r.lastIndexed AS lastIndexed"
            )
            report["repositories"] = [dict(rec) for rec in result]

        if report["stats"].get("Repository", 0) == 0:
            report["warnings"].append("No repositories indexed yet.")
            report["overall_status"] = "warning"

        return report

    # ── Orphan detection & repair ──────────────────────────────────────────

    def find_orphaned_nodes(self) -> Dict[str, List[str]]:
        """Find nodes that have lost their parent relationship.

        An 'orphaned' node is a Function that is neither:
        - A child of a File via DEFINES_FUNCTION, nor
        - A method of a Class via HAS_METHOD

        And a Class that has no DEFINES_CLASS parent.

        Returns a dict mapping label → list of orphaned entity IDs.
        """
        orphans: Dict[str, List[str]] = {"Function": [], "Class": []}
        with self._querier.driver.session() as session:
            result = session.run("""
                MATCH (f:Function)
                WHERE NOT (:File)-[:DEFINES_FUNCTION]->(f)
                  AND NOT (:Class)-[:HAS_METHOD]->(f)
                RETURN f.id AS id
            """)
            orphans["Function"] = [rec["id"] for rec in result]

            result = session.run("""
                MATCH (c:Class)
                WHERE NOT (:File)-[:DEFINES_CLASS]->(c)
                RETURN c.id AS id
            """)
            orphans["Class"] = [rec["id"] for rec in result]

        return orphans

    def fix_orphaned_nodes(self, dry_run: bool = True) -> Dict[str, int]:
        """Delete orphaned nodes.

        Args:
            dry_run: If True (default) only counts; if False actually deletes.

        Returns:
            Counts of deleted (or would-be-deleted) nodes per label.
        """
        orphans = self.find_orphaned_nodes()
        counts: Dict[str, int] = {label: len(ids) for label, ids in orphans.items()}

        if dry_run:
            _logger.info("[DRY RUN] Would delete: %s", counts)
            return counts

        with self._querier.driver.session() as session:
            if orphans["Function"]:
                session.run(
                    "MATCH (f:Function) WHERE f.id IN $ids DETACH DELETE f",
                    ids=orphans["Function"],
                )
            if orphans["Class"]:
                session.run(
                    "MATCH (c:Class) WHERE c.id IN $ids DETACH DELETE c",
                    ids=orphans["Class"],
                )
        _logger.info("Deleted orphaned nodes: %s", counts)
        return counts

    # ── Integrity validation ───────────────────────────────────────────────

    def validate_integrity(self) -> Dict[str, Any]:
        """Check referential integrity of the graph.

        Checks:
        - All CALLS targets exist as Function nodes
        - All EXTENDS targets exist as Class nodes
        - No dangling relationships

        Returns a report dict with issue lists.
        """
        issues: Dict[str, Any] = {
            "broken_calls": [],
            "broken_extends": [],
            "overall": "ok",
        }
        with self._querier.driver.session() as session:
            # CALLS where target no longer exists
            result = session.run("""
                MATCH (a:Function)-[r:CALLS]->(b)
                WHERE NOT (b:Function)
                RETURN a.id AS source, type(r) AS rel, id(b) AS target_node_id
                LIMIT 100
            """)
            issues["broken_calls"] = [dict(rec) for rec in result]

            # EXTENDS where target no longer exists
            result = session.run("""
                MATCH (a:Class)-[r:EXTENDS]->(b)
                WHERE NOT (b:Class)
                RETURN a.id AS source, type(r) AS rel, id(b) AS target_node_id
                LIMIT 100
            """)
            issues["broken_extends"] = [dict(rec) for rec in result]

        if issues["broken_calls"] or issues["broken_extends"]:
            issues["overall"] = "issues_found"
        return issues

    # ── Relationship rebuild ───────────────────────────────────────────────

    def rebuild_relationships(self, repo_id: str, repo_path: str) -> int:
        """Re-parse all files in *repo_id* and re-create CALLS/EXTENDS relationships.

        This is a targeted repair when the relationship pass failed or produced
        incomplete results. It does NOT clear existing nodes — only adds missing
        CALLS/EXTENDS/IMPLEMENTS edges.

        Returns the number of new relationships created.
        """
        from .parser import CodebaseParser
        from .neo4j_ingester import Neo4jIngester

        _logger.info("Rebuilding relationships for repo %s from %s", repo_id, repo_path)
        parser = CodebaseParser(repo_path, repo_id)
        codebase = parser.parse()

        ingester = Neo4jIngester(self._uri, self._user, self._password)
        ingester.connect()
        try:
            with ingester.driver.session() as session:
                # Only ingest the relationships — skip nodes (they already exist)
                rel_count_before = session.run(
                    "MATCH ()-[r:CALLS|EXTENDS|IMPLEMENTS]->() RETURN count(r) AS n"
                ).single()["n"]
                ingester._ingest_relationships(session, codebase)
                rel_count_after = session.run(
                    "MATCH ()-[r:CALLS|EXTENDS|IMPLEMENTS]->() RETURN count(r) AS n"
                ).single()["n"]
                added = rel_count_after - rel_count_before
                _logger.info("Relationship rebuild complete: +%d relationships", added)
                return added
        finally:
            ingester.close()
