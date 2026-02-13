"""
Java parser using tree-sitter.
Handles .java files.
"""
from pathlib import Path
from typing import Dict, List, Optional

import tree_sitter_java as ts_java
from tree_sitter import Language, Parser

from ..languages import LanguageConfig, register_parser
from ..models import (
    Class, Function, Variable, Import, Interface,
    Relationship, Parameter
)
from .tree_sitter_base import TreeSitterBaseParser


@register_parser
class JavaLanguageParser(TreeSitterBaseParser):
    """Java parser using tree-sitter."""

    def __init__(self):
        super().__init__()
        self._java_parser: Optional[Parser] = None

    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="Java",
            extensions={".java"},
            comment_styles=["//", "/* */", "/** */"]
        )

    def _ensure_parser(self):
        if self._java_parser is None:
            lang = Language(ts_java.language())
            self._java_parser = Parser(lang)
        return self._java_parser

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

        self._walk(root, source_bytes, fp, classes, functions, variables,
                   imports, interfaces, relationships, current_class=None)

        return {
            'classes': classes,
            'functions': functions,
            'variables': variables,
            'imports': imports,
            'interfaces': interfaces,
            'relationships': relationships,
            'function_calls': self._current_function_calls,
        }

    def _walk(self, node, source_bytes, fp, classes, functions, variables,
              imports, interfaces, relationships, current_class):
        for child in node.children:
            self._visit_node(child, source_bytes, fp, classes, functions,
                             variables, imports, interfaces, relationships,
                             current_class)

    def _visit_node(self, node, source_bytes, fp, classes, functions, variables,
                    imports, interfaces, relationships, current_class):
        ntype = node.type

        if ntype == 'class_declaration':
            self._parse_class(node, source_bytes, fp, classes, functions,
                              variables, imports, interfaces, relationships,
                              current_class)
        elif ntype == 'interface_declaration':
            self._parse_interface(node, source_bytes, fp, interfaces,
                                  functions, relationships)
        elif ntype == 'enum_declaration':
            self._parse_enum(node, source_bytes, fp, classes, functions,
                             variables, relationships, current_class)
        elif ntype in ('method_declaration', 'constructor_declaration'):
            self._parse_method(node, source_bytes, fp, functions,
                               relationships, current_class)
        elif ntype == 'import_declaration':
            self._parse_import(node, source_bytes, fp, imports)
        elif ntype == 'field_declaration':
            self._parse_field(node, source_bytes, fp, variables,
                              relationships, current_class)
        elif ntype == 'package_declaration':
            pass  # Could be used for module info
        else:
            self._walk(node, source_bytes, fp, classes, functions, variables,
                       imports, interfaces, relationships, current_class)

    def _parse_class(self, node, source_bytes, fp, classes, functions,
                     variables, imports, interfaces, relationships, parent_class):
        name_node = self._find_first_child_by_type(node, 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        class_id = self._make_id(fp, name)

        modifiers = self._extract_modifiers(node, source_bytes)
        is_abstract = 'abstract' in modifiers
        decorators = self._extract_annotations(node, source_bytes)

        base_classes = []
        superclass = self._find_first_child_by_type(node, 'superclass')
        if superclass:
            type_node = self._find_first_child_by_type(
                superclass, 'type_identifier', 'identifier')
            if type_node:
                base_classes.append(self._extract_text(type_node, source_bytes))

        # Interfaces
        impl = self._find_first_child_by_type(node, 'super_interfaces')
        if impl:
            for type_node in self._find_descendants_by_type(
                    impl, 'type_identifier', 'identifier'):
                iface_name = self._extract_text(type_node, source_bytes)
                relationships.append(Relationship(
                    rel_type='IMPLEMENTS',
                    source_id=class_id,
                    target_id=iface_name,
                ))

        cls = Class(
            id=class_id,
            name=name,
            docstring=self._extract_docstring(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_abstract=is_abstract,
            decorators=decorators,
            base_classes=base_classes,
            language_type="class",
        )
        classes.append(cls)

        # If inner class, add relationship to parent
        if parent_class:
            relationships.append(Relationship(
                rel_type='HAS_VARIABLE',
                source_id=parent_class,
                target_id=class_id,
                properties={'kind': 'inner_class'}
            ))

        # Parse body
        body = self._find_first_child_by_type(node, 'class_body')
        if body:
            self._walk(body, source_bytes, fp, classes, functions, variables,
                       imports, interfaces, relationships, class_id)

    def _parse_interface(self, node, source_bytes, fp, interfaces,
                         functions, relationships):
        name_node = self._find_first_child_by_type(node, 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        iface_id = self._make_id(fp, name)

        methods = []
        body = self._find_first_child_by_type(node, 'interface_body')
        if body:
            for method_node in self._find_children_by_type(
                    body, 'method_declaration', 'constant_declaration'):
                mn = self._find_first_child_by_type(method_node, 'identifier')
                if mn:
                    methods.append(self._extract_text(mn, source_bytes))

        iface = Interface(
            id=iface_id,
            name=name,
            docstring=self._extract_docstring(node, source_bytes),
            methods=methods,
        )
        interfaces.append(iface)

    def _parse_enum(self, node, source_bytes, fp, classes, functions,
                    variables, relationships, parent_class):
        name_node = self._find_first_child_by_type(node, 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        class_id = self._make_id(fp, name)

        decorators = self._extract_annotations(node, source_bytes)

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

        # Parse enum body for methods
        body = self._find_first_child_by_type(node, 'enum_body')
        if body:
            for child in body.children:
                if child.type in ('method_declaration', 'constructor_declaration'):
                    self._parse_method(child, source_bytes, fp, functions,
                                       relationships, class_id)

    def _parse_method(self, node, source_bytes, fp, functions,
                      relationships, current_class):
        name_node = self._find_first_child_by_type(node, 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        is_method = current_class is not None

        if is_method:
            func_id = self._make_id(fp, current_class.split(':')[-1], name)
        else:
            func_id = self._make_id(fp, name)

        modifiers = self._extract_modifiers(node, source_bytes)
        visibility = "public"
        if 'private' in modifiers:
            visibility = "private"
        elif 'protected' in modifiers:
            visibility = "protected"

        is_static = 'static' in modifiers
        is_abstract = 'abstract' in modifiers

        params = self._extract_parameters(node, source_bytes)
        return_type = self._extract_return_type(node, source_bytes)
        decorators = self._extract_annotations(node, source_bytes)

        sig_parts = []
        for p in params:
            part = p.name
            if p.type_annotation:
                part = f"{p.type_annotation} {part}"
            sig_parts.append(part)
        signature = f"({', '.join(sig_parts)})"
        if return_type:
            signature = f"{return_type} {name}{signature}"

        func = Function(
            id=func_id,
            name=name,
            signature=signature,
            docstring=self._extract_docstring(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_async=False,
            is_static=is_static,
            is_method=is_method,
            return_type=return_type,
            complexity=self._calculate_complexity(node),
            parameters=params,
            visibility=visibility,
        )
        functions.append(func)

        # Extract function calls
        calls = self._extract_function_calls(
            node, source_bytes, ('method_invocation', 'object_creation_expression'))
        if calls:
            self._current_function_calls[func_id] = calls

        if is_method and current_class:
            relationships.append(Relationship(
                rel_type='HAS_METHOD',
                source_id=current_class,
                target_id=func_id,
                properties={'visibility': visibility}
            ))

    def _parse_import(self, node, source_bytes, fp, imports):
        text = self._extract_text(node, source_bytes).strip()
        # Remove 'import ' prefix and trailing ';'
        source = text.replace('import ', '').replace('static ', '').rstrip(';').strip()
        parts = source.rsplit('.', 1)
        name = parts[-1] if parts else source
        import_id = self._make_id(fp, 'import', source)

        imp = Import(
            id=import_id,
            name=name,
            source=source,
            is_external=True,
            imported_symbols=[name] if name != '*' else [],
        )
        imports.append(imp)

    def _parse_field(self, node, source_bytes, fp, variables,
                     relationships, current_class):
        modifiers = self._extract_modifiers(node, source_bytes)
        is_static = 'static' in modifiers
        is_final = 'final' in modifiers

        type_node = self._find_first_child_by_type(
            node, 'type_identifier', 'integral_type', 'boolean_type',
            'floating_point_type', 'void_type', 'generic_type',
            'array_type', 'identifier')
        type_ann = self._extract_text(type_node, source_bytes) if type_node else None

        for declarator in self._find_descendants_by_type(node, 'variable_declarator'):
            name_node = self._find_first_child_by_type(declarator, 'identifier')
            if not name_node:
                continue
            name = self._extract_text(name_node, source_bytes)

            if current_class:
                var_id = self._make_id(fp, current_class.split(':')[-1], name)
            else:
                var_id = self._make_id(fp, name)

            var = Variable(
                id=var_id,
                name=name,
                var_type=type_ann,
                scope='class' if current_class else 'global',
                is_constant=is_final and is_static,
            )
            variables.append(var)

            if current_class:
                relationships.append(Relationship(
                    rel_type='HAS_VARIABLE',
                    source_id=current_class,
                    target_id=var_id,
                ))

    def _extract_modifiers(self, node, source_bytes) -> List[str]:
        """Extract Java modifiers (public, private, static, etc.)."""
        modifiers = []
        for child in node.children:
            if child.type == 'modifiers':
                for mod in child.children:
                    if mod.type in ('public', 'private', 'protected', 'static',
                                    'final', 'abstract', 'synchronized',
                                    'volatile', 'transient', 'native',
                                    'default', 'strictfp'):
                        modifiers.append(mod.type)
                    elif mod.type == 'modifier':
                        modifiers.append(self._extract_text(mod, source_bytes))
        return modifiers

    def _extract_annotations(self, node, source_bytes) -> List[str]:
        """Extract Java annotations as decorators."""
        annotations = []
        for child in node.children:
            if child.type == 'modifiers':
                for mod in child.children:
                    if mod.type in ('marker_annotation', 'annotation'):
                        name_n = self._find_first_child_by_type(mod, 'identifier')
                        if name_n:
                            annotations.append(self._extract_text(name_n, source_bytes))
        return annotations

    def _extract_parameters(self, node, source_bytes) -> List[Parameter]:
        params = []
        param_list = self._find_first_child_by_type(node, 'formal_parameters')
        if not param_list:
            return params

        for param_node in self._find_children_by_type(
                param_list, 'formal_parameter', 'spread_parameter'):
            name_n = self._find_first_child_by_type(param_node, 'identifier')
            if not name_n:
                continue
            name = self._extract_text(name_n, source_bytes)

            type_n = self._find_first_child_by_type(
                param_node, 'type_identifier', 'integral_type',
                'boolean_type', 'floating_point_type', 'generic_type',
                'array_type', 'void_type')
            type_ann = self._extract_text(type_n, source_bytes) if type_n else None

            params.append(Parameter(name=name, type_annotation=type_ann))
        return params

    def _extract_return_type(self, node, source_bytes) -> Optional[str]:
        """Extract return type for Java methods."""
        for child in node.children:
            if child.type in ('type_identifier', 'integral_type',
                              'boolean_type', 'floating_point_type',
                              'void_type', 'generic_type', 'array_type'):
                # Make sure it's before the method name
                name_node = self._find_first_child_by_type(node, 'identifier')
                if name_node and child.end_byte <= name_node.start_byte:
                    return self._extract_text(child, source_bytes)
        return None
