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


def get_all_supported_extensions() -> Set[str]:
    """Get all file extensions supported by registered parsers."""
    return set(LANGUAGE_PARSERS.keys())


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
# Tree-sitter based parsers (registered on import)
# =============================================================================

# Import parsers package to trigger @register_parser decorators
from . import parsers  # noqa: F401, E402
