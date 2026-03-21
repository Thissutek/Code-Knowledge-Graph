#!/usr/bin/env python3
"""
Code-KAG CLI
Command-line interface for the Code Knowledge Graph system
"""
import argparse
import json
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def cmd_index(args):
    """Index a repository"""
    from src.neo4j_ingester import ingest_repository

    changed_files = None
    if args.incremental and args.changed_files:
        changed_files = args.changed_files

    print(f"Indexing repository: {args.path}")
    stats = ingest_repository(
        args.path,
        repo_id=args.id,
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        incremental=args.incremental,
        changed_files=changed_files,
        skip_embeddings=args.no_embeddings,
    )
    print(f"Indexing complete!")
    print(f"Statistics: {json.dumps(stats, indent=2)}")


def cmd_search(args):
    """Search the code knowledge graph"""
    from src.neo4j_ingester import CodeKAGQuerier

    q = CodeKAGQuerier(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    q.connect()

    try:
        results = q.semantic_code_search(args.query, args.limit, repo_id=args.repo_id)
        print(json.dumps(results, indent=2))
    finally:
        q.close()


def cmd_function(args):
    """Get function details"""
    from src.neo4j_ingester import CodeKAGQuerier

    q = CodeKAGQuerier(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    q.connect()

    try:
        results = q.find_function_by_name(args.name, repo_id=args.repo_id)
        if results:
            print(json.dumps(results, indent=2))
        else:
            print(f"Function '{args.name}' not found")
    finally:
        q.close()


def cmd_callgraph(args):
    """Get function call graph"""
    from src.neo4j_ingester import CodeKAGQuerier

    q = CodeKAGQuerier(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    q.connect()

    try:
        result = q.get_function_callgraph(args.function_id, args.depth, repo_id=args.repo_id)
        print(json.dumps(result, indent=2))
    finally:
        q.close()


def cmd_serve(args):
    """Start the MCP server"""
    import asyncio
    from src.mcp_server import main

    # Set environment variables
    if args.neo4j_uri:
        os.environ['NEO4J_URI'] = args.neo4j_uri
    if args.neo4j_user:
        os.environ['NEO4J_USERNAME'] = args.neo4j_user
    if args.neo4j_password:
        os.environ['NEO4J_PASSWORD'] = args.neo4j_password

    print("Starting Code-KAG MCP Server...", file=sys.stderr)
    asyncio.run(main())


def cmd_stats(args):
    """Show statistics about indexed repositories"""
    from src.neo4j_ingester import CodeKAGQuerier

    q = CodeKAGQuerier(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    q.connect()

    try:
        with q.driver.session() as session:
            result = session.run("""
                MATCH (r:Repository)
                OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(f:File)
                WITH r, count(DISTINCT f) AS files
                OPTIONAL MATCH (r)-[:CONTAINS_MODULE]->(m:Module)
                WITH r, files, count(DISTINCT m) AS modules
                OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(:File)-[:DEFINES_CLASS]->(c:Class)
                WITH r, files, modules, count(DISTINCT c) AS classes
                OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(:File)-[:DEFINES_FUNCTION]->(func:Function)
                WITH r, files, modules, classes, count(DISTINCT func) AS topLevelFuncs
                OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(:File)-[:DEFINES_CLASS]->(:Class)-[:HAS_METHOD]->(m2:Function)
                RETURN r.id AS repo, r.name AS name, r.path AS path,
                       files, modules, classes, topLevelFuncs + count(DISTINCT m2) AS functions
            """)

            for record in result:
                print(f"\nRepository: {record['name']}")
                print(f"  Path: {record['path']}")
                print(f"  Files: {record['files']}")
                print(f"  Modules: {record['modules']}")
                print(f"  Classes: {record['classes']}")
                print(f"  Functions: {record['functions']}")
    finally:
        q.close()


def cmd_check_staleness(args):
    """Check if a repository's index is stale.

    Exits with code 0 if the repo was indexed within --max-age-hours.
    Exits with code 1 if the index is stale or the repo has never been indexed.
    """
    from src.neo4j_ingester import CodeKAGQuerier

    q = CodeKAGQuerier(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    q.connect()

    try:
        with q.driver.session() as session:
            result = session.run("""
                MATCH (r:Repository {id: $repo_id})
                RETURN r.lastIndexed AS lastIndexed
            """, repo_id=args.repo_id)
            record = result.single()
            if not record or record["lastIndexed"] is None:
                print(f"[code-kag] Repository '{args.repo_id}' has not been indexed.", file=sys.stderr)
                sys.exit(1)

            last_indexed = record["lastIndexed"]
            # Neo4j datetime objects support .to_native() -> datetime
            if hasattr(last_indexed, 'to_native'):
                last_indexed = last_indexed.to_native()

            import datetime as dt
            now = dt.datetime.now(tz=last_indexed.tzinfo)
            age_hours = (now - last_indexed).total_seconds() / 3600

            if age_hours > args.max_age_hours:
                print(f"[code-kag] Index is stale ({age_hours:.1f}h old, limit {args.max_age_hours}h).", file=sys.stderr)
                sys.exit(1)

            print(f"[code-kag] Index is fresh ({age_hours:.1f}h old).", file=sys.stderr)
            sys.exit(0)
    finally:
        q.close()


def cmd_hooks_install(args):
    """Install code-kag git hooks into a repository"""
    from src.hooks import HookManager

    manager = HookManager()
    manager.install(
        repo_path=args.repo_path,
        repo_id=args.id,
        mode=args.mode,
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
    )


def cmd_hooks_uninstall(args):
    """Uninstall code-kag git hooks from a repository"""
    from src.hooks import HookManager

    manager = HookManager()
    manager.uninstall(repo_path=args.repo_path)


def main():
    parser = argparse.ArgumentParser(
        description="Code Knowledge Graph CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Index a repository
  python cli.py index /path/to/repo --id my-project

  # Incremental re-index
  python cli.py index /path/to/repo --id my-project --incremental --changed-files src/main.py src/utils.py

  # Search for code
  python cli.py search "database connection"

  # Get function details
  python cli.py function parse_config

  # Start MCP server
  python cli.py serve

  # Show statistics
  python cli.py stats

  # Install git hooks
  python cli.py hooks install /path/to/repo --id my-project --mode incremental

  # Uninstall git hooks
  python cli.py hooks uninstall /path/to/repo
"""
    )

    # Global arguments
    parser.add_argument('--neo4j-uri', default=os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
                        help='Neo4j connection URI (env: NEO4J_URI)')
    parser.add_argument('--neo4j-user', default=os.getenv('NEO4J_USERNAME', 'neo4j'),
                        help='Neo4j username (env: NEO4J_USERNAME)')
    parser.add_argument('--neo4j-password', default=os.getenv('NEO4J_PASSWORD'),
                        help='Neo4j password (env: NEO4J_PASSWORD)')

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Index command
    index_parser = subparsers.add_parser('index', help='Index a repository')
    index_parser.add_argument('path', help='Path to the repository')
    index_parser.add_argument('--id', help='Repository ID (default: directory name)')
    index_parser.add_argument('--incremental', action='store_true',
                              help='Only re-index changed files')
    index_parser.add_argument('--changed-files', nargs='+', metavar='FILE',
                              help='List of changed files (relative paths) for incremental indexing')
    index_parser.add_argument('--no-embeddings', action='store_true', default=False,
                              help='Skip vector embedding generation (faster indexing, no semantic search)')
    index_parser.set_defaults(func=cmd_index)

    # Search command
    search_parser = subparsers.add_parser('search', help='Search code')
    search_parser.add_argument('query', help='Search query')
    search_parser.add_argument('--limit', type=int, default=10, help='Max results')
    search_parser.add_argument('--repo-id', default=None, help='Scope results to a specific repository')
    search_parser.set_defaults(func=cmd_search)

    # Function command
    func_parser = subparsers.add_parser('function', help='Get function details')
    func_parser.add_argument('name', help='Function name')
    func_parser.add_argument('--repo-id', default=None, help='Scope results to a specific repository')
    func_parser.set_defaults(func=cmd_function)

    # Call graph command
    cg_parser = subparsers.add_parser('callgraph', help='Get call graph')
    cg_parser.add_argument('function_id', help='Function ID')
    cg_parser.add_argument('--depth', type=int, default=2, help='Traversal depth')
    cg_parser.add_argument('--repo-id', default=None, help='Scope results to a specific repository')
    cg_parser.set_defaults(func=cmd_callgraph)

    # Serve command
    serve_parser = subparsers.add_parser('serve', help='Start MCP server')
    serve_parser.set_defaults(func=cmd_serve)

    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show statistics')
    stats_parser.set_defaults(func=cmd_stats)

    # Check-staleness command
    stale_parser = subparsers.add_parser('check-staleness',
                                         help='Check if a repository index is stale (exit 0 = fresh, 1 = stale)')
    stale_parser.add_argument('--repo-id', required=True, help='Repository ID to check')
    stale_parser.add_argument('--max-age-hours', type=float, default=24.0,
                              help='Maximum acceptable index age in hours (default: 24)')
    stale_parser.set_defaults(func=cmd_check_staleness)

    # Hooks command group
    hooks_parser = subparsers.add_parser('hooks', help='Manage git hooks')
    hooks_sub = hooks_parser.add_subparsers(dest='hooks_command', help='Hook commands')

    # hooks install
    hooks_install = hooks_sub.add_parser('install', help='Install code-kag git hooks')
    hooks_install.add_argument('repo_path', help='Path to the git repository')
    hooks_install.add_argument('--id', help='Repository ID (default: directory name)')
    hooks_install.add_argument('--mode', choices=['incremental', 'full'],
                               default='incremental',
                               help='Re-indexing mode (default: incremental)')
    hooks_install.set_defaults(func=cmd_hooks_install)

    # hooks uninstall
    hooks_uninstall = hooks_sub.add_parser('uninstall', help='Uninstall code-kag git hooks')
    hooks_uninstall.add_argument('repo_path', help='Path to the git repository')
    hooks_uninstall.set_defaults(func=cmd_hooks_uninstall)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == 'hooks' and (not hasattr(args, 'hooks_command') or args.hooks_command is None):
        hooks_parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == '__main__':
    main()
