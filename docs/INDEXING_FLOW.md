```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant Parser
    participant AST as Python AST
    participant Codebase as ParsedCodebase
    participant Ingester as Neo4jIngester
    participant Neo4j

    User->>CLI: python cli.py index /path/to/repo
    CLI->>Parser: parse_repository(path)
    
    Note over Parser: Phase 1: Discovery
    Parser->>Parser: Walk directory tree
    Parser->>Parser: Find all .py files
    Parser->>Parser: Skip __pycache__, venv, etc.
    
    Note over Parser: Phase 2: Parse Each File
    loop For each Python file
        Parser->>AST: ast.parse(source_code)
        AST-->>Parser: Abstract Syntax Tree
        
        Parser->>Parser: Extract Classes
        Parser->>Parser: Extract Functions/Methods
        Parser->>Parser: Extract Variables
        Parser->>Parser: Extract Imports
        Parser->>Parser: Track function calls
        Parser->>Parser: Track class usages
        
        Parser->>Codebase: Add entities + relationships
    end
    
    Note over Parser: Phase 3: Resolve Cross-References
    Parser->>Parser: Match function calls to definitions
    Parser->>Parser: Resolve class inheritance
    Parser->>Parser: Link import dependencies
    Parser->>Codebase: Add cross-file relationships
    
    Parser-->>CLI: ParsedCodebase
    
    Note over Ingester: Phase 4: Database Setup
    CLI->>Ingester: ingest(codebase)
    Ingester->>Neo4j: Connect
    Ingester->>Neo4j: CREATE CONSTRAINTS
    Ingester->>Neo4j: CREATE INDEXES
    Ingester->>Neo4j: Clear existing repo data
    
    Note over Ingester: Phase 5: Batch Insert
    Ingester->>Neo4j: MERGE Repository
    Ingester->>Neo4j: UNWIND files → MERGE File nodes
    Ingester->>Neo4j: UNWIND modules → MERGE Module nodes
    Ingester->>Neo4j: UNWIND classes → MERGE Class nodes
    Ingester->>Neo4j: UNWIND functions → MERGE Function nodes
    Ingester->>Neo4j: UNWIND variables → MERGE Variable nodes
    Ingester->>Neo4j: UNWIND imports → MERGE Import nodes
    
    Note over Ingester: Phase 6: Create Relationships
    Ingester->>Neo4j: MATCH + MERGE relationships (CALLS, EXTENDS, etc.)
    
    Ingester-->>CLI: Statistics
    CLI-->>User: ✅ Indexed! Files: X, Classes: Y, Functions: Z
```

## Indexing Flow Explained

### Phase 1: Discovery
- Recursively walk the repository directory
- Filter for Python files (`.py`, `.pyw`)
- Skip ignored directories (`__pycache__`, `venv`, `node_modules`, `.git`)

### Phase 2: Parse Each File
For each Python file:
1. Read source code
2. Parse into AST (Abstract Syntax Tree)
3. Visit AST nodes to extract:
   - **Classes**: name, docstring, decorators, line numbers
   - **Functions/Methods**: signature, parameters, return type, complexity
   - **Variables**: module-level and class attributes
   - **Imports**: what modules/symbols are imported

### Phase 3: Resolve Cross-References
After all files are parsed:
1. Match function calls to their definitions
2. Resolve class inheritance chains
3. Link file imports to actual files
4. Build the DEPENDS_ON relationships

### Phase 4: Database Setup
1. Connect to Neo4j
2. Create uniqueness constraints on ID fields
3. Create indexes for fast lookups (name, path, docstring)
4. Clear any existing data for this repository

### Phase 5: Batch Insert Nodes
Using Cypher `UNWIND` for efficient batch operations:
```cypher
UNWIND $records AS record
MERGE (f:Function {id: record.id})
SET f.name = record.name, f.signature = record.signature, ...
```

### Phase 6: Create Relationships
For each relationship type:
```cypher
UNWIND $records AS record
MATCH (source:Function {id: record.sourceId})
MATCH (target:Function {id: record.targetId})
MERGE (source)-[rel:CALLS]->(target)
SET rel.lineNumbers = record.lineNumbers
```

## Relationship Types

| Relationship | Source → Target | Description |
|-------------|-----------------|-------------|
| `CONTAINS_FILE` | Repository → File | Repo contains this file |
| `CONTAINS_MODULE` | Repository → Module | Repo has this module/package |
| `BELONGS_TO_MODULE` | File → Module | File is part of module |
| `DEFINES_CLASS` | File → Class | File defines this class |
| `DEFINES_FUNCTION` | File → Function | File defines top-level function |
| `HAS_METHOD` | Class → Function | Class has this method |
| `HAS_VARIABLE` | Class → Variable | Class has this attribute |
| `EXTENDS` | Class → Class | Class inherits from |
| `IMPLEMENTS` | Class → Interface | Class implements interface |
| `CALLS` | Function → Function | Function calls another |
| `USES_CLASS` | Function → Class | Function uses/instantiates class |
| `IMPORTS` | File → Import | File has this import statement |
| `IMPORTS_FROM` | File → File | File imports from another file |
| `DEPENDS_ON` | File → File | File depends on another |
