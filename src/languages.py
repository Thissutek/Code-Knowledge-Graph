"""
Language Support Architecture
Defines the interface for language-specific parsers
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Optional, Set
from pathlib import Path

from .models import (
    Class, Function, Variable, Import, Interface,
    Relationship, ParsedCodebase
)


@dataclass
class LanguageConfig:
    """Configuration for a language parser"""
    name: str
    extensions: Set[str]
    comment_styles: List[str]  # e.g., ["//", "#", "/* */"]
    

class LanguageParser(ABC):
    """Abstract base class for language-specific parsers"""
    
    @property
    @abstractmethod
    def config(self) -> LanguageConfig:
        """Return language configuration"""
        pass
    
    @abstractmethod
    def parse_file(self, file_path: Path, source_code: str) -> Dict:
        """
        Parse a single source file and return extracted entities.
        
        Returns:
            Dict with keys: classes, functions, variables, imports, relationships
        """
        pass
    
    def can_parse(self, file_path: Path) -> bool:
        """Check if this parser can handle the given file"""
        return file_path.suffix.lower() in self.config.extensions


# =============================================================================
# Supported Languages Registry
# =============================================================================

LANGUAGE_PARSERS: Dict[str, type] = {}


def register_parser(parser_class: type):
    """Decorator to register a language parser"""
    config = parser_class().config
    for ext in config.extensions:
        LANGUAGE_PARSERS[ext] = parser_class
    return parser_class


def get_parser_for_file(file_path: Path) -> Optional[LanguageParser]:
    """Get the appropriate parser for a file"""
    ext = file_path.suffix.lower()
    if ext in LANGUAGE_PARSERS:
        return LANGUAGE_PARSERS[ext]()
    return None


# =============================================================================
# Python Parser (Current Implementation)
# =============================================================================

@register_parser
class PythonLanguageParser(LanguageParser):
    """Python language parser using AST"""
    
    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="Python",
            extensions={".py", ".pyw"},
            comment_styles=["#", '"""', "'''"]
        )
    
    def parse_file(self, file_path: Path, source_code: str) -> Dict:
        """Parse Python file using AST"""
        # Import here to avoid circular imports
        from .parser import PythonParser
        
        parser = PythonParser(str(file_path), "", source_code)
        
        import ast
        try:
            tree = ast.parse(source_code, filename=str(file_path))
            parser.visit(tree)
        except SyntaxError:
            return {
                'classes': [],
                'functions': [],
                'variables': [],
                'imports': [],
                'relationships': []
            }
        
        return {
            'classes': parser.classes,
            'functions': parser.functions,
            'variables': parser.variables,
            'imports': parser.imports,
            'relationships': parser.relationships
        }


# =============================================================================
# TypeScript/JavaScript Parser (Stub - TODO)
# =============================================================================

# @register_parser
class TypeScriptParser(LanguageParser):
    """
    TypeScript/JavaScript parser using tree-sitter
    
    TODO: Implement using tree-sitter-typescript
    
    Installation:
        pip install tree-sitter tree-sitter-typescript
    """
    
    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="TypeScript",
            extensions={".ts", ".tsx", ".js", ".jsx"},
            comment_styles=["//", "/* */"]
        )
    
    def parse_file(self, file_path: Path, source_code: str) -> Dict:
        """
        Parse TypeScript/JavaScript file
        
        Would extract:
        - Classes and interfaces
        - Functions (including arrow functions)
        - Exports and imports
        - Type annotations
        """
        # TODO: Implement with tree-sitter
        # 
        # Example approach:
        # 1. Use tree-sitter to parse into AST
        # 2. Walk tree for class_declaration, function_declaration, etc.
        # 3. Extract type annotations from type_annotation nodes
        # 4. Handle ES6 modules (import/export)
        #
        # from tree_sitter import Language, Parser
        # import tree_sitter_typescript as ts_lang
        # 
        # parser = Parser()
        # parser.set_language(Language(ts_lang.language_typescript()))
        # tree = parser.parse(source_code.encode())
        # 
        raise NotImplementedError("TypeScript parser not yet implemented")


# =============================================================================
# Java Parser (Stub - TODO)
# =============================================================================

# @register_parser  
class JavaParser(LanguageParser):
    """
    Java parser using tree-sitter
    
    TODO: Implement using tree-sitter-java
    """
    
    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="Java",
            extensions={".java"},
            comment_styles=["//", "/* */", "/** */"]
        )
    
    def parse_file(self, file_path: Path, source_code: str) -> Dict:
        """
        Parse Java file
        
        Would extract:
        - Classes, interfaces, enums
        - Methods with access modifiers
        - Fields with types
        - Annotations
        - Package and import statements
        """
        raise NotImplementedError("Java parser not yet implemented")


# =============================================================================
# Go Parser (Stub - TODO)  
# =============================================================================

# @register_parser
class GoParser(LanguageParser):
    """
    Go parser using tree-sitter
    
    TODO: Implement using tree-sitter-go
    """
    
    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="Go",
            extensions={".go"},
            comment_styles=["//", "/* */"]
        )
    
    def parse_file(self, file_path: Path, source_code: str) -> Dict:
        """
        Parse Go file
        
        Would extract:
        - Structs and interfaces
        - Functions and methods (with receivers)
        - Package declarations
        - Imports
        """
        raise NotImplementedError("Go parser not yet implemented")


# =============================================================================
# Rust Parser (Stub - TODO)
# =============================================================================

# @register_parser
class RustParser(LanguageParser):
    """
    Rust parser using tree-sitter
    
    TODO: Implement using tree-sitter-rust
    """
    
    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="Rust",
            extensions={".rs"},
            comment_styles=["//", "/* */", "///", "//!"]
        )
    
    def parse_file(self, file_path: Path, source_code: str) -> Dict:
        """
        Parse Rust file
        
        Would extract:
        - Structs, enums, traits
        - Functions and impl blocks
        - Modules and use statements
        - Macros
        """
        raise NotImplementedError("Rust parser not yet implemented")


# =============================================================================
# C/C++ Parser (Stub - TODO)
# =============================================================================

# @register_parser
class CppParser(LanguageParser):
    """
    C/C++ parser using tree-sitter
    
    TODO: Implement using tree-sitter-c and tree-sitter-cpp
    """
    
    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="C/C++",
            extensions={".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"},
            comment_styles=["//", "/* */"]
        )
    
    def parse_file(self, file_path: Path, source_code: str) -> Dict:
        """
        Parse C/C++ file
        
        Would extract:
        - Classes and structs
        - Functions (declarations and definitions)
        - Namespaces
        - #include directives
        - Templates
        """
        raise NotImplementedError("C/C++ parser not yet implemented")
