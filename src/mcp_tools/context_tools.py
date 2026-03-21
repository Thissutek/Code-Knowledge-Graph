"""Context MCP tools: function/class details, file deps, entry points, complexity, tests."""
import json
from typing import Any, Dict

from .utils import get_querier, _parse_limit


async def handle_get_function_details(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    function_id = arguments.get("function_id")
    function_name = arguments.get("function_name")
    repo_id = arguments.get("repo_id")

    if function_id:
        context = q.get_code_context(function_id, repo_id=repo_id)
        if context:
            return json.dumps(context, indent=2)

    if function_name:
        results = q.find_function_by_name(function_name, repo_id=repo_id)
        if results:
            if results[0].get("id"):
                context = q.get_code_context(results[0]["id"], repo_id=repo_id)
                return json.dumps(context, indent=2)
            return json.dumps(results[0], indent=2)

    return json.dumps({"error": "Function not found"})


async def handle_get_class_details(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    class_name = arguments["class_name"]
    repo_id = arguments.get("repo_id")

    results = q.find_class_by_name(class_name, repo_id=repo_id)
    if not results:
        return json.dumps({"error": f"Class '{class_name}' not found"})

    hierarchy = q.get_class_hierarchy(class_name, repo_id=repo_id)
    result = results[0]
    if hierarchy:
        result["ancestors"] = hierarchy.get("ancestors", [])
        result["descendants"] = hierarchy.get("descendants", [])

    return json.dumps(result, indent=2)


async def handle_get_file_dependencies(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    file_path = arguments["file_path"]
    repo_id = arguments.get("repo_id")

    result = q.get_file_dependencies(file_path, repo_id=repo_id)
    if not result:
        return json.dumps({"error": f"File '{file_path}' not found"})
    return json.dumps(result, indent=2)


async def handle_get_code_context(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    entity_id = arguments["entity_id"]
    repo_id = arguments.get("repo_id")

    result = q.get_code_context(entity_id, repo_id=repo_id)
    if not result:
        return json.dumps({"error": f"Entity '{entity_id}' not found"})
    return json.dumps(result, indent=2)


async def handle_find_entry_points(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    limit = _parse_limit(arguments.get("limit", 20), default=20)
    repo_id = arguments.get("repo_id")
    exclude_test_files = arguments.get("exclude_test_files", True)
    path_prefix = arguments.get("path_prefix", "")

    test_filter = (
        "AND NOT (file.path CONTAINS '/test' OR file.path CONTAINS 'test_' OR file.path ENDS WITH '_test.py')"
        if exclude_test_files else ""
    )
    prefix_filter = "AND file.path CONTAINS $path_prefix" if path_prefix else ""

    with q.driver.session() as session:
        if repo_id:
            result = session.run(f"""
                MATCH (r:Repository {{id: $repo_id}})-[:CONTAINS_FILE]->(file:File)-[:DEFINES_FUNCTION]->(f:Function)
                WHERE NOT ()-[:CALLS]->(f)
                AND NOT f.name STARTS WITH '_'
                AND f.name <> '__init__'
                {test_filter}
                {prefix_filter}
                RETURN f.id AS id, f.name AS name, f.signature AS signature,
                       file.path AS filePath
                LIMIT $limit
            """, limit=limit, repo_id=repo_id, path_prefix=path_prefix)
        else:
            result = session.run(f"""
                MATCH (f:Function)
                WHERE NOT ()-[:CALLS]->(f)
                AND NOT f.name STARTS WITH '_'
                AND f.name <> '__init__'
                OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION]->(f)
                WITH f, file
                WHERE file IS NULL
                   OR (true
                       {test_filter}
                       {prefix_filter})
                RETURN f.id AS id, f.name AS name, f.signature AS signature,
                       file.path AS filePath
                LIMIT $limit
            """, limit=limit, path_prefix=path_prefix)
        results = [dict(r) for r in result]

    return json.dumps({"entry_points": results}, indent=2)


async def handle_find_high_complexity(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    min_complexity = arguments.get("min_complexity", 5)
    limit = _parse_limit(arguments.get("limit", 10), default=10)
    repo_id = arguments.get("repo_id")

    with q.driver.session() as session:
        if repo_id:
            result = session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)-[:DEFINES_FUNCTION|HAS_METHOD*]->(f:Function)
                WHERE f.complexity >= $min_complexity
                RETURN f.id AS id, f.name AS name, f.complexity AS complexity,
                       f.signature AS signature, file.path AS filePath
                ORDER BY f.complexity DESC
                LIMIT $limit
            """, min_complexity=min_complexity, limit=limit, repo_id=repo_id)
        else:
            result = session.run("""
                MATCH (f:Function)
                WHERE f.complexity >= $min_complexity
                OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION|HAS_METHOD*]->(f)
                RETURN f.id AS id, f.name AS name, f.complexity AS complexity,
                       f.signature AS signature, file.path AS filePath
                ORDER BY f.complexity DESC
                LIMIT $limit
            """, min_complexity=min_complexity, limit=limit)
        results = [dict(r) for r in result]

    return json.dumps({"high_complexity_functions": results}, indent=2)


async def handle_get_tests_for_function(arguments: Dict[str, Any]) -> str:
    q = get_querier()
    function_id = arguments["function_id"]
    repo_id = arguments.get("repo_id")

    results = q.get_tests_for_function(function_id, repo_id=repo_id)
    return json.dumps({"function_id": function_id, "tests": results, "count": len(results)}, indent=2)


HANDLERS = {
    "get_function_details": handle_get_function_details,
    "get_class_details": handle_get_class_details,
    "get_file_dependencies": handle_get_file_dependencies,
    "get_code_context": handle_get_code_context,
    "find_entry_points": handle_find_entry_points,
    "find_high_complexity_functions": handle_find_high_complexity,
    "get_tests_for_function": handle_get_tests_for_function,
}
