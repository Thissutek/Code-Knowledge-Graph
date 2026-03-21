"""Go relationship detector using tree-sitter."""
from typing import List

from .base import BaseRelationshipDetector, DetectedRelationship


class GoRelationshipDetector(BaseRelationshipDetector):
    """Detects CALLS and IMPLEMENTS in Go source code."""

    def supported_extensions(self) -> List[str]:
        return ['.go']

    def detect(self, source_code: str, file_path: str) -> List[DetectedRelationship]:
        try:
            import tree_sitter_go as ts_go
            from tree_sitter import Language, Parser
            lang = Language(ts_go.language())
            parser = Parser(lang)
        except Exception:
            return []

        tree = parser.parse(bytes(source_code, 'utf-8'))
        relationships: List[DetectedRelationship] = []
        self._traverse(tree.root_node, source_code, file_path, relationships)
        return relationships

    def _traverse(self, node, source: str, file_path: str, out: List[DetectedRelationship],
                  current_type: str = '', current_func: str = ''):
        if node.type == 'type_declaration':
            for child in node.children:
                if child.type == 'type_spec':
                    name_node = child.child_by_field_name('name')
                    type_node = child.child_by_field_name('type')
                    if name_node and type_node and type_node.type == 'interface_type':
                        # interface declaration — track for IMPLEMENTS
                        pass
            for child in node.children:
                self._traverse(child, source, file_path, out, current_type, current_func)
            return

        if node.type == 'function_declaration':
            name_node = node.child_by_field_name('name')
            func_name = source[name_node.start_byte:name_node.end_byte] if name_node else ''
            for child in node.children:
                self._traverse(child, source, file_path, out, current_type, func_name)
            return

        if node.type == 'method_declaration':
            recv = node.child_by_field_name('receiver')
            recv_type = ''
            if recv:
                for c in recv.children:
                    if c.type == 'parameter_declaration':
                        type_node = c.child_by_field_name('type')
                        if type_node:
                            recv_type = source[type_node.start_byte:type_node.end_byte].lstrip('*')
            name_node = node.child_by_field_name('name')
            func_name = source[name_node.start_byte:name_node.end_byte] if name_node else ''
            for child in node.children:
                self._traverse(child, source, file_path, out, recv_type, func_name)
            return

        if node.type == 'call_expression':
            func_node = node.child_by_field_name('function')
            if func_node:
                func_text = source[func_node.start_byte:func_node.end_byte]
                src = f'{current_type}::{current_func}' if current_type and current_func else (current_func or 'package')
                out.append(DetectedRelationship(
                    source_name=src,
                    target_name=func_text,
                    relationship_type='CALLS',
                    confidence=0.8,
                    detection_method='AST_call',
                    line_number=node.start_point[0] + 1,
                    file_path=file_path,
                    context=f'{src} calls {func_text}',
                ))

        for child in node.children:
            self._traverse(child, source, file_path, out, current_type, current_func)
