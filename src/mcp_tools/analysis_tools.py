"""Analysis MCP tools: call graphs, dead code, change impact, circular deps, hotspots."""
import json
from typing import Any, Dict

from .utils import get_querier


async def handle_get_call_graph(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    function_id = arguments["function_id"]
    depth = arguments.get("depth", 2)
    repo_id = arguments.get("repo_id")

    result = q.get_function_callgraph(function_id, depth, repo_id=repo_id)
    if not result:
        return json.dumps({"error": f"Function '{function_id}' not found or has no calls"})
    return json.dumps(result, indent=2)


async def handle_get_callers(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    function_id = arguments["function_id"]
    limit = arguments.get("limit", 20)
    repo_id = arguments.get("repo_id")

    results = q.get_callers(function_id, limit=limit, repo_id=repo_id)
    if not results:
        return json.dumps({"function_id": function_id, "callers": [], "message": "No callers found"})
    return json.dumps({"function_id": function_id, "callers": results}, indent=2)


async def handle_get_class_hierarchy(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    class_name = arguments["class_name"]
    repo_id = arguments.get("repo_id")

    result = q.get_class_hierarchy(class_name, repo_id=repo_id)
    if not result:
        return json.dumps({"error": f"Class '{class_name}' not found"})
    return json.dumps(result, indent=2)


async def handle_find_dead_code(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    repo_id = arguments.get("repo_id")
    limit = arguments.get("limit", 50)
    results = q.find_dead_code(repo_id=repo_id, limit=limit)
    return json.dumps({"dead_code_candidates": results, "count": len(results)}, indent=2)


async def handle_analyze_change_impact(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    function_id = arguments["function_id"]
    max_depth = arguments.get("max_depth", 3)
    limit = arguments.get("limit", 50)
    results = q.analyze_change_impact(function_id, max_depth=max_depth, limit=limit)
    return json.dumps({
        "function_id": function_id,
        "max_depth": max_depth,
        "affected_functions": results,
        "count": len(results),
    }, indent=2)


async def handle_find_circular_dependencies(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    repo_id = arguments.get("repo_id")
    min_len = arguments.get("min_cycle_length", 2)
    max_len = arguments.get("max_cycle_length", 5)
    limit = arguments.get("limit", 20)
    results = q.find_circular_dependencies(
        min_cycle_length=min_len, max_cycle_length=max_len,
        limit=limit, repo_id=repo_id,
    )
    return json.dumps({"circular_dependencies": results, "count": len(results)}, indent=2)


async def handle_get_complexity_hotspots(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    repo_id = arguments.get("repo_id")
    limit = arguments.get("limit", 20)
    results = q.get_complexity_hotspots(repo_id=repo_id, limit=limit)
    return json.dumps({"hotspots": results, "count": len(results)}, indent=2)


HANDLERS = {
    "get_call_graph": handle_get_call_graph,
    "get_callers": handle_get_callers,
    "get_class_hierarchy": handle_get_class_hierarchy,
    "find_dead_code": handle_find_dead_code,
    "analyze_change_impact": handle_analyze_change_impact,
    "find_circular_dependencies": handle_find_circular_dependencies,
    "get_complexity_hotspots": handle_get_complexity_hotspots,
}
