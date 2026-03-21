"""Search MCP tools: search_code, find_similar_code."""
import json
from typing import Any, Dict

from .utils import get_querier, _parse_limit


TOOL_DEFINITIONS = []  # populated lazily from server.py — definitions live in mcp_server.py


async def handle_search_code(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    query = arguments.get("query", "")
    search_type = arguments.get("type", "all")
    limit = _parse_limit(arguments.get("limit", 10), default=10)
    repo_id = arguments.get("repo_id")

    if search_type == "all":
        results = q.semantic_code_search(query, limit, repo_id=repo_id)
    elif search_type == "function":
        results = q.find_function_by_name(query, repo_id=repo_id)
        if not results:
            results = q.search_functions(query, limit, repo_id=repo_id)
    elif search_type == "class":
        results = q.find_class_by_name(query, repo_id=repo_id)
        if not results:
            results = q.search_classes(query, limit, repo_id=repo_id)
    elif search_type == "file":
        with q.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                    WHERE f.name CONTAINS $search_term OR f.path CONTAINS $search_term
                    RETURN f.id AS id, f.name AS name, f.path AS path,
                           f.linesOfCode AS lines
                    LIMIT $limit
                """, search_term=query, limit=limit, repo_id=repo_id)
            else:
                result = session.run("""
                    MATCH (f:File)
                    WHERE f.name CONTAINS $search_term OR f.path CONTAINS $search_term
                    RETURN f.id AS id, f.name AS name, f.path AS path,
                           f.linesOfCode AS lines
                    LIMIT $limit
                """, search_term=query, limit=limit)
            results = [dict(r) for r in result]
    else:
        results = []

    if not results:
        return json.dumps({"message": f"No results found for '{query}'", "results": []})

    return json.dumps({"query": query, "type": search_type, "results": results}, indent=2)


async def handle_find_similar_code(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    function_id = arguments["function_id"]
    limit = _parse_limit(arguments.get("limit", 5), default=5)
    repo_id = arguments.get("repo_id")

    results = q.find_similar_functions(function_id, limit, repo_id=repo_id)
    if not results:
        return json.dumps({"message": "No similar functions found", "results": []})

    return json.dumps({"function_id": function_id, "similar": results}, indent=2)


HANDLERS = {
    "search_code": handle_search_code,
    "find_similar_code": handle_find_similar_code,
}
