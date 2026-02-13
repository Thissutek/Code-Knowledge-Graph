"""
Shared base class for all tree-sitter based language parsers.
"""
from abc import abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Any

from tree_sitter import Language, Parser, Node

from ..languages import LanguageParser, LanguageConfig
from ..models import (
    Class, Function, Variable, Import, Interface,
    Relationship, Parameter
)


class TreeSitterBaseParser(LanguageParser):
    """Base class for tree-sitter based parsers with shared utilities."""

    def __init__(self):
        self._parser: Optional[Parser] = None
        self._language: Optional[Language] = None

    def _init_tree_sitter(self, language_module, func_name: str = "language"):
        """Initialize tree-sitter parser with the given language module."""
        lang_func = getattr(language_module, func_name)
        self._language = Language(lang_func())
        self._parser = Parser(self._language)

    def _parse_tree(self, source_code: str):
        """Parse source code into a tree-sitter tree."""
        return self._parser.parse(source_code.encode('utf-8'))

    def _extract_text(self, node: Node, source_bytes: bytes) -> str:
        """Extract text content from a tree-sitter node."""
        return source_bytes[node.start_byte:node.end_byte].decode('utf-8')

    def _find_children_by_type(self, node: Node, *types: str) -> List[Node]:
        """Find direct children of a node matching the given types."""
        return [child for child in node.children if child.type in types]

    def _find_descendants_by_type(self, node: Node, *types: str) -> List[Node]:
        """Recursively find all descendants matching the given types."""
        results = []
        for child in node.children:
            if child.type in types:
                results.append(child)
            results.extend(self._find_descendants_by_type(child, *types))
        return results

    def _find_first_child_by_type(self, node: Node, *types: str) -> Optional[Node]:
        """Find the first direct child matching the given types."""
        for child in node.children:
            if child.type in types:
                return child
        return None

    def _extract_docstring(self, node: Node, source_bytes: bytes) -> str:
        """Extract a documentation comment preceding or inside a node."""
        # Look for comment nodes immediately before this node
        parent = node.parent
        if parent is None:
            return ""

        idx = None
        for i, child in enumerate(parent.children):
            if child.id == node.id:
                idx = i
                break

        if idx is None:
            return ""

        # Look backwards for comment nodes
        comments = []
        for i in range(idx - 1, -1, -1):
            sibling = parent.children[i]
            if sibling.type in ('comment', 'line_comment', 'block_comment',
                                'doc_comment', 'documentation_comment'):
                comments.insert(0, self._extract_text(sibling, source_bytes))
            else:
                break

        if comments:
            return self._clean_comment('\n'.join(comments))

        # Also check first child (for languages that put doc inside the node)
        if node.children:
            first = node.children[0]
            if first.type in ('comment', 'line_comment', 'block_comment',
                              'doc_comment', 'documentation_comment'):
                return self._clean_comment(self._extract_text(first, source_bytes))

        return ""

    def _clean_comment(self, text: str) -> str:
        """Clean comment markers from text."""
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            line = line.strip()
            # Remove common comment prefixes
            for prefix in ('///', '//', '/**', '*/', '*', '/*', '#'):
                if line.startswith(prefix):
                    line = line[len(prefix):]
                    break
            cleaned.append(line.strip())
        return '\n'.join(cleaned).strip()

    def _make_id(self, file_path: str, *parts: str) -> str:
        """Create a unique ID from parts."""
        return ':'.join(filter(None, [file_path] + list(parts)))

    def _calculate_complexity(self, node: Node) -> int:
        """Estimate cyclomatic complexity from tree-sitter nodes."""
        complexity = 1
        branch_types = {
            'if_statement', 'if_expression', 'else_clause',
            'while_statement', 'while_expression',
            'for_statement', 'for_expression', 'for_in_statement',
            'catch_clause', 'except_clause',
            'case_clause', 'switch_case', 'match_arm',
            'conditional_expression', 'ternary_expression',
            '&&', '||', 'and', 'or',
        }
        for desc in self._find_descendants_by_type(node, *branch_types):
            complexity += 1
        return complexity
