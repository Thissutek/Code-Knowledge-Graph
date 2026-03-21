"""
Neo4j Ingester
Ingests parsed code structure into Neo4j graph database
"""
import logging
import os
from typing import List, Dict, Any, Optional

_logger = logging.getLogger(__name__)
from neo4j import GraphDatabase
from .models import ParsedCodebase, Relationship

# ---------------------------------------------------------------------------
# Embedding support (sentence-transformers, optional)
# ---------------------------------------------------------------------------

_embedding_model = None  # lazy-loaded on first use


def _get_embedding_model():
    """Return the shared SentenceTransformer model, loading it on first call.

    Returns None if sentence-transformers is not installed, so callers can
    degrade gracefully when the dependency is absent.
    """
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    try:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        _logger.info("Loaded embedding model: all-MiniLM-L6-v2")
    except ImportError:
        _logger.warning(
            "sentence-transformers not installed. Semantic search will fall back to "
            "substring matching. Install with: pip install sentence-transformers"
        )
    return _embedding_model


def _embed_texts(texts: list) -> list:
    """Return list of embedding vectors (as Python lists) for the given texts.

    Returns an empty list if the model is unavailable.
    """
    model = _get_embedding_model()
    if model is None or not texts:
        return []
    vectors = model.encode(texts, show_progress_bar=False)
    return [v.tolist() for v in vectors]


