"""
Code Knowledge Graph (Code-KAG)
A knowledge graph system for code search and context retrieval
"""

__version__ = "0.1.0"

from .models import (
    Repository, File, Module, Class, Function, 
    Variable, Import, Interface, ParsedCodebase
)
from .parser import CodebaseParser, parse_repository
from .neo4j_ingester import Neo4jIngester, CodeKAGQuerier, ingest_repository

__all__ = [
    # Models
    'Repository', 'File', 'Module', 'Class', 'Function',
    'Variable', 'Import', 'Interface', 'ParsedCodebase',
    # Parser
    'CodebaseParser', 'parse_repository',
    # Neo4j
    'Neo4jIngester', 'CodeKAGQuerier', 'ingest_repository',
]
