"""
Tree-sitter based language parsers.
Importing this package registers all language parsers.
"""
from .typescript_parser import TypeScriptLanguageParser
from .java_parser import JavaLanguageParser
from .go_parser import GoLanguageParser
from .rust_parser import RustLanguageParser
from .cpp_parser import CppLanguageParser

__all__ = [
    'TypeScriptLanguageParser',
    'JavaLanguageParser',
    'GoLanguageParser',
    'RustLanguageParser',
    'CppLanguageParser',
]
