"""TypeScript/JavaScript relationship detector using tree-sitter."""
from typing import List

from .base import BaseRelationshipDetector, DetectedRelationship


class TypeScriptRelationshipDetector(BaseRelationshipDetector):
    """Detects CALLS, EXTENDS, IMPLEMENTS, and INSTANTIATES in TS/JS source."""

    def supported_extensions(self) -> List[str]:
        return ['.ts', '.tsx', '.js', '.jsx']

    def detect(self, source_code: str, file_path: str) -> List[DetectedRelationship]:
        try:
            import tree_sitter_typescript as ts_ts
            from tree_sitter import Language, Parser
            lang = Language(ts_ts.language_typescript())
            parser = Parser(lang)
        except Exception:
            return []

        tree = parser.parse(bytes(source_code, 'utf-8'))
        relationships: List[DetectedRelationship] = []
        self._traverse(tree.root_node, source_code, file_path, relationships)
        return relationships

    def _traverse(self, node, source: str, file_path: str, out: List[DetectedRelationship],
                  current_class: str = '', current_func: str = ''):
        if node.type == 'class_declaration':
            name_node = node.child_by_field_name('name')
            class_name = source[name_node.start_byte:name_node.end_byte] if name_node else ''

            # EXTENDS
            heritage = node.child_by_field_name('class_heritage')
            if heritage and class_name:
                for child in heritage.children:
                    if child.type == 'extends_clause':
                        for c in child.children:
                            if c.type == 'identifier':
                                parent = source[c.start_byte:c.end_byte]
                                out.append(DetectedRelationship(
                                    source_name=class_name,
                                    target_name=parent,
                                    relationship_type='EXTENDS',
                                    confidence=0.95,
                                    detection_method='AST_extends',
                                    line_number=child.start_point[0] + 1,
                                    file_path=file_path,
                                    context=f'class {class_name} extends {parent}',
                                ))
                    if child.type == 'implements_clause':
                        for c in child.children:
                            if c.type == 'type_identifier':
                                iface = source[c.start_byte:c.end_byte]
                                out.append(DetectedRelationship(
                                    source_name=class_name,
                                    target_name=iface,
                                    relationship_type='IMPLEMENTS',
                                    confidence=0.95,
                                    detection_method='AST_implements',
                                    line_number=child.start_point[0] + 1,
                                    file_path=file_path,
                                    context=f'class {class_name} implements {iface}',
                                ))

            for child in node.children:
                self._traverse(child, source, file_path, out, class_name, current_func)
            return

        if node.type in ('function_declaration', 'method_definition', 'arrow_function'):
            name_node = node.child_by_field_name('name')
            func_name = source[name_node.start_byte:name_node.end_byte] if name_node else current_func
            for child in node.children:
                self._traverse(child, source, file_path, out, current_class, func_name)
            return

        if node.type == 'call_expression':
            func_node = node.child_by_field_name('function')
            if func_node:
                func_text = source[func_node.start_byte:func_node.end_byte]
                src = f'{current_class}::{current_func}' if current_class and current_func else (current_func or 'module')
                base = func_text.split('.')[-1]
                if base and base[0].isupper() and not base.isupper():
                    out.append(DetectedRelationship(
                        source_name=src,
                        target_name=base,
                        relationship_type='INSTANTIATES',
                        confidence=0.8,
                        detection_method='AST_new_call',
                        line_number=node.start_point[0] + 1,
                        file_path=file_path,
                        context=f'{src} instantiates {base}',
                    ))
                else:
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

        if node.type == 'new_expression':
            constructor = node.child_by_field_name('constructor')
            if constructor:
                name = source[constructor.start_byte:constructor.end_byte]
                src = f'{current_class}::{current_func}' if current_class and current_func else (current_func or 'module')
                out.append(DetectedRelationship(
                    source_name=src,
                    target_name=name,
                    relationship_type='INSTANTIATES',
                    confidence=0.9,
                    detection_method='AST_new_expression',
                    line_number=node.start_point[0] + 1,
                    file_path=file_path,
                    context=f'new {name}',
                ))

        for child in node.children:
            self._traverse(child, source, file_path, out, current_class, current_func)
