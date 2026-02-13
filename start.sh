#!/bin/bash
# =============================================================================
# Code-KAG Easy Setup Script
# =============================================================================
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# =============================================================================
# Help
# =============================================================================
show_help() {
    cat << EOF
Code-KAG - Code Knowledge Graph Setup

USAGE:
    ./start.sh [COMMAND] [OPTIONS]

COMMANDS:
    start               Start Neo4j database (default)
    index <path>        Index a repository
    status              Show status of services
    stop                Stop all services
    clean               Stop and remove all data
    logs                Show logs
    shell               Open CLI shell
    help                Show this help

EXAMPLES:
    # Start Neo4j database
    ./start.sh start

    # Index a repository
    ./start.sh index /path/to/my/project

    # Index with custom ID
    ./start.sh index /path/to/project my-project-id

    # Check status
    ./start.sh status

    # View logs
    ./start.sh logs

    # Stop everything
    ./start.sh stop

ENVIRONMENT VARIABLES:
    NEO4J_PASSWORD      Password for Neo4j (set in .env file)
    NEO4J_PORT          Neo4j browser port (default: 7474)
    BOLT_PORT           Neo4j bolt port (default: 7687)

EOF
}

# =============================================================================
# Commands
# =============================================================================

cmd_start() {
    print_step "Starting Neo4j database..."
    docker-compose up -d neo4j
    
    print_step "Waiting for Neo4j to be healthy..."
    local retries=30
    while [ $retries -gt 0 ]; do
        if docker-compose ps neo4j | grep -q "healthy"; then
            break
        fi
        echo -n "."
        sleep 2
        retries=$((retries - 1))
    done
    echo ""
    
    if [ $retries -eq 0 ]; then
        print_error "Neo4j failed to start. Check logs with: ./start.sh logs"
        exit 1
    fi
    
    print_success "Neo4j is running!"
    echo ""
    echo "  Browser UI: http://localhost:${NEO4J_PORT:-7474}"
    echo "  Username:   neo4j"
    echo "  Password:   (from .env file)"
    echo ""
    print_step "Next: Index a repository with: ./start.sh index /path/to/code"
}

cmd_index() {
    local repo_path="$1"
    local repo_id="$2"
    
    if [ -z "$repo_path" ]; then
        print_error "Please provide a path to index"
        echo "Usage: ./start.sh index /path/to/repository [repo-id]"
        exit 1
    fi
    
    # Convert to absolute path
    repo_path=$(cd "$repo_path" 2>/dev/null && pwd || echo "$repo_path")
    
    if [ ! -d "$repo_path" ]; then
        print_error "Directory not found: $repo_path"
        exit 1
    fi
    
    # Default repo ID to directory name
    if [ -z "$repo_id" ]; then
        repo_id=$(basename "$repo_path")
    fi
    
    print_step "Indexing repository: $repo_path"
    print_step "Repository ID: $repo_id"
    echo ""
    
    # Make sure Neo4j is running
    if ! docker-compose ps neo4j | grep -q "running"; then
        print_warning "Neo4j is not running. Starting..."
        cmd_start
    fi
    
    # Run indexer
    CODE_PATH="$repo_path" REPO_ID="$repo_id" docker-compose run --rm indexer
    
    print_success "Indexing complete!"
    echo ""
    echo "View your graph at: http://localhost:${NEO4J_PORT:-7474}"
    echo ""
    echo "Try this Cypher query to see your code:"
    echo "  MATCH (n) RETURN n LIMIT 100"
}

cmd_status() {
    print_step "Service Status:"
    docker-compose ps
    echo ""
    
    # Check Neo4j stats
    if docker-compose ps neo4j | grep -q "running"; then
        print_step "Repository Statistics:"
        docker-compose run --rm --entrypoint python code-kag cli.py stats 2>/dev/null || \
            print_warning "Could not fetch stats (is Neo4j healthy?)"
    fi
}

cmd_stop() {
    print_step "Stopping services..."
    docker-compose down
    print_success "All services stopped"
}

cmd_clean() {
    print_warning "This will delete ALL data including the Neo4j database!"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_step "Stopping and removing everything..."
        docker-compose down -v --remove-orphans
        print_success "All data cleaned"
    else
        print_step "Cancelled"
    fi
}

cmd_logs() {
    docker-compose logs -f
}

cmd_shell() {
    print_step "Opening Code-KAG CLI shell..."
    docker-compose run --rm --entrypoint bash code-kag
}

cmd_mcp() {
    print_step "Starting MCP server..."
    docker-compose up -d code-kag
    print_success "MCP server is running"
    echo ""
    echo "Add this to your Claude Desktop config:"
    cat << EOF

{
  "mcpServers": {
    "code-kag": {
      "command": "docker",
      "args": ["exec", "-i", "code-kag-server", "python", "src/mcp_server.py"]
    }
  }
}

EOF
}

# =============================================================================
# Main
# =============================================================================

# Change to script directory
cd "$(dirname "$0")"

case "${1:-start}" in
    start)
        cmd_start
        ;;
    index)
        cmd_index "$2" "$3"
        ;;
    status)
        cmd_status
        ;;
    stop)
        cmd_stop
        ;;
    clean)
        cmd_clean
        ;;
    logs)
        cmd_logs
        ;;
    shell)
        cmd_shell
        ;;
    mcp)
        cmd_mcp
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
