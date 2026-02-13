"""
Rust parser using tree-sitter.
Handles .rs files.
"""
from pathlib import Path
from typing import Dict, List, Optional

import tree_sitter_rust as ts_rust
from tree_sitter import Language, Parser

from ..languages import LanguageConfig, register_parser
from ..models import (
    Class, Function, Variable, Import, Interface,
    Relationship, Parameter
)
from .tree_sitter_base import TreeSitterBaseParser


@register_parser
class RustLanguageParser(TreeSitterBaseParser):
    """Rust parser using tree-sitter."""

    def __init__(self):
        super().__init__()
        self._rust_parser: Optional[Parser] = None

    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="Rust",
            extensions={".rs"},
            comment_styles=["//", "/* */", "///", "//!"]
        )

    def _ensure_parser(self):
        if self._rust_parser is None:
            lang = Language(ts_rust.language())
            self._rust_parser = Parser(lang)
        return self._rust_parser

    def parse_file(self, file_path: Path, source_code: str) -> Dict:
        parser = self._ensure_parser()
        source_bytes = source_code.encode('utf-8')
        tree = parser.parse(source_bytes)
        root = tree.root_node

        fp = str(file_path)
        classes: List[Class] = []
        functions: List[Function] = []
        variables: List[Variable] = []
        imports: List[Import] = []
        interfaces: List[Interface] = []
        relationships: List[Relationship] = []
        self._current_function_calls: Dict[str, list] = {}
        self._source_bytes = source_bytes

        for child in root.children:
            self._visit_node(child, source_bytes, fp, classes, functions,
                             variables, imports, interfaces, relationships)

        return {
            'classes': classes,
            'functions': functions,
            'variables': variables,
            'imports': imports,
            'interfaces': interfaces,
            'relationships': relationships,
            'function_calls': self._current_function_calls,
        }

    def _visit_node(self, node, source_bytes, fp, classes, functions,
                    variables, imports, interfaces, relationships):
        ntype = node.type

        if ntype == 'struct_item':
            self._parse_struct(node, source_bytes, fp, classes)
        elif ntype == 'enum_item':
            self._parse_enum(node, source_bytes, fp, classes)
        elif ntype == 'trait_item':
            self._parse_trait(node, source_bytes, fp, interfaces,
                              functions, relationships)
        elif ntype == 'impl_item':
            self._parse_impl(node, source_bytes, fp, functions,
                             relationships, classes)
        elif ntype == 'function_item':
            self._parse_function(node, source_bytes, fp, functions,
                                 relationships, current_class=None)
        elif ntype == 'use_declaration':
            self._parse_use(node, source_bytes, fp, imports)
        elif ntype in ('const_item', 'static_item', 'let_declaration'):
            self._parse_variable(node, source_bytes, fp, variables,
                                 is_const=(ntype == 'const_item'))
        elif ntype == 'mod_item':
            # Module declaration - process children
            body = self._find_first_child_by_type(node, 'declaration_list')
            if body:
                for child in body.children:
                    self._visit_node(child, source_bytes, fp, classes,
                                     functions, variables, imports,
                                     interfaces, relationships)

    def _parse_struct(self, node, source_bytes, fp, classes):
        """Parse Rust struct definition."""
        name_node = self._find_first_child_by_type(node, 'type_identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        class_id = self._make_id(fp, name)

        is_pub = self._is_pub(node, source_bytes)
        decorators = self._extract_attributes(node, source_bytes)

        cls = Class(
            id=class_id,
            name=name,
            docstring=self._extract_docstring(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            decorators=decorators,
            language_type="struct",
        )
        classes.append(cls)

    def _parse_enum(self, node, source_bytes, fp, classes):
        """Parse Rust enum definition."""
        name_node = self._find_first_child_by_type(node, 'type_identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        class_id = self._make_id(fp, name)

        decorators = self._extract_attributes(node, source_bytes)

        cls = Class(
            id=class_id,
            name=name,
            docstring=self._extract_docstring(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            decorators=decorators,
            language_type="enum",
        )
        classes.append(cls)

    def _parse_trait(self, node, source_bytes, fp, interfaces,
                     functions, relationships):
        """Parse Rust trait definition."""
        name_node = self._find_first_child_by_type(node, 'type_identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        iface_id = self._make_id(fp, name)

        methods = []
        body = self._find_first_child_by_type(node, 'declaration_list')
        if body:
            for child in body.children:
                if child.type in ('function_signature_item', 'function_item'):
                    fn_name = self._find_first_child_by_type(child, 'identifier')
                    if fn_name:
                        methods.append(self._extract_text(fn_name, source_bytes))

        iface = Interface(
            id=iface_id,
            name=name,
            docstring=self._extract_docstring(node, source_bytes),
            methods=methods,
        )
        interfaces.append(iface)

    def _parse_impl(self, node, source_bytes, fp, functions,
                    relationships, classes):
        """Parse Rust impl block."""
        # Find the type being implemented
        type_node = self._find_first_child_by_type(node, 'type_identifier', 'generic_type')
        if not type_node:
            return

        if type_node.type == 'generic_type':
            inner = self._find_first_child_by_type(type_node, 'type_identifier')
            if inner:
                type_name = self._extract_text(inner, source_bytes)
            else:
                type_name = self._extract_text(type_node, source_bytes)
        else:
            type_name = self._extract_text(type_node, source_bytes)

        class_id = self._make_id(fp, type_name)

        # Check if this is a trait implementation (impl Trait for Type)
        trait_name = None
        saw_for = False
        for child in node.children:
            if child.type in ('type_identifier', 'generic_type', 'scoped_type_identifier'):
                if saw_for:
                    # This is the type after 'for'
                    if child.type == 'generic_type':
                        inner = self._find_first_child_by_type(child, 'type_identifier')
                        type_name = self._extract_text(inner, source_bytes) if inner else self._extract_text(child, source_bytes)
                    else:
                        type_name = self._extract_text(child, source_bytes)
                    class_id = self._make_id(fp, type_name)
                elif trait_name is None:
                    if child.type == 'generic_type':
                        inner = self._find_first_child_by_type(child, 'type_identifier')
                        trait_name = self._extract_text(inner, source_bytes) if inner else self._extract_text(child, source_bytes)
                    else:
                        trait_name = self._extract_text(child, source_bytes)
            elif self._extract_text(child, source_bytes) == 'for':
                saw_for = True

        if saw_for and trait_name:
            relationships.append(Relationship(
                rel_type='IMPLEMENTS',
                source_id=class_id,
                target_id=trait_name,
            ))

        # Parse methods in impl block
        body = self._find_first_child_by_type(node, 'declaration_list')
        if body:
            for child in body.children:
                if child.type == 'function_item':
                    self._parse_function(child, source_bytes, fp, functions,
                                         relationships, class_id)

    def _parse_function(self, node, source_bytes, fp, functions,
                        relationships, current_class):
        """Parse Rust function definition."""
        name_node = self._find_first_child_by_type(node, 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        is_method = current_class is not None

        if is_method:
            func_id = self._make_id(fp, current_class.split(':')[-1], name)
        else:
            func_id = self._make_id(fp, name)

        is_pub = self._is_pub(node, source_bytes)
        visibility = "public" if is_pub else "private"
        is_async = any(
            self._extract_text(c, source_bytes) == 'async'
            for c in node.children
        )

        params = self._extract_rust_parameters(node, source_bytes)
        return_type = self._extract_rust_return_type(node, source_bytes)
        decorators = self._extract_attributes(node, source_bytes)

        sig_parts = []
        for p in params:
            part = p.name
            if p.type_annotation:
                part += f": {p.type_annotation}"
            sig_parts.append(part)
        signature = f"({', '.join(sig_parts)})"
        if return_type:
            signature += f" -> {return_type}"

        func = Function(
            id=func_id,
            name=name,
            signature=signature,
            docstring=self._extract_docstring(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_async=is_async,
            is_static=not is_method or not any(
                p.name in ('self', '&self', '&mut self', 'mut self')
                for p in params),
            is_method=is_method,
            return_type=return_type,
            complexity=self._calculate_complexity(node),
            parameters=params,
            visibility=visibility,
        )
        functions.append(func)

        # Extract function calls
        calls = self._extract_function_calls(
            node, source_bytes, ('call_expression', 'macro_invocation'))
        if calls:
            self._current_function_calls[func_id] = calls

        if is_method and current_class:
            relationships.append(Relationship(
                rel_type='HAS_METHOD',
                source_id=current_class,
                target_id=func_id,
                properties={'visibility': visibility}
            ))

    def _parse_use(self, node, source_bytes, fp, imports):
        """Parse Rust use declarations."""
        text = self._extract_text(node, source_bytes).strip().rstrip(';')
        # Remove 'use ' or 'pub use ' prefix
        source = text.replace('pub use ', '').replace('use ', '')

        # Expand into flat paths (handles nested braces recursively)
        paths = self._expand_use_paths(source)
        for path in paths:
            raw = path.split(' as ')[0].strip()
            name = path.split('::')[-1].split(' as ')[-1].strip()
            if name == 'self':
                # `use foo::bar::self` → import bar from foo::bar
                parts = raw.rsplit('::', 1)
                name = parts[0].rsplit('::', 1)[-1] if '::' in parts[0] else parts[0]
            import_id = self._make_id(fp, 'import', raw)
            imp = Import(
                id=import_id,
                name=name,
                source=raw,
                is_external=True,
                imported_symbols=[name],
            )
            imports.append(imp)

    @staticmethod
    def _expand_use_paths(source: str) -> list:
        """Recursively expand Rust use paths with nested braces into flat paths.

        Example: ``std::{io::{Read, Write}, fmt}``
            → ``['std::io::Read', 'std::io::Write', 'std::fmt']``
        """
        if '{' not in source:
            return [source.strip()] if source.strip() else []

        open_pos = source.index('{')
        base = source[:open_pos].rstrip(':')
        close_pos = RustLanguageParser._find_matching_brace(source, open_pos)
        inner = source[open_pos + 1:close_pos]

        results = []
        for segment in RustLanguageParser._split_respecting_braces(inner):
            segment = segment.strip()
            if not segment:
                continue
            full = f"{base}::{segment}" if base else segment
            # Recurse for nested braces
            results.extend(RustLanguageParser._expand_use_paths(full))
        return results

    @staticmethod
    def _find_matching_brace(s: str, open_pos: int) -> int:
        """Return the index of the closing brace matching the ``{`` at *open_pos*."""
        depth = 0
        for i in range(open_pos, len(s)):
            if s[i] == '{':
                depth += 1
            elif s[i] == '}':
                depth -= 1
                if depth == 0:
                    return i
        return len(s) - 1  # fallback

    @staticmethod
    def _split_respecting_braces(s: str) -> list:
        """Split *s* on commas that are not inside braces."""
        parts = []
        depth = 0
        current = []
        for ch in s:
            if ch == '{':
                depth += 1
                current.append(ch)
            elif ch == '}':
                depth -= 1
                current.append(ch)
            elif ch == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append(''.join(current))
        return parts

    def _parse_variable(self, node, source_bytes, fp, variables, is_const):
        """Parse Rust const/static/let declarations."""
        name_node = self._find_first_child_by_type(node, 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        var_id = self._make_id(fp, name)

        type_n = self._find_first_child_by_type(
            node, 'type_identifier', 'primitive_type', 'reference_type',
            'generic_type', 'array_type', 'tuple_type')
        type_ann = self._extract_text(type_n, source_bytes) if type_n else None

        var = Variable(
            id=var_id,
            name=name,
            var_type=type_ann,
            scope='global',
            is_constant=is_const,
        )
        variables.append(var)

    def _is_pub(self, node, source_bytes) -> bool:
        """Check if a node has pub visibility."""
        for child in node.children:
            if child.type == 'visibility_modifier':
                return True
        return False

    def _extract_attributes(self, node, source_bytes) -> List[str]:
        """Extract Rust attributes (#[...]) as decorators."""
        attrs = []
        parent = node.parent
        if not parent:
            return attrs
        idx = None
        for i, child in enumerate(parent.children):
            if child.id == node.id:
                idx = i
                break
        if idx is None:
            return attrs
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == 'attribute_item':
                text = self._extract_text(sib, source_bytes)
                # Clean up #[...] syntax
                text = text.strip('#[]')
                attrs.append(text)
            else:
                break
        return attrs

    def _extract_rust_parameters(self, node, source_bytes) -> List[Parameter]:
        """Extract Rust function parameters."""
        params = []
        param_list = self._find_first_child_by_type(node, 'parameters')
        if not param_list:
            return params

        for child in param_list.children:
            if child.type == 'parameter':
                # Regular parameter
                pattern = self._find_first_child_by_type(child, 'identifier')
                if pattern:
                    name = self._extract_text(pattern, source_bytes)
                    type_n = self._find_first_child_by_type(
                        child, 'type_identifier', 'primitive_type',
                        'reference_type', 'generic_type', 'array_type',
                        'tuple_type', 'function_type')
                    type_ann = self._extract_text(
                        type_n, source_bytes) if type_n else None
                    params.append(Parameter(
                        name=name, type_annotation=type_ann))
            elif child.type == 'self_parameter':
                text = self._extract_text(child, source_bytes)
                params.append(Parameter(name=text))

        return params

    def _extract_rust_return_type(self, node, source_bytes) -> Optional[str]:
        """Extract Rust function return type."""
        # Look for -> followed by type
        saw_arrow = False
        for child in node.children:
            if self._extract_text(child, source_bytes) == '->':
                saw_arrow = True
                continue
            if saw_arrow and child.type != 'block':
                return self._extract_text(child, source_bytes)
        return None
