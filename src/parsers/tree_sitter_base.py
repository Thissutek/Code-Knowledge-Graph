"""
Shared base class for all tree-sitter based language parsers.
"""
from abc import abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

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

    # ── Call extraction helpers ────────────────────────────────────────────

    def _extract_function_calls(
        self, func_node: Node, source_bytes: bytes,
        call_node_types: tuple = ('call_expression',),
    ) -> List[Tuple[str, int]]:
        """Walk *func_node* for call sites and return ``[(name, line), ...]``."""
        calls: List[Tuple[str, int]] = []
        for call_node in self._find_descendants_by_type(func_node, *call_node_types):
            name = self._extract_call_name(call_node, source_bytes)
            if name:
                line = call_node.start_point[0] + 1
                calls.append((name, line))
        return calls

    def _extract_call_name(self, call_node: Node, source_bytes: bytes) -> Optional[str]:
        """Extract the called function name from a call-expression node.

        Handles: ``foo()``, ``obj.foo()``, ``Mod::func()``, ``new Foo()``,
        ``macro!()``.
        """
        # member_expression / field_expression: obj.method() → method
        member = self._find_first_child_by_type(
            call_node, 'member_expression', 'field_expression',
            'selector_expression')
        if member:
            prop = self._find_first_child_by_type(
                member, 'property_identifier', 'field_identifier')
            if prop:
                return self._extract_text(prop, source_bytes)
            # Fall through to pick last identifier from member node
            ids = self._find_children_by_type(member, 'identifier')
            if len(ids) >= 2:
                return self._extract_text(ids[-1], source_bytes)
            elif ids:
                return self._extract_text(ids[0], source_bytes)

        # Java method_invocation: Object.method(...) — identifiers separated by '.'
        # Pick the identifier right after the '.' separator
        if call_node.type == 'method_invocation':
            saw_dot = False
            for child in call_node.children:
                if child.type == '.':
                    saw_dot = True
                elif saw_dot and child.type == 'identifier':
                    return self._extract_text(child, source_bytes)
            # Single identifier call (no dot): just return it
            ident = self._find_first_child_by_type(call_node, 'identifier')
            if ident:
                return self._extract_text(ident, source_bytes)

        # scoped_identifier: Mod::func()
        scoped = self._find_first_child_by_type(
            call_node, 'scoped_identifier')
        if scoped:
            name_node = self._find_first_child_by_type(scoped, 'identifier')
            if name_node:
                return self._extract_text(name_node, source_bytes)

        # Direct identifier: foo()
        func = self._find_first_child_by_type(
            call_node, 'identifier', 'field_identifier', 'property_identifier')
        if func:
            return self._extract_text(func, source_bytes)

        # super() call
        super_node = self._find_first_child_by_type(call_node, 'super')
        if super_node:
            return 'super'

        # new_expression / object_creation_expression: new Foo()
        type_node = self._find_first_child_by_type(
            call_node, 'type_identifier')
        if type_node:
            return self._extract_text(type_node, source_bytes)
        # Look deeper for type_identifier (e.g., generic_type wrapping)
        type_descs = self._find_descendants_by_type(
            call_node, 'type_identifier')
        if type_descs:
            return self._extract_text(type_descs[-1], source_bytes)

        return None
