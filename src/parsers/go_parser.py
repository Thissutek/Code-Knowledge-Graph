"""
Go parser using tree-sitter.
Handles .go files.
"""
from pathlib import Path
from typing import Dict, List, Optional

import tree_sitter_go as ts_go
from tree_sitter import Language, Parser

from ..languages import LanguageConfig, register_parser
from ..models import (
    Class, Function, Variable, Import, Interface,
    Relationship, Parameter
)
from .tree_sitter_base import TreeSitterBaseParser


@register_parser
class GoLanguageParser(TreeSitterBaseParser):
    """Go parser using tree-sitter."""

    def __init__(self):
        super().__init__()
        self._go_parser: Optional[Parser] = None

    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="Go",
            extensions={".go"},
            comment_styles=["//", "/* */"]
        )

    def _ensure_parser(self):
        if self._go_parser is None:
            lang = Language(ts_go.language())
            self._go_parser = Parser(lang)
        return self._go_parser

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

        if ntype == 'type_declaration':
            self._parse_type_declaration(node, source_bytes, fp, classes,
                                         interfaces, relationships, variables)
        elif ntype == 'function_declaration':
            self._parse_function(node, source_bytes, fp, functions,
                                 relationships)
        elif ntype == 'method_declaration':
            self._parse_method(node, source_bytes, fp, functions,
                               relationships, classes)
        elif ntype == 'import_declaration':
            self._parse_import(node, source_bytes, fp, imports)
        elif ntype in ('var_declaration', 'const_declaration',
                       'short_var_declaration'):
            self._parse_variable(node, source_bytes, fp, variables,
                                 is_const=(ntype == 'const_declaration'))

    def _parse_type_declaration(self, node, source_bytes, fp, classes,
                                interfaces, relationships, variables=None):
        """Parse Go type declarations (struct, interface, type alias)."""
        for spec in self._find_children_by_type(node, 'type_spec'):
            name_node = self._find_first_child_by_type(spec, 'type_identifier')
            if not name_node:
                continue
            name = self._extract_text(name_node, source_bytes)

            # Check what kind of type
            struct_type = self._find_first_child_by_type(spec, 'struct_type')
            iface_type = self._find_first_child_by_type(spec, 'interface_type')

            if struct_type:
                self._parse_struct(name, struct_type, source_bytes, fp,
                                   classes, relationships, node, variables)
            elif iface_type:
                self._parse_interface(name, iface_type, source_bytes, fp,
                                      interfaces, node)
            else:
                # Type alias - treat as class
                class_id = self._make_id(fp, name)
                visibility = "public" if name[0].isupper() else "private"
                cls = Class(
                    id=class_id,
                    name=name,
                    docstring=self._extract_docstring(node, source_bytes),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    language_type="class",
                )
                classes.append(cls)

    def _parse_struct(self, name, struct_node, source_bytes, fp, classes,
                      relationships, decl_node, variables=None):
        """Parse Go struct type."""
        class_id = self._make_id(fp, name)
        visibility = "public" if name[0].isupper() else "private"

        # Extract embedded types and named fields
        base_classes = []
        field_list = self._find_first_child_by_type(struct_node, 'field_declaration_list')
        if field_list:
            for field in self._find_children_by_type(field_list, 'field_declaration'):
                field_names = self._find_children_by_type(field, 'field_identifier')
                type_nodes = self._find_children_by_type(
                    field, 'type_identifier', 'qualified_type', 'pointer_type',
                    'array_type', 'slice_type', 'map_type', 'interface_type',
                    'function_type', 'channel_type', 'struct_type')
                if not field_names and type_nodes:
                    # Embedded type (composition)
                    type_text = self._extract_text(type_nodes[0], source_bytes).lstrip('*')
                    base_classes.append(type_text)
                elif field_names and variables is not None:
                    # Named field — extract as Variable
                    type_ann = self._extract_text(
                        type_nodes[0], source_bytes) if type_nodes else None
                    for fn in field_names:
                        fname = self._extract_text(fn, source_bytes)
                        var_id = self._make_id(fp, name, fname)
                        field_vis = "public" if fname[0].isupper() else "private"
                        var = Variable(
                            id=var_id,
                            name=fname,
                            var_type=type_ann,
                            scope='instance',
                            is_constant=False,
                        )
                        variables.append(var)
                        relationships.append(Relationship(
                            rel_type='HAS_VARIABLE',
                            source_id=class_id,
                            target_id=var_id,
                            properties={'visibility': field_vis}
                        ))

        cls = Class(
            id=class_id,
            name=name,
            docstring=self._extract_docstring(decl_node, source_bytes),
            start_line=decl_node.start_point[0] + 1,
            end_line=decl_node.end_point[0] + 1,
            base_classes=base_classes,
            language_type="struct",
        )
        classes.append(cls)

    def _parse_interface(self, name, iface_node, source_bytes, fp,
                         interfaces, decl_node):
        """Parse Go interface type."""
        iface_id = self._make_id(fp, name)

        methods = []
        for method_spec in self._find_descendants_by_type(
                iface_node, 'method_spec', 'method_elem'):
            name_n = self._find_first_child_by_type(
                method_spec, 'field_identifier')
            if name_n:
                methods.append(self._extract_text(name_n, source_bytes))

        iface = Interface(
            id=iface_id,
            name=name,
            docstring=self._extract_docstring(decl_node, source_bytes),
            methods=methods,
        )
        interfaces.append(iface)

    def _parse_function(self, node, source_bytes, fp, functions, relationships):
        """Parse Go function declaration."""
        name_node = self._find_first_child_by_type(node, 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        func_id = self._make_id(fp, name)

        visibility = "public" if name[0].isupper() else "private"
        params = self._extract_go_parameters(node, source_bytes)
        return_type = self._extract_go_return_type(node, source_bytes)

        sig_parts = []
        for p in params:
            part = p.name
            if p.type_annotation:
                part += f" {p.type_annotation}"
            sig_parts.append(part)
        signature = f"({', '.join(sig_parts)})"
        if return_type:
            signature += f" {return_type}"

        func = Function(
            id=func_id,
            name=name,
            signature=signature,
            docstring=self._extract_docstring(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_async=False,
            is_static=False,
            is_method=False,
            return_type=return_type,
            complexity=self._calculate_complexity(node),
            parameters=params,
            visibility=visibility,
        )
        functions.append(func)

        # Extract function calls
        calls = self._extract_function_calls(
            node, source_bytes, ('call_expression',))
        if calls:
            self._current_function_calls[func_id] = calls

    def _parse_method(self, node, source_bytes, fp, functions,
                      relationships, classes):
        """Parse Go method declaration (with receiver)."""
        name_node = self._find_first_child_by_type(node, 'field_identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)

        # Extract receiver type
        receiver_type = None
        param_list = self._find_first_child_by_type(node, 'parameter_list')
        if param_list:
            for param in self._find_children_by_type(
                    param_list, 'parameter_declaration'):
                type_n = self._find_first_child_by_type(
                    param, 'type_identifier', 'pointer_type')
                if type_n:
                    receiver_type = self._extract_text(
                        type_n, source_bytes).lstrip('*')
                    break

        # Find the class for this receiver
        class_id = None
        if receiver_type:
            for cls in classes:
                if cls.name == receiver_type:
                    class_id = cls.id
                    break
            if class_id is None:
                class_id = self._make_id(fp, receiver_type)

        is_method = class_id is not None
        if is_method:
            func_id = self._make_id(fp, receiver_type, name)
        else:
            func_id = self._make_id(fp, name)

        visibility = "public" if name[0].isupper() else "private"

        # Get parameters (skip receiver)
        params = self._extract_go_parameters(node, source_bytes, skip_first=True)
        return_type = self._extract_go_return_type(node, source_bytes)

        sig_parts = []
        for p in params:
            part = p.name
            if p.type_annotation:
                part += f" {p.type_annotation}"
            sig_parts.append(part)
        signature = f"({', '.join(sig_parts)})"
        if return_type:
            signature += f" {return_type}"

        func = Function(
            id=func_id,
            name=name,
            signature=signature,
            docstring=self._extract_docstring(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_async=False,
            is_static=False,
            is_method=is_method,
            return_type=return_type,
            complexity=self._calculate_complexity(node),
            parameters=params,
            visibility=visibility,
        )
        functions.append(func)

        # Extract function calls
        calls = self._extract_function_calls(
            node, source_bytes, ('call_expression',))
        if calls:
            self._current_function_calls[func_id] = calls

        if is_method and class_id:
            relationships.append(Relationship(
                rel_type='HAS_METHOD',
                source_id=class_id,
                target_id=func_id,
                properties={'visibility': visibility}
            ))

    def _parse_import(self, node, source_bytes, fp, imports):
        """Parse Go import declarations."""
        for spec in self._find_descendants_by_type(node, 'import_spec'):
            path_node = self._find_first_child_by_type(spec, 'interpreted_string_literal')
            if not path_node:
                continue
            source = self._extract_text(path_node, source_bytes).strip('"')
            name = source.rsplit('/', 1)[-1]

            # Check for alias
            alias_node = self._find_first_child_by_type(spec, 'package_identifier', 'dot', 'blank_identifier')
            if alias_node and alias_node.type == 'package_identifier':
                name = self._extract_text(alias_node, source_bytes)

            import_id = self._make_id(fp, 'import', source)
            imp = Import(
                id=import_id,
                name=name,
                source=source,
                is_external=True,
                imported_symbols=[name],
            )
            imports.append(imp)

        # Single import (without parens)
        if not self._find_descendants_by_type(node, 'import_spec'):
            path_node = self._find_first_child_by_type(
                node, 'interpreted_string_literal')
            if path_node:
                source = self._extract_text(path_node, source_bytes).strip('"')
                name = source.rsplit('/', 1)[-1]
                import_id = self._make_id(fp, 'import', source)
                imp = Import(
                    id=import_id,
                    name=name,
                    source=source,
                    is_external=True,
                    imported_symbols=[name],
                )
                imports.append(imp)

    def _parse_variable(self, node, source_bytes, fp, variables, is_const):
        """Parse Go variable/constant declarations."""
        for spec in self._find_descendants_by_type(
                node, 'var_spec', 'const_spec'):
            for name_node in self._find_children_by_type(spec, 'identifier'):
                name = self._extract_text(name_node, source_bytes)
                var_id = self._make_id(fp, name)

                type_n = self._find_first_child_by_type(
                    spec, 'type_identifier', 'pointer_type',
                    'array_type', 'slice_type', 'map_type')
                type_ann = self._extract_text(
                    type_n, source_bytes) if type_n else None

                var = Variable(
                    id=var_id,
                    name=name,
                    var_type=type_ann,
                    scope='global',
                    is_constant=is_const,
                )
                variables.append(var)

    def _extract_go_parameters(self, node, source_bytes,
                               skip_first: bool = False) -> List[Parameter]:
        """Extract parameters from Go function/method."""
        params = []
        param_lists = self._find_children_by_type(node, 'parameter_list')
        if not param_lists:
            return params

        # For methods, first parameter_list is receiver, second is params
        if skip_first and len(param_lists) > 1:
            param_list = param_lists[1]
        elif skip_first:
            return params
        else:
            param_list = param_lists[0]

        for param_decl in self._find_children_by_type(
                param_list, 'parameter_declaration'):
            type_n = self._find_first_child_by_type(
                param_decl, 'type_identifier', 'pointer_type',
                'array_type', 'slice_type', 'map_type',
                'interface_type', 'function_type', 'channel_type',
                'qualified_type', 'struct_type')
            type_ann = self._extract_text(type_n, source_bytes) if type_n else None

            for name_n in self._find_children_by_type(param_decl, 'identifier'):
                name = self._extract_text(name_n, source_bytes)
                params.append(Parameter(name=name, type_annotation=type_ann))

            # Unnamed parameter (just a type)
            if not self._find_children_by_type(param_decl, 'identifier') and type_ann:
                params.append(Parameter(name='_', type_annotation=type_ann))

        return params

    def _extract_go_return_type(self, node, source_bytes) -> Optional[str]:
        """Extract return type from Go function."""
        # Look for result types after the parameter lists
        param_lists = self._find_children_by_type(node, 'parameter_list')
        body = self._find_first_child_by_type(node, 'block')

        # Find nodes between last param list and body
        in_result = False
        for child in node.children:
            if child.type == 'parameter_list':
                in_result = True
                continue
            if child.type == 'block':
                break
            if in_result and child.type in ('type_identifier', 'pointer_type',
                                             'array_type', 'slice_type',
                                             'map_type', 'parameter_list',
                                             'qualified_type', 'interface_type'):
                return self._extract_text(child, source_bytes)

        return None
