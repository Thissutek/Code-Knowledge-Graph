"""Python relationship detector using stdlib ast."""
import ast
from typing import List

from .base import BaseRelationshipDetector, DetectedRelationship


class PythonRelationshipDetector(BaseRelationshipDetector):
    """Detects CALLS, EXTENDS, INSTANTIATES, and USES_CLASS in Python source."""

    def supported_extensions(self) -> List[str]:
        return ['.py']

    def detect(self, source_code: str, file_path: str) -> List[DetectedRelationship]:
        try:
            tree = ast.parse(source_code, filename=file_path)
        except SyntaxError:
            return []

        visitor = _PythonVisitor(file_path)
        visitor.visit(tree)
        return visitor.relationships


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.relationships: List[DetectedRelationship] = []
        self._class_stack: List[str] = []
        self._func_stack: List[str] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        class_name = node.name
        # EXTENDS from base classes
        for base in node.bases:
            base_name = self._expr_name(base)
            if base_name:
                self.relationships.append(DetectedRelationship(
                    source_name=class_name,
                    target_name=base_name,
                    relationship_type='EXTENDS',
                    confidence=0.95,
                    detection_method='AST_extends',
                    line_number=node.lineno,
                    file_path=self.file_path,
                    context=f'class {class_name}({base_name})',
                ))

        self._class_stack.append(class_name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call):
        func_name = self._expr_name(node.func)
        if not func_name:
            self.generic_visit(node)
            return

        source = self._current_source()
        base = func_name.split('.')[-1]

        # Heuristic: PascalCase call → class instantiation
        if base and base[0].isupper() and not base.isupper():
            self.relationships.append(DetectedRelationship(
                source_name=source,
                target_name=base,
                relationship_type='INSTANTIATES',
                confidence=0.85,
                detection_method='AST_instantiation',
                line_number=node.lineno,
                file_path=self.file_path,
                context=f'{source} instantiates {base}',
            ))
        else:
            self.relationships.append(DetectedRelationship(
                source_name=source,
                target_name=func_name,
                relationship_type='CALLS',
                confidence=0.85,
                detection_method='AST_call',
                line_number=node.lineno,
                file_path=self.file_path,
                context=f'{source} calls {func_name}',
            ))
        self.generic_visit(node)

    def _current_source(self) -> str:
        if self._class_stack and self._func_stack:
            return f'{self._class_stack[-1]}::{self._func_stack[-1]}'
        if self._func_stack:
            return self._func_stack[-1]
        if self._class_stack:
            return self._class_stack[-1]
        return 'module'

    @staticmethod
    def _expr_name(node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = _PythonVisitor._expr_name(node.value)
            return f'{parent}.{node.attr}' if parent else node.attr
        return ''
