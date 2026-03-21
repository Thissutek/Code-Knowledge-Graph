"""Code-KAG MCP server — aggregates all modular tool handlers."""
import asyncio
import logging
import sys
from typing import Any, Dict

_logger = logging.getLogger(__name__)

# MCP SDK
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        CallToolResult, ListResourcesResult, ListToolsResult,
        Resource, TextContent, Tool,
    )
except ImportError:
    print("MCP SDK not installed. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

from .admin_tools import HANDLERS as _ADMIN_HANDLERS
from .analysis_tools import HANDLERS as _ANALYSIS_HANDLERS
from .context_tools import HANDLERS as _CONTEXT_HANDLERS
from .search_tools import HANDLERS as _SEARCH_HANDLERS
from .utils import get_querier

# ---------------------------------------------------------------------------
# Aggregate handler registry
# ---------------------------------------------------------------------------

TOOL_HANDLERS: Dict[str, Any] = {
    **_SEARCH_HANDLERS,
    **_ANALYSIS_HANDLERS,
    **_CONTEXT_HANDLERS,
    **_ADMIN_HANDLERS,
}

# ---------------------------------------------------------------------------
# Server instance (imports tool definitions from the legacy mcp_server module
# so the Tool() objects don't need to be duplicated)
# ---------------------------------------------------------------------------

server = Server("code-kag")


@server.list_tools()
async def list_tools() -> ListToolsResult:
    # Import TOOLS from mcp_server to avoid duplicating definitions
    from src.mcp_server import TOOLS
    return ListToolsResult(tools=TOOLS)


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
    if name not in TOOL_HANDLERS:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Unknown tool: {name}")],
            isError=True,
        )
    try:
        result = await TOOL_HANDLERS[name](arguments)
        return CallToolResult(content=[TextContent(type="text", text=result)])
    except ConnectionError as exc:
        return CallToolResult(
            content=[TextContent(type="text", text=(
                f"Neo4j connection error: {exc}. "
                "Ensure Neo4j is running and accessible."
            ))],
            isError=True,
        )
    except KeyError as exc:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Missing required argument: {exc}")],
            isError=True,
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {exc}")],
            isError=True,
        )


@server.list_resources()
async def list_resources() -> ListResourcesResult:
    resources = []
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
                    name=record["name"],
                    description=f"Code repository at {record['path']}",
                ))
    except Exception:
        pass
    return ListResourcesResult(resources=resources)


async def main() -> None:
    print("Starting Code KAG MCP Server...", file=sys.stderr)
    try:
        get_querier()
        print("Connected to Neo4j", file=sys.stderr)
    except Exception as exc:
        print(f"Warning: Could not connect to Neo4j: {exc}", file=sys.stderr)
        print("Some tools may not work until Neo4j is available", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
