"""Admin MCP tools: index_repository, health_check, get_graph_stats, list/remove repos."""
import json
import time
from typing import Any, Dict

from .utils import get_querier, _validate_repo_path, SERVER_START_TIME


async def handle_index_repository(arguments: Dict[str, Any]) -> str:
    from src.neo4j_ingester import ingest_repository

    repo_path = arguments["repo_path"]
    repo_id = arguments.get("repo_id")

    try:
        safe_path = _validate_repo_path(repo_path)
        stats = ingest_repository(safe_path, repo_id=repo_id)
        return json.dumps({"success": True, "repository": repo_path, "stats": stats}, indent=2)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


async def handle_health_check(arguments: Dict[str, Any]) -> str:
    health = {
        "status": "unhealthy",
        "neo4j": {"connected": False},
        "repositories": {"count": 0, "list": []},
        "node_counts": {},
        "relationship_count": 0,
        "uptime_seconds": round(time.time() - SERVER_START_TIME, 1),
    }

    try:
        q = get_querier()
        start = time.time()
        q.driver.verify_connectivity()
        latency = round((time.time() - start) * 1000, 1)
        health["neo4j"] = {"connected": True, "latency_ms": latency}

        with q.driver.session() as session:
            repos = session.run("""
                MATCH (r:Repository)
                RETURN r.id AS id, r.name AS name, r.lastIndexed AS lastIndexed
            """)
            repo_list = [
                {"id": r["id"], "name": r["name"],
                 "lastIndexed": str(r["lastIndexed"]) if r["lastIndexed"] else None}
                for r in repos
            ]
            health["repositories"] = {"count": len(repo_list), "list": repo_list}

            counts = session.run("""
                OPTIONAL MATCH (f:File)
                WITH count(f) AS files
                OPTIONAL MATCH (c:Class)
                WITH files, count(c) AS classes
                OPTIONAL MATCH (fn:Function)
                WITH files, classes, count(fn) AS functions
                OPTIONAL MATCH (m:Module)
                WITH files, classes, functions, count(m) AS modules
                OPTIONAL MATCH (v:Variable)
                WITH files, classes, functions, modules, count(v) AS variables
                OPTIONAL MATCH (i:Import)
                RETURN files, classes, functions, modules, variables, count(i) AS imports
            """)
            row = counts.single()
            if row:
                health["node_counts"] = dict(row)

            rel_row = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()
            health["relationship_count"] = rel_row["count"] if rel_row else 0

        health["status"] = "healthy"
    except Exception as exc:
        health["error"] = str(exc)

    return json.dumps(health, indent=2)


async def handle_get_graph_stats(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    repo_id = arguments.get("repo_id")

    with q.driver.session() as session:
        if repo_id:
            repo_query = "MATCH (r:Repository {id: $repo_id})"
            params: Dict[str, Any] = {"repo_id": repo_id}
        else:
            repo_query = "MATCH (r:Repository)"
            params = {}

        result = session.run(f"""
            {repo_query}
            OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(f:File)
            WITH r, count(DISTINCT f) AS files
            OPTIONAL MATCH (r)-[:CONTAINS_MODULE]->(m:Module)
            WITH r, files, count(DISTINCT m) AS modules
            OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(:File)-[:DEFINES_CLASS]->(c:Class)
            WITH r, files, modules, count(DISTINCT c) AS classes
            OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(:File)-[:DEFINES_FUNCTION]->(func:Function)
            WITH r, files, modules, classes, count(DISTINCT func) AS topLevelFuncs
            OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(:File)-[:DEFINES_CLASS]->(:Class)-[:HAS_METHOD]->(m2:Function)
            WITH r, files, modules, classes, topLevelFuncs, count(DISTINCT m2) AS methodCount
            WITH r, files, modules, classes, topLevelFuncs + methodCount AS functions
            OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(:File)-[:IMPORTS]->(i:Import)
            RETURN r.id AS repo_id, r.name AS name, r.lastIndexed AS lastIndexed,
                   files, modules, classes, functions, count(DISTINCT i) AS imports
        """, **params)

        repos = []
        totals: Dict[str, int] = {"files": 0, "modules": 0, "classes": 0, "functions": 0, "imports": 0}
        for row in result:
            repo_stats = {
                "repo_id": row["repo_id"],
                "name": row["name"],
                "lastIndexed": str(row["lastIndexed"]) if row["lastIndexed"] else None,
                "files": row["files"],
                "modules": row["modules"],
                "classes": row["classes"],
                "functions": row["functions"],
                "imports": row["imports"],
            }
            repos.append(repo_stats)
            for key in totals:
                totals[key] += row[key]

        rel_row = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()
        total_rels = rel_row["count"] if rel_row else 0

    return json.dumps({"repositories": repos, "totals": totals, "total_relationships": total_rels}, indent=2)


async def handle_list_repositories(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    repos = q.list_repositories()
    return json.dumps({"repositories": repos, "count": len(repos)}, indent=2)


async def handle_remove_repository(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    repo_id = arguments["repo_id"]
    removed = q.remove_repository(repo_id)
    if removed:
        return json.dumps({"success": True, "message": f"Repository '{repo_id}' removed"})
    return json.dumps({"success": False, "message": f"Repository '{repo_id}' not found"})


HANDLERS = {
    "index_repository": handle_index_repository,
    "health_check": handle_health_check,
    "get_graph_stats": handle_get_graph_stats,
    "list_repositories": handle_list_repositories,
    "remove_repository": handle_remove_repository,
}
