"""Java relationship detector using tree-sitter."""
from typing import List

from .base import BaseRelationshipDetector, DetectedRelationship


class JavaRelationshipDetector(BaseRelationshipDetector):
    """Detects CALLS, EXTENDS, IMPLEMENTS, and INSTANTIATES in Java source."""

    def supported_extensions(self) -> List[str]:
        return ['.java']

    def detect(self, source_code: str, file_path: str) -> List[DetectedRelationship]:
        try:
            import tree_sitter_java as ts_java
            from tree_sitter import Language, Parser
            lang = Language(ts_java.language())
            parser = Parser(lang)
        except Exception:
            return []

        tree = parser.parse(bytes(source_code, 'utf-8'))
        relationships: List[DetectedRelationship] = []
        self._traverse(tree.root_node, source_code, file_path, relationships)
        return relationships

    def _traverse(self, node, source: str, file_path: str, out: List[DetectedRelationship],
                  current_class: str = '', current_method: str = ''):
        if node.type == 'class_declaration':
            name_node = node.child_by_field_name('name')
            class_name = source[name_node.start_byte:name_node.end_byte] if name_node else ''

            # EXTENDS
            superclass = node.child_by_field_name('superclass')
            if superclass and class_name:
                for c in superclass.children:
                    if c.type == 'type_identifier':
                        parent = source[c.start_byte:c.end_byte]
                        out.append(DetectedRelationship(
                            source_name=class_name,
                            target_name=parent,
                            relationship_type='EXTENDS',
                            confidence=0.95,
                            detection_method='AST_extends',
                            line_number=superclass.start_point[0] + 1,
                            file_path=file_path,
                            context=f'class {class_name} extends {parent}',
                        ))

            # IMPLEMENTS
            interfaces = node.child_by_field_name('interfaces')
            if interfaces and class_name:
                for c in interfaces.children:
                    if c.type == 'type_list':
                        for t in c.children:
                            if t.type == 'type_identifier':
                                iface = source[t.start_byte:t.end_byte]
                                out.append(DetectedRelationship(
                                    source_name=class_name,
                                    target_name=iface,
                                    relationship_type='IMPLEMENTS',
                                    confidence=0.95,
                                    detection_method='AST_implements',
                                    line_number=interfaces.start_point[0] + 1,
                                    file_path=file_path,
                                    context=f'class {class_name} implements {iface}',
                                ))

            for child in node.children:
                self._traverse(child, source, file_path, out, class_name, current_method)
            return

        if node.type == 'method_declaration':
            name_node = node.child_by_field_name('name')
            method_name = source[name_node.start_byte:name_node.end_byte] if name_node else ''
            for child in node.children:
                self._traverse(child, source, file_path, out, current_class, method_name)
            return

        if node.type == 'method_invocation':
            name_node = node.child_by_field_name('name')
            obj_node = node.child_by_field_name('object')
            if name_node:
                method = source[name_node.start_byte:name_node.end_byte]
                obj = source[obj_node.start_byte:obj_node.end_byte] if obj_node else ''
                func_text = f'{obj}.{method}' if obj else method
                src = f'{current_class}::{current_method}' if current_class and current_method else (current_method or 'class')
                out.append(DetectedRelationship(
                    source_name=src,
                    target_name=func_text,
                    relationship_type='CALLS',
                    confidence=0.8,
                    detection_method='AST_method_invocation',
                    line_number=node.start_point[0] + 1,
                    file_path=file_path,
                    context=f'{src} calls {func_text}',
                ))

        if node.type == 'object_creation_expression':
            type_node = node.child_by_field_name('type')
            if type_node:
                class_name_created = source[type_node.start_byte:type_node.end_byte]
                src = f'{current_class}::{current_method}' if current_class and current_method else (current_method or 'class')
                out.append(DetectedRelationship(
                    source_name=src,
                    target_name=class_name_created,
                    relationship_type='INSTANTIATES',
                    confidence=0.9,
                    detection_method='AST_new_object',
                    line_number=node.start_point[0] + 1,
                    file_path=file_path,
                    context=f'new {class_name_created}',
                ))

        for child in node.children:
            self._traverse(child, source, file_path, out, current_class, current_method)