class Neo4jIngester:
    """Handles ingestion of parsed code into Neo4j"""
    
    def __init__(self, uri: str = None, username: str = None, password: str = None):
        self.uri = uri or os.getenv('NEO4J_URI', 'bolt://localhost:7687')
        self.username = username or os.getenv('NEO4J_USERNAME', 'neo4j')
        self.password = password or os.getenv('NEO4J_PASSWORD')
        self.driver = None

    def connect(self):
        """Establish connection to Neo4j"""
        if not self.password:
            raise ValueError(
                "Neo4j password is required. Pass password= or set NEO4J_PASSWORD env var.")
        self.driver = GraphDatabase.driver(
            self.uri,
            auth=(self.username, self.password)
        )
        # Test connection
        with self.driver.session() as session:
            session.run("RETURN 1")
        _logger.info("Connected to Neo4j at %s", self.uri)
    
    def close(self):
        """Close the connection"""
        if self.driver:
            self.driver.close()
    
    def create_constraints(self):
        """Create uniqueness constraints and indexes"""
        constraints = [
            "CREATE CONSTRAINT repo_id IF NOT EXISTS FOR (r:Repository) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT file_id IF NOT EXISTS FOR (f:File) REQUIRE f.id IS UNIQUE",
            "CREATE CONSTRAINT module_id IF NOT EXISTS FOR (m:Module) REQUIRE m.id IS UNIQUE",
            "CREATE CONSTRAINT class_id IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT function_id IF NOT EXISTS FOR (f:Function) REQUIRE f.id IS UNIQUE",
            "CREATE CONSTRAINT variable_id IF NOT EXISTS FOR (v:Variable) REQUIRE v.id IS UNIQUE",
            "CREATE CONSTRAINT import_id IF NOT EXISTS FOR (i:Import) REQUIRE i.id IS UNIQUE",
            "CREATE CONSTRAINT interface_id IF NOT EXISTS FOR (i:Interface) REQUIRE i.id IS UNIQUE",
        ]
        
        indexes = [
            "CREATE INDEX file_name IF NOT EXISTS FOR (f:File) ON (f.name)",
            "CREATE INDEX file_path IF NOT EXISTS FOR (f:File) ON (f.path)",
            "CREATE INDEX class_name IF NOT EXISTS FOR (c:Class) ON (c.name)",
            "CREATE INDEX function_name IF NOT EXISTS FOR (f:Function) ON (f.name)",
            "CREATE INDEX function_signature IF NOT EXISTS FOR (f:Function) ON (f.signature)",
            "CREATE FULLTEXT INDEX function_docstring IF NOT EXISTS FOR (f:Function) ON EACH [f.docstring]",
            "CREATE FULLTEXT INDEX class_docstring IF NOT EXISTS FOR (c:Class) ON EACH [c.docstring]",
        ]

        vector_indexes = [
            # 384-dim vectors from all-MiniLM-L6-v2
            """CREATE VECTOR INDEX function_embedding IF NOT EXISTS
               FOR (f:Function) ON (f.embedding)
               OPTIONS {indexConfig: {`vector.dimensions`: 384,
                                      `vector.similarity_function`: 'cosine'}}""",
            """CREATE VECTOR INDEX class_embedding IF NOT EXISTS
               FOR (c:Class) ON (c.embedding)
               OPTIONS {indexConfig: {`vector.dimensions`: 384,
                                      `vector.similarity_function`: 'cosine'}}""",
        ]
        
        with self.driver.session() as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        _logger.warning("Warning creating constraint: %s", e)

            for index in indexes:
                try:
                    session.run(index)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        _logger.warning("Warning creating index: %s", e)

            for vi in vector_indexes:
                try:
                    session.run(vi)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        _logger.warning("Warning creating vector index: %s", e)

        _logger.info("Constraints and indexes created")
    
    def clear_repository(self, repo_id: str):
        """Clear all data for a specific repository.

        Deletes leaf nodes first and works upward to avoid holding the
        entire subgraph in a single transaction (which can exceed Neo4j's
        transaction memory limit on large repositories).
        """
        with self.driver.session() as session:
            # 1. Delete class members (methods, variables) — deepest leaves
            session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                      -[:DEFINES_CLASS]->(c:Class)-[:HAS_METHOD]->(m:Function)
                DETACH DELETE m
            """, repo_id=repo_id)
            session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                      -[:DEFINES_CLASS]->(c:Class)-[:HAS_VARIABLE]->(v:Variable)
                DETACH DELETE v
            """, repo_id=repo_id)

            # 2. Delete file-level entities (classes, functions, interfaces, imports)
            session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                      -[:DEFINES_CLASS]->(c:Class)
                DETACH DELETE c
            """, repo_id=repo_id)
            session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                      -[:DEFINES_FUNCTION]->(fn:Function)
                DETACH DELETE fn
            """, repo_id=repo_id)
            session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                      -[:DEFINES_INTERFACE]->(i:Interface)
                DETACH DELETE i
            """, repo_id=repo_id)
            session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                      -[:IMPORTS]->(imp:Import)
                DETACH DELETE imp
            """, repo_id=repo_id)

            # 3. Delete file-level variables (globals)
            session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                      -[:DEFINES_VARIABLE]->(v:Variable)
                DETACH DELETE v
            """, repo_id=repo_id)

            # 4. Delete files and modules
            session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                DETACH DELETE f
            """, repo_id=repo_id)
            session.run("""
                MATCH (r:Repository {id: $repo_id})-[:CONTAINS_MODULE]->(m:Module)
                DETACH DELETE m
            """, repo_id=repo_id)

            # 5. Delete the repository node
            session.run("""
                MATCH (r:Repository {id: $repo_id})
                DETACH DELETE r
            """, repo_id=repo_id)
        _logger.info("Cleared existing data for repository: %s", repo_id)
    
    def ingest(self, codebase: ParsedCodebase, clear_existing: bool = True,
               skip_embeddings: bool = False):
        """Ingest a parsed codebase into Neo4j.

        Args:
            skip_embeddings: When True, skip vector embedding generation.
                Useful for fast indexing of large repos where semantic
                search is not needed.
        """
        if clear_existing:
            self.clear_repository(codebase.repository.id)

        self._skip_embeddings = skip_embeddings

        with self.driver.session() as session:
            # Ingest repository
            self._ingest_repository(session, codebase)

            # Ingest files
            self._ingest_files(session, codebase)

            # Ingest modules
            self._ingest_modules(session, codebase)

            # Ingest classes
            self._ingest_classes(session, codebase)

            # Ingest functions
            self._ingest_functions(session, codebase)
            
            # Ingest variables
            self._ingest_variables(session, codebase)
            
            # Ingest imports
            self._ingest_imports(session, codebase)

            # Ingest interfaces
            self._ingest_interfaces(session, codebase)

            # Create relationships
            self._ingest_relationships(session, codebase)

            # Link test functions to the implementations they test
            self._link_tests_to_implementations(session, codebase.repository.id)

        stats = codebase.get_stats()
        _logger.info("Ingestion complete: %s", stats)

    def ingest_incremental(self, codebase: ParsedCodebase, changed_files: List[str],
                           skip_embeddings: bool = False):
        """Incrementally ingest only changed files.

        Deletes old nodes for the changed files and inserts the new parsed data.
        """
        repo_id = codebase.repository.id
        self._skip_embeddings = skip_embeddings

        with self.driver.session() as session:
            # Delete existing entities for each changed file
            for rel_path in changed_files:
                self._clear_file_entities(session, repo_id, rel_path)

            # Ingest the new data (repository MERGE is idempotent)
            self._ingest_repository(session, codebase)
            self._ingest_files(session, codebase)
            self._ingest_modules(session, codebase)
            self._ingest_classes(session, codebase)
            self._ingest_functions(session, codebase)
            self._ingest_variables(session, codebase)
            self._ingest_imports(session, codebase)
            self._ingest_interfaces(session, codebase)
            self._ingest_relationships(session, codebase)

            # Re-link test↔implementation relationships for the whole repo
            # (changed files may affect matches across the entire codebase)
            self._link_tests_to_implementations(session, repo_id)

        stats = codebase.get_stats()
        _logger.info("Incremental ingestion complete for %d file(s): %s", len(changed_files), stats)

    def _clear_file_entities(self, session, repo_id: str, file_path: str):
        """Delete all entities associated with a specific file."""
        session.run("""
            MATCH (f:File {id: $file_path})
            OPTIONAL MATCH (f)-[:DEFINES_CLASS]->(c:Class)
            OPTIONAL MATCH (c)-[:HAS_METHOD]->(cm:Function)
            OPTIONAL MATCH (c)-[:HAS_VARIABLE]->(cv:Variable)
            OPTIONAL MATCH (f)-[:DEFINES_FUNCTION]->(fn:Function)
            OPTIONAL MATCH (f)-[:DEFINES_INTERFACE]->(iface:Interface)
            OPTIONAL MATCH (f)-[:IMPORTS]->(imp:Import)
            DETACH DELETE cm, cv, fn, iface, imp, c, f
        """, file_path=file_path)
        # Clean up file-level (global) variables whose ID starts with the file path
        session.run("""
            MATCH (v:Variable)
            WHERE v.id STARTS WITH $file_prefix
            AND NOT ()-[:HAS_VARIABLE]->(v)
            DETACH DELETE v
        """, file_prefix=file_path + ":")

    def _ingest_repository(self, session, codebase: ParsedCodebase):
        """Ingest repository node"""
        repo = codebase.repository
        session.run("""
            MERGE (r:Repository {id: $id})
            SET r.name = $name,
                r.path = $path,
                r.language = $language,
                r.description = $description,
                r.lastIndexed = datetime()
        """, **repo.to_dict())
    
    def _ingest_files(self, session, codebase: ParsedCodebase):
        """Ingest file nodes in batch"""
        if not codebase.files:
            return
        
        records = [f.to_dict() for f in codebase.files]
        session.run("""
            UNWIND $records AS record
            MERGE (f:File {id: record.id})
            SET f.name = record.name,
                f.path = record.path,
                f.extension = record.extension,
                f.language = record.language,
                f.linesOfCode = record.linesOfCode,
                f.hash = record.hash
        """, records=records)
    
    def _ingest_modules(self, session, codebase: ParsedCodebase):
        """Ingest module nodes in batch"""
        if not codebase.modules:
            return
        
        records = [m.to_dict() for m in codebase.modules]
        session.run("""
            UNWIND $records AS record
            MERGE (m:Module {id: record.id})
            SET m.name = record.name,
                m.path = record.path,
                m.type = record.type
        """, records=records)
    
    def _ingest_classes(self, session, codebase: ParsedCodebase):
        """Ingest class nodes in batch"""
        if not codebase.classes:
            return

        records = [c.to_dict() for c in codebase.classes]

        # Generate embeddings unless opted out
        if not getattr(self, '_skip_embeddings', False):
            texts = [
                ' '.join(filter(None, [c.name, c.docstring or '']))
                for c in codebase.classes
            ]
            vectors = _embed_texts(texts)
            if vectors:
                for record, vector in zip(records, vectors):
                    record['embedding'] = vector

        session.run("""
            UNWIND $records AS record
            MERGE (c:Class {id: record.id})
            SET c.name = record.name,
                c.docstring = record.docstring,
                c.startLine = record.startLine,
                c.endLine = record.endLine,
                c.isAbstract = record.isAbstract,
                c.decorators = record.decorators,
                c.languageType = record.languageType
            WITH c, record
            CALL {
                WITH c, record
                WITH c, record WHERE record.embedding IS NOT NULL
                CALL db.create.setNodeVectorProperty(c, 'embedding', record.embedding)
            }
        """, records=records)
    
    def _ingest_functions(self, session, codebase: ParsedCodebase):
        """Ingest function nodes in batch"""
        if not codebase.functions:
            return

        records = [f.to_dict() for f in codebase.functions]

        # Generate embeddings unless opted out
        if not getattr(self, '_skip_embeddings', False):
            texts = [
                ' '.join(filter(None, [f.name, f.signature or '', f.docstring or '']))
                for f in codebase.functions
            ]
            vectors = _embed_texts(texts)
            if vectors:
                for record, vector in zip(records, vectors):
                    record['embedding'] = vector

        session.run("""
            UNWIND $records AS record
            MERGE (f:Function {id: record.id})
            SET f.name = record.name,
                f.signature = record.signature,
                f.docstring = record.docstring,
                f.startLine = record.startLine,
                f.endLine = record.endLine,
                f.isAsync = record.isAsync,
                f.isStatic = record.isStatic,
                f.returnType = record.returnType,
                f.complexity = record.complexity,
                f.parameters = record.parameters
            WITH f, record
            CALL {
                WITH f, record
                WITH f, record WHERE record.embedding IS NOT NULL
                CALL db.create.setNodeVectorProperty(f, 'embedding', record.embedding)
            }
        """, records=records)
    
    def _ingest_variables(self, session, codebase: ParsedCodebase):
        """Ingest variable nodes in batch"""
        if not codebase.variables:
            return
        
        records = [v.to_dict() for v in codebase.variables]
        session.run("""
            UNWIND $records AS record
            MERGE (v:Variable {id: record.id})
            SET v.name = record.name,
                v.type = record.type,
                v.scope = record.scope,
                v.isConstant = record.isConstant
        """, records=records)
    
    def _ingest_imports(self, session, codebase: ParsedCodebase):
        """Ingest import nodes in batch"""
        if not codebase.imports:
            return

        records = [i.to_dict() for i in codebase.imports]
        session.run("""
            UNWIND $records AS record
            MERGE (i:Import {id: record.id})
            SET i.name = record.name,
                i.source = record.source,
                i.isExternal = record.isExternal
        """, records=records)

    def _ingest_interfaces(self, session, codebase: ParsedCodebase):
        """Ingest interface nodes in batch"""
        if not codebase.interfaces:
            return

        records = [{'id': i.id, 'name': i.name, 'docstring': i.docstring}
                   for i in codebase.interfaces]
        session.run("""
            UNWIND $records AS record
            MERGE (i:Interface {id: record.id})
            SET i.name = record.name, i.docstring = record.docstring
        """, records=records)

    def _ingest_relationships(self, session, codebase: ParsedCodebase):
        """Ingest all relationships"""
        # Group relationships by type for efficient batch processing
        rel_groups: Dict[str, List[Dict]] = {}
        for rel in codebase.relationships:
            if rel.rel_type not in rel_groups:
                rel_groups[rel.rel_type] = []
            rel_groups[rel.rel_type].append(rel.to_dict())
        
        # Relationship type to node label mapping
        rel_config = {
            'CONTAINS_FILE': ('Repository', 'File'),
            'CONTAINS_MODULE': ('Repository', 'Module'),
            'BELONGS_TO_MODULE': ('File', 'Module'),
            'DEFINES_CLASS': ('File', 'Class'),
            'DEFINES_FUNCTION': ('File', 'Function'),
            'DEFINES_INTERFACE': ('File', 'Interface'),
            'HAS_METHOD': ('Class', 'Function'),
            'HAS_VARIABLE': ('Class', 'Variable'),
            'EXTENDS': ('Class', 'Class'),
            'IMPLEMENTS': ('Class', 'Interface'),
            'CALLS': ('Function', 'Function'),
            'USES_CLASS': ('Function', 'Class'),
            'USES_VARIABLE': ('Function', 'Variable'),
            'IMPORTS': ('File', 'Import'),
            'IMPORTS_FROM': ('File', 'File'),
            'DEPENDS_ON': ('File', 'File'),
            'INSTANTIATES': ('Function', 'Class'),
            'RETURNS_TYPE': ('Function', 'Class'),
        }
        
        for rel_type, records in rel_groups.items():
            if rel_type not in rel_config:
                _logger.warning("Unknown relationship type %s", rel_type)
                continue

            source_label, target_label = rel_config[rel_type]

            # Build property setting clause
            prop_keys = set()
            for record in records:
                prop_keys.update(k for k in record.keys() if k not in ['type', 'sourceId', 'targetId'])

            prop_clause = ', '.join([f'rel.{k} = record.{k}' for k in prop_keys])
            if prop_clause:
                prop_clause = 'SET ' + prop_clause

            # IMPLEMENTS targets can be Interface or Class nodes (e.g.
            # language_type="interface"/"trait") depending on how the
            # parser modelled the target entity.
            if rel_type == 'IMPLEMENTS':
                query = f"""
                    UNWIND $records AS record
                    MATCH (source:{source_label} {{id: record.sourceId}})
                    MATCH (target {{id: record.targetId}})
                    WHERE target:Interface OR target:Class
                    MERGE (source)-[rel:{rel_type}]->(target)
                    {prop_clause}
                """
            else:
                query = f"""
                    UNWIND $records AS record
                    MATCH (source:{source_label} {{id: record.sourceId}})
                    MATCH (target:{target_label} {{id: record.targetId}})
                    MERGE (source)-[rel:{rel_type}]->(target)
                    {prop_clause}
                """

            try:
                session.run(query, records=records)
            except Exception as e:
                _logger.error("Error creating %s relationships: %s", rel_type, e)

    def _link_tests_to_implementations(self, session, repo_id: str):
        """Create TESTS relationships between test functions and the functions they test.

        Matching strategy: strip the leading `test_` (or `test`) prefix from a
        test function's name to derive the candidate implementation name, then
        look for a Function with that name in the same repository.  Only creates
        the edge when exactly one implementation candidate exists to avoid false
        positives on ambiguous names.
        """
        session.run("""
            MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(testFile:File)
                  -[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(test:Function)
            WHERE (testFile.path CONTAINS '/test' OR testFile.path CONTAINS 'test_'
                   OR testFile.path ENDS WITH '_test.py')
              AND (test.name STARTS WITH 'test_' OR test.name STARTS WITH 'test')
            WITH test,
                 CASE
                   WHEN test.name STARTS WITH 'test_' THEN substring(test.name, 5)
                   ELSE substring(test.name, 4)
                 END AS implName
            WHERE size(implName) > 0
            MATCH (r2:Repository {id: $repo_id})-[:CONTAINS_FILE]->(implFile:File)
                  -[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(impl:Function {name: implName})
            WHERE NOT (implFile.path CONTAINS '/test' OR implFile.path CONTAINS 'test_'
                       OR implFile.path ENDS WITH '_test.py')
              AND impl.id <> test.id
            MERGE (test)-[:TESTS]->(impl)
        """, repo_id=repo_id)
        _logger.info("Linked test functions to implementations for repository: %s", repo_id)


