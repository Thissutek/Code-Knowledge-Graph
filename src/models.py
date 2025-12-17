"""
Code Knowledge Graph Data Models
Defines the structure for code entities and their relationships
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
import json


@dataclass
class Property:
    """Base property for Neo4j nodes"""
    name: str
    type: str
    value: Any = None


@dataclass
class CodeEntity:
    """Base class for all code entities"""
    id: str
    name: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class Repository(CodeEntity):
    """Represents a code repository"""
    path: str = ""
    language: str = ""
    description: str = ""
    last_indexed: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        if self.last_indexed:
            d['lastIndexed'] = self.last_indexed.isoformat()
        return d


@dataclass
class File(CodeEntity):
    """Represents a source code file"""
    path: str = ""
    extension: str = ""
    language: str = ""
    lines_of_code: int = 0
    content_hash: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d['linesOfCode'] = self.lines_of_code
        d['hash'] = self.content_hash
        return d


@dataclass
class Module(CodeEntity):
    """Represents a module/package"""
    path: str = ""
    module_type: str = "module"  # package, namespace, module
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d['type'] = self.module_type
        return d


@dataclass
class Class(CodeEntity):
    """Represents a class definition"""
    docstring: str = ""
    start_line: int = 0
    end_line: int = 0
    is_abstract: bool = False
    decorators: List[str] = field(default_factory=list)
    base_classes: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d['startLine'] = self.start_line
        d['endLine'] = self.end_line
        d['isAbstract'] = self.is_abstract
        d['decorators'] = self.decorators
        return d


@dataclass
class Parameter:
    """Represents a function parameter"""
    name: str
    type_annotation: Optional[str] = None
    default_value: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'type': self.type_annotation,
            'default': self.default_value
        }


@dataclass
class Function(CodeEntity):
    """Represents a function or method"""
    signature: str = ""
    docstring: str = ""
    start_line: int = 0
    end_line: int = 0
    is_async: bool = False
    is_static: bool = False
    is_method: bool = False
    return_type: Optional[str] = None
    complexity: int = 1
    parameters: List[Parameter] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)  # Function IDs this function calls
    uses_classes: List[str] = field(default_factory=list)  # Class IDs used
    visibility: str = "public"  # public, private, protected
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d['startLine'] = self.start_line
        d['endLine'] = self.end_line
        d['isAsync'] = self.is_async
        d['isStatic'] = self.is_static
        d['returnType'] = self.return_type
        d['complexity'] = self.complexity
        d['parameters'] = json.dumps([p.to_dict() for p in self.parameters])
        return d


@dataclass  
class Variable(CodeEntity):
    """Represents a variable or constant"""
    var_type: Optional[str] = None
    scope: str = "local"  # global, class, local
    is_constant: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d['type'] = self.var_type
        d['isConstant'] = self.is_constant
        return d


@dataclass
class Import(CodeEntity):
    """Represents an import statement"""
    source: str = ""
    is_external: bool = True
    imported_symbols: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d['isExternal'] = self.is_external
        return d


@dataclass
class Interface(CodeEntity):
    """Represents an interface (for TypeScript/Java)"""
    docstring: str = ""
    methods: List[str] = field(default_factory=list)


@dataclass
class Relationship:
    """Represents a relationship between entities"""
    rel_type: str
    source_id: str
    target_id: str
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.rel_type,
            'sourceId': self.source_id,
            'targetId': self.target_id,
            **self.properties
        }


@dataclass
class ParsedCodebase:
    """Container for all parsed code entities"""
    repository: Repository
    files: List[File] = field(default_factory=list)
    modules: List[Module] = field(default_factory=list)
    classes: List[Class] = field(default_factory=list)
    functions: List[Function] = field(default_factory=list)
    variables: List[Variable] = field(default_factory=list)
    imports: List[Import] = field(default_factory=list)
    interfaces: List[Interface] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    
    def add_relationship(self, rel_type: str, source_id: str, target_id: str, **props):
        """Add a relationship between entities"""
        self.relationships.append(Relationship(rel_type, source_id, target_id, props))
    
    def get_stats(self) -> Dict[str, int]:
        """Get statistics about the parsed codebase"""
        return {
            'files': len(self.files),
            'modules': len(self.modules),
            'classes': len(self.classes),
            'functions': len(self.functions),
            'variables': len(self.variables),
            'imports': len(self.imports),
            'interfaces': len(self.interfaces),
            'relationships': len(self.relationships)
        }
