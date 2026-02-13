#!/usr/bin/env python3
"""
Test script for Code-KAG
Demonstrates parsing capabilities without requiring Neo4j
"""
import os
import sys
import json
import tempfile
import shutil

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import parse_repository
from src.models import ParsedCodebase


# Sample Python code to parse
SAMPLE_CODE = '''
"""
Sample module for testing Code-KAG parser
"""
import os
from typing import List, Optional
from dataclasses import dataclass


MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30


@dataclass
class Config:
    """Configuration settings for the application"""
    host: str
    port: int
    debug: bool = False
    
    def to_dict(self) -> dict:
        """Convert config to dictionary"""
        return {
            'host': self.host,
            'port': self.port,
            'debug': self.debug
        }


class BaseService:
    """Base class for all services"""
    
    def __init__(self, config: Config):
        self.config = config
        self._initialized = False
    
    def initialize(self) -> bool:
        """Initialize the service"""
        self._initialized = True
        return True


class DatabaseService(BaseService):
    """Service for database operations"""
    
    connection_count: int = 0
    
    def __init__(self, config: Config, db_url: str):
        super().__init__(config)
        self.db_url = db_url
        self._connection = None
    
    async def connect(self) -> bool:
        """Establish database connection"""
        if self._connection:
            return True
        
        for attempt in range(MAX_RETRIES):
            try:
                self._connection = self._create_connection()
                DatabaseService.connection_count += 1
                return True
            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    raise
        return False
    
    def _create_connection(self):
        """Create actual database connection"""
        # Implementation details
        pass
    
    def execute_query(self, query: str, params: Optional[dict] = None) -> List[dict]:
        """Execute a database query"""
        if not self._connection:
            raise RuntimeError("Not connected")
        
        result = self._run_query(query, params)
        return self._process_results(result)
    
    def _run_query(self, query: str, params: dict) -> any:
        """Run the actual query"""
        pass
    
    def _process_results(self, result: any) -> List[dict]:
        """Process query results"""
        return []


def create_service(config: Config) -> DatabaseService:
    """Factory function to create a database service"""
    db_url = os.getenv('DATABASE_URL', 'localhost:5432')
    service = DatabaseService(config, db_url)
    service.initialize()
    return service


def main():
    """Main entry point"""
    config = Config(host='localhost', port=8080, debug=True)
    service = create_service(config)
    print("Service created:", service)


if __name__ == '__main__':
    main()
'''


def create_sample_repo():
    """Create a temporary repository with sample code"""
    temp_dir = tempfile.mkdtemp(prefix='code-kag-test-')
    
    # Create structure
    os.makedirs(os.path.join(temp_dir, 'src'))
    os.makedirs(os.path.join(temp_dir, 'src', 'services'))
    
    # Write main module
    with open(os.path.join(temp_dir, 'src', 'main.py'), 'w') as f:
        f.write(SAMPLE_CODE)
    
    # Write __init__ files
    with open(os.path.join(temp_dir, 'src', '__init__.py'), 'w') as f:
        f.write('"""Source package"""')
    
    with open(os.path.join(temp_dir, 'src', 'services', '__init__.py'), 'w') as f:
        f.write('"""Services package"""')
    
    # Add another file
    service_code = '''
"""Additional service module"""
from .main import BaseService, Config


class CacheService(BaseService):
    """Caching service"""
    
    def __init__(self, config: Config):
        super().__init__(config)
        self._cache = {}
    
    def get(self, key: str):
        """Get value from cache"""
        return self._cache.get(key)
    
    def set(self, key: str, value: any, ttl: int = 3600):
        """Set value in cache"""
        self._cache[key] = value
'''
    with open(os.path.join(temp_dir, 'src', 'services', 'cache.py'), 'w') as f:
        f.write(service_code)
    
    return temp_dir


def print_entity(entity, indent=2):
    """Pretty print an entity"""
    prefix = ' ' * indent
    d = entity.to_dict()
    for k, v in d.items():
        if v and str(v).strip():
            print(f"{prefix}{k}: {v}")


def main():
    print("=" * 60)
    print("Code-KAG Parser Test")
    print("=" * 60)
    
    # Create sample repository
    print("\n📁 Creating sample repository...")
    repo_path = create_sample_repo()
    print(f"   Created at: {repo_path}")
    
    try:
        # Parse the repository
        print("\n🔍 Parsing repository...")
        codebase = parse_repository(repo_path, repo_id="test-repo")
        
        # Print statistics
        stats = codebase.get_stats()
        print("\n📊 Statistics:")
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        # Print files
        print("\n📄 Files:")
        for f in codebase.files:
            print(f"   - {f.path} ({f.lines_of_code} lines)")
        
        # Print modules
        if codebase.modules:
            print("\n📦 Modules:")
            for m in codebase.modules:
                print(f"   - {m.name} ({m.module_type})")
        
        # Print classes
        print("\n🏛️  Classes:")
        for cls in codebase.classes:
            bases = cls.base_classes
            base_str = f" extends {', '.join(bases)}" if bases else ""
            print(f"   - {cls.name}{base_str}")
            if cls.docstring:
                print(f"     \"{cls.docstring[:50]}...\"" if len(cls.docstring) > 50 else f"     \"{cls.docstring}\"")
        
        # Print functions
        print("\n⚡ Functions:")
        for func in codebase.functions:
            method_str = " (method)" if func.is_method else ""
            async_str = " async" if func.is_async else ""
            print(f"   - {func.name}{async_str}{method_str}")
            print(f"     Signature: {func.signature}")
            print(f"     Lines: {func.start_line}-{func.end_line}, Complexity: {func.complexity}")
        
        # Print relationships
        print("\n🔗 Sample Relationships:")
        rel_types = {}
        for rel in codebase.relationships:
            if rel.rel_type not in rel_types:
                rel_types[rel.rel_type] = []
            rel_types[rel.rel_type].append(rel)
        
        for rel_type, rels in rel_types.items():
            print(f"\n   {rel_type} ({len(rels)} total):")
            for rel in rels[:3]:  # Show first 3 of each type
                print(f"     {rel.source_id} -> {rel.target_id}")
            if len(rels) > 3:
                print(f"     ... and {len(rels) - 3} more")
        
        # Export sample JSON
        print("\n💾 Sample JSON output (first class):")
        if codebase.classes:
            print(json.dumps(codebase.classes[0].to_dict(), indent=2))
        
        print("\n✅ Parser test completed successfully!")
        print("\n📝 Next steps:")
        print("   1. Start Neo4j: docker-compose up -d")
        print("   2. Set credentials: export NEO4J_PASSWORD=your-password")
        print("   3. Index your real repo: python cli.py index /path/to/your/code")
        print("   4. Start MCP server: python cli.py serve")
        
    finally:
        # Cleanup
        print(f"\n🧹 Cleaning up {repo_path}")
        shutil.rmtree(repo_path)


if __name__ == '__main__':
    main()
