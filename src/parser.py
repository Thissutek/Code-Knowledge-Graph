"""
Python Code Parser
Extracts code structure from Python files using AST
"""
import ast
import os
import hashlib
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from .models import (
    ParsedCodebase, Repository, File, Module, Class, Function,
    Variable, Import, Parameter, Relationship
)


class PythonParser(ast.NodeVisitor):
    """AST visitor that extracts code structure from Python files"""

    def __init__(self, file_path: str, repo_id: str, source_code: str):
        self.file_path = file_path
        self.repo_id = repo_id
        self.source_code = source_code
        self.lines = source_code.split('\n')

        # Current context
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None

        # Extracted entities
        self.classes: List[Class] = []
        self.functions: List[Function] = []
        self.variables: List[Variable] = []
        self.imports: List[Import] = []

        # Relationships
        self.relationships: List[Relationship] = []

        # Tracking for call resolution
        self.function_calls: Dict[str, List[Tuple[str, int]]] = {}  # function_id -> [(called_name, line)]
        self.class_usages: Dict[str, Set[str]] = {}  # function_id -> set of class names used

    def _make_id(self, *parts) -> str:
        """Create a unique ID from parts"""
        return ':'.join(filter(None, [self.file_path] + list(parts)))

    def _get_docstring(self, node) -> str:
        """Extract docstring from a node"""
        return ast.get_docstring(node) or ""

    def _get_decorators(self, node) -> List[str]:
        """Extract decorator names from a node"""
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    decorators.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    decorators.append(dec.func.attr)
            elif isinstance(dec, ast.Attribute):
                decorators.append(dec.attr)
        return decorators

    def _get_type_annotation(self, annotation) -> Optional[str]:
        """Convert type annotation AST to string"""
        if annotation is None:
            return None
        try:
            return ast.unparse(annotation)
        except:
            return str(annotation)

    def _calculate_complexity(self, node) -> int:
        """Calculate cyclomatic complexity of a function"""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
            elif isinstance(child, (ast.Assert, ast.comprehension)):
                complexity += 1
        return complexity

    def _get_base_classes(self, node: ast.ClassDef) -> List[str]:
        """Extract base class names"""
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(f"{ast.unparse(base)}")
        return bases

    def visit_Import(self, node: ast.Import):
        """Handle import statements"""
        for alias in node.names:
            import_id = self._make_id('import', alias.name)
            imp = Import(
                id=import_id,
                name=alias.asname or alias.name,
                source=alias.name,
                is_external=not alias.name.startswith('.')
            )
            self.imports.append(imp)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Handle from ... import statements"""
        module = node.module or ''
        for alias in node.names:
            import_id = self._make_id('import', module, alias.name)
            imp = Import(
                id=import_id,
                name=alias.asname or alias.name,
                source=f"{module}.{alias.name}" if module else alias.name,
                is_external=not module.startswith('.') if module else True,
                imported_symbols=[alias.name]
            )
            self.imports.append(imp)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        """Handle class definitions"""
        class_id = self._make_id(node.name)

        # Check if abstract
        is_abstract = any(
            isinstance(base, ast.Attribute) and base.attr == 'ABC'
            or isinstance(base, ast.Name) and base.id == 'ABC'
            for base in node.bases
        ) or any(
            d in ['abstractmethod', 'abstractproperty']
            for d in self._get_decorators(node)
        )

        cls = Class(
            id=class_id,
            name=node.name,
            docstring=self._get_docstring(node),
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            is_abstract=is_abstract,
            decorators=self._get_decorators(node),
            base_classes=self._get_base_classes(node)
        )
        self.classes.append(cls)

        # Visit children with class context
        old_class = self.current_class
        self.current_class = class_id
        self.generic_visit(node)
        self.current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Handle function definitions"""
        self._process_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Handle async function definitions"""
        self._process_function(node, is_async=True)

    def _process_function(self, node, is_async: bool):
        """Process a function or method definition"""
        is_method = self.current_class is not None

        if is_method:
            func_id = self._make_id(self.current_class.split(':')[-1], node.name)
        else:
            func_id = self._make_id(node.name)

        # Extract parameters
        parameters = []
        for arg in node.args.args:
            param = Parameter(
                name=arg.arg,
                type_annotation=self._get_type_annotation(arg.annotation)
            )
            parameters.append(param)

        # Handle default values
        defaults = node.args.defaults
        if defaults:
            offset = len(parameters) - len(defaults)
            for i, default in enumerate(defaults):
                try:
                    parameters[offset + i].default_value = ast.unparse(default)
                except:
                    pass

        # Determine visibility
        visibility = "public"
        if node.name.startswith('__') and not node.name.endswith('__'):
            visibility = "private"
        elif node.name.startswith('_'):
            visibility = "protected"

        # Build signature
        sig_parts = []
        for p in parameters:
            part = p.name
            if p.type_annotation:
                part += f": {p.type_annotation}"
            if p.default_value:
                part += f" = {p.default_value}"
            sig_parts.append(part)

        return_type = self._get_type_annotation(node.returns)
        signature = f"({', '.join(sig_parts)})"
        if return_type:
            signature += f" -> {return_type}"

        decorators = self._get_decorators(node)
        is_static = 'staticmethod' in decorators

        func = Function(
            id=func_id,
            name=node.name,
            signature=signature,
            docstring=self._get_docstring(node),
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            is_async=is_async,
            is_static=is_static,
            is_method=is_method,
            return_type=return_type,
            complexity=self._calculate_complexity(node),
            parameters=parameters,
            visibility=visibility
        )
        self.functions.append(func)

        # Add method relationship if in class
        if is_method:
            self.relationships.append(Relationship(
                rel_type='HAS_METHOD',
                source_id=self.current_class,
                target_id=func_id,
                properties={'visibility': visibility}
            ))

        # Track function calls within this function
        self.function_calls[func_id] = []
        self.class_usages[func_id] = set()

        # Visit children with function context
        old_func = self.current_function
        self.current_function = func_id
        self.generic_visit(node)
        self.current_function = old_func

    def visit_Call(self, node: ast.Call):
        """Track function calls"""
        if self.current_function:
            called_name = None
            if isinstance(node.func, ast.Name):
                called_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                called_name = node.func.attr

            if called_name:
                self.function_calls[self.current_function].append(
                    (called_name, node.lineno)
                )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        """Track class usages (instantiation, type hints, etc.)"""
        if self.current_function and node.id[0].isupper():
            self.class_usages[self.current_function].add(node.id)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        """Handle variable assignments at module/class level"""
        if self.current_function is None:  # Only module/class level
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_id = self._make_id(target.id)
                    if self.current_class:
                        var_id = self._make_id(self.current_class.split(':')[-1], target.id)

                    # Check if it's a constant (ALL_CAPS)
                    is_constant = target.id.isupper()

                    var = Variable(
                        id=var_id,
                        name=target.id,
                        scope='class' if self.current_class else 'global',
                        is_constant=is_constant
                    )
                    self.variables.append(var)

                    if self.current_class:
                        self.relationships.append(Relationship(
                            rel_type='HAS_VARIABLE',
                            source_id=self.current_class,
                            target_id=var_id
                        ))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        """Handle annotated assignments"""
        if self.current_function is None and isinstance(node.target, ast.Name):
            var_id = self._make_id(node.target.id)
            if self.current_class:
                var_id = self._make_id(self.current_class.split(':')[-1], node.target.id)

            var = Variable(
                id=var_id,
                name=node.target.id,
                var_type=self._get_type_annotation(node.annotation),
                scope='class' if self.current_class else 'global',
                is_constant=node.target.id.isupper()
            )
            self.variables.append(var)

            if self.current_class:
                self.relationships.append(Relationship(
                    rel_type='HAS_VARIABLE',
                    source_id=self.current_class,
                    target_id=var_id
                ))
        self.generic_visit(node)


class CodebaseParser:
    """Main parser for analyzing entire codebases"""

    IGNORE_DIRS = {'.git', '.svn', '__pycache__', 'node_modules', 'venv', '.venv', 'env', '.env', 'dist', 'build'}

    def __init__(self, repo_path: str, repo_id: Optional[str] = None):
        self.repo_path = Path(repo_path).resolve()
        self.repo_id = repo_id or self.repo_path.name
        self._pending_function_calls: Dict[str, Dict] = {}
        self._pending_class_usages: Dict[str, Dict] = {}

    def parse(self) -> ParsedCodebase:
        """Parse the entire codebase"""
        from .languages import get_all_supported_extensions

        self._pending_function_calls = {}
        self._pending_class_usages = {}

        # Create repository entity
        repo = Repository(
            id=self.repo_id,
            name=self.repo_path.name,
            path=str(self.repo_path),
            language='multi'
        )

        codebase = ParsedCodebase(repository=repo)

        # Find all supported source files
        source_files = self._find_source_files(get_all_supported_extensions())

        # Parse each file
        for file_path in source_files:
            self._parse_file(file_path, codebase)

        # Resolve cross-references and build additional relationships
        self._resolve_relationships(codebase)

        return codebase

    def parse_incremental(self, changed_files: List[str]) -> ParsedCodebase:
        """Parse only the specified changed files."""
        from .languages import get_all_supported_extensions

        self._pending_function_calls = {}
        self._pending_class_usages = {}

        repo = Repository(
            id=self.repo_id,
            name=self.repo_path.name,
            path=str(self.repo_path),
            language='multi'
        )

        codebase = ParsedCodebase(repository=repo)
        supported = get_all_supported_extensions()

        for rel_path in changed_files:
            file_path = self.repo_path / rel_path
            if file_path.exists() and file_path.suffix.lower() in supported:
                self._parse_file(file_path, codebase)

        self._resolve_relationships(codebase)
        return codebase

    def _find_source_files(self, extensions: Set[str]) -> List[Path]:
        """Find all source files in the repository matching supported extensions."""
        source_files = []

        for root, dirs, files in os.walk(self.repo_path):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS]

            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in extensions:
                    source_files.append(file_path)

        return source_files

    def _parse_file(self, file_path: Path, codebase: ParsedCodebase):
        """Parse a single source file using the appropriate language parser."""
        from .languages import get_parser_for_file

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source_code = f.read()
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return

        # Create file entity
        rel_path = file_path.relative_to(self.repo_path)
        file_id = str(rel_path)

        # Determine language name from parser
        parser = get_parser_for_file(file_path)
        language = parser.config.name if parser else "Unknown"

        file_entity = File(
            id=file_id,
            name=file_path.name,
            path=str(rel_path),
            extension=file_path.suffix,
            language=language,
            lines_of_code=len(source_code.split('\n')),
            content_hash=hashlib.md5(source_code.encode()).hexdigest()
        )
        codebase.files.append(file_entity)

        # Add file -> repository relationship
        codebase.add_relationship('CONTAINS_FILE', self.repo_id, file_id)

        # Determine module
        module_path = rel_path.parent
        if module_path != Path('.'):
            module_id = str(module_path).replace('/', '.').replace('\\', '.')

            # Check if module already exists
            if not any(m.id == module_id for m in codebase.modules):
                module = Module(
                    id=module_id,
                    name=module_path.name,
                    path=str(module_path),
                    module_type='package'
                )
                codebase.modules.append(module)
                codebase.add_relationship('CONTAINS_MODULE', self.repo_id, module_id)

            codebase.add_relationship('BELONGS_TO_MODULE', file_id, module_id)

        # Use language-specific parser
        if parser is None:
            print(f"No parser available for {file_path}")
            return

        result = parser.parse_file(file_path, source_code)

        # Add parsed entities
        codebase.classes.extend(result.get('classes', []))
        codebase.functions.extend(result.get('functions', []))
        codebase.variables.extend(result.get('variables', []))
        codebase.imports.extend(result.get('imports', []))
        codebase.interfaces.extend(result.get('interfaces', []))
        codebase.relationships.extend(result.get('relationships', []))

        # Add file -> class relationships
        for cls in result.get('classes', []):
            codebase.add_relationship('DEFINES_CLASS', file_id, cls.id)

        # Add file -> function relationships (only top-level functions)
        for func in result.get('functions', []):
            if not func.is_method:
                codebase.add_relationship('DEFINES_FUNCTION', file_id, func.id)

        # Add file -> import relationships
        for imp in result.get('imports', []):
            codebase.add_relationship('IMPORTS', file_id, imp.id)

        # Store call information for later resolution
        function_calls = result.get('function_calls', {})
        if function_calls:
            self._pending_function_calls[file_id] = function_calls
        class_usages = result.get('class_usages', {})
        if class_usages:
            self._pending_class_usages[file_id] = class_usages

    def _resolve_relationships(self, codebase: ParsedCodebase):
        """Resolve cross-file relationships"""
        # Build lookup tables
        class_by_name: Dict[str, Class] = {}
        func_by_name: Dict[str, List[Function]] = {}

        for cls in codebase.classes:
            class_by_name[cls.name] = cls
            # Also index by short name for namespaced C++ classes
            if '::' in cls.name:
                short = cls.name.rsplit('::', 1)[-1]
                if short not in class_by_name:
                    class_by_name[short] = cls

        for func in codebase.functions:
            if func.name not in func_by_name:
                func_by_name[func.name] = []
            func_by_name[func.name].append(func)

        # Resolve class inheritance
        for cls in codebase.classes:
            for base_name in cls.base_classes:
                if base_name in class_by_name:
                    base_cls = class_by_name[base_name]
                    codebase.add_relationship('EXTENDS', cls.id, base_cls.id)

        # Build interface lookup for IMPLEMENTS resolution
        interface_by_name = {}
        for iface in codebase.interfaces:
            interface_by_name[iface.name] = iface

        # Resolve IMPLEMENTS with unresolved target IDs
        unresolved_implements = []
        for rel in codebase.relationships:
            if rel.rel_type == 'IMPLEMENTS' and ':' not in rel.target_id:
                if rel.target_id in interface_by_name:
                    rel.target_id = interface_by_name[rel.target_id].id
                elif rel.target_id in class_by_name:
                    # Target may be a Class with language_type="interface"/"trait"
                    rel.target_id = class_by_name[rel.target_id].id
                else:
                    unresolved_implements.append(rel)

        # Remove unresolvable IMPLEMENTS relationships (external dependencies)
        for rel in unresolved_implements:
            if rel in codebase.relationships:
                codebase.relationships.remove(rel)

        # Resolve function calls and class usages
        for _file_id, function_calls in self._pending_function_calls.items():
            for func_id, calls in function_calls.items():
                for called_name, line in calls:
                    # Try to find the called function
                    if called_name in func_by_name:
                        for target_func in func_by_name[called_name]:
                            codebase.add_relationship(
                                'CALLS', func_id, target_func.id,
                                lineNumbers=str([line])
                            )
                            break

        for _file_id, class_usages in self._pending_class_usages.items():
            for func_id, class_names in class_usages.items():
                for class_name in class_names:
                    if class_name in class_by_name:
                        codebase.add_relationship(
                            'USES_CLASS', func_id, class_by_name[class_name].id
                        )

        # Resolve import dependencies between files
        import_to_file: Dict[str, str] = {}
        for file_entity in codebase.files:
            # Convert file path to module name
            module_name = file_entity.path.replace('/', '.').replace('\\', '.').replace('.py', '')
            import_to_file[module_name] = file_entity.id
            # Also add just the filename without path
            import_to_file[file_entity.name.replace('.py', '')] = file_entity.id

        for file_entity in codebase.files:
            for imp in codebase.imports:
                if imp.id.startswith(file_entity.id):
                    # This import belongs to this file
                    source_module = imp.source.split('.')[0]
                    if source_module in import_to_file and import_to_file[source_module] != file_entity.id:
                        codebase.add_relationship(
                            'IMPORTS_FROM', file_entity.id, import_to_file[source_module],
                            symbols=str(imp.imported_symbols)
                        )
                        codebase.add_relationship(
                            'DEPENDS_ON', file_entity.id, import_to_file[source_module],
                            dependencyType='import'
                        )


def parse_repository(repo_path: str, repo_id: Optional[str] = None) -> ParsedCodebase:
    """Convenience function to parse a repository"""
    parser = CodebaseParser(repo_path, repo_id)
    return parser.parse()
