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
    
    print(f"Indexing repository: {args.path}")
    stats = ingest_repository(
        args.path,
        repo_id=args.id,
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password
    )
    print(f"Indexing complete!")
    print(f"Statistics: {json.dumps(stats, indent=2)}")


def cmd_search(args):
    """Search the code knowledge graph"""
    from src.neo4j_ingester import CodeKAGQuerier
    
    q = CodeKAGQuerier(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    q.connect()
    
    try:
        results = q.semantic_code_search(args.query, args.limit)
        print(json.dumps(results, indent=2))
    finally:
        q.close()


def cmd_function(args):
    """Get function details"""
    from src.neo4j_ingester import CodeKAGQuerier
    
    q = CodeKAGQuerier(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    q.connect()
    
    try:
        results = q.find_function_by_name(args.name)
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
        result = q.get_function_callgraph(args.function_id, args.depth)
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
                OPTIONAL MATCH (r)-[:CONTAINS_MODULE]->(m:Module)
                WITH r, count(DISTINCT f) AS files, count(DISTINCT m) AS modules
                MATCH (c:Class)
                WITH r, files, modules, count(c) AS classes
                MATCH (func:Function)
                RETURN r.id AS repo, r.name AS name, r.path AS path,
                       files, modules, classes, count(func) AS functions
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


def main():
    parser = argparse.ArgumentParser(
        description="Code Knowledge Graph CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Index a repository
  python cli.py index /path/to/repo --id my-project
  
  # Search for code
  python cli.py search "database connection"
  
  # Get function details
  python cli.py function parse_config
  
  # Start MCP server
  python cli.py serve
  
  # Show statistics
  python cli.py stats
"""
    )
    
    # Global arguments
    parser.add_argument('--neo4j-uri', default=os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
                        help='Neo4j connection URI')
    parser.add_argument('--neo4j-user', default=os.getenv('NEO4J_USERNAME', 'neo4j'),
                        help='Neo4j username')
    parser.add_argument('--neo4j-password', default=os.getenv('NEO4J_PASSWORD', 'password'),
                        help='Neo4j password')
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Index command
    index_parser = subparsers.add_parser('index', help='Index a repository')
    index_parser.add_argument('path', help='Path to the repository')
    index_parser.add_argument('--id', help='Repository ID (default: directory name)')
    index_parser.set_defaults(func=cmd_index)
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search code')
    search_parser.add_argument('query', help='Search query')
    search_parser.add_argument('--limit', type=int, default=10, help='Max results')
    search_parser.set_defaults(func=cmd_search)
    
    # Function command
    func_parser = subparsers.add_parser('function', help='Get function details')
    func_parser.add_argument('name', help='Function name')
    func_parser.set_defaults(func=cmd_function)
    
    # Call graph command
    cg_parser = subparsers.add_parser('callgraph', help='Get call graph')
    cg_parser.add_argument('function_id', help='Function ID')
    cg_parser.add_argument('--depth', type=int, default=2, help='Traversal depth')
    cg_parser.set_defaults(func=cmd_callgraph)
    
    # Serve command
    serve_parser = subparsers.add_parser('serve', help='Start MCP server')
    serve_parser.set_defaults(func=cmd_serve)
    
    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show statistics')
    stats_parser.set_defaults(func=cmd_stats)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == '__main__':
    main()