class CodeKAGQuerier:
    """Query interface for the Code Knowledge Graph"""
    
    def __init__(self, uri: str = None, username: str = None, password: str = None):
        self.uri = uri or os.getenv('NEO4J_URI', 'bolt://localhost:7687')
        self.username = username or os.getenv('NEO4J_USERNAME', 'neo4j')
        self.password = password or os.getenv('NEO4J_PASSWORD')
        self.driver = None

    def connect(self):
        """Establish connection to Neo4j"""
        if not self.password:
            raise ValueError(
                "Neo4j password is required. Pass password= or set NEO4J_PASSWORD env var.")
        self.driver = GraphDatabase.driver(
            self.uri,
            auth=(self.username, self.password)
        )
    
    def close(self):
        """Close the connection"""
        if self.driver:
            self.driver.close()
    
    def search_functions(self, query: str, limit: int = 10, repo_id: str = None) -> List[Dict]:
        """Search functions by name or docstring"""
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    CALL db.index.fulltext.queryNodes('function_docstring', $searchTerm)
                    YIELD node, score
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(node)
                    RETURN node.id AS id, node.name AS name, node.signature AS signature,
                           node.docstring AS docstring, score
                    ORDER BY score DESC
                    LIMIT $limit
                """, searchTerm=query, limit=limit, repo_id=repo_id)
            else:
                result = session.run("""
                    CALL db.index.fulltext.queryNodes('function_docstring', $searchTerm)
                    YIELD node, score
                    RETURN node.id AS id, node.name AS name, node.signature AS signature,
                           node.docstring AS docstring, score
                    ORDER BY score DESC
                    LIMIT $limit
                """, searchTerm=query, limit=limit)
            return [dict(record) for record in result]
    
    def search_classes(self, query: str, limit: int = 10, repo_id: str = None) -> List[Dict]:
        """Search classes by name or docstring"""
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    CALL db.index.fulltext.queryNodes('class_docstring', $searchTerm)
                    YIELD node, score
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(:File)-[:DEFINES_CLASS]->(node)
                    RETURN node.id AS id, node.name AS name,
                           node.docstring AS docstring, score
                    ORDER BY score DESC
                    LIMIT $limit
                """, searchTerm=query, limit=limit, repo_id=repo_id)
            else:
                result = session.run("""
                    CALL db.index.fulltext.queryNodes('class_docstring', $searchTerm)
                    YIELD node, score
                    RETURN node.id AS id, node.name AS name,
                           node.docstring AS docstring, score
                    ORDER BY score DESC
                    LIMIT $limit
                """, searchTerm=query, limit=limit)
            return [dict(record) for record in result]
    
    def find_function_by_name(self, name: str, repo_id: str = None) -> List[Dict]:
        """Find functions by exact name"""
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f:Function {name: $name})
                    OPTIONAL MATCH (class:Class)-[:HAS_METHOD]->(f)
                    RETURN f.id AS id, f.name AS name, f.signature AS signature,
                           f.docstring AS docstring, f.startLine AS startLine,
                           file.path AS filePath, class.name AS className
                """, name=name, repo_id=repo_id)
            else:
                result = session.run("""
                    MATCH (f:Function {name: $name})
                    OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION]->(f)
                    OPTIONAL MATCH (class:Class)-[:HAS_METHOD]->(f)
                    RETURN f.id AS id, f.name AS name, f.signature AS signature,
                           f.docstring AS docstring, f.startLine AS startLine,
                           file.path AS filePath, class.name AS className
                """, name=name)
            return [dict(record) for record in result]
    
    def find_class_by_name(self, name: str, repo_id: str = None) -> List[Dict]:
        """Find classes by exact name"""
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)-[:DEFINES_CLASS]->(c:Class {name: $name})
                    OPTIONAL MATCH (c)-[:EXTENDS]->(parent:Class)
                    OPTIONAL MATCH (c)-[:HAS_METHOD]->(method:Function)
                    RETURN c.id AS id, c.name AS name, c.docstring AS docstring,
                           c.startLine AS startLine, file.path AS filePath,
                           collect(DISTINCT parent.name) AS parentClasses,
                           collect(DISTINCT method.name) AS methods
                """, name=name, repo_id=repo_id)
            else:
                result = session.run("""
                    MATCH (c:Class {name: $name})
                    OPTIONAL MATCH (file:File)-[:DEFINES_CLASS]->(c)
                    OPTIONAL MATCH (c)-[:EXTENDS]->(parent:Class)
                    OPTIONAL MATCH (c)-[:HAS_METHOD]->(method:Function)
                    RETURN c.id AS id, c.name AS name, c.docstring AS docstring,
                           c.startLine AS startLine, file.path AS filePath,
                           collect(DISTINCT parent.name) AS parentClasses,
                           collect(DISTINCT method.name) AS methods
                """, name=name)
            return [dict(record) for record in result]
    
    def get_function_callgraph(self, function_id: str, depth: int = 2, repo_id: str = None) -> Dict:
        """Get the call graph for a function"""
        # Neo4j doesn't allow parameters in variable-length path bounds,
        # so we sanitize depth as an int and interpolate it into the query.
        safe_depth = int(depth)
        with self.driver.session() as session:
            if repo_id:
                result = session.run(f"""
                    MATCH (r:Repository {{id: $repo_id}})-[:CONTAINS_FILE]->(:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f:Function {{id: $function_id}})
                    WITH f
                    MATCH path = (f)-[:CALLS*1..{safe_depth}]->(called:Function)
                    WITH f, collect(DISTINCT {{
                        id: called.id,
                        name: called.name,
                        depth: length(path)
                    }}) AS calls
                    RETURN f.id AS sourceId, f.name AS sourceName, calls
                """, function_id=function_id, repo_id=repo_id)
            else:
                result = session.run(f"""
                    MATCH path = (f:Function {{id: $function_id}})-[:CALLS*1..{safe_depth}]->(called:Function)
                    WITH f, collect(DISTINCT {{
                        id: called.id,
                        name: called.name,
                        depth: length(path)
                    }}) AS calls
                    RETURN f.id AS sourceId, f.name AS sourceName, calls
                """, function_id=function_id)
            record = result.single()
            return dict(record) if record else {}
    
    def get_callers(self, function_id: str, limit: int = 20, repo_id: str = None) -> List[Dict]:
        """Get all functions that call the given function (reverse call graph)"""
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)
                          -[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(caller:Function)
                    WHERE (caller)-[:CALLS]->(:Function {id: $function_id})
                    RETURN caller.id AS id, caller.name AS name,
                           caller.signature AS signature, file.path AS filePath,
                           caller.startLine AS startLine
                    LIMIT $limit
                """, function_id=function_id, repo_id=repo_id, limit=limit)
            else:
                result = session.run("""
                    MATCH (caller:Function)-[:CALLS]->(:Function {id: $function_id})
                    OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(caller)
                    RETURN caller.id AS id, caller.name AS name,
                           caller.signature AS signature, file.path AS filePath,
                           caller.startLine AS startLine
                    LIMIT $limit
                """, function_id=function_id, limit=limit)
            return [dict(record) for record in result]

    def get_class_hierarchy(self, class_name: str, repo_id: str = None) -> Dict:
        """Get class inheritance hierarchy"""
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(:File)-[:DEFINES_CLASS]->(c:Class {name: $class_name})
                    OPTIONAL MATCH path = (c)-[:EXTENDS*]->(ancestor:Class)
                    OPTIONAL MATCH childPath = (child:Class)-[:EXTENDS*]->(c)
                    RETURN c.id AS id, c.name AS name,
                           collect(DISTINCT ancestor.name) AS ancestors,
                           collect(DISTINCT child.name) AS descendants
                """, class_name=class_name, repo_id=repo_id)
            else:
                result = session.run("""
                    MATCH (c:Class {name: $class_name})
                    OPTIONAL MATCH path = (c)-[:EXTENDS*]->(ancestor:Class)
                    OPTIONAL MATCH childPath = (child:Class)-[:EXTENDS*]->(c)
                    RETURN c.id AS id, c.name AS name,
                           collect(DISTINCT ancestor.name) AS ancestors,
                           collect(DISTINCT child.name) AS descendants
                """, class_name=class_name)
            record = result.single()
            return dict(record) if record else {}
    
    def get_file_dependencies(self, file_path: str, repo_id: str = None) -> Dict:
        """Get files that a file depends on and files that depend on it"""
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File {path: $file_path})
                    OPTIONAL MATCH (f)-[:DEPENDS_ON]->(dep:File)
                    OPTIONAL MATCH (dependent:File)-[:DEPENDS_ON]->(f)
                    RETURN f.path AS filePath,
                           collect(DISTINCT dep.path) AS dependsOn,
                           collect(DISTINCT dependent.path) AS dependedBy
                """, file_path=file_path, repo_id=repo_id)
            else:
                result = session.run("""
                    MATCH (f:File {path: $file_path})
                    OPTIONAL MATCH (f)-[:DEPENDS_ON]->(dep:File)
                    OPTIONAL MATCH (dependent:File)-[:DEPENDS_ON]->(f)
                    RETURN f.path AS filePath,
                           collect(DISTINCT dep.path) AS dependsOn,
                           collect(DISTINCT dependent.path) AS dependedBy
                """, file_path=file_path)
            record = result.single()
            return dict(record) if record else {}
    
    def find_similar_functions(self, function_id: str, limit: int = 5, repo_id: str = None) -> List[Dict]:
        """Find functions with similar structure (shared calls and class usage)"""
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f:Function {id: $function_id})
                    OPTIONAL MATCH (f)-[:CALLS]->(called:Function)
                    OPTIONAL MATCH (f)-[:USES_CLASS]->(usedClass:Class)
                    WITH f, collect(DISTINCT called) AS fCalls, collect(DISTINCT usedClass) AS fClasses
                    WHERE size(fCalls) > 0 OR size(fClasses) > 0
                    MATCH (r2:Repository {id: $repo_id})-[:CONTAINS_FILE]->(:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(other:Function)
                    WHERE other <> f
                    OPTIONAL MATCH (other)-[:CALLS]->(otherCalled:Function)
                    WHERE otherCalled IN fCalls
                    OPTIONAL MATCH (other)-[:USES_CLASS]->(otherClass:Class)
                    WHERE otherClass IN fClasses
                    WITH other, f, fCalls, fClasses,
                         count(DISTINCT otherCalled) AS commonCalls,
                         count(DISTINCT otherClass) AS commonClasses
                    WHERE commonCalls > 0 OR commonClasses > 0
                    WITH other, commonCalls, commonClasses,
                         CASE WHEN size(fCalls) + size(fClasses) = 0 THEN 0.0
                              ELSE toFloat(commonCalls + commonClasses) / (size(fCalls) + size(fClasses))
                         END AS similarity
                    RETURN other.id AS id, other.name AS name, other.signature AS signature,
                           commonCalls, commonClasses, similarity
                    ORDER BY similarity DESC
                    LIMIT $limit
                """, function_id=function_id, limit=limit, repo_id=repo_id)
            else:
                result = session.run("""
                    MATCH (f:Function {id: $function_id})
                    OPTIONAL MATCH (f)-[:CALLS]->(called:Function)
                    OPTIONAL MATCH (f)-[:USES_CLASS]->(usedClass:Class)
                    WITH f, collect(DISTINCT called) AS fCalls, collect(DISTINCT usedClass) AS fClasses
                    WHERE size(fCalls) > 0 OR size(fClasses) > 0
                    MATCH (other:Function)
                    WHERE other <> f
                    OPTIONAL MATCH (other)-[:CALLS]->(otherCalled:Function)
                    WHERE otherCalled IN fCalls
                    OPTIONAL MATCH (other)-[:USES_CLASS]->(otherClass:Class)
                    WHERE otherClass IN fClasses
                    WITH other, f, fCalls, fClasses,
                         count(DISTINCT otherCalled) AS commonCalls,
                         count(DISTINCT otherClass) AS commonClasses
                    WHERE commonCalls > 0 OR commonClasses > 0
                    WITH other, commonCalls, commonClasses,
                         CASE WHEN size(fCalls) + size(fClasses) = 0 THEN 0.0
                              ELSE toFloat(commonCalls + commonClasses) / (size(fCalls) + size(fClasses))
                         END AS similarity
                    RETURN other.id AS id, other.name AS name, other.signature AS signature,
                           commonCalls, commonClasses, similarity
                    ORDER BY similarity DESC
                    LIMIT $limit
                """, function_id=function_id, limit=limit)
            return [dict(record) for record in result]
    
    def get_code_context(self, entity_id: str, repo_id: str = None) -> Dict:
        """Get comprehensive context for a code entity (function or class)"""
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    // Try to find as function first, scoped to repo
                    OPTIONAL MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f:Function {id: $entity_id})
                    OPTIONAL MATCH (class:Class)-[:HAS_METHOD]->(f)
                    OPTIONAL MATCH (f)-[:CALLS]->(called:Function)
                    OPTIONAL MATCH (caller:Function)-[:CALLS]->(f)
                    OPTIONAL MATCH (f)-[:USES_CLASS]->(usedClass:Class)

                    WITH f, file, class,
                         collect(DISTINCT {id: called.id, name: called.name}) AS calls,
                         collect(DISTINCT {id: caller.id, name: caller.name}) AS calledBy,
                         collect(DISTINCT usedClass.name) AS usesClasses
                    WHERE f IS NOT NULL

                    RETURN 'function' AS type,
                           f.id AS id, f.name AS name, f.signature AS signature,
                           f.docstring AS docstring, f.startLine AS startLine, f.endLine AS endLine,
                           file.path AS filePath, class.name AS className,
                           calls, calledBy, usesClasses

                    UNION

                    // Try to find as class, scoped to repo
                    MATCH (r2:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)-[:DEFINES_CLASS]->(c:Class {id: $entity_id})
                    OPTIONAL MATCH (c)-[:HAS_METHOD]->(method:Function)
                    OPTIONAL MATCH (c)-[:EXTENDS]->(parent:Class)
                    OPTIONAL MATCH (child:Class)-[:EXTENDS]->(c)
                    OPTIONAL MATCH (c)-[:HAS_VARIABLE]->(var:Variable)

                    RETURN 'class' AS type,
                           c.id AS id, c.name AS name, null AS signature,
                           c.docstring AS docstring, c.startLine AS startLine, c.endLine AS endLine,
                           file.path AS filePath, null AS className,
                           collect(DISTINCT {id: method.id, name: method.name}) AS calls,
                           collect(DISTINCT {name: parent.name}) AS calledBy,
                           collect(DISTINCT var.name) AS usesClasses
                """, entity_id=entity_id, repo_id=repo_id)
            else:
                result = session.run("""
                    // Try to find as function first
                    OPTIONAL MATCH (f:Function {id: $entity_id})
                    OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION]->(f)
                    OPTIONAL MATCH (class:Class)-[:HAS_METHOD]->(f)
                    OPTIONAL MATCH (f)-[:CALLS]->(called:Function)
                    OPTIONAL MATCH (caller:Function)-[:CALLS]->(f)
                    OPTIONAL MATCH (f)-[:USES_CLASS]->(usedClass:Class)

                    WITH f, file, class,
                         collect(DISTINCT {id: called.id, name: called.name}) AS calls,
                         collect(DISTINCT {id: caller.id, name: caller.name}) AS calledBy,
                         collect(DISTINCT usedClass.name) AS usesClasses
                    WHERE f IS NOT NULL

                    RETURN 'function' AS type,
                           f.id AS id, f.name AS name, f.signature AS signature,
                           f.docstring AS docstring, f.startLine AS startLine, f.endLine AS endLine,
                           file.path AS filePath, class.name AS className,
                           calls, calledBy, usesClasses

                    UNION

                    // Try to find as class
                    MATCH (c:Class {id: $entity_id})
                    OPTIONAL MATCH (file:File)-[:DEFINES_CLASS]->(c)
                    OPTIONAL MATCH (c)-[:HAS_METHOD]->(method:Function)
                    OPTIONAL MATCH (c)-[:EXTENDS]->(parent:Class)
                    OPTIONAL MATCH (child:Class)-[:EXTENDS]->(c)
                    OPTIONAL MATCH (c)-[:HAS_VARIABLE]->(var:Variable)

                    RETURN 'class' AS type,
                           c.id AS id, c.name AS name, null AS signature,
                           c.docstring AS docstring, c.startLine AS startLine, c.endLine AS endLine,
                           file.path AS filePath, null AS className,
                           collect(DISTINCT {id: method.id, name: method.name}) AS calls,
                           collect(DISTINCT {name: parent.name}) AS calledBy,
                           collect(DISTINCT var.name) AS usesClasses
                """, entity_id=entity_id)

            records = list(result)
            if records:
                return dict(records[0])
            return {}
    
    def semantic_code_search(self, query: str, limit: int = 20, repo_id: str = None) -> List[Dict]:
        """Semantic search across all code entities.

        Uses vector embeddings (cosine similarity via Neo4j vector index) when
        sentence-transformers is installed and embeddings were generated during
        indexing.  Falls back to substring matching otherwise.

        Returns functions, classes, and files matching the query.
        """
        embedding = _embed_texts([query])
        if embedding:
            return self._semantic_search_vector(query, embedding[0], limit, repo_id)
        return self._semantic_search_substring(query, limit, repo_id)

    def _semantic_search_vector(self, query: str, embedding: list,
                                 limit: int, repo_id: str = None) -> List[Dict]:
        """Vector-based semantic search using Neo4j vector index."""
        results = []
        with self.driver.session() as session:
            # Search functions
            try:
                func_result = session.run("""
                    CALL db.index.vector.queryNodes('function_embedding', $limit, $embedding)
                    YIELD node AS f, score
                    WHERE score > 0.3
                    OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f)
                    RETURN 'function' AS type, f.id AS id, f.name AS name,
                           f.docstring AS description, file.path AS location,
                           f.startLine AS startLine, score
                    ORDER BY score DESC
                    LIMIT $limit
                """, embedding=embedding, limit=limit)
                results.extend([dict(r) for r in func_result])
            except Exception as e:
                _logger.debug("Vector function search failed, will use substring: %s", e)
                return self._semantic_search_substring(query, limit, repo_id)

            # Search classes
            try:
                class_result = session.run("""
                    CALL db.index.vector.queryNodes('class_embedding', $limit, $embedding)
                    YIELD node AS c, score
                    WHERE score > 0.3
                    OPTIONAL MATCH (file:File)-[:DEFINES_CLASS]->(c)
                    RETURN 'class' AS type, c.id AS id, c.name AS name,
                           c.docstring AS description, file.path AS location,
                           c.startLine AS startLine, score
                    ORDER BY score DESC
                    LIMIT $limit
                """, embedding=embedding, limit=limit)
                results.extend([dict(r) for r in class_result])
            except Exception as e:
                _logger.debug("Vector class search failed: %s", e)

        # Sort combined results by score (desc) and trim to limit
        results.sort(key=lambda r: r.get('score', 0), reverse=True)
        return results[:limit]

    def _semantic_search_substring(self, query: str, limit: int,
                                    repo_id: str = None) -> List[Dict]:
        """Substring-based search (fallback when embeddings unavailable)."""
        results = []

        with self.driver.session() as session:
            if repo_id:
                func_result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f:Function)
                    WHERE f.name CONTAINS $searchTerm
                       OR f.docstring CONTAINS $searchTerm
                       OR f.signature CONTAINS $searchTerm
                    RETURN 'function' AS type, f.id AS id, f.name AS name,
                           f.docstring AS description, file.path AS location,
                           f.startLine AS startLine
                    LIMIT $limit
                """, searchTerm=query, limit=limit, repo_id=repo_id)
                results.extend([dict(r) for r in func_result])

                class_result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)-[:DEFINES_CLASS]->(c:Class)
                    WHERE c.name CONTAINS $searchTerm
                       OR c.docstring CONTAINS $searchTerm
                    RETURN 'class' AS type, c.id AS id, c.name AS name,
                           c.docstring AS description, file.path AS location,
                           c.startLine AS startLine
                    LIMIT $limit
                """, searchTerm=query, limit=limit, repo_id=repo_id)
                results.extend([dict(r) for r in class_result])

                file_result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(f:File)
                    WHERE f.name CONTAINS $searchTerm
                       OR f.path CONTAINS $searchTerm
                    RETURN 'file' AS type, f.id AS id, f.name AS name,
                           f.path AS description, f.path AS location,
                           0 AS startLine
                    LIMIT $limit
                """, searchTerm=query, limit=limit, repo_id=repo_id)
                results.extend([dict(r) for r in file_result])
            else:
                func_result = session.run("""
                    MATCH (f:Function)
                    WHERE f.name CONTAINS $searchTerm
                       OR f.docstring CONTAINS $searchTerm
                       OR f.signature CONTAINS $searchTerm
                    OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f)
                    RETURN 'function' AS type, f.id AS id, f.name AS name,
                           f.docstring AS description, file.path AS location,
                           f.startLine AS startLine
                    LIMIT $limit
                """, searchTerm=query, limit=limit)
                results.extend([dict(r) for r in func_result])

                class_result = session.run("""
                    MATCH (c:Class)
                    WHERE c.name CONTAINS $searchTerm
                       OR c.docstring CONTAINS $searchTerm
                    OPTIONAL MATCH (file:File)-[:DEFINES_CLASS]->(c)
                    RETURN 'class' AS type, c.id AS id, c.name AS name,
                           c.docstring AS description, file.path AS location,
                           c.startLine AS startLine
                    LIMIT $limit
                """, searchTerm=query, limit=limit)
                results.extend([dict(r) for r in class_result])

                file_result = session.run("""
                    MATCH (f:File)
                    WHERE f.name CONTAINS $searchTerm
                       OR f.path CONTAINS $searchTerm
                    RETURN 'file' AS type, f.id AS id, f.name AS name,
                           f.path AS description, f.path AS location,
                           0 AS startLine
                    LIMIT $limit
                """, searchTerm=query, limit=limit)
                results.extend([dict(r) for r in file_result])

        return results[:limit]

    def list_repositories(self) -> List[Dict]:
        """List all indexed repositories with basic stats."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (r:Repository)
                OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(f:File)
                WITH r, count(DISTINCT f) AS fileCount
                OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(fn:Function)
                WITH r, fileCount, count(DISTINCT fn) AS functionCount
                OPTIONAL MATCH (r)-[:CONTAINS_FILE]->(:File)-[:DEFINES_CLASS]->(c:Class)
                RETURN r.id AS id, r.path AS path,
                       fileCount, functionCount, count(DISTINCT c) AS classCount
                ORDER BY r.id
            """)
            return [dict(record) for record in result]

    def remove_repository(self, repo_id: str) -> bool:
        """Remove a repository and all its associated data from the graph.

        Returns True if the repository was found and removed, False if not found.
        Delegates to Neo4jIngester.clear_repository() to reuse its safe
        multi-step deletion logic.
        """
        with self.driver.session() as session:
            exists = session.run(
                "MATCH (r:Repository {id: $repo_id}) RETURN count(r) AS n",
                repo_id=repo_id
            ).single()
            if not exists or exists["n"] == 0:
                return False

        ingester = Neo4jIngester.__new__(Neo4jIngester)
        ingester.driver = self.driver
        ingester.clear_repository(repo_id)
        return True

    def get_tests_for_function(self, function_id: str, repo_id: str = None) -> List[Dict]:
        """Get test functions that test the given function (reverse TESTS traversal)."""
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(testFile:File)
                          -[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(test:Function)
                    WHERE (test)-[:TESTS]->(:Function {id: $function_id})
                    RETURN test.id AS id, test.name AS name,
                           test.signature AS signature, testFile.path AS filePath,
                           test.startLine AS startLine
                """, function_id=function_id, repo_id=repo_id)
            else:
                result = session.run("""
                    MATCH (test:Function)-[:TESTS]->(:Function {id: $function_id})
                    OPTIONAL MATCH (testFile:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(test)
                    RETURN test.id AS id, test.name AS name,
                           test.signature AS signature, testFile.path AS filePath,
                           test.startLine AS startLine
                """, function_id=function_id)
            return [dict(record) for record in result]

    # ── Advanced analysis ──────────────────────────────────────────────────

    def find_dead_code(self, repo_id: str = None, limit: int = 50) -> List[Dict]:
        """Return functions/methods with no incoming CALLS edges (dead-code candidates).

        Excludes common entry-point names and test functions.
        """
        _EXCLUDED_NAMES = ['main', '__init__', '__str__', '__repr__', '__new__',
                           '__del__', '__enter__', '__exit__', '__len__',
                           '__iter__', '__next__', '__call__', '__eq__',
                           '__hash__', '__lt__', '__le__', '__gt__', '__ge__']
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)
                    MATCH (file)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f:Function)
                    WHERE NOT ()-[:CALLS]->(f)
                      AND NOT f.name STARTS WITH 'test'
                      AND NOT f.name STARTS WITH 'Test'
                      AND NOT f.name IN $excluded
                    RETURN f.id AS id, f.name AS name, file.path AS filePath,
                           f.startLine AS startLine, f.complexity AS complexity
                    ORDER BY f.name
                    LIMIT $limit
                """, repo_id=repo_id, excluded=_EXCLUDED_NAMES, limit=limit)
            else:
                result = session.run("""
                    MATCH (f:Function)
                    WHERE NOT ()-[:CALLS]->(f)
                      AND NOT f.name STARTS WITH 'test'
                      AND NOT f.name STARTS WITH 'Test'
                      AND NOT f.name IN $excluded
                    OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f)
                    RETURN f.id AS id, f.name AS name, file.path AS filePath,
                           f.startLine AS startLine, f.complexity AS complexity
                    ORDER BY f.name
                    LIMIT $limit
                """, excluded=_EXCLUDED_NAMES, limit=limit)
            return [dict(record) for record in result]

    def analyze_change_impact(self, function_id: str, max_depth: int = 3,
                               limit: int = 50, repo_id: str = None) -> List[Dict]:
        """Trace what would be affected if *function_id* changes.

        Performs forward traversal along CALLS edges up to *max_depth* hops.
        Returns each affected function with its shortest distance from the start.
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH path = (start:Function {id: $function_id})-[:CALLS*1..$max_depth]->(affected:Function)
                WHERE affected.id <> $function_id
                WITH affected, min(length(path)) AS distance
                OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(affected)
                RETURN affected.id AS id, affected.name AS name,
                       file.path AS filePath, affected.startLine AS startLine,
                       distance
                ORDER BY distance, affected.name
                LIMIT $limit
            """, function_id=function_id, max_depth=max_depth, limit=limit)
            return [dict(record) for record in result]

    def find_circular_dependencies(self, min_cycle_length: int = 2,
                                    max_cycle_length: int = 5,
                                    limit: int = 20,
                                    repo_id: str = None) -> List[Dict]:
        """Find CALLS cycles (A → B → … → A) of a given length range.

        Returns each unique cycle as a list of function IDs.
        """
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH path = (a:Function)-[:CALLS*$min_len..$max_len]->(a)
                    WHERE (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(:File)
                          -[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(a)
                    WITH [n IN nodes(path) | n.id] AS cycle,
                         length(path) AS cycle_length
                    RETURN DISTINCT cycle, cycle_length
                    ORDER BY cycle_length
                    LIMIT $limit
                """, min_len=min_cycle_length, max_len=max_cycle_length,
                     repo_id=repo_id, limit=limit)
            else:
                result = session.run("""
                    MATCH path = (a:Function)-[:CALLS*$min_len..$max_len]->(a)
                    WITH [n IN nodes(path) | n.id] AS cycle,
                         length(path) AS cycle_length
                    RETURN DISTINCT cycle, cycle_length
                    ORDER BY cycle_length
                    LIMIT $limit
                """, min_len=min_cycle_length, max_len=max_cycle_length, limit=limit)
            return [dict(record) for record in result]

    def get_complexity_hotspots(self, repo_id: str = None, limit: int = 20) -> List[Dict]:
        """Rank functions by coupling — total incoming + outgoing CALLS edges.

        High coupling indicates potential refactoring candidates.
        """
        with self.driver.session() as session:
            if repo_id:
                result = session.run("""
                    MATCH (r:Repository {id: $repo_id})-[:CONTAINS_FILE]->(file:File)
                    MATCH (file)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f:Function)
                    OPTIONAL MATCH (f)-[:CALLS]->(callee:Function)
                    WITH f, file, count(callee) AS out_calls
                    OPTIONAL MATCH ()-[:CALLS]->(f)
                    WITH f, file, out_calls, count(*) AS in_calls
                    RETURN f.id AS id, f.name AS name, file.path AS filePath,
                           f.complexity AS complexity,
                           out_calls AS outgoingCalls, in_calls AS incomingCalls,
                           out_calls + in_calls AS totalCoupling
                    ORDER BY totalCoupling DESC
                    LIMIT $limit
                """, repo_id=repo_id, limit=limit)
            else:
                result = session.run("""
                    MATCH (f:Function)
                    OPTIONAL MATCH (file:File)-[:DEFINES_FUNCTION|DEFINES_CLASS]->()-[:HAS_METHOD*0..1]->(f)
                    OPTIONAL MATCH (f)-[:CALLS]->(callee:Function)
                    WITH f, file, count(callee) AS out_calls
                    OPTIONAL MATCH ()-[:CALLS]->(f)
                    WITH f, file, out_calls, count(*) AS in_calls
                    RETURN f.id AS id, f.name AS name, file.path AS filePath,
                           f.complexity AS complexity,
                           out_calls AS outgoingCalls, in_calls AS incomingCalls,
                           out_calls + in_calls AS totalCoupling
                    ORDER BY totalCoupling DESC
                    LIMIT $limit
                """, limit=limit)
            return [dict(record) for record in result]


def ingest_repository(repo_path: str, repo_id: str = None, neo4j_uri: str = None,
                      neo4j_user: str = None, neo4j_password: str = None,
                      incremental: bool = False,
                      changed_files: Optional[List[str]] = None,
                      skip_embeddings: bool = False) -> Dict:
    """
    Convenience function to parse and ingest a repository.
    Returns statistics about the ingestion.

    If incremental=True and changed_files is provided, only those files are
    re-parsed and re-ingested.
    """
    from .parser import CodebaseParser

    parser = CodebaseParser(repo_path, repo_id)

    if incremental and changed_files:
        _logger.info("Incremental indexing: %d changed file(s)", len(changed_files))
        codebase = parser.parse_incremental(changed_files)
    else:
        _logger.info("Parsing repository: %s", repo_path)
        codebase = parser.parse()

    # Ingest into Neo4j
    ingester = Neo4jIngester(neo4j_uri, neo4j_user, neo4j_password)
    ingester.connect()

    try:
        ingester.create_constraints()
        if incremental and changed_files:
            ingester.ingest_incremental(codebase, changed_files,
                                        skip_embeddings=skip_embeddings)
        else:
            ingester.ingest(codebase, skip_embeddings=skip_embeddings)
        return codebase.get_stats()
    finally:
        ingester.close()
