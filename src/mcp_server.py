#!/usr/bin/env python3
"""
Code Knowledge Graph MCP Server
Exposes code search and context retrieval capabilities to AI assistants
"""
import os
import sys
import json
import time
import asyncio
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

# MCP SDK imports
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Tool, TextContent, CallToolResult,
        ListToolsResult, Resource, ListResourcesResult
    )
except ImportError:
    print("MCP SDK not installed. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.neo4j_ingester import CodeKAGQuerier
from src.parser import parse_repository


# Initialize MCP server
server = Server("code-kag")

# Global querier instance
querier: Optional[CodeKAGQuerier] = None

# Track server start time for uptime reporting
SERVER_START_TIME = time.time()


def get_querier() -> CodeKAGQuerier:
    """Get or create the Neo4j querier, with connection validation and retry."""
    global querier

    # Validate existing connection
    if querier is not None:
        try:
            querier.driver.verify_connectivity()
            return querier
        except Exception:
            # Connection is stale, close and recreate
            try:
                querier.close()
            except Exception:
                pass
            querier = None

    # Retry up to 3 times with backoff
    last_error = None
    for attempt in range(3):
        try:
            q = CodeKAGQuerier()
            q.connect()
            q.driver.verify_connectivity()
            querier = q
            return querier
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(1 * (attempt + 1))

    raise ConnectionError(
        f"Failed to connect to Neo4j after 3 attempts: {last_error}. "
        "Check that Neo4j is running and NEO4J_URI/NEO4J_USERNAME/NEO4J_PASSWORD are correct."
    )


# =============================================================================
# Tool Definitions
# =============================================================================

TOOLS = [
    Tool(
        name="search_code",
        description="""Search the code knowledge graph for functions, classes, or files.
        Use this to find code by name, description, or docstring content.
        Returns matching code entities with their locations and descriptions.""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - can be a function name, class name, or keyword"
                },
                "type": {
                    "type": "string",
                    "enum": ["all", "function", "class", "file"],
                    "default": "all",
                    "description": "Type of code entity to search for"
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of results to return"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to scope results to a specific project"
                }
            },
            "required": ["query"]
        }
    ),
    Tool(
        name="get_function_details",
        description="""Get detailed information about a specific function.
        Returns the function signature, docstring, parameters, location,
        what functions it calls, and what functions call it.""",
        inputSchema={
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Name of the function to look up"
                },
                "function_id": {
                    "type": "string",
                    "description": "Full ID of the function (file:class:function format)"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to scope results to a specific project"
                }
            }
        }
    ),
    Tool(
        name="get_class_details",
        description="""Get detailed information about a specific class.
        Returns the class docstring, methods, parent classes, child classes,
        and class variables.""",
        inputSchema={
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Name of the class to look up"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to scope results to a specific project"
                }
            },
            "required": ["class_name"]
        }
    ),
    Tool(
        name="get_call_graph",
        description="""Get the call graph for a function - what functions it calls
        and optionally the transitive calls up to a specified depth.
        Useful for understanding code flow and dependencies.""",
        inputSchema={
            "type": "object",
            "properties": {
                "function_id": {
                    "type": "string",
                    "description": "ID of the function (file:function or file:class:method)"
                },
                "depth": {
                    "type": "integer",
                    "default": 2,
                    "description": "How many levels of calls to trace"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to scope results to a specific project"
                }
            },
            "required": ["function_id"]
        }
    ),
    Tool(
        name="get_class_hierarchy",
        description="""Get the inheritance hierarchy for a class.
        Returns ancestor classes (parents) and descendant classes (children).""",
        inputSchema={
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Name of the class"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to scope results to a specific project"
                }
            },
            "required": ["class_name"]
        }
    ),
    Tool(
        name="get_file_dependencies",
        description="""Get the dependency graph for a file.
        Returns what files this file imports from and what files import from it.
        Useful for understanding module relationships.""",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file relative to repository root"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to scope results to a specific project"
                }
            },
            "required": ["file_path"]
        }
    ),
    Tool(
        name="find_similar_code",
        description="""Find functions that are similar to a given function.
        Similarity is based on shared function calls and class usage patterns.
        Useful for finding related code or potential duplicates.""",
        inputSchema={
            "type": "object",
            "properties": {
                "function_id": {
                    "type": "string",
                    "description": "ID of the function to find similar code for"
                },
                "limit": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum number of similar functions to return"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to scope results to a specific project"
                }
            },
            "required": ["function_id"]
        }
    ),
    Tool(
        name="get_code_context",
        description="""Get comprehensive context for a code entity.
        Returns all relevant information including relationships to other code.
        Use this when you need full context about a function or class.""",
        inputSchema={
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "ID of the code entity (function or class)"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to scope results to a specific project"
                }
            },
            "required": ["entity_id"]
        }
    ),
    Tool(
        name="index_repository",
        description="""Index a repository into the code knowledge graph.
        Parses all Python files and creates nodes/relationships in Neo4j.
        Use this when setting up a new repository or updating after changes.""",
        inputSchema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the repository to index"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional unique ID for the repository"
                }
            },
            "required": ["repo_path"]
        }
    ),
    Tool(
        name="find_entry_points",
        description="""Find potential entry points in the codebase.
        Returns functions that are not called by other functions (top-level entry points).
        Useful for understanding where code execution might begin.""",
        inputSchema={
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to filter by"
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum number of entry points to return"
                }
            }
        }
    ),
    Tool(
        name="find_high_complexity_functions",
        description="""Find functions with high cyclomatic complexity.
        Returns functions sorted by complexity score.
        Useful for identifying code that might need refactoring.""",
        inputSchema={
            "type": "object",
            "properties": {
                "min_complexity": {
                    "type": "integer",
                    "default": 5,
                    "description": "Minimum complexity threshold"
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of functions to return"
                },
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to scope results to a specific project"
                }
            }
        }
    ),
    Tool(
        name="health_check",
        description="""Check the health of the Code-KAG system.
        Returns Neo4j connectivity status, node/relationship counts,
        indexed repositories, and server uptime.""",
        inputSchema={
            "type": "object",
            "properties": {}
        }
    ),
    Tool(
        name="get_graph_stats",
        description="""Get detailed statistics about the code knowledge graph.
        Returns per-repository breakdowns of files, classes, functions, etc.
        Optionally filter by repository ID.""",
        inputSchema={
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "Optional repository ID to filter stats for"
                }
            }
        }
    )
]


# =============================================================================
# Tool Handlers
# =============================================================================

async def handle_search_code(arguments: Dict[str, Any]) -> str:
    """Handle code search requests"""
    q = get_querier()
    query = arguments.get("query", "")
    search_type = arguments.get("type", "all")
    limit = arguments.get("limit", 10)
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
        # Simple file search
        with q.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                    WHERE f.name CONTAINS $query OR f.path CONTAINS $query
                    RETURN f.id AS id, f.name AS name, f.path AS path,
                           f.linesOfCode AS lines
                    LIMIT $limit
                """, query=query, limit=limit, repo_id=repo_id)
            else:
                result = session.run("""
                    MATCH (f:File)
                    WHERE f.name CONTAINS $query OR f.path CONTAINS $query
                    RETURN f.id AS id, f.name AS name, f.path AS path,
                           f.linesOfCode AS lines
                    LIMIT $limit
                """, query=query, limit=limit)
            results = [dict(r) for r in result]
    else:
        results = []
    
    if not results:
        return json.dumps({"message": f"No results found for '{query}'", "results": []})
    
    return json.dumps({"query": query, "type": search_type, "results": results}, indent=2)


async def handle_get_function_details(arguments: Dict[str, Any]) -> str:
    """Get detailed function information"""
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
            # Get full context for first result
            if results[0].get('id'):
                context = q.get_code_context(results[0]['id'], repo_id=repo_id)
                return json.dumps(context, indent=2)
            return json.dumps(results[0], indent=2)

    return json.dumps({"error": "Function not found"})


async def handle_get_class_details(arguments: Dict[str, Any]) -> str:
    """Get detailed class information"""
    q = get_querier()
    class_name = arguments["class_name"]
    repo_id = arguments.get("repo_id")

    results = q.find_class_by_name(class_name, repo_id=repo_id)
    if not results:
        return json.dumps({"error": f"Class '{class_name}' not found"})

    # Also get hierarchy
    hierarchy = q.get_class_hierarchy(class_name, repo_id=repo_id)

    result = results[0]
    if hierarchy:
        result["ancestors"] = hierarchy.get("ancestors", [])
        result["descendants"] = hierarchy.get("descendants", [])

    return json.dumps(result, indent=2)


async def handle_get_call_graph(arguments: Dict[str, Any]) -> str:
    """Get function call graph"""
    q = get_querier()
    function_id = arguments["function_id"]
    depth = arguments.get("depth", 2)
    repo_id = arguments.get("repo_id")

    result = q.get_function_callgraph(function_id, depth, repo_id=repo_id)
    if not result:
        return json.dumps({"error": f"Function '{function_id}' not found or has no calls"})

    return json.dumps(result, indent=2)


async def handle_get_class_hierarchy(arguments: Dict[str, Any]) -> str:
    """Get class inheritance hierarchy"""
    q = get_querier()
    class_name = arguments["class_name"]
    repo_id = arguments.get("repo_id")

    result = q.get_class_hierarchy(class_name, repo_id=repo_id)
    if not result:
        return json.dumps({"error": f"Class '{class_name}' not found"})

    return json.dumps(result, indent=2)


async def handle_get_file_dependencies(arguments: Dict[str, Any]) -> str:
    """Get file dependency information"""
    q = get_querier()
    file_path = arguments["file_path"]
    repo_id = arguments.get("repo_id")

    result = q.get_file_dependencies(file_path, repo_id=repo_id)
    if not result:
        return json.dumps({"error": f"File '{file_path}' not found"})

    return json.dumps(result, indent=2)


async def handle_find_similar_code(arguments: Dict[str, Any]) -> str:
    """Find similar functions"""
    q = get_querier()
    function_id = arguments["function_id"]
    limit = arguments.get("limit", 5)
    repo_id = arguments.get("repo_id")

    results = q.find_similar_functions(function_id, limit, repo_id=repo_id)
    if not results:
        return json.dumps({"message": "No similar functions found", "results": []})

    return json.dumps({"function_id": function_id, "similar": results}, indent=2)


async def handle_get_code_context(arguments: Dict[str, Any]) -> str:
    """Get comprehensive code context"""
    q = get_querier()
    entity_id = arguments["entity_id"]
    repo_id = arguments.get("repo_id")

    result = q.get_code_context(entity_id, repo_id=repo_id)
    if not result:
        return json.dumps({"error": f"Entity '{entity_id}' not found"})

    return json.dumps(result, indent=2)


async def handle_index_repository(arguments: Dict[str, Any]) -> str:
    """Index a repository into the knowledge graph"""
    from src.neo4j_ingester import ingest_repository
    
    repo_path = arguments["repo_path"]
    repo_id = arguments.get("repo_id")
    
    try:
        stats = ingest_repository(repo_path, repo_id=repo_id)
        return json.dumps({
            "success": True,
            "repository": repo_path,
            "stats": stats
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        })


async def handle_find_entry_points(arguments: Dict[str, Any]) -> str:
    """Find entry point functions"""
    q = get_querier()
    limit = arguments.get("limit", 20)
    repo_id = arguments.get("repo_id")

    with q.driver.session() as session:
        if repo_id:
            result = session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)-[:DEFINES_FUNCTION]->(f:Function)
                WHERE NOT ()-[:CALLS]->(f)
                AND NOT f.name STARTS WITH '_'
                AND f.name <> '__init__'
                RETURN f.id AS id, f.name AS name, f.signature AS signature,
                       file.path AS filePath
                LIMIT $limit
            """, limit=limit, repo_id=repo_id)
        else:
            result = session.run("""
                MATCH (f:Function)
                WHERE NOT ()-[:CALLS]->(f)
                AND NOT f.name STARTS WITH '_'
                AND f.name <> '__init__'
                OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION]->(f)
                RETURN f.id AS id, f.name AS name, f.signature AS signature,
                       file.path AS filePath
                LIMIT $limit
            """, limit=limit)
        results = [dict(r) for r in result]

    return json.dumps({"entry_points": results}, indent=2)


async def handle_find_high_complexity(arguments: Dict[str, Any]) -> str:
    """Find high complexity functions"""
    q = get_querier()
    min_complexity = arguments.get("min_complexity", 5)
    limit = arguments.get("limit", 10)
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


async def handle_health_check(arguments: Dict[str, Any]) -> str:
    """Check system health"""
    health = {
        "status": "unhealthy",
        "neo4j": {"connected": False},
        "repositories": {"count": 0, "list": []},
        "node_counts": {},
        "relationship_count": 0,
        "uptime_seconds": round(time.time() - SERVER_START_TIME, 1)
    }

    try:
        q = get_querier()
        start = time.time()
        q.driver.verify_connectivity()
        latency = round((time.time() - start) * 1000, 1)
        health["neo4j"] = {"connected": True, "latency_ms": latency}

        with q.driver.session() as session:
            # Repositories
            repos = session.run("""
                MATCH (r:Repository)
                RETURN r.id AS id, r.name AS name, r.lastIndexed AS lastIndexed
            """)
            repo_list = []
            for r in repos:
                repo_list.append({
                    "id": r["id"],
                    "name": r["name"],
                    "lastIndexed": str(r["lastIndexed"]) if r["lastIndexed"] else None
                })
            health["repositories"] = {"count": len(repo_list), "list": repo_list}

            # Node counts using individual queries with WITH aggregation
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
                health["node_counts"] = {
                    "files": row["files"],
                    "classes": row["classes"],
                    "functions": row["functions"],
                    "modules": row["modules"],
                    "variables": row["variables"],
                    "imports": row["imports"]
                }

            # Total relationships
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS count")
            rel_row = rel_count.single()
            health["relationship_count"] = rel_row["count"] if rel_row else 0

        health["status"] = "healthy"
    except Exception as e:
        health["error"] = str(e)

    return json.dumps(health, indent=2)


async def handle_get_graph_stats(arguments: Dict[str, Any]) -> str:
    """Get per-repository graph statistics"""
    q = get_querier()
    repo_id = arguments.get("repo_id")

    with q.driver.session() as session:
        if repo_id:
            repo_query = "MATCH (r:Repository {id: $repo_id})"
            params = {"repo_id": repo_id}
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
        totals = {"files": 0, "modules": 0, "classes": 0, "functions": 0, "imports": 0}
        for row in result:
            repo_stats = {
                "repo_id": row["repo_id"],
                "name": row["name"],
                "lastIndexed": str(row["lastIndexed"]) if row["lastIndexed"] else None,
                "files": row["files"],
                "modules": row["modules"],
                "classes": row["classes"],
                "functions": row["functions"],
                "imports": row["imports"]
            }
            repos.append(repo_stats)
            for key in totals:
                totals[key] += row[key]

        # Total relationships
        rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS count")
        rel_row = rel_count.single()
        total_rels = rel_row["count"] if rel_row else 0

    return json.dumps({
        "repositories": repos,
        "totals": totals,
        "total_relationships": total_rels
    }, indent=2)


# Tool handler mapping
TOOL_HANDLERS = {
    "search_code": handle_search_code,
    "get_function_details": handle_get_function_details,
    "get_class_details": handle_get_class_details,
    "get_call_graph": handle_get_call_graph,
    "get_class_hierarchy": handle_get_class_hierarchy,
    "get_file_dependencies": handle_get_file_dependencies,
    "find_similar_code": handle_find_similar_code,
    "get_code_context": handle_get_code_context,
    "index_repository": handle_index_repository,
    "find_entry_points": handle_find_entry_points,
    "find_high_complexity_functions": handle_find_high_complexity,
    "health_check": handle_health_check,
    "get_graph_stats": handle_get_graph_stats,
}


# =============================================================================
# MCP Server Handlers
# =============================================================================

@server.list_tools()
async def list_tools() -> ListToolsResult:
    """Return list of available tools"""
    return ListToolsResult(tools=TOOLS)


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
    """Handle tool calls"""
    if name not in TOOL_HANDLERS:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Unknown tool: {name}")],
            isError=True
        )

    try:
        result = await TOOL_HANDLERS[name](arguments)
        return CallToolResult(
            content=[TextContent(type="text", text=result)]
        )
    except ConnectionError as e:
        return CallToolResult(
            content=[TextContent(type="text", text=(
                f"Neo4j connection error: {e}. "
                "Ensure Neo4j is running and accessible."
            ))],
            isError=True
        )
    except KeyError as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Missing required argument: {e}")],
            isError=True
        )
    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")],
            isError=True
        )


@server.list_resources()
async def list_resources() -> ListResourcesResult:
    """List available resources"""
    resources = []
    
    # List indexed repositories
    try:
        q = get_querier()
        with q.driver.session() as session:
            result = session.run("""
                MATCH (r:Repository)
                RETURN r.id AS id, r.name AS name, r.path AS path
            """)
            for record in result:
                resources.append(Resource(
                    uri=f"codekag://repository/{record['id']}",
                    name=record['name'],
                    description=f"Code repository at {record['path']}"
                ))
    except Exception:
        pass
    
    return ListResourcesResult(resources=resources)


# =============================================================================
# Main Entry Point
# =============================================================================

async def main():
    """Run the MCP server"""
    print("Starting Code KAG MCP Server...", file=sys.stderr)
    
    # Initialize querier
    try:
        get_querier()
        print("Connected to Neo4j", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Could not connect to Neo4j: {e}", file=sys.stderr)
        print("Some tools may not work until Neo4j is available", file=sys.stderr)
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
