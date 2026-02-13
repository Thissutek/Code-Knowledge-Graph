"""
Tests for the Python AST parser — both PythonParser and PythonLanguageParser.
These are regression tests to ensure the existing Python parsing is intact.
"""
from pathlib import Path

from src.parser import PythonParser, CodebaseParser
from src.languages import PythonLanguageParser
from tests.conftest import SAMPLE_PYTHON

import ast


# ── PythonParser unit tests ─────────────────────────────────────────────────

class TestPythonParser:
    """Direct tests against the AST visitor."""

    def _parse(self, code: str, file_path: str = "test.py"):
        p = PythonParser(file_path, "repo", code)
        tree = ast.parse(code, filename=file_path)
        p.visit(tree)
        return p

    # -- Classes --

    def test_extracts_classes(self):
        p = self._parse(SAMPLE_PYTHON)
        names = [c.name for c in p.classes]
        assert "Config" in names
        assert "Service" in names

    def test_class_docstring(self):
        p = self._parse(SAMPLE_PYTHON)
        config = next(c for c in p.classes if c.name == "Config")
        assert "Application configuration" in config.docstring

    def test_class_inheritance(self):
        p = self._parse(SAMPLE_PYTHON)
        svc = next(c for c in p.classes if c.name == "Service")
        assert "Config" in svc.base_classes

    def test_abstract_class_detected(self):
        code = "from abc import ABC\nclass Base(ABC):\n    pass\n"
        p = self._parse(code)
        assert p.classes[0].is_abstract is True

    def test_decorators_extracted(self):
        code = "@staticmethod\ndef foo(): pass\n"
        p = self._parse(code)
        assert p.functions[0].is_static is True

    def test_class_language_type_default(self):
        p = self._parse(SAMPLE_PYTHON)
        for cls in p.classes:
            assert cls.language_type == "class"

    # -- Functions --

    def test_extracts_functions(self):
        p = self._parse(SAMPLE_PYTHON)
        names = [f.name for f in p.functions]
        assert "to_dict" in names
        assert "create_service" in names
        assert "main" in names

    def test_async_detected(self):
        p = self._parse(SAMPLE_PYTHON)
        start_fn = next(f for f in p.functions if f.name == "start")
        assert start_fn.is_async is True

    def test_method_flag(self):
        p = self._parse(SAMPLE_PYTHON)
        to_dict = next(f for f in p.functions if f.name == "to_dict")
        assert to_dict.is_method is True
        create = next(f for f in p.functions if f.name == "create_service")
        assert create.is_method is False

    def test_visibility(self):
        p = self._parse(SAMPLE_PYTHON)
        internal = next(f for f in p.functions if f.name == "_internal")
        assert internal.visibility == "protected"
        private = next(f for f in p.functions if f.name == "__private")
        assert private.visibility == "private"
        public = next(f for f in p.functions if f.name == "main")
        assert public.visibility == "public"

    def test_return_type(self):
        p = self._parse(SAMPLE_PYTHON)
        to_dict = next(f for f in p.functions if f.name == "to_dict")
        assert to_dict.return_type == "dict"

    def test_parameters(self):
        p = self._parse(SAMPLE_PYTHON)
        create = next(f for f in p.functions if f.name == "create_service")
        assert len(create.parameters) == 1
        assert create.parameters[0].name == "name"
        assert create.parameters[0].type_annotation == "str"

    def test_complexity_baseline(self):
        p = self._parse(SAMPLE_PYTHON)
        main_fn = next(f for f in p.functions if f.name == "main")
        assert main_fn.complexity >= 1

    # -- Variables --

    def test_module_level_variables(self):
        p = self._parse(SAMPLE_PYTHON)
        names = [v.name for v in p.variables]
        assert "MAX_RETRIES" in names

    def test_constant_detection(self):
        p = self._parse(SAMPLE_PYTHON)
        mr = next(v for v in p.variables if v.name == "MAX_RETRIES")
        assert mr.is_constant is True

    # -- Imports --

    def test_import(self):
        p = self._parse(SAMPLE_PYTHON)
        sources = [i.source for i in p.imports]
        assert "os" in sources

    def test_import_from(self):
        p = self._parse(SAMPLE_PYTHON)
        names = [i.name for i in p.imports]
        assert "List" in names
        assert "Optional" in names

    # -- Relationships --

    def test_has_method_relationships(self):
        p = self._parse(SAMPLE_PYTHON)
        has_methods = [r for r in p.relationships if r.rel_type == "HAS_METHOD"]
        assert len(has_methods) > 0

    # -- Call tracking --

    def test_function_calls_tracked(self):
        p = self._parse(SAMPLE_PYTHON)
        assert len(p.function_calls) > 0

    def test_class_usages_tracked(self):
        p = self._parse(SAMPLE_PYTHON)
        # create_service uses Service
        create_id = next(
            fid for fid in p.class_usages if "create_service" in fid
        )
        assert "Service" in p.class_usages[create_id]


# ── PythonLanguageParser ────────────────────────────────────────────────────

class TestPythonLanguageParser:
    def test_config_extensions(self):
        plp = PythonLanguageParser()
        assert ".py" in plp.config.extensions
        assert ".pyw" in plp.config.extensions

    def test_can_parse(self):
        plp = PythonLanguageParser()
        assert plp.can_parse(Path("main.py"))
        assert not plp.can_parse(Path("main.js"))

    def test_parse_file_returns_expected_keys(self):
        plp = PythonLanguageParser()
        result = plp.parse_file(Path("test.py"), SAMPLE_PYTHON)
        for key in ("classes", "functions", "variables", "imports", "relationships"):
            assert key in result

    def test_parse_file_syntax_error_returns_empty(self):
        plp = PythonLanguageParser()
        result = plp.parse_file(Path("bad.py"), "def (invalid syntax")
        assert result["classes"] == []
        assert result["functions"] == []


# ── CodebaseParser (Python-only repo) ──────────────────────────────────────

class TestCodebaseParserPythonRegression:
    """Ensure the full parse pipeline still works for a Python-only repo."""

    def test_parse_python_repo(self, python_only_repo):
        parser = CodebaseParser(str(python_only_repo), "py-test")
        codebase = parser.parse()

        assert codebase.repository.id == "py-test"
        assert len(codebase.files) >= 3  # __init__, main.py, cache.py
        assert len(codebase.classes) >= 3  # Config, Service, CacheService
        assert len(codebase.functions) >= 4
        assert len(codebase.imports) >= 2

    def test_file_entities_have_language(self, python_only_repo):
        parser = CodebaseParser(str(python_only_repo), "py-test")
        codebase = parser.parse()
        py_files = [f for f in codebase.files if f.extension == ".py"]
        assert all(f.language == "Python" for f in py_files)

    def test_cross_file_relationships(self, python_only_repo):
        parser = CodebaseParser(str(python_only_repo), "py-test")
        codebase = parser.parse()
        rel_types = {r.rel_type for r in codebase.relationships}
        assert "CONTAINS_FILE" in rel_types
        assert "DEFINES_CLASS" in rel_types
        assert "HAS_METHOD" in rel_types

    def test_modules_created(self, python_only_repo):
        parser = CodebaseParser(str(python_only_repo), "py-test")
        codebase = parser.parse()
        assert len(codebase.modules) >= 1
        mod_names = [m.name for m in codebase.modules]
        assert "src" in mod_names
