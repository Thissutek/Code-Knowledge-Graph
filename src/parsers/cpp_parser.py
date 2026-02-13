"""
C/C++ parser using tree-sitter.
Handles .c, .cpp, .cc, .h, .hpp files.
"""
from pathlib import Path
from typing import Dict, List, Optional

import tree_sitter_c as ts_c
import tree_sitter_cpp as ts_cpp
from tree_sitter import Language, Parser

from ..languages import LanguageConfig, register_parser
from ..models import (
    Class, Function, Variable, Import, Interface,
    Relationship, Parameter
)
from .tree_sitter_base import TreeSitterBaseParser


C_EXTENSIONS = {'.c', '.h'}
CPP_EXTENSIONS = {'.cpp', '.cc', '.cxx', '.hpp', '.hxx'}


@register_parser
class CppLanguageParser(TreeSitterBaseParser):
    """C/C++ parser using tree-sitter."""

    def __init__(self):
        super().__init__()
        self._c_parser: Optional[Parser] = None
        self._cpp_parser: Optional[Parser] = None

    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="C/C++",
            extensions={".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"},
            comment_styles=["//", "/* */"]
        )

    def _ensure_parser(self, is_cpp: bool):
        if is_cpp:
            if self._cpp_parser is None:
                lang = Language(ts_cpp.language())
                self._cpp_parser = Parser(lang)
            return self._cpp_parser
        else:
            if self._c_parser is None:
                lang = Language(ts_c.language())
                self._c_parser = Parser(lang)
            return self._c_parser

    def parse_file(self, file_path: Path, source_code: str) -> Dict:
        ext = file_path.suffix.lower()
        is_cpp = ext in CPP_EXTENSIONS
        parser = self._ensure_parser(is_cpp)

        source_bytes = source_code.encode('utf-8')
        tree = parser.parse(source_bytes)
        root = tree.root_node

        fp = str(file_path)
        classes: List[Class] = []
        functions: List[Function] = []
        variables: List[Variable] = []
        imports: List[Import] = []
        relationships: List[Relationship] = []

        # Track current access specifier for C++ classes
        self._current_access = "public"

        self._walk(root, source_bytes, fp, classes, functions, variables,
                   imports, relationships, current_class=None,
                   current_namespace=None)

        return {
            'classes': classes,
            'functions': functions,
            'variables': variables,
            'imports': imports,
            'interfaces': [],
            'relationships': relationships,
        }

    def _walk(self, node, source_bytes, fp, classes, functions, variables,
              imports, relationships, current_class, current_namespace):
        for child in node.children:
            self._visit_node(child, source_bytes, fp, classes, functions,
                             variables, imports, relationships,
                             current_class, current_namespace)

    def _visit_node(self, node, source_bytes, fp, classes, functions, variables,
                    imports, relationships, current_class, current_namespace):
        ntype = node.type

        if ntype in ('class_specifier', 'struct_specifier'):
            self._parse_class_or_struct(node, source_bytes, fp, classes,
                                        functions, variables, imports,
                                        relationships, current_class,
                                        current_namespace)
        elif ntype == 'enum_specifier':
            self._parse_enum(node, source_bytes, fp, classes, current_namespace)
        elif ntype == 'function_definition':
            self._parse_function(node, source_bytes, fp, functions,
                                 relationships, current_class)
        elif ntype == 'declaration':
            self._parse_declaration(node, source_bytes, fp, functions,
                                    variables, relationships, current_class)
        elif ntype == 'preproc_include':
            self._parse_include(node, source_bytes, fp, imports)
        elif ntype == 'namespace_definition':
            self._parse_namespace(node, source_bytes, fp, classes, functions,
                                  variables, imports, relationships)
        elif ntype == 'access_specifier':
            text = self._extract_text(node, source_bytes).rstrip(':').strip()
            self._current_access = text
        elif ntype == 'field_declaration':
            self._parse_field(node, source_bytes, fp, variables,
                              relationships, current_class)
        else:
            self._walk(node, source_bytes, fp, classes, functions, variables,
                       imports, relationships, current_class, current_namespace)

    def _parse_class_or_struct(self, node, source_bytes, fp, classes,
                               functions, variables, imports,
                               relationships, parent_class,
                               current_namespace):
        name_node = self._find_first_child_by_type(node, 'type_identifier', 'identifier')
        if not name_node:
            return  # Anonymous struct
        name = self._extract_text(name_node, source_bytes)

        if current_namespace:
            full_name = f"{current_namespace}::{name}"
        else:
            full_name = name
        class_id = self._make_id(fp, full_name)

        is_struct = node.type == 'struct_specifier'
        lang_type = "struct" if is_struct else "class"

        # Default access for struct is public, class is private
        if is_struct:
            self._current_access = "public"
        else:
            self._current_access = "private"

        # Base classes
        base_classes = []
        base_clause = self._find_first_child_by_type(node, 'base_class_clause')
        if base_clause:
            for type_node in self._find_descendants_by_type(
                    base_clause, 'type_identifier'):
                base_classes.append(self._extract_text(type_node, source_bytes))

        cls = Class(
            id=class_id,
            name=full_name,
            docstring=self._extract_docstring(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            base_classes=base_classes,
            language_type=lang_type,
        )
        classes.append(cls)

        # Parse body
        body = self._find_first_child_by_type(node, 'field_declaration_list')
        if body:
            self._walk(body, source_bytes, fp, classes, functions, variables,
                       imports, relationships, class_id, current_namespace)

    def _parse_enum(self, node, source_bytes, fp, classes, current_namespace):
        name_node = self._find_first_child_by_type(node, 'type_identifier', 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        if current_namespace:
            name = f"{current_namespace}::{name}"
        class_id = self._make_id(fp, name)

        cls = Class(
            id=class_id,
            name=name,
            docstring=self._extract_docstring(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            language_type="enum",
        )
        classes.append(cls)

    def _parse_function(self, node, source_bytes, fp, functions,
                        relationships, current_class):
        """Parse C/C++ function definition."""
        # Find the declarator which contains the function name
        declarator = self._find_first_child_by_type(
            node, 'function_declarator', 'pointer_declarator')
        if not declarator:
            return

        # Handle pointer to function
        if declarator.type == 'pointer_declarator':
            declarator = self._find_first_child_by_type(
                declarator, 'function_declarator')
            if not declarator:
                return

        name_node = self._find_first_child_by_type(
            declarator, 'identifier', 'field_identifier',
            'qualified_identifier', 'destructor_name')
        if not name_node:
            return

        name = self._extract_text(name_node, source_bytes)
        # For qualified names like ClassName::method
        if '::' in name:
            parts = name.rsplit('::', 1)
            name = parts[-1]

        is_method = current_class is not None
        if is_method:
            func_id = self._make_id(fp, current_class.split(':')[-1], name)
        else:
            func_id = self._make_id(fp, name)

        visibility = self._current_access if is_method else "public"
        params = self._extract_cpp_parameters(declarator, source_bytes)
        return_type = self._extract_cpp_return_type(node, source_bytes)

        # Check for static, virtual, etc.
        specifiers = self._extract_specifiers(node, source_bytes)
        is_static = 'static' in specifiers
        is_virtual = 'virtual' in specifiers

        sig_parts = []
        for p in params:
            part = p.name
            if p.type_annotation:
                part = f"{p.type_annotation} {part}"
            if p.default_value:
                part += f" = {p.default_value}"
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

        if is_method and current_class:
            relationships.append(Relationship(
                rel_type='HAS_METHOD',
                source_id=current_class,
                target_id=func_id,
                properties={'visibility': visibility}
            ))

    def _parse_declaration(self, node, source_bytes, fp, functions,
                           variables, relationships, current_class):
        """Parse a declaration which could be a function prototype or variable."""
        # Check if it contains a function declarator
        func_decl = self._find_descendants_by_type(node, 'function_declarator')
        if func_decl:
            # This is a function declaration/prototype
            # We extract it similarly but mark it
            for fd in func_decl:
                name_node = self._find_first_child_by_type(
                    fd, 'identifier', 'field_identifier',
                    'qualified_identifier')
                if name_node:
                    name = self._extract_text(name_node, source_bytes)
                    if '::' in name:
                        name = name.rsplit('::', 1)[-1]

                    is_method = current_class is not None
                    if is_method:
                        func_id = self._make_id(
                            fp, current_class.split(':')[-1], name)
                    else:
                        func_id = self._make_id(fp, name)

                    # Skip if we already have this function
                    if any(f.id == func_id for f in functions):
                        continue

                    visibility = self._current_access if is_method else "public"
                    params = self._extract_cpp_parameters(fd, source_bytes)
                    return_type = self._extract_cpp_return_type(
                        node, source_bytes)
                    specifiers = self._extract_specifiers(node, source_bytes)

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
                        is_static='static' in specifiers,
                        is_method=is_method,
                        return_type=return_type,
                        complexity=1,
                        parameters=params,
                        visibility=visibility,
                    )
                    functions.append(func)

                    if is_method and current_class:
                        relationships.append(Relationship(
                            rel_type='HAS_METHOD',
                            source_id=current_class,
                            target_id=func_id,
                            properties={'visibility': visibility}
                        ))
        else:
            # Variable declaration
            self._parse_variable_decl(node, source_bytes, fp, variables,
                                      relationships, current_class)

    def _parse_variable_decl(self, node, source_bytes, fp, variables,
                             relationships, current_class):
        """Parse variable declarations."""
        # Get type
        type_node = self._find_first_child_by_type(
            node, 'type_identifier', 'primitive_type', 'sized_type_specifier',
            'template_type', 'auto')
        type_ann = self._extract_text(type_node, source_bytes) if type_node else None

        for declarator in self._find_descendants_by_type(
                node, 'init_declarator', 'identifier'):
            if declarator.type == 'identifier':
                name = self._extract_text(declarator, source_bytes)
            else:
                name_n = self._find_first_child_by_type(
                    declarator, 'identifier')
                if not name_n:
                    continue
                name = self._extract_text(name_n, source_bytes)

            if current_class:
                var_id = self._make_id(
                    fp, current_class.split(':')[-1], name)
            else:
                var_id = self._make_id(fp, name)

            specifiers = self._extract_specifiers(node, source_bytes)
            is_const = 'const' in specifiers or 'constexpr' in specifiers

            var = Variable(
                id=var_id,
                name=name,
                var_type=type_ann,
                scope='class' if current_class else 'global',
                is_constant=is_const,
            )
            variables.append(var)

            if current_class:
                relationships.append(Relationship(
                    rel_type='HAS_VARIABLE',
                    source_id=current_class,
                    target_id=var_id,
                ))

    def _parse_field(self, node, source_bytes, fp, variables,
                     relationships, current_class):
        """Parse class/struct field declarations."""
        type_node = self._find_first_child_by_type(
            node, 'type_identifier', 'primitive_type', 'sized_type_specifier',
            'template_type', 'auto')
        type_ann = self._extract_text(type_node, source_bytes) if type_node else None

        for declarator in self._find_descendants_by_type(
                node, 'field_identifier'):
            name = self._extract_text(declarator, source_bytes)
            if current_class:
                var_id = self._make_id(
                    fp, current_class.split(':')[-1], name)
            else:
                var_id = self._make_id(fp, name)

            var = Variable(
                id=var_id,
                name=name,
                var_type=type_ann,
                scope='class' if current_class else 'global',
                is_constant=False,
            )
            variables.append(var)

            if current_class:
                relationships.append(Relationship(
                    rel_type='HAS_VARIABLE',
                    source_id=current_class,
                    target_id=var_id,
                ))

    def _parse_include(self, node, source_bytes, fp, imports):
        """Parse #include directives."""
        path_node = self._find_first_child_by_type(
            node, 'string_literal', 'system_lib_string')
        if not path_node:
            return
        source = self._extract_text(path_node, source_bytes).strip('<>"')
        name = source.rsplit('/', 1)[-1]
        is_system = path_node.type == 'system_lib_string'

        import_id = self._make_id(fp, 'import', source)
        imp = Import(
            id=import_id,
            name=name,
            source=source,
            is_external=is_system,
            imported_symbols=[],
        )
        imports.append(imp)

    def _parse_namespace(self, node, source_bytes, fp, classes, functions,
                         variables, imports, relationships):
        """Parse C++ namespace definition."""
        name_node = self._find_first_child_by_type(node, 'identifier', 'namespace_identifier')
        ns_name = self._extract_text(name_node, source_bytes) if name_node else None

        body = self._find_first_child_by_type(node, 'declaration_list')
        if body:
            self._walk(body, source_bytes, fp, classes, functions, variables,
                       imports, relationships, current_class=None,
                       current_namespace=ns_name)

    def _extract_cpp_parameters(self, declarator_node, source_bytes) -> List[Parameter]:
        """Extract parameters from a C/C++ function declarator."""
        params = []
        param_list = self._find_first_child_by_type(
            declarator_node, 'parameter_list')
        if not param_list:
            return params

        for child in param_list.children:
            if child.type in ('parameter_declaration', 'optional_parameter_declaration'):
                name_n = self._find_first_child_by_type(
                    child, 'identifier')
                name = self._extract_text(
                    name_n, source_bytes) if name_n else '_'

                type_n = self._find_first_child_by_type(
                    child, 'type_identifier', 'primitive_type',
                    'sized_type_specifier', 'template_type', 'auto')
                type_ann = self._extract_text(
                    type_n, source_bytes) if type_n else None

                default = None
                if child.type == 'optional_parameter_declaration':
                    # Find default value after '='
                    for c in child.children:
                        if c.type == '=':
                            idx = list(child.children).index(c)
                            if idx + 1 < len(child.children):
                                default = self._extract_text(
                                    child.children[idx + 1], source_bytes)

                params.append(Parameter(
                    name=name,
                    type_annotation=type_ann,
                    default_value=default,
                ))
        return params

    def _extract_cpp_return_type(self, node, source_bytes) -> Optional[str]:
        """Extract return type from a C/C++ function."""
        for child in node.children:
            if child.type in ('type_identifier', 'primitive_type',
                              'sized_type_specifier', 'template_type',
                              'auto'):
                return self._extract_text(child, source_bytes)
        return None

    def _extract_specifiers(self, node, source_bytes) -> List[str]:
        """Extract storage/type specifiers."""
        specifiers = []
        for child in node.children:
            if child.type in ('storage_class_specifier', 'type_qualifier',
                              'virtual', 'explicit', 'inline'):
                specifiers.append(self._extract_text(child, source_bytes))
        return specifiers
