"""
TypeScript/JavaScript parser using tree-sitter.
Handles .ts, .tsx, .js, .jsx files.
"""
from pathlib import Path
from typing import Dict, List, Optional

import tree_sitter_typescript as ts_typescript

from ..languages import LanguageConfig, register_parser
from ..models import (
    Class, Function, Variable, Import, Interface,
    Relationship, Parameter
)
from .tree_sitter_base import TreeSitterBaseParser


@register_parser
class TypeScriptLanguageParser(TreeSitterBaseParser):
    """TypeScript/JavaScript parser using tree-sitter."""

    def __init__(self):
        super().__init__()
        self._ts_parser = None
        self._tsx_parser = None

    @property
    def config(self) -> LanguageConfig:
        return LanguageConfig(
            name="TypeScript",
            extensions={".ts", ".tsx", ".js", ".jsx"},
            comment_styles=["//", "/* */"]
        )

    def _ensure_parser(self, is_tsx: bool):
        """Lazily initialize the correct parser variant."""
        if is_tsx:
            if self._tsx_parser is None:
                from tree_sitter import Language, Parser
                lang = Language(ts_typescript.language_tsx())
                self._tsx_parser = Parser(lang)
            return self._tsx_parser
        else:
            if self._ts_parser is None:
                from tree_sitter import Language, Parser
                lang = Language(ts_typescript.language_typescript())
                self._ts_parser = Parser(lang)
            return self._ts_parser

    def parse_file(self, file_path: Path, source_code: str) -> Dict:
        ext = file_path.suffix.lower()
        is_tsx = ext in ('.tsx', '.jsx')
        parser = self._ensure_parser(is_tsx)

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
                              variables, relationships, current_class)
        elif ntype in ('function_declaration', 'method_definition',
                       'generator_function_declaration'):
            self._parse_function(node, source_bytes, fp, functions,
                                 relationships, current_class)
        elif ntype in ('lexical_declaration', 'variable_declaration'):
            self._parse_variable_declaration(node, source_bytes, fp, functions,
                                             variables, relationships,
                                             current_class)
        elif ntype in ('import_statement', 'import_declaration'):
            self._parse_import(node, source_bytes, fp, imports)
        elif ntype in ('export_statement', 'export_declaration'):
            # Process children of exports
            self._walk(node, source_bytes, fp, classes, functions, variables,
                       imports, interfaces, relationships, current_class)
        elif ntype == 'interface_declaration':
            self._parse_interface(node, source_bytes, fp, interfaces)
        elif ntype in ('enum_declaration',):
            self._parse_enum(node, source_bytes, fp, classes, relationships)
        else:
            self._walk(node, source_bytes, fp, classes, functions, variables,
                       imports, interfaces, relationships, current_class)

    def _parse_class(self, node, source_bytes, fp, classes, functions,
                     variables, relationships, parent_class):
        name_node = self._find_first_child_by_type(node, 'type_identifier', 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        class_id = self._make_id(fp, name)

        base_classes = []
        heritage = self._find_first_child_by_type(node, 'class_heritage')
        if heritage:
            extends_clause = self._find_descendants_by_type(heritage, 'extends_clause')
            for ec in extends_clause:
                type_nodes = self._find_children_by_type(ec, 'identifier', 'type_identifier')
                for tn in type_nodes:
                    base_classes.append(self._extract_text(tn, source_bytes))

            implements_clause = self._find_descendants_by_type(heritage, 'implements_clause')
            for ic in implements_clause:
                type_nodes = self._find_descendants_by_type(ic, 'type_identifier', 'identifier')
                for tn in type_nodes:
                    iface_name = self._extract_text(tn, source_bytes)
                    relationships.append(Relationship(
                        rel_type='IMPLEMENTS',
                        source_id=class_id,
                        target_id=iface_name
                    ))

        is_abstract = any(
            self._extract_text(c, source_bytes) == 'abstract'
            for c in self._find_children_by_type(node, 'abstract')
        )

        decorators = self._extract_decorators(node, source_bytes)

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

        body = self._find_first_child_by_type(node, 'class_body')
        if body:
            for child in body.children:
                if child.type in ('method_definition', 'public_field_definition',
                                  'property_definition', 'field_definition'):
                    if child.type == 'method_definition':
                        self._parse_function(child, source_bytes, fp, functions,
                                             relationships, class_id)
                    else:
                        self._parse_class_field(child, source_bytes, fp,
                                                variables, relationships, class_id)

    def _parse_function(self, node, source_bytes, fp, functions, relationships,
                        current_class):
        name_node = self._find_first_child_by_type(
            node, 'identifier', 'property_identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        is_method = current_class is not None

        if is_method:
            func_id = self._make_id(fp, current_class.split(':')[-1], name)
        else:
            func_id = self._make_id(fp, name)

        params = self._extract_parameters(node, source_bytes)
        return_type = self._extract_return_type(node, source_bytes)
        is_async = any(
            self._extract_text(c, source_bytes) == 'async'
            for c in node.children if c.type in ('async', 'identifier')
        )
        is_static = any(
            self._extract_text(c, source_bytes) == 'static'
            for c in node.children if c.type in ('static', 'identifier')
        )

        visibility = "public"
        for child in node.children:
            text = self._extract_text(child, source_bytes)
            if text == 'private' or name.startswith('#'):
                visibility = "private"
                break
            elif text == 'protected':
                visibility = "protected"
                break

        sig_parts = []
        for p in params:
            part = p.name
            if p.type_annotation:
                part += f": {p.type_annotation}"
            if p.default_value:
                part += f" = {p.default_value}"
            sig_parts.append(part)
        signature = f"({', '.join(sig_parts)})"
        if return_type:
            signature += f" -> {return_type}"

        decorators = self._extract_decorators(node, source_bytes)

        func = Function(
            id=func_id,
            name=name,
            signature=signature,
            docstring=self._extract_docstring(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_async=is_async,
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
            node, source_bytes, ('call_expression', 'new_expression'))
        if calls:
            self._current_function_calls[func_id] = calls

        if is_method and current_class:
            relationships.append(Relationship(
                rel_type='HAS_METHOD',
                source_id=current_class,
                target_id=func_id,
                properties={'visibility': visibility}
            ))

    def _parse_variable_declaration(self, node, source_bytes, fp, functions,
                                    variables, relationships, current_class):
        """Parse variable declarations, detecting arrow function assignments."""
        for declarator in self._find_children_by_type(node, 'variable_declarator'):
            name_node = self._find_first_child_by_type(declarator, 'identifier')
            if not name_node:
                continue
            name = self._extract_text(name_node, source_bytes)

            value_node = self._find_first_child_by_type(
                declarator, 'arrow_function', 'function_expression',
                'generator_function')
            if value_node:
                # This is a function assigned to a variable
                func_id = self._make_id(fp, name)
                params = self._extract_parameters(value_node, source_bytes)
                return_type = self._extract_return_type(value_node, source_bytes)
                is_async = any(
                    self._extract_text(c, source_bytes) == 'async'
                    for c in value_node.children if c.type in ('async',)
                )

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
                    is_static=False,
                    is_method=False,
                    return_type=return_type,
                    complexity=self._calculate_complexity(value_node),
                    parameters=params,
                    visibility="public",
                )
                functions.append(func)
            else:
                # Regular variable
                is_const = any(
                    self._extract_text(c, source_bytes) == 'const'
                    for c in node.children
                )
                type_ann = None
                type_node = self._find_first_child_by_type(
                    declarator, 'type_annotation')
                if type_node:
                    type_ann = self._extract_text(type_node, source_bytes).lstrip(': ')

                var_id = self._make_id(fp, name)
                scope = 'class' if current_class else 'global'
                var = Variable(
                    id=var_id,
                    name=name,
                    var_type=type_ann,
                    scope=scope,
                    is_constant=is_const or name.isupper(),
                )
                variables.append(var)

                if current_class:
                    relationships.append(Relationship(
                        rel_type='HAS_VARIABLE',
                        source_id=current_class,
                        target_id=var_id,
                    ))

    def _parse_import(self, node, source_bytes, fp, imports):
        """Parse ES6 import statements."""
        source_node = self._find_first_child_by_type(node, 'string')
        if not source_node:
            return
        source = self._extract_text(source_node, source_bytes).strip("'\"")
        is_external = not source.startswith('.')

        symbols = []
        for named in self._find_descendants_by_type(node, 'import_specifier'):
            name_n = self._find_first_child_by_type(named, 'identifier')
            if name_n:
                symbols.append(self._extract_text(name_n, source_bytes))

        # Default import
        default_import = None
        for child in node.children:
            if child.type == 'identifier' and child != self._find_first_child_by_type(node, 'string'):
                default_import = self._extract_text(child, source_bytes)
                break

        import_name = default_import or source.split('/')[-1]
        import_id = self._make_id(fp, 'import', source)

        imp = Import(
            id=import_id,
            name=import_name,
            source=source,
            is_external=is_external,
            imported_symbols=symbols,
        )
        imports.append(imp)

    def _parse_interface(self, node, source_bytes, fp, interfaces):
        """Parse TypeScript interface declarations."""
        name_node = self._find_first_child_by_type(node, 'type_identifier', 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        iface_id = self._make_id(fp, name)

        methods = []
        body = self._find_first_child_by_type(node, 'interface_body', 'object_type')
        if body:
            for sig in self._find_descendants_by_type(body, 'method_signature',
                                                       'property_signature'):
                sig_name = self._find_first_child_by_type(sig, 'property_identifier', 'identifier')
                if sig_name:
                    methods.append(self._extract_text(sig_name, source_bytes))

        iface = Interface(
            id=iface_id,
            name=name,
            docstring=self._extract_docstring(node, source_bytes),
            methods=methods,
        )
        interfaces.append(iface)

    def _parse_enum(self, node, source_bytes, fp, classes, relationships):
        """Parse TypeScript enum declarations as Class with language_type='enum'."""
        name_node = self._find_first_child_by_type(node, 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
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

    def _parse_class_field(self, node, source_bytes, fp, variables,
                           relationships, class_id):
        """Parse class field/property definitions."""
        name_node = self._find_first_child_by_type(
            node, 'property_identifier', 'identifier')
        if not name_node:
            return
        name = self._extract_text(name_node, source_bytes)
        var_id = self._make_id(fp, class_id.split(':')[-1], name)

        type_ann = None
        type_node = self._find_first_child_by_type(node, 'type_annotation')
        if type_node:
            type_ann = self._extract_text(type_node, source_bytes).lstrip(': ')

        var = Variable(
            id=var_id,
            name=name,
            var_type=type_ann,
            scope='class',
            is_constant=False,
        )
        variables.append(var)
        relationships.append(Relationship(
            rel_type='HAS_VARIABLE',
            source_id=class_id,
            target_id=var_id,
        ))

    def _extract_parameters(self, node, source_bytes) -> List[Parameter]:
        """Extract function parameters from a function node."""
        params = []
        param_list = self._find_first_child_by_type(
            node, 'formal_parameters', 'parameters')
        if not param_list:
            return params

        for param_node in param_list.children:
            if param_node.type in ('required_parameter', 'optional_parameter',
                                    'formal_parameter', 'identifier',
                                    'rest_parameter', 'parameter'):
                if param_node.type == 'identifier':
                    params.append(Parameter(
                        name=self._extract_text(param_node, source_bytes)))
                else:
                    name_n = self._find_first_child_by_type(
                        param_node, 'identifier')
                    if name_n:
                        name = self._extract_text(name_n, source_bytes)
                        type_ann = None
                        type_n = self._find_first_child_by_type(
                            param_node, 'type_annotation')
                        if type_n:
                            type_ann = self._extract_text(
                                type_n, source_bytes).lstrip(': ')
                        default = None
                        for child in param_node.children:
                            if child.type == '=':
                                idx = list(param_node.children).index(child)
                                if idx + 1 < len(param_node.children):
                                    default = self._extract_text(
                                        param_node.children[idx + 1],
                                        source_bytes)
                        params.append(Parameter(
                            name=name,
                            type_annotation=type_ann,
                            default_value=default,
                        ))
        return params

    def _extract_return_type(self, node, source_bytes) -> Optional[str]:
        """Extract return type annotation."""
        for child in node.children:
            if child.type == 'type_annotation':
                return self._extract_text(child, source_bytes).lstrip(': ')
        return None

    def _extract_decorators(self, node, source_bytes) -> List[str]:
        """Extract decorator names from preceding decorator nodes."""
        decorators = []
        parent = node.parent
        if not parent:
            return decorators
        idx = None
        for i, child in enumerate(parent.children):
            if child.id == node.id:
                idx = i
                break
        if idx is None:
            return decorators
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == 'decorator':
                name_node = self._find_first_child_by_type(sib, 'identifier', 'call_expression')
                if name_node:
                    if name_node.type == 'call_expression':
                        fn = self._find_first_child_by_type(name_node, 'identifier')
                        if fn:
                            decorators.append(self._extract_text(fn, source_bytes))
                    else:
                        decorators.append(self._extract_text(name_node, source_bytes))
            else:
                break
        return decorators
