"""Rust relationship detector using tree-sitter."""
from typing import List

from .base import BaseRelationshipDetector, DetectedRelationship


class RustRelationshipDetector(BaseRelationshipDetector):
    """Detects CALLS, IMPLEMENTS, and INSTANTIATES in Rust source."""

    def supported_extensions(self) -> List[str]:
        return ['.rs']

    def detect(self, source_code: str, file_path: str) -> List[DetectedRelationship]:
        try:
            import tree_sitter_rust as ts_rust
            from tree_sitter import Language, Parser
            lang = Language(ts_rust.language())
            parser = Parser(lang)
        except Exception:
            return []

        tree = parser.parse(bytes(source_code, 'utf-8'))
        relationships: List[DetectedRelationship] = []
        self._traverse(tree.root_node, source_code, file_path, relationships)
        return relationships

    def _traverse(self, node, source: str, file_path: str, out: List[DetectedRelationship],
                  current_impl: str = '', current_fn: str = ''):
        if node.type == 'impl_item':
            # impl Trait for Struct
            trait_node = node.child_by_field_name('trait')
            type_node = node.child_by_field_name('type')
            struct_name = source[type_node.start_byte:type_node.end_byte] if type_node else ''
            if trait_node and struct_name:
                trait_name = source[trait_node.start_byte:trait_node.end_byte]
                out.append(DetectedRelationship(
                    source_name=struct_name,
                    target_name=trait_name,
                    relationship_type='IMPLEMENTS',
                    confidence=0.95,
                    detection_method='AST_impl_trait',
                    line_number=node.start_point[0] + 1,
                    file_path=file_path,
                    context=f'impl {trait_name} for {struct_name}',
                ))
            for child in node.children:
                self._traverse(child, source, file_path, out, struct_name, current_fn)
            return

        if node.type == 'function_item':
            name_node = node.child_by_field_name('name')
            fn_name = source[name_node.start_byte:name_node.end_byte] if name_node else ''
            for child in node.children:
                self._traverse(child, source, file_path, out, current_impl, fn_name)
            return

        if node.type == 'call_expression':
            func_node = node.child_by_field_name('function')
            if func_node:
                func_text = source[func_node.start_byte:func_node.end_byte]
                src = f'{current_impl}::{current_fn}' if current_impl and current_fn else (current_fn or 'module')
                # Heuristic: Type::new() or SomeThing {} → INSTANTIATES
                if '::new' in func_text or (func_text[0:1].isupper()):
                    out.append(DetectedRelationship(
                        source_name=src,
                        target_name=func_text.split('::')[0],
                        relationship_type='INSTANTIATES',
                        confidence=0.8,
                        detection_method='AST_constructor_call',
                        line_number=node.start_point[0] + 1,
                        file_path=file_path,
                        context=f'{src} instantiates via {func_text}',
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

        for child in node.children:
            self._traverse(child, source, file_path, out, current_impl, current_fn)
